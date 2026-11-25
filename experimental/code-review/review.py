#!/usr/bin/env python3
"""Evidence-oriented local reviews using Codex CLI. Python 3.10+, stdlib only."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid


HERE = Path(__file__).resolve().parent
VERSION = "0.3.0"


class ReviewError(Exception):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(repo, *args, binary=False, input_data=None):
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-C", str(repo), *args],
        input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReviewError(f"Git 명령 실패 ({args[0]}): {detail}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict").strip()


def resolve_commit(repo, ref, *, option=None):
    try:
        return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    except ReviewError as exc:
        raise ReviewError(
            f"{option or '지정한 ref'}를 커밋으로 해석하지 못했습니다: {ref!r}\n"
            f"대상 저장소: {repo}\n"
            "저장소 경로와 브랜치/커밋명을 확인하세요. 원격 ref는 자동 fetch하지 않습니다.\n"
            f"Git 원인: {exc}"
        ) from exc


def repository_root(value):
    repo = Path(value).expanduser().resolve()
    if not repo.is_dir():
        raise ReviewError(f"저장소 경로가 없습니다: {repo}")
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != repo:
        raise ReviewError(f"--repo에는 Git 저장소의 루트를 지정하세요: {root}")
    return root


def default_base(repo):
    for ref in ("refs/remotes/origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            resolve_commit(repo, ref)
            return ref
        except ReviewError:
            pass
    raise ReviewError("기준 브랜치를 찾지 못했습니다. --base를 지정하세요.")


def safe_path(value):
    path = PurePosixPath(value)
    if (not value or "\x00" in value or path.is_absolute()
            or any(part in ("..", ".git") for part in path.parts)
            or value != path.as_posix()):
        raise ReviewError(f"잘못된 저장소 상대 경로: {value!r}")
    return path


def changed_paths(snapshot, base):
    fields = git(snapshot, "diff", "--name-status", "-z", "--find-renames", base,
                 binary=True).decode("utf-8").split("\x00")
    entries, index = [], 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        old_path = None
        if status[0] in ("R", "C"):
            old_path = fields[index]
            index += 1
        path = fields[index]
        index += 1
        entries.append({"path": path, "status": status, "old_path": old_path})
    tracked = {entry["path"] for entry in entries}
    for path in untracked_paths(snapshot):
        if path not in tracked:
            entries.append({"path": path, "status": "?", "old_path": None})
    return entries


def untracked_paths(repo):
    return [p for p in git(repo, "ls-files", "--others", "--exclude-standard", "-z",
                           binary=True).decode("utf-8").split("\x00") if p]


def file_digest(path):
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "directory"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_fingerprint(snapshot):
    tracked = git(snapshot, "ls-files", "-z", binary=True).decode("utf-8").split("\x00")
    return {p: file_digest(snapshot / p) for p in tracked + untracked_paths(snapshot)
            if p}


def check_unchanged(snapshot, fingerprint):
    for path, digest in fingerprint.items():
        if file_digest(snapshot / path) != digest:
            raise ReviewError(f"리뷰 중 기존 파일이 변경되었습니다: {path}. 결과를 확정하지 않습니다.")


def make_snapshot(repo, run, head, dirty):
    snapshot = run / "checkout"
    patch = git(repo, "diff", "--binary", "HEAD", binary=True) if dirty else b""
    originals = {}
    if dirty:
        for path in untracked_paths(repo):
            safe_path(path)
            originals[path] = file_digest(repo / path)
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "clone", "--quiet", "--no-hardlinks",
         "--no-checkout", "--", str(repo), str(snapshot)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ReviewError("격리 checkout 생성 실패: " + result.stderr.decode("utf-8", errors="replace"))
    git(snapshot, "checkout", "--quiet", "--detach", head)
    if patch:
        git(snapshot, "apply", "--binary", "-", input_data=patch)
    for path in originals:
        src, dest = repo / path, snapshot / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dest.symlink_to(os.readlink(src))
        else:
            shutil.copy2(src, dest)
    if dirty and (git(repo, "diff", "--binary", "HEAD", binary=True) != patch
                  or set(untracked_paths(repo)) != set(originals)
                  or any(file_digest(repo / p) != digest for p, digest in originals.items())):
        raise ReviewError("작업 트리가 복사 중 변경되었습니다. 변경을 멈춘 뒤 다시 실행하세요.")
    return snapshot


def obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def arr(items):
    return {"type": "array", "items": items}


STRING = {"type": "string"}
NULL_STRING = {"type": ["string", "null"]}
PRIORITY = {"type": "integer", "enum": [0, 1, 2, 3]}
ASSESSMENT = obj({
    "confidence_score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    "rationale": STRING, "review_summary": STRING,
})
LOCATION = obj({"path": STRING, "revision": {"type": "string", "enum": ["base", "head"]},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1}})
EVIDENCE = obj({**LOCATION["properties"], "note": STRING})
CANDIDATE = obj({
    "title": STRING, "priority": PRIORITY, "location": LOCATION,
    "trigger": STRING, "expected": STRING, "actual": STRING, "impact": STRING,
    "contract_evidence": arr(EVIDENCE), "code_evidence": arr(EVIDENCE),
    "defenses_to_check": arr(STRING),
})
DISCOVERY_SCHEMA = obj({
    "summary": STRING,
    "assessment": ASSESSMENT,
    "coverage": arr(obj({"path": STRING,
                         "status": {"type": "string", "enum": ["reviewed", "not_reviewed"]},
                         "reason": STRING})),
    "candidates": arr(CANDIDATE), "limitations": arr(STRING),
})
FINDING = obj({
    "title": STRING, "priority": PRIORITY, "location": LOCATION,
    "trigger": STRING, "expected": STRING, "actual": STRING, "impact": STRING,
    "contract_basis": STRING, "code_evidence": arr(EVIDENCE),
    "defenses_checked": arr(STRING), "suggested_fix": STRING,
    "validation": obj({"method": {"type": "string", "enum": ["static", "runtime"]},
                       "commands": arr(STRING), "observations": STRING}),
})
VERIFICATION_SCHEMA = obj({
    "assessment": ASSESSMENT,
    "verdicts": arr(obj({
        "candidate_id": STRING,
        "status": {"type": "string", "enum": ["confirmed", "refuted", "unresolved", "duplicate"]},
        "reason": STRING, "duplicate_of": NULL_STRING,
        "finding": {"anyOf": [FINDING, {"type": "null"}]},
    })),
    "limitations": arr(STRING),
})

PIPELINE_VERIFICATION_SCHEMA = obj({**VERIFICATION_SCHEMA["properties"],
                                    "new_candidates": arr(CANDIDATE)})
RECONCILIATION_SCHEMA = obj({
    "summary": STRING, "assessment": ASSESSMENT,
    "duplicates": arr(obj({"candidate_id": STRING, "duplicate_of": STRING, "reason": STRING})),
    "limitations": arr(STRING),
})


def validate_json(value, schema, path="$"):
    """Validate the small JSON Schema subset used by our Codex output schemas."""
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                validate_json(value, choice, path)
                return
            except ReviewError:
                pass
        raise ReviewError(f"{path}: 허용된 JSON 형식이 아닙니다.")
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "integer": type(value) is int,
               "null": value is None}
    if types and not any(matches.get(kind, False) for kind in types):
        raise ReviewError(f"{path}: JSON 타입 오류 ({types})")
    if "enum" in schema and value not in schema["enum"]:
        raise ReviewError(f"{path}: 허용되지 않은 값")
    if "minimum" in schema and value < schema["minimum"]:
        raise ReviewError(f"{path}: 최소값 미만")
    if isinstance(value, dict):
        properties = schema["properties"]
        if set(value) != set(schema["required"]):
            raise ReviewError(f"{path}: 필수 필드 누락 또는 알 수 없는 필드")
        for key, child in value.items():
            validate_json(child, properties[key], path + "." + key)
    if isinstance(value, list):
        for i, child in enumerate(value):
            validate_json(child, schema["items"], f"{path}[{i}]")


def stage_prompt(name, packet):
    common = (HERE / "prompts" / "common.md").read_text(encoding="utf-8")
    specific = (HERE / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    return common + "\n\n" + specific + "\n\nREVIEW INPUT (JSON data):\n" + json.dumps(packet, ensure_ascii=False)


def extract_commands(events):
    commands = []
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        if (event.get("type") == "item.completed" and item.get("type") == "command_execution"):
            commands.append({"command": item.get("command", ""),
                             "exit_code": item.get("exit_code"),
                             "output": item.get("aggregated_output", "")})
    return commands


def command_text(command):
    """Codex may log the shell wrapper as well as the model's command text."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command.strip()
    if (len(parts) == 3 and Path(parts[0]).name in {"bash", "zsh", "sh", "fish"}
            and parts[1] in {"-c", "-lc", "-ic", "-lic"}):
        return parts[2].strip()
    return command.strip()


