"""Bounded parallel reviews of a pinned tree. No SDK or third-party Python packages."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import time


def load_checks(args, api):
    config = {}
    if args.checks_config:
        path = Path(args.checks_config).expanduser().resolve()
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise api.ReviewError(f"검사 설정을 읽지 못했습니다: {path}: {exc}") from exc
        if not isinstance(config, dict) or set(config) - {"setup", "tests", "groups"}:
            raise api.ReviewError("검사 설정은 setup, tests, groups만 포함하는 JSON 객체여야 합니다.")
    checks = {}
    for name, cli in (("setup", args.setup_command), ("tests", args.test_command)):
        commands = config.get(name, [])
        if not isinstance(commands, list):
            raise api.ReviewError(f"{name}은 argv 배열들의 목록이어야 합니다.")
        try:
            commands = commands + [shlex.split(value) for value in cli]
        except ValueError as exc:
            raise api.ReviewError(f"명령 인수 해석 실패: {exc}") from exc
        if any(not isinstance(command, list) or not command or
               any(not isinstance(word, str) or not word or "\x00" in word for word in command)
               for command in commands):
            raise api.ReviewError(f"{name}의 각 명령은 비어 있지 않은 문자열 argv 배열이어야 합니다.")
        checks[name] = commands
    groups = config.get("groups", {})
    if not isinstance(groups, dict) or any(not isinstance(k, str) or not k or
            not isinstance(v, list) or not v or any(not isinstance(g, str) or not g for g in v)
            for k, v in groups.items()):
        raise api.ReviewError("groups는 그룹 이름과 경로 glob 목록을 연결하는 객체여야 합니다.")
    checks["groups"] = groups
    if (checks["setup"] or checks["tests"]) and not args.run_tests:
        raise api.ReviewError("설치·테스트 명령 실행에는 --run-tests가 필요합니다.")
    return checks


def read_source(snapshot, path, api, base=None):
    try:
        api.safe_path(path)
        if base:
            data = api.git(snapshot, "show", f"{base}:{path}", binary=True)
        else:
            target = snapshot / path
            if not target.resolve().is_relative_to(snapshot.resolve()) or not target.is_file():
                return None
            data = target.read_bytes()
        return data.decode("utf-8") if b"\x00" not in data else None
    except (api.ReviewError, OSError, UnicodeError):
        return None


def family(path):
    """Conservative directory affinity; imports and user groups refine this hint."""
    parts = list(PurePosixPath(path).parts)
    if parts[:2] == [".github", "workflows"]:
        return ".github/workflows"
    for index, part in enumerate(parts):
        if part in ("core", "modules", "features", "services") and index + 1 < len(parts):
            return "/".join(parts[:index + 2])
    if parts and parts[0] in ("apps", "packages") and len(parts) > 1:
        return "/".join(parts[:2])
    if parts and parts[0] in ("src", "test", "tests"):
        return "/".join(parts[1:3]) or "root"
    return str(PurePosixPath(path).parent)


IMPORT = re.compile(r'''(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)["'](\.[^"']+)["']''')


def build_context(snapshot, changes, base, run, checks, api):
    """Materialize source evidence once. The lexical index never limits exploration."""
    started = time.monotonic()
    paths = [c["path"] for c in changes]
    tracked = [p for p in api.git(snapshot, "ls-files", "-z", binary=True).decode().split("\x00") if p]
    inventory = set(tracked + paths)
    imports, excerpts = [], []
    for path in paths:
        head = read_source(snapshot, path, api)
        old_path = next(c.get("old_path") or path for c in changes if c["path"] == path)
        before = read_source(snapshot, old_path, api, base)
        versions = {}
        for revision, source in (("head", head), ("base", before)):
            if source is None:
                versions[revision] = {"available": False}
                continue
            lines = source.splitlines()
            # Bounded convenience excerpts; the complete diff/tree remains accessible.
            versions[revision] = {"available": True, "sha256": hashlib.sha256(source.encode()).hexdigest(),
                "line_count": len(lines), "start_line": 1, "end_line": min(len(lines), 120),
                "excerpt": "\n".join(f"{i}: {line}" for i, line in enumerate(lines[:120], 1)),
                "truncated": len(lines) > 120}
            for match in IMPORT.finditer(source):
                specifier = match.group(1)
                revision_path = old_path if revision == "base" else path
                prefix = str(PurePosixPath(revision_path).parent / specifier)
                # Resolve relative lexical references without claiming compiler semantics.
                normalized = []
                for part in PurePosixPath(prefix).parts:
                    if part == "..":
                        if normalized:
                            normalized.pop()
                    elif part != ".":
                        normalized.append(part)
                prefix = "/".join(normalized)
                choices = [prefix] + [prefix + suffix for suffix in (".ts", ".tsx", ".js", ".jsx", ".py")]
                if prefix.endswith((".js", ".jsx")):
                    choices += [str(PurePosixPath(prefix).with_suffix(".ts")), str(PurePosixPath(prefix).with_suffix(".tsx"))]
                choices += [prefix + "/index" + suffix for suffix in (".ts", ".tsx", ".js")]
                target = next((p for p in choices if p in inventory), None)
                imports.append({"source": path, "source_path_at_revision": revision_path, "revision": revision,
                                "line": source[:match.start()].count("\n") + 1,
                                "specifier": specifier, "target": target})
        excerpts.append({"path": path, "old_path": old_path, "versions": versions})
    guidance = set()
    for path in paths:
        for parent in [PurePosixPath("."), *PurePosixPath(path).parents]:
            for name in ("AGENTS.md", "README.md", "package.json", "pyproject.toml", "tsconfig.json"):
                candidate = str(parent / name)
                if candidate in inventory:
                    guidance.add(candidate)
    guidance_sources = []
    for path in sorted(guidance):
        source = read_source(snapshot, path, api)
        if source is None:
            continue
        lines = source.splitlines()
        end = len(lines) if PurePosixPath(path).name == "AGENTS.md" else min(len(lines), 120)
        guidance_sources.append({"path": path, "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "line_count": len(lines), "excerpt": "\n".join(f"{i}: {line}" for i, line in enumerate(lines[:end], 1)),
            "truncated": end < len(lines)})
    api.write_json(run / "source-inventory.json", sorted(inventory))
    pack = {"merge_base": base, "head": api.git(snapshot, "rev-parse", "HEAD"),
            "diff_file": str(run / "change.diff"), "changes": changes,
            "source_excerpts": excerpts, "relative_import_hints": imports,
            "guidance_paths": sorted(guidance), "guidance_sources": guidance_sources,
            "source_inventory": str(run / "source-inventory.json"),
            "limitations": ["Relative-import hints are lexical, not AST/type resolution. Aliases, dynamic calls, consumers and base-only files may be absent.",
                            "Code and general documentation excerpts stop at line 120; AGENTS.md is retained in full. Read the full diff/source; excerpts are not coverage."]}
    api.write_json(run / "context-pack.json", pack)
    parent = {p: p for p in paths}
    def root(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p
    def union(a, b):
        parent[root(b)] = root(a)
    by_family = {}
    for p in paths:
        if family(p) in by_family:
            union(p, by_family[family(p)])
        by_family[family(p)] = p
    for link in imports:
        if link["target"] in parent:
            union(link["source"], link["target"])
    components = {}
    for p in paths:
        components.setdefault(root(p), []).append(p)
    groups = []
    if checks["groups"]:
        assigned = set()
        for name, patterns in checks["groups"].items():
            members = [p for p in paths if any(fnmatch.fnmatchcase(p, pattern) for pattern in patterns)]
            overlap = set(members) & assigned
            if overlap:
                raise api.ReviewError(f"명시 그룹에 중복 경로가 있습니다: {sorted(overlap)}")
            if members:
                groups.append({"name": name, "paths": members, "origin": "explicit"})
                assigned.update(members)
        for members in components.values():
            remaining = [p for p in members if p not in assigned]
            if remaining:
                groups.append({"name": family(remaining[0]), "paths": remaining, "origin": "directory/import hints"})
    else:
        groups = [{"name": family(members[0]), "paths": members, "origin": "directory/import hints"}
                  for members in components.values()]
    assignments = [p for g in groups for p in g["paths"]]
    if len(assignments) != len(set(assignments)) or set(assignments) != set(paths):
        raise api.ReviewError("탐색 그룹이 변경 경로를 정확히 한 번씩 배정하지 않았습니다.")
    api.write_json(run / "work-plan.json", {"groups": groups, "crosscutting": True,
        "partitioning": "Affinity hints only; investigators may follow references anywhere in the pinned tree.",
        "context_wall_seconds": round(time.monotonic() - started, 3)})
    return groups


def clone_frozen(snapshot, destination, api):
    """Share only immutable Git objects from our run, never the original repository."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--quiet", "--shared",
                             "--no-checkout", "--", str(snapshot), str(destination)], capture_output=True)
    if result.returncode:
        raise api.ReviewError("검증 checkout 생성 실패: " + result.stderr.decode(errors="replace"))
    api.git(destination, "checkout", "--quiet", "--detach", api.git(snapshot, "rev-parse", "HEAD"))
    patch = api.git(snapshot, "diff", "--binary", "HEAD", binary=True)
    if patch:
        api.git(destination, "apply", "--binary", "-", input_data=patch)
    import shutil
    for path in api.untracked_paths(snapshot):
        api.safe_path(path)
        src, dst = snapshot / path, destination / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(src.readlink())
        else:
            shutil.copy2(src, dst)


def prepare_environment(snapshot, run, checks, args, api):
    started = time.monotonic()
    checkout = run / "validation-checkout"
    result = {"status": "preparing", "checkout": str(checkout), "setup": [], "tests": [],
              "started_at": api.utc_now(), "setup_status": "skipped", "tests_status": "skipped"}
    try:
        clone_frozen(snapshot, checkout, api)
        fingerprint = api.tree_fingerprint(checkout)
        head = api.git(checkout, "rev-parse", "HEAD")
        for kind, timeout in (("setup", args.setup_timeout), ("tests", args.test_timeout)):
            if kind == "tests" and result["setup_status"] == "failed":
                result["tests_skip_reason"] = "setup failed; no product test result"
                break
            for index, argv in enumerate(checks[kind], 1):
                if args._cancel_event.is_set():
                    raise api.ReviewError("환경 준비가 취소되었습니다.")
                log = run / f"{kind}-{index:03d}.log"
                begin = time.monotonic()
                record = {"argv": argv, "started_at": api.utc_now(), "log": str(log)}
                print(f"[{kind}-{index:03d}] 설정된 명령 실행 중…", flush=True)
                with log.open("w", encoding="utf-8") as output:
                    process = subprocess.Popen(argv, cwd=checkout, stdout=output, stderr=subprocess.STDOUT,
                                               text=True, start_new_session=True)
                    try:
                        while process.poll() is None:
                            if args._cancel_event.is_set():
                                raise api.ReviewError("설정된 명령 실행이 취소되었습니다.")
                            if time.monotonic() - begin >= timeout:
                                record["timed_out"] = True
                                api.stop_process(process)
                                break
                            try:
                                process.wait(timeout=0.2)
                            except subprocess.TimeoutExpired:
                                pass
                    except BaseException:
                        api.stop_process(process)
                        raise
                record.update({"finished_at": api.utc_now(), "wall_seconds": round(time.monotonic() - begin, 3),
                    "exit_code": process.returncode, "status": "passed" if process.returncode == 0 else "failed"})
                # Keep large install logs out of every model prompt; preserve complete logs on disk.
                with log.open("rb") as output:
                    output.seek(max(0, log.stat().st_size - 2000))
                    record["output_tail"] = output.read().decode(errors="replace")
                result[kind].append(record)
                api.check_unchanged(checkout, fingerprint)
                if api.git(checkout, "rev-parse", "HEAD") != head:
                    raise api.ReviewError("설정된 명령이 검증 checkout의 HEAD를 변경했습니다.")
                if record["status"] == "failed":
                    result[kind + "_status"] = "failed"
                    if kind == "setup":
                        break
            if checks[kind] and result[kind + "_status"] != "failed":
                result[kind + "_status"] = "passed"
        result["status"] = "completed" if result["setup_status"] != "failed" else "setup_failed"
    except Exception as exc:
        result.update({"status": "failed", "error": str(exc)})
    finally:
        result.update({"finished_at": api.utc_now(), "wall_seconds": round(time.monotonic() - started, 3)})
        api.write_json(run / "checks.json", result)
    return result