def stop_process(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_codex(stage, prompt_name, packet, schema, snapshot, run, args, writable=False):
    prompt = stage_prompt(prompt_name, packet)
    prompt_file, schema_file = run / f"{stage}.prompt.md", run / f"{stage}.schema.json"
    output_file, events_file = run / f"{stage}.json", run / f"{stage}.events.jsonl"
    stderr_file = run / f"{stage}.stderr.log"
    prompt_file.write_text(prompt, encoding="utf-8")
    write_json(schema_file, schema)
    command = [args.codex, "-a", "never", "exec", "-C", str(snapshot),
               "--sandbox", "workspace-write" if writable else "read-only",
               "--ephemeral", "--json", "--color", "never",
               "--output-schema", str(schema_file), "-o", str(output_file)]
    if args.model:
        command += ["--model", args.model]
    if args.reasoning:
        command += ["-c", f'model_reasoning_effort="{args.reasoning}"']
    command.append("-")
    write_json(run / f"{stage}.command.json", command)
    print(f"[{stage}] Codex 실행 중…", flush=True)
    started, started_at = time.monotonic(), utc_now()
    metric = {"stage": stage, "started_at": started_at, "status": "running",
              "commands": [], "usage": {}, "model": args.model,
              "reasoning": args.reasoning, "service_tier": "inherit Codex configuration; not measured"}
    cancel = getattr(args, "_cancel_event", threading.Event())
    def read_events(stream, events):
        command_starts = {}
        for line in stream:
            events.write(line)
            events.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "command_execution":
                identifier = item.get("id")
                if event.get("type") == "item.started":
                    command_starts.setdefault(identifier, (time.monotonic(), utc_now()))
                elif event.get("type") == "item.completed":
                    begin = command_starts.pop(identifier, None)
                    metric["commands"].append({"item_id": identifier, "command": item.get("command"),
                        "exit_code": item.get("exit_code"), "started_at": begin[1] if begin else None,
                        "finished_at": utc_now(),
                        "wall_seconds": round(time.monotonic() - begin[0], 3) if begin else None,
                        "output_bytes": len((item.get("aggregated_output") or "").encode("utf-8"))})
            if isinstance(event.get("usage"), dict):
                metric["usage"] = event["usage"]
    with events_file.open("w", encoding="utf-8") as events, stderr_file.open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=stderr, text=True, start_new_session=True)
        except OSError as exc:
            raise ReviewError(f"Codex 실행 실패: {exc}") from exc
        reader = threading.Thread(target=read_events, args=(process.stdout, events), daemon=True)
        def send_prompt():
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        writer = threading.Thread(target=send_prompt, daemon=True)
        reader.start()
        writer.start()
        try:
            while process.poll() is None:
                if cancel.is_set():
                    raise ReviewError(f"{stage} 실행이 취소되었습니다.")
                if time.monotonic() - started >= args.timeout:
                    raise subprocess.TimeoutExpired(command, args.timeout)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            metric["status"] = "completed" if process.returncode == 0 else "failed"
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            metric["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "timeout"
            stop_process(process)
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise ReviewError(f"{stage} 시간 초과 ({args.timeout}초). 로그: {stderr_file}") from exc
        except BaseException:
            metric["status"] = "cancelled"
            stop_process(process)
            raise
        finally:
            reader.join(timeout=5)
            writer.join(timeout=5)
            if reader.is_alive() or writer.is_alive():
                # A descendant retaining the pipes must not defeat cancellation/timeout.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                reader.join(timeout=5)
                writer.join(timeout=5)
            process.stdout.close()
            metric.update({"finished_at": utc_now(), "wall_seconds": round(time.monotonic() - started, 3),
                           "exit_code": process.returncode})
            write_json(run / f"{stage}.metrics.json", metric)
    if process.returncode:
        raise ReviewError(f"{stage} Codex 종료 코드 {process.returncode}. 로그: {stderr_file}")
    if not output_file.is_file():
        raise ReviewError(f"{stage} 결과 파일이 생성되지 않았습니다.")
    try:
        output = json.loads(output_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReviewError(f"{stage} 결과가 유효한 JSON이 아닙니다: {output_file}") from exc
    validate_json(output, schema)
    for key in ("rationale", "review_summary"):
        if not output["assessment"][key].strip():
            raise ReviewError(f"{stage} 평가의 {key}가 비어 있습니다.")
    if "summary" in output and not output["summary"].strip():
        raise ReviewError(f"{stage} 변경 요약이 비어 있습니다.")
    commands = extract_commands(events_file)
    write_json(run / f"{stage}.commands.json", commands)
    return output, commands


def check_reference(reference, snapshot, base):
    path = safe_path(reference["path"])
    if reference["end_line"] < reference["start_line"]:
        raise ReviewError("줄 범위가 역순입니다.")
    if reference["revision"] == "base":
        content = git(snapshot, "show", f"{base}:{path}", binary=True)
    else:
        target = snapshot / str(path)
        if not target.resolve().is_relative_to(snapshot.resolve()):
            raise ReviewError("checkout 밖의 파일을 참조했습니다.")
        if not target.is_file():
            raise ReviewError("참조한 파일이 없습니다.")
        content = target.read_bytes()
    if b"\x00" in content or reference["end_line"] > len(content.splitlines()):
        raise ReviewError("참조한 줄이 없거나 바이너리 파일입니다.")


def normalize_verdicts(result, candidates, snapshot, base, commands, run_tests, defer_duplicates=False):
    expected_ids = {c["id"] for c in candidates}
    verdicts = result["verdicts"]
    actual_ids = [v["candidate_id"] for v in verdicts]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ReviewError("검증 결과가 모든 후보를 정확히 한 번씩 처리하지 않았습니다.")
    for verdict in verdicts:
        if not verdict["reason"].strip():
            raise ReviewError("검증 결과에 판정 이유가 없습니다.")
        if verdict["status"] != "confirmed":
            verdict["finding"] = None
            continue
        finding, error = verdict["finding"], None
        if finding is None:
            error = "확인 판정에 finding이 없습니다."
        else:
            try:
                for key in ("title", "trigger", "expected", "actual", "impact", "contract_basis"):
                    if not finding[key].strip():
                        raise ReviewError(f"필수 근거가 비어 있습니다: {key}")
                if not finding["code_evidence"] or not any(s.strip() for s in finding["defenses_checked"]):
                    raise ReviewError("코드 근거나 방어 로직 확인 내역이 없습니다.")
                if not finding["validation"]["observations"].strip():
                    raise ReviewError("검증 관찰 결과가 없습니다.")
                check_reference(finding["location"], snapshot, base)
                for evidence in finding["code_evidence"]:
                    if not evidence["note"].strip():
                        raise ReviewError("코드 근거 설명이 없습니다.")
                    check_reference(evidence, snapshot, base)
                if finding["validation"]["method"] == "runtime":
                    claimed = finding["validation"]["commands"]
                    executed = {command_text(c["command"]): c for c in commands if c["exit_code"] is not None}
                    if not run_tests or not claimed or not all(command_text(c) in executed for c in claimed):
                        raise ReviewError("주장한 재현 명령의 실제 실행 기록이 없습니다.")
                    verdict["execution_evidence"] = [executed[command_text(c)] for c in claimed]
            except (ReviewError, OSError) as exc:
                error = str(exc)
        if error:
            verdict["status"] = "unresolved"
            verdict["reason"] += " [실행기 근거 검사: " + error + "]"
            verdict["finding"] = None
    confirmed = {v["candidate_id"] for v in verdicts if v["status"] == "confirmed"}
    for verdict in verdicts:
        if verdict["status"] == "duplicate":
            if defer_duplicates:
                continue
            if verdict["duplicate_of"] not in confirmed or verdict["duplicate_of"] == verdict["candidate_id"]:
                verdict["status"] = "unresolved"
                verdict["reason"] += " [중복 대상이 확인된 후보가 아닙니다.]"
                verdict["duplicate_of"] = None
        else:
            verdict["duplicate_of"] = None
    return verdicts


def summarize_review(manifest, discoveries, verdicts, verification):
    """Keep model judgments separate from facts and enforce conservative score caps."""
    counts = {status: sum(v["status"] == status for v in verdicts)
              for status in ("confirmed", "refuted", "unresolved", "duplicate")}
    counts["candidates"] = len(verdicts)
    confirmed = [v["finding"] for v in verdicts if v["status"] == "confirmed"]
    priorities = {f"P{p}": sum(f["priority"] == p for f in confirmed) for p in range(4)}
    covered = {c["path"] for d in discoveries for c in d["coverage"] if c["status"] == "reviewed"}
    not_reviewed = [c["path"] for c in manifest["changes"] if c["path"] not in covered]
    assessments = [{"stage": d.get("_stage", "discover" if index == 0 else "challenge"), **d["assessment"]}
                   for index, d in enumerate(discoveries)]
    if verification is not None:
        assessments.extend(verification.get("_stage_assessments", []))
        assessments.append({"stage": verification.get("_stage", "verify"), **verification["assessment"]})
        assessment = assessments[-1]
    else:
        assessment = min(assessments, key=lambda a: a["confidence_score"], default=None)
    adjustments = []
    score = assessment["confidence_score"] if assessment else None
    if score is not None:
        caps = []
        if confirmed:
            priority = min(f["priority"] for f in confirmed)
            caps.append((priority + 1, f"확인된 P{priority} 문제가 있어 최대 {priority + 1}/5입니다."))
        if counts["unresolved"]:
            caps.append((3, f"미확인 후보 {counts['unresolved']}건이 있어 최대 3/5입니다."))
        if not_reviewed:
            caps.append((3, f"미검토 파일 {len(not_reviewed)}개가 있어 최대 3/5입니다."))
        if manifest["status"] != "completed":
            caps.append((3, "리뷰가 미완료여서 최대 3/5입니다."))
        if manifest["limitations"]:
            caps.append((4, "기록된 검토 한계가 있어 최대 4/5입니다."))
        adjustments = [reason for cap, reason in caps if score > cap]
        score = min([score] + [cap for cap, _ in caps])
    if not manifest["changes"]:
        conclusion = "리뷰할 변경이 없어 점수를 산정하지 않았습니다."
    elif confirmed:
        severity = ", ".join(f"{key} {count}건" for key, count in priorities.items() if count)
        conclusion = f"확인된 문제 {len(confirmed)}건 ({severity})을 수정한 뒤 다시 리뷰하세요."
    elif manifest["status"] != "completed":
        conclusion = "확인된 문제는 없지만 리뷰가 미완료입니다. 미확인 항목과 검토 한계를 확인하세요."
    else:
        conclusion = "검토한 범위에서 확인된 문제를 찾지 못했습니다."
    rationale, review_summary = conclusion, conclusion
    if assessment:
        rationale = assessment["rationale"]
        if manifest["status"] != "completed":
            rationale = " ".join(reason for _, reason in caps)
        elif adjustments:
            rationale = " ".join(adjustments)
        else:
            review_summary = assessment["review_summary"]
    return {
        "status": manifest["status"],
        "change_summary": discoveries[-1]["summary"] if discoveries else "변경 없음",
        "conclusion": conclusion,
        "review_summary": review_summary,
        "confidence": {"score": score, "out_of": 5, "rationale": rationale,
                       "source_stage": assessment["stage"] if assessment else None,
                       "model_score": assessment["confidence_score"] if assessment else None,
                       "adjustments": adjustments,
                       "meaning": "리뷰한 변경의 머지 준비 상태에 대한 평가이며, 버그 확률이나 정확도 통계가 아닙니다."},
        "stage_assessments": assessments, "counts": counts, "priorities": priorities,
        "coverage": {"reviewed": len(covered), "total": len(manifest["changes"]),
                     "not_reviewed": not_reviewed},
        "validation": {"verification_performed": bool(verification and verification.get("_candidate_verification_performed", True)),
                       "runtime_confirmed": sum(f["validation"]["method"] == "runtime" for f in confirmed),
                       "static_confirmed": sum(f["validation"]["method"] == "static" for f in confirmed)},
        "limitations": manifest["limitations"],
    }


def render_report(manifest, discoveries, verdicts, summary):
    confidence = summary["confidence"]
    rating = f"{confidence['score']}/5" if confidence["score"] is not None else "미산정"
    lines = ["# 로컬 코드 리뷰", "", f"## Confidence Score: {rating}", "",
             f"**{summary['conclusion']}**", "", confidence["rationale"], ""]
    if confidence["adjustments"]:
        lines += [f"모델 평가 {confidence['model_score']}/5에 실행기 제한을 적용했습니다.", ""]
    lines += [confidence["meaning"], "", "## Summary", "", summary["change_summary"], ""]
    if summary["review_summary"] != summary["conclusion"]:
        lines += ["**검토 요약:** " + summary["review_summary"], ""]
    counts, coverage = summary["counts"], summary["coverage"]
    lines += [f"- 확인 {counts['confirmed']}건 / 미확인 {counts['unresolved']}건 / "
              f"기각 {counts['refuted']}건 / 중복 {counts['duplicate']}건",
              f"- 변경 파일 검토: {coverage['reviewed']}/{coverage['total']}",
              f"- 실행 기록으로 확인한 재현: {summary['validation']['runtime_confirmed']}건",
              "", "## 실행 정보", "", f"- 상태: {manifest['status']}",
             f"- 저장소: `{manifest['repository']}`",
             f"- 기준: `{manifest['merge_base']}` → `{manifest['head']}`",
             f"- 작업 트리 포함: {manifest['uncommitted']}",
             f"- 실행 테스트 허용: {manifest['run_tests']}", ""]
    if "pipeline" in manifest:
        pipeline = manifest["pipeline"]
        lines += [f"- 실행 방식: 병렬 · 동시 작업 한도 {pipeline['workers']} · 탐색 그룹 {pipeline['groups']}",
                  f"- 전체 상호작용 조사: {pipeline['crosscutting']}", ""]
    if "checks" in manifest:
        checks = manifest["checks"]
        lines += ["## 환경 준비와 회귀 검사", "",
                  f"- 환경: {checks['status']} / 준비: {checks['setup_status']} / 회귀 검사: {checks['tests_status']}"]
        for kind in ("setup", "tests"):
            for check in checks[kind]:
                lines += [f"- {kind}: `{shlex.join(check['argv'])}` · {check['status']} · "
                          f"종료 {check['exit_code']} · {check['wall_seconds']}초 · 로그 `{Path(check['log']).name}`"]
        if checks.get("error"):
            lines += ["- 오류: " + checks["error"]]
        if checks["tests_status"] == "skipped":
            lines += ["- 설정된 회귀 테스트는 실행되지 않았습니다. 테스트 명령이 없거나 환경 준비가 차단됐습니다."]
        lines += [""]
    lines += ["## 실행 시간", "", "단계·명령별 시간과 토큰 사용량은 `performance.json`에 기록합니다.", ""]
    confirmed = sorted((v for v in verdicts if v["status"] == "confirmed"),
                       key=lambda v: (v["finding"]["priority"], v["candidate_id"]))
    lines += ["## 확인된 문제", ""]
    if not confirmed:
        lines += ["확인된 문제를 찾지 못했습니다. 검토 범위와 미확인 항목을 함께 확인하세요.", ""]
    for verdict in confirmed:
        finding, loc = verdict["finding"], verdict["finding"]["location"]
        lines += [f"### {verdict['candidate_id']} · P{finding['priority']} · {finding['title']}", "",
                  f"`{loc['path']}:{loc['start_line']}-{loc['end_line']}` ({loc['revision']})", ""]
        for label, key in (("발생 조건", "trigger"), ("기대 동작", "expected"),
                           ("실제 동작", "actual"), ("영향", "impact"),
                           ("계약 근거", "contract_basis"), ("수정 방향", "suggested_fix")):
            lines += [f"**{label}:** {finding[key]}", ""]
        lines += ["**확인한 방어 로직:** " + "; ".join(finding["defenses_checked"]), ""]
        for evidence in finding["code_evidence"]:
            lines += [f"- `{evidence['path']}:{evidence['start_line']}-{evidence['end_line']}`"
                      f" ({evidence['revision']}): {evidence['note']}"]
        validation = finding["validation"]
        lines += ["", f"**검증 ({validation['method']}):** {validation['observations']}", ""]
        for command in validation["commands"]:
            lines += [f"- 실행 명령: `{command}`"]
        lines += [""]
    lines += ["## 후보별 처리 결과", "", "| 후보 | 판정 | 이유 |", "| --- | --- | --- |"]
    for verdict in verdicts:
        reason = verdict["reason"].replace("|", "\\|").replace("\n", " ")
        lines += [f"| {verdict['candidate_id']} | {verdict['status']} | {reason} |"]
    lines += ["", "## 검토 범위와 한계", ""]
    for entry in manifest["changes"]:
        path = entry["path"]
        covered = any(c["path"] == path and c["status"] == "reviewed"
                      for d in discoveries for c in d["coverage"])
        lines += [f"- {'검토됨' if covered else '미검토'}: `{path}`"]
        if not covered:
            reasons = [c["reason"] for d in discoveries for c in d["coverage"] if c["path"] == path]
            lines += ["  - " + ("; ".join(reasons) or "모델이 검토 범위를 보고하지 않았습니다.")]
    for limit in manifest["limitations"]:
        lines += ["- " + limit]
    lines += ["", "모델의 판정과 코드 참조 검사를 기록한 결과입니다. 사람의 리뷰 및 CI를 함께 사용하세요.", ""]
    return "\n".join(lines)


def review(args):
    import pipeline
    args._cancel_event = threading.Event()
    checks = pipeline.load_checks(args, sys.modules[__name__])
    if args.execution == "serial" and (checks["setup"] or checks["tests"] or checks["groups"]):
        raise ReviewError("설치·회귀 검사·그룹 설정은 --execution parallel에서 사용하세요.")
    repo = repository_root(args.repo)
    base_ref = args.base or default_base(repo)
    base_tip = resolve_commit(repo, base_ref, option="--base")
    head = resolve_commit(repo, args.head, option="--head")
    if args.uncommitted and head != resolve_commit(repo, "HEAD"):
        raise ReviewError("--uncommitted는 현재 HEAD를 리뷰할 때만 사용할 수 있습니다.")
    base = git(repo, "merge-base", base_tip, head)
    context = []
    for value in args.context:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ReviewError(f"문맥 파일이 없습니다: {path}")
        context.append({"name": path.name, "content": path.read_text(encoding="utf-8")})
    if not args.dry_run and shutil.which(args.codex) is None:
        raise ReviewError("Codex CLI를 찾지 못했습니다. 설치하고 codex login을 실행하세요.")
    output = Path(args.output_dir).expanduser().resolve()
    # Runs inside the source could get swept into an uncommitted snapshot.
    if args.uncommitted and output.is_relative_to(repo):
        ignored = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(output / "probe")])
        if ignored.returncode:
            raise ReviewError("--uncommitted 실행 결과 경로는 대상 저장소 밖이거나 Git에서 제외된 경로여야 합니다.")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run = output / run_id
    run.mkdir(parents=True)
    manifest = {"version": VERSION, "run_id": run_id, "started_at": utc_now(),
                "status": "preparing", "repository": str(repo), "base_ref": base_ref,
                "base_tip": base_tip, "merge_base": base, "head": head,
                "uncommitted": args.uncommitted, "run_tests": args.run_tests,
                "depth": args.depth, "model": args.model or "inherit Codex config",
                "execution": args.execution, "workers": args.workers,
                "reasoning": args.reasoning or "inherit Codex config",
                "language": args.language, "changes": [], "limitations": [],
                "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "implementation_files": {str(p.relative_to(HERE)): file_digest(p)
                    for p in [HERE / "review.py", HERE / "pipeline.py", *sorted((HERE / "prompts").glob("*.md"))]}}
    write_json(run / "manifest.json", manifest)
    print(f"리뷰 이력: {run}", flush=True)
    try:
        snapshot = make_snapshot(repo, run, head, args.uncommitted)
        changes = changed_paths(snapshot, base)
        manifest["changes"] = changes
        diff_file = run / "change.diff"
        diff_file.write_bytes(git(snapshot, "diff", "--binary", "--find-renames", base, binary=True))
        # git diff excludes untracked files; the inventory explicitly tells Codex to read them.
        dirty_state = git(repo, "status", "--porcelain", "--untracked-files=normal")
        if dirty_state and not args.uncommitted:
            manifest["limitations"].append("원본의 커밋되지 않은 변경은 제외했습니다 (--uncommitted로 포함 가능).")
        if any(line.split()[0] == "160000" for line in git(snapshot, "ls-files", "--stage").splitlines()):
            manifest["limitations"].append("서브모듈은 자동 다운로드하지 않습니다. 필요한 내부 문맥은 별도로 제공하세요.")
        write_json(run / "context.json", context)
        write_json(run / "checks-config.json", checks)
        write_json(run / "manifest.json", manifest)
        packet = {"merge_base": base, "head": head, "changes": changes,
                  "diff_file": str(diff_file), "extra_context": context,
                  "language": args.language, "test_execution_enabled": False,
                  "limitations": manifest["limitations"]}
        if args.dry_run:
            (run / "discover.prompt.md").write_text(stage_prompt("discover", packet), encoding="utf-8")
            write_json(run / "discover.schema.json", DISCOVERY_SCHEMA)
            if args.execution == "parallel":
                _, _, jobs = pipeline.prepare_jobs(snapshot, run, packet, manifest, args, sys.modules[__name__], checks)
                for stage, prompt_name, data in jobs:
                    (run / f"{stage}.prompt.md").write_text(stage_prompt(prompt_name, data), encoding="utf-8")
                    write_json(run / f"{stage}.schema.json", DISCOVERY_SCHEMA)
            manifest["status"] = "prepared"
            print("준비 완료. Codex 호출 없이 checkout, 입력과 프롬프트를 저장했습니다.", flush=True)
            return run
        discoveries, candidates, verdicts = [], [], []
        verification = None
        fingerprint = tree_fingerprint(snapshot)
        pipeline_limits = None
        if changes and args.execution == "parallel":
            discoveries, candidates, verdicts, verification, pipeline_limits = pipeline.run_pipeline(
                snapshot, run, packet, manifest, args, sys.modules[__name__], checks)
        elif changes:
            for stage in (["discover", "challenge"] if args.depth == "deep" else ["discover"]):
                prior_reviews = [{key: d[key] for key in ("summary", "coverage", "limitations")}
                                 for d in discoveries]
                result, _ = run_codex(stage, stage, {**packet, "existing_candidates": candidates,
                                                   "prior_reviews": prior_reviews},
                                      DISCOVERY_SCHEMA, snapshot, run, args)
                check_unchanged(snapshot, fingerprint)
                changed_set = {c["path"] for c in changes}
                coverage_paths = [c["path"] for c in result["coverage"]]
                if len(coverage_paths) != len(set(coverage_paths)) or set(coverage_paths) - changed_set:
                    raise ReviewError("탐색 결과의 검토 범위에 중복 또는 대상 밖 파일이 있습니다.")
                discoveries.append(result)
                for candidate in result["candidates"]:
                    candidates.append({"id": f"C{len(candidates) + 1:04d}",
                                       "discovery_stage": stage, **candidate})
                write_json(run / "candidates.json", candidates)
            if candidates:
                verification_packet = {**packet, "candidates": candidates,
                                       "prior_reviews": [{key: d[key] for key in ("summary", "coverage", "limitations")}
                                                         for d in discoveries],
                                       "test_execution_enabled": args.run_tests}
                result, commands = run_codex("verify", "verify", verification_packet,
                                             VERIFICATION_SCHEMA, snapshot, run, args,
                                             writable=args.run_tests)
                check_unchanged(snapshot, fingerprint)
                verdicts = normalize_verdicts(result, candidates, snapshot, base, commands, args.run_tests)
                verification = result
                manifest["limitations"] += result["limitations"]
        if pipeline_limits is not None:
            review_limitations = pipeline_limits
        else:
            review_limitations = list(verification["limitations"]) if verification is not None else []
            for discovery in discoveries:
                manifest["limitations"] += discovery["limitations"]
                review_limitations += discovery["limitations"]
        covered = {c["path"] for d in discoveries for c in d["coverage"] if c["status"] == "reviewed"}
        incomplete = (bool(review_limitations) or any(c["path"] not in covered for c in changes)
                      or any(v["status"] == "unresolved" for v in verdicts))
        manifest["status"] = "incomplete" if incomplete else "completed"
        manifest["limitations"] = list(dict.fromkeys(manifest["limitations"]))
        write_json(run / "candidates.json", candidates)
        write_json(run / "verdicts.json", verdicts)
        write_json(run / "findings.json", [v for v in verdicts if v["status"] == "confirmed"])
        summary = summarize_review(manifest, discoveries, verdicts, verification)
        write_json(run / "summary.json", summary)
        (run / "report.md").write_text(render_report(manifest, discoveries, verdicts, summary), encoding="utf-8")
        print(f"확인 {sum(v['status'] == 'confirmed' for v in verdicts)} / "
              f"미확인 {sum(v['status'] == 'unresolved' for v in verdicts)} / 상태 {manifest['status']}", flush=True)
        score = summary["confidence"]["score"]
        print(f"Confidence Score: {str(score) + '/5' if score is not None else '미산정'}", flush=True)
        print(f"보고서: {run / 'report.md'}", flush=True)
        return run
    except (ReviewError, OSError, UnicodeError, KeyboardInterrupt) as exc:
        manifest["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        manifest["error"] = str(exc) or "사용자가 중단했습니다."
        (run / "summary.json").unlink(missing_ok=True)
        (run / "report.md").write_text("# 리뷰 미완료\n\n" + manifest["error"] + "\n", encoding="utf-8")
        raise
    finally:
        manifest["finished_at"] = utc_now()
        manifest["performance"] = {"path": str(run / "performance.json"),
                                   "wall_seconds": pipeline.performance(run, manifest, sys.modules[__name__])["wall_seconds"]}
        write_json(run / "manifest.json", manifest)


def feedback(args):
    run = Path(args.run).expanduser().resolve()
    if not (run / "manifest.json").is_file():
        raise ReviewError("리뷰 실행 폴더가 아닙니다.")
    verdicts = json.loads((run / "verdicts.json").read_text(encoding="utf-8"))
    indexed = {v["candidate_id"]: v for v in verdicts}
    if args.label != "missed" and args.candidate not in indexed:
        raise ReviewError("존재하지 않는 후보 ID입니다. 놓친 버그는 --label missed로 기록하세요.")
    if args.label in ("true_positive", "false_positive") and indexed[args.candidate]["status"] != "confirmed":
        raise ReviewError("true_positive/false_positive는 보고된 confirmed 후보에만 적용합니다.")
    if args.label == "missed" and args.candidate in indexed and indexed[args.candidate]["status"] == "confirmed":
        raise ReviewError("이미 보고된 confirmed 후보는 missed로 기록할 수 없습니다.")
    record = {"candidate_id": args.candidate, "label": args.label, "note": args.note, "at": utc_now()}
    with (run / "feedback.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"피드백 저장: {run / 'feedback.jsonl'}")


def stats(args):
    root = Path(args.runs).expanduser().resolve()
    counts = {key: 0 for key in ("true_positive", "false_positive", "uncertain", "missed")}
    labeled_runs = 0
    for path in sorted(root.glob("*/feedback.jsonl")):
        latest = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            latest[record["candidate_id"]] = record["label"]
        for label in latest.values():
            counts[label] += 1
        labeled_runs += 1
    tp, fp, missed = counts["true_positive"], counts["false_positive"], counts["missed"]
    write = {"labeled_runs": labeled_runs, **counts,
             "precision_among_labeled_findings": tp / (tp + fp) if tp + fp else None,
             "false_discovery_fraction": fp / (tp + fp) if tp + fp else None,
             "detection_among_recorded_bugs": tp / (tp + missed) if tp + missed else None,
             "note": "사람이 라벨링한 사례의 집계입니다. 전체 버그 탐지율이나 통계적 품질 보장이 아닙니다."}
    print(json.dumps(write, ensure_ascii=False, indent=2))


def parser():
    cli = argparse.ArgumentParser(description="Codex로 로컬 변경의 엣지케이스를 탐색·검증하고 기록합니다.")
    cli.add_argument("--version", action="version", version=VERSION)
    sub = cli.add_subparsers(dest="command", required=True)
    run = sub.add_parser("review", help="저장소 변경 리뷰")
    run.add_argument("--repo", required=True, help="대상 Git 저장소 루트")
    run.add_argument("--base", help="기준 브랜치/커밋 (기본: origin/HEAD 또는 main/master)")
    run.add_argument("--head", default="HEAD", help="리뷰할 head 커밋 (기본: HEAD)")
    run.add_argument("--uncommitted", action="store_true", help="staged/unstaged/untracked 변경도 포함")
    run.add_argument("--context", action="append", default=[], help="PR 설명·계약·팀 규칙 파일 (반복 가능)")
    run.add_argument("--depth", choices=("standard", "deep"), default="standard", help="deep은 단일 그룹에도 전체 상호작용 조사 (serial: 추가 탐색 1회)")
    run.add_argument("--execution", choices=("parallel", "serial"), default="parallel", help="기본: 병렬 탐색·후보 즉시 검증; serial은 기존 순차 실행")
    run.add_argument("--workers", type=int, default=4, help="병렬 작업 한도 (환경 준비 포함, 기본: 4)")
    run.add_argument("--verify-batch-size", type=int, default=1, help="독립 검증 작업당 후보 수 (기본: 1)")
    run.add_argument("--checks-config", help="사용자가 지정한 setup/tests argv 배열과 groups glob을 담은 JSON")
    run.add_argument("--setup-command", action="append", default=[], help="격리 환경 준비 명령 (반복 가능, 셸 확장 없음)")
    run.add_argument("--test-command", action="append", default=[], help="후보와 무관하게 실행할 회귀 검사 명령 (반복 가능, 셸 확장 없음)")
    run.add_argument("--setup-timeout", type=int, default=180, help="환경 준비 명령별 제한 초 (기본: 180)")
    run.add_argument("--test-timeout", type=int, default=300, help="회귀 검사 명령별 제한 초 (기본: 300)")
    run.add_argument("--max-followup-rounds", type=int, default=2, help="검증 중 발견한 새 후보의 후속 검증 회수 (초과 후보는 미확인, 기본: 2)")
    run.add_argument("--run-tests", action="store_true", help="검증 checkout에서 재현 파일 생성·테스트 허용")
    run.add_argument("--model", help="Codex 모델 (기본: 기존 Codex 설정)")
    run.add_argument("--reasoning", choices=("minimal", "low", "medium", "high", "xhigh", "max"), help="모델이 지원하는 추론 수준")
    run.add_argument("--language", default="Korean", help="리뷰 보고 언어")
    run.add_argument("--codex", default="codex", help="Codex 실행 파일 경로")
    run.add_argument("--output-dir", default=str(HERE / "runs"), help="실행 결과 저장 루트")
    run.add_argument("--timeout", type=int, default=900, help="Codex 단계별 제한 초 (기본: 900)")
    run.add_argument("--dry-run", action="store_true", help="입력·checkout만 준비하고 Codex를 호출하지 않음")
    run.set_defaults(handler=review)
    label = sub.add_parser("feedback", help="사람이 판정한 실제 버그·오탐 기록")
    label.add_argument("--run", required=True)
    label.add_argument("--candidate", required=True)
    label.add_argument("--label", required=True, choices=("true_positive", "false_positive", "uncertain", "missed"))
    label.add_argument("--note", required=True, help="판정 근거; missed에는 위치와 발생 조건 포함")
    label.set_defaults(handler=feedback)
    aggregate = sub.add_parser("stats", help="사람의 판정 집계")
    aggregate.add_argument("--runs", default=str(HERE / "runs"))
    aggregate.set_defaults(handler=stats)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "review":
        if min(args.timeout, args.workers, args.verify_batch_size, args.setup_timeout, args.test_timeout) <= 0 or args.max_followup_rounds < 0:
            print("오류: 시간 제한·workers·verify-batch-size는 양수, max-followup-rounds는 0 이상이어야 합니다.", file=sys.stderr)
            return 2
    try:
        result = args.handler(args)
        if args.command == "review" and result:
            manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
            return 3 if manifest["status"] == "incomplete" else 0
        return 0
    except KeyboardInterrupt:
        print("리뷰를 중단했습니다. 실행 이력을 확인하세요.", file=sys.stderr)
        return 130
    except (ReviewError, OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