def prepare_jobs(snapshot, run, packet, manifest, args, api, checks):
    groups = build_context(snapshot, manifest["changes"], packet["merge_base"], run, checks, api)
    shared = {**packet, "all_changes": packet["changes"], "context_pack": str(run / "context-pack.json"),
              "pipeline": True, "depth": args.depth}
    by_path = {c["path"]: c for c in packet["changes"]}
    pending = deque()
    # The global reviewer starts early and does not depend on another reviewer's conclusions.
    if args.depth == "deep" or len(groups) > 1:
        pending.append(("crosscut", "crosscut", {**shared, "investigation_kind": "crosscutting",
            "existing_candidates": [], "prior_reviews": []}))
    pack = json.loads((run / "context-pack.json").read_text())
    for index, group in enumerate(groups, 1):
        stage = f"discover-{index:03d}"
        guides = [g for g in pack["guidance_sources"] if str(PurePosixPath(g["path"]).parent) == "." or
                  any(p.startswith(str(PurePosixPath(g["path"]).parent) + "/") for p in group["paths"])]
        scoped = {**pack, "changes": [by_path[p] for p in group["paths"]],
                  "guidance_sources": guides, "guidance_paths": [g["path"] for g in guides],
                  "source_excerpts": [e for e in pack["source_excerpts"] if e["path"] in group["paths"]],
                  "relative_import_hints": [e for e in pack["relative_import_hints"] if e["source"] in group["paths"]],
                  "full_context_pack": str(run / "context-pack.json")}
        api.write_json(run / f"{stage}.context.json", scoped)
        pending.append((stage, "scout", {**shared, "investigation_kind": "scout",
            "context_pack": str(run / f"{stage}.context.json"),
            "changes": [by_path[p] for p in group["paths"]], "group": group,
            "existing_candidates": [], "prior_reviews": []}))
    return groups, shared, pending


def run_pipeline(snapshot, run, packet, manifest, args, api, checks):
    groups, shared, pending = prepare_jobs(snapshot, run, packet, manifest, args, api, checks)
    discoveries, candidates, verdicts, verification_results, limits = [], [], [], [], []
    candidate_rounds, aliases = {}, []
    waiting_verification = deque()
    active = {}
    fingerprint = api.tree_fingerprint(snapshot)
    head = api.git(snapshot, "rev-parse", "HEAD")
    environment = {"status": "disabled", "setup_status": "skipped", "tests_status": "skipped", "setup": [], "tests": []}
    verify_index, writable_active = 0, False
    def unchanged(checkout, before, original_head, repro_directory=None):
        api.check_unchanged(checkout, before)
        if api.git(checkout, "rev-parse", "HEAD") != original_head:
            raise api.ReviewError("리뷰 작업이 checkout의 HEAD를 변경했습니다.")
        tracked = api.git(checkout, "ls-files", "-z", binary=True).decode().split("\x00")
        new_paths = set(p for p in tracked + api.untracked_paths(checkout) if p) - set(before)
        if any(not repro_directory or not p.startswith(repro_directory + "/") for p in new_paths):
            raise api.ReviewError("리뷰 작업이 허용된 재현 경로 밖에 파일을 추가했습니다.")
    def investigate(stage, prompt, data):
        result, _ = api.run_codex(stage, prompt, data, api.DISCOVERY_SCHEMA, snapshot, run, args)
        unchanged(snapshot, fingerprint, head)
        allowed = {c["path"] for c in data["changes"]}
        reported = [c["path"] for c in result["coverage"]]
        if len(reported) != len(set(reported)) or set(reported) - allowed:
            raise api.ReviewError(f"{stage}: 검토 범위가 배정 범위를 벗어나거나 중복됐습니다.")
        for path in sorted(allowed - set(reported)):
            result["coverage"].append({"path": path, "status": "not_reviewed", "reason": "담당 작업의 범위 보고가 누락되었습니다."})
        result["_stage"] = stage
        return result
    def verify(stage, batch, data, checkout, writable):
        before = api.tree_fingerprint(checkout)
        original_head = api.git(checkout, "rev-parse", "HEAD")
        result, commands = api.run_codex(stage, "verify", data, api.PIPELINE_VERIFICATION_SCHEMA,
                                        checkout, run, args, writable=writable)
        unchanged(checkout, before, original_head, data.get("repro_directory") if writable else None)
        # Findings must cite the pinned input tree, not newly created repro or dependency files.
        normalized = api.normalize_verdicts(result, batch, snapshot, packet["merge_base"], commands,
                                            writable, defer_duplicates=True)
        result["_stage"] = stage
        return result, normalized
    def register(items, source, round_number=0):
        added = []
        for item in items:
            # Identical verification follow-ups link to an existing hypothesis; scouts retain their independent observations.
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            existing = next((c for c in candidates if json.dumps({k: c[k] for k in api.CANDIDATE["properties"]},
                                 sort_keys=True, ensure_ascii=False) == key), None) if round_number else None
            if existing:
                aliases.append({"source": source, "candidate_id": existing["id"], "reason": "identical follow-up hypothesis"})
                continue
            identifier = f"C{len(candidates) + 1:04d}"
            candidate = {"id": identifier, "discovery_stage": source, **item}
            candidates.append(candidate)
            candidate_rounds[identifier] = round_number
            if round_number > args.max_followup_rounds:
                verdicts.append({"candidate_id": identifier, "status": "unresolved", "duplicate_of": None,
                                 "finding": None, "reason": "새 후보의 후속 검증 회수 제한에 도달했습니다."})
            else:
                added.append(candidate)
        if added:
            for start in range(0, len(added), args.verify_batch_size):
                waiting_verification.append(added[start:start + args.verify_batch_size])
        api.write_json(run / "candidates.json", candidates)
        api.write_json(run / "candidate-links.json", aliases)
    pool = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="review")
    try:
        if args.run_tests:
            future = pool.submit(prepare_environment, snapshot, run, checks, args, api)
            active[future] = ("environment", "environment", None)
            environment["status"] = "preparing"
        while pending or waiting_verification or active:
            if args._cancel_event.is_set():
                raise api.ReviewError("병렬 리뷰가 취소되었습니다.")
            while len(active) < args.workers:
                can_verify = waiting_verification and environment["status"] != "preparing" and not writable_active
                if can_verify:
                    batch = waiting_verification.popleft()
                    verify_index += 1
                    stage = f"verify-{verify_index:03d}"
                    writable = args.run_tests and environment["status"] == "completed"
                    checkout = Path(environment["checkout"]) if writable else snapshot
                    data = {**shared, "investigation_kind": "verification", "candidates": batch,
                            "known_candidates": list(candidates), "prior_verdicts": list(verdicts),
                            "prior_reviews": [{k: d[k] for k in ("summary", "coverage", "limitations")} for d in discoveries],
                            "validation_environment": environment, "test_execution_enabled": writable,
                            "repro_directory": f".review-repros/{stage}"}
                    active[pool.submit(verify, stage, batch, data, checkout, writable)] = (stage, "verify", batch)
                    # Share a prepared writable checkout only serially. Read-only verifiers may run in parallel.
                    writable_active = writable_active or writable
                    if writable:
                        break
                elif pending:
                    stage, prompt, data = pending.popleft()
                    active[pool.submit(investigate, stage, prompt, data)] = (stage, "discover", data)
                else:
                    break
            if not active:
                raise api.ReviewError("검증 대기열이 진행되지 못했습니다.")
            done, _ = wait(active, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda f: active[f][0]):
                stage, kind, data = active.pop(future)
                if kind == "environment":
                    environment = future.result()
                    if environment["status"] != "completed" or environment["tests_status"] == "failed":
                        limits.append("환경 준비·회귀 검사 실패: checks.json과 명령 로그를 확인하세요. 제품 버그 여부는 별도 검증이 필요합니다.")
                    continue
                try:
                    completed = future.result()
                    if kind == "discover":
                        discoveries.append(completed)
                        if any(c["status"] != "reviewed" for c in completed["coverage"]):
                            limits.append(f"{stage}: 배정 범위에 미검토 경로가 있습니다.")
                        register(completed["candidates"], stage)
                    else:
                        result, normalized = completed
                        verdicts.extend(normalized)
                        verification_results.append(result)
                        limits.extend(result["limitations"])
                        round_number = max(candidate_rounds[c["id"]] for c in data) + 1
                        register(result["new_candidates"], stage, round_number)
                except Exception as exc:
                    limits.append(f"{stage} 실행 실패: {exc}")
                    if kind == "verify":
                        verdicts.extend({"candidate_id": c["id"], "status": "unresolved", "reason": str(exc),
                                         "duplicate_of": None, "finding": None} for c in data)
                finally:
                    if kind == "verify" and args.run_tests:
                        writable_active = False
                api.write_json(run / "verdicts.json", verdicts)
                print(f"[{stage}] 처리 완료 · 후보 {len(candidates)} / 판정 {len(verdicts)}", flush=True)
    except BaseException:
        args._cancel_event.set()
        for future in active:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    unchanged(snapshot, fingerprint, head)
    indexed = {v["candidate_id"]: v for v in verdicts}
    if len(indexed) != len(verdicts) or set(indexed) != {c["id"] for c in candidates}:
        raise api.ReviewError("병렬 검증 결과에 후보 누락·중복이 있습니다.")
    # Reconciliation judges duplicate semantics and the whole change, never promotes unresolved findings.
    reconciliation = None
    if len(discoveries) > 1 or len(verification_results) > 1:
        data = {**shared, "investigation_kind": "reconciliation", "candidates": candidates,
                "verdicts": [{k: v[k] for k in ("candidate_id", "status", "reason", "duplicate_of", "finding")} for v in verdicts],
                "prior_reviews": [{"stage": d["_stage"], **{k: d[k] for k in ("summary", "assessment", "coverage", "limitations")}} for d in discoveries],
                "verification_assessments": [{"stage": v["_stage"], "assessment": v["assessment"]} for v in verification_results],
                "validation_environment": environment, "runner_limitations": limits}
        try:
            reconciliation, _ = api.run_codex("reconcile", "reconcile", data, api.RECONCILIATION_SCHEMA,
                                              snapshot, run, args)
            unchanged(snapshot, fingerprint, head)
            duplicate_ids = [v["candidate_id"] for v in reconciliation["duplicates"]]
            targets = {v["duplicate_of"] for v in reconciliation["duplicates"]}
            if len(set(duplicate_ids)) != len(duplicate_ids) or set(duplicate_ids) & targets:
                raise api.ReviewError("최종 중복 병합에 중복 ID 또는 순환·연쇄 대상이 있습니다.")
            for duplicate in reconciliation["duplicates"]:
                source, target = indexed.get(duplicate["candidate_id"]), indexed.get(duplicate["duplicate_of"])
                if (source is None or target is None or source["status"] != "confirmed" or target["status"] != "confirmed"
                    or not duplicate["reason"].strip() or target["finding"]["priority"] > source["finding"]["priority"]):
                    raise api.ReviewError("최종 중복 병합은 확인된 후보 사이에서 우선순위를 보존해야 합니다.")
            for duplicate in reconciliation["duplicates"]:
                indexed[duplicate["candidate_id"]].update({"status": "duplicate", "duplicate_of": duplicate["duplicate_of"],
                                                         "finding": None, "reason": duplicate["reason"]})
            limits.extend(reconciliation["limitations"])
        except Exception as exc:
            limits.append(f"최종 정리 실패: {exc}")
            reconciliation = None
    for verdict in verdicts:
        if verdict["status"] == "duplicate":
            target = indexed.get(verdict["duplicate_of"])
            if target is None or target["status"] != "confirmed" or target is verdict:
                verdict.update({"status": "unresolved", "duplicate_of": None, "finding": None,
                                "reason": verdict["reason"] + " [중복 대상이 확인된 후보가 아닙니다.]"})
    verdicts.sort(key=lambda v: v["candidate_id"])
    discoveries.sort(key=lambda d: d["_stage"])
    verification = None
    if reconciliation:
        verification = {"_stage": "reconcile", "assessment": reconciliation["assessment"], "limitations": limits,
                        "verdicts": verdicts, "_candidate_verification_performed": bool(verification_results)}
    elif verification_results:
        lowest = min(verification_results, key=lambda v: v["assessment"]["confidence_score"])
        verification = {"_stage": "verification aggregate", "assessment": lowest["assessment"], "limitations": limits,
                        "verdicts": verdicts, "_candidate_verification_performed": True}
    if verification:
        verification["_stage_assessments"] = [{"stage": v["_stage"], **v["assessment"]} for v in verification_results]
    if reconciliation and discoveries:
        # Keep raw job summaries on disk. This field represents the entire change, not the last partition.
        discoveries[-1] = {**discoveries[-1], "summary": reconciliation["summary"]}
    for discovery in discoveries:
        limits.extend(discovery["limitations"])
    manifest["limitations"].extend(limits)
    manifest["checks"] = environment
    manifest["pipeline"] = {"workers": args.workers, "groups": len(groups),
                            "crosscutting": args.depth == "deep" or len(groups) > 1,
                            "candidate_delivery": "after each discovery job's schema-validated result",
                            "writable_verifiers": 1, "verify_batch_size": args.verify_batch_size,
                            "max_followup_rounds": args.max_followup_rounds}
    api.write_json(run / "checks.json", environment)
    return discoveries, candidates, verdicts, verification, limits


def performance(run, manifest, api):
    stages = []
    usage = {}
    for path in sorted(run.glob("*.metrics.json")):
        metric = json.loads(path.read_text())
        stages.append(metric)
        for key, value in metric.get("usage", {}).items():
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + value
    from datetime import datetime
    elapsed = (datetime.fromisoformat(manifest["finished_at"]) - datetime.fromisoformat(manifest["started_at"])).total_seconds()
    result = {"wall_seconds": round(elapsed, 3), "stage_work_seconds": round(sum(m["wall_seconds"] for m in stages), 3),
              "usage": usage, "stages": stages,
              "note": "Stage work overlaps in parallel mode. Command times include tool/sandbox latency; token usage is reported by Codex, not a billing estimate."}
    api.write_json(run / "performance.json", result)
    return result
