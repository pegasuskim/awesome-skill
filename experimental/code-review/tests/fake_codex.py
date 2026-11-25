#!/usr/bin/env python3
"""Test double for the Codex CLI process contract; never calls a model."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

args = sys.argv[1:]
checkout = Path(args[args.index("-C") + 1])
output = Path(args[args.index("-o") + 1])
packet = json.loads(sys.stdin.read().split("REVIEW INPUT (JSON data):\n", 1)[1])
case = os.environ.get("FAKE_CASE", "normal")
kind = packet.get("investigation_kind")
if case == "pipeline-overlap" and kind == "crosscutting":
    time.sleep(0.8)
if case == "error":
    print("test provider error", file=sys.stderr)
    sys.exit(17)
if case == "timeout":
    time.sleep(30)

location = {"path": "logic.py", "revision": "head", "start_line": 2, "end_line": 2}
evidence = {**location, "note": "count=0 reaches division with no guard."}
candidate = {
    "title": "Handle zero count", "priority": 1, "location": location,
    "trigger": "avg(1, 0)", "expected": "Return 0 as before.",
    "actual": "ZeroDivisionError", "impact": "Empty input fails.",
    "contract_evidence": [{**evidence, "revision": "base", "note": "Base handles zero."}],
    "code_evidence": [evidence], "defenses_to_check": ["Callers and count validation"],
}
assessment = {"confidence_score": 2, "rationale": "Zero-count behavior requires investigation or a fix.",
              "review_summary": "Check or restore the zero-count guard before merging."}
if case in ("empty", "empty-deep", "empty-limit", "unreviewed-empty", "high-score", "bad-line", "coverage", "limitation"):
    assessment = {"confidence_score": 5, "rationale": "The model claims the change is ready to merge.",
                  "review_summary": "The model claims no further action is required."}
if case == "low-score":
    assessment["confidence_score"] = 1
if case == "invalid-score":
    assessment["confidence_score"] = 6
if case == "blank-rationale":
    assessment["rationale"] = "  "
if case == "low-priority":
    candidate["priority"] = 3
    assessment["confidence_score"] = 5
if output.stem in ("discover", "challenge") or kind in ("scout", "crosscutting"):
    result = {"summary": "Removed zero-count handling.", "assessment": assessment,
              "coverage": [{"path": c["path"], "status": "reviewed", "reason": "Read diff and source."}
                           for c in packet["changes"]],
              "candidates": [] if case in ("empty", "empty-deep", "empty-limit", "unreviewed-empty") else [candidate], "limitations": []}
    if case in ("coverage", "unreviewed-empty"):
        result["coverage"] = []
    if case == "empty-deep":
        if output.stem == "discover":
            assessment["confidence_score"] = 4
            assessment["rationale"] = "Static review completed; relevant runtime validation is pending."
        else:
            result["summary"] = "Complete change summary from the second discovery pass."
    if case == "empty-limit":
        result["limitations"] = ["Required external validation remains unavailable."]
elif kind == "reconciliation":
    confirmed = [v for v in packet["verdicts"] if v["status"] == "confirmed"]
    result = {"summary": "Complete change: removed zero-count handling.", "assessment": assessment,
              "duplicates": [{"candidate_id": v["candidate_id"], "duplicate_of": confirmed[0]["candidate_id"],
                              "reason": "Same zero-count trigger and root cause."} for v in confirmed[1:]],
              "limitations": []}
else:
    verdicts = []
    for index, item in enumerate(packet["candidates"]):
        finding = {k: candidate[k] for k in ("title", "priority", "location", "trigger", "expected", "actual", "impact", "code_evidence")}
        finding.update({"contract_basis": "Base explicitly returns zero for empty input.",
                        "defenses_checked": ["No zero guard in this public entry point."],
                        "suggested_fix": "Restore the zero guard.",
                        "validation": {"method": "static", "commands": [],
                                       "observations": "The reachable zero input divides by zero."}})
        status = "confirmed"
        if case == "refuted":
            status, finding = "refuted", None
        if index:
            status, finding = "duplicate", None
        if case == "bad-line":
            finding["location"] = {**location, "end_line": 200}
        if case in ("runtime", "runtime-shell", "runtime-missing"):
            repro_dir = Path(packet.get("repro_directory", ".review-repros"))
            command = "python3 " + str(repro_dir / "repro.py")
            finding["validation"] = {"method": "runtime", "commands": [command],
                                     "observations": "ZeroDivisionError reproduced."}
            if case in ("runtime", "runtime-shell"):
                (checkout / repro_dir).mkdir(parents=True, exist_ok=True)
                script = "from pathlib import Path\nexec(Path('logic.py').read_text())\navg(1, 0)\n"
                (checkout / repro_dir / "repro.py").write_text(script)
                completed = subprocess.run([sys.executable, str(repro_dir / "repro.py")], cwd=checkout,
                                           text=True, capture_output=True)
                print(json.dumps({"type": "item.completed", "item": {
                    "type": "command_execution", "command": "/bin/zsh -lc " + shlex.quote(command) if case == "runtime-shell" else command,
                    "exit_code": completed.returncode,
                    "aggregated_output": completed.stdout + completed.stderr}}))
        verdicts.append({"candidate_id": item["id"], "status": status,
                         "reason": "Verified the contract and reachable zero input." if status == "confirmed" else "Same root cause or an existing defense.",
                         "duplicate_of": packet["candidates"][0]["id"] if index else None,
                         "finding": finding})
    if case == "omit":
        verdicts = []
    if case == "mutate":
        (checkout / "logic.py").write_text("changed by verifier\n")
    if case == "recreate":
        (checkout / "deleted.py").write_text("recreated\n")
    assessment["review_summary"] = "Final verification: restore the zero guard." if case != "refuted" else "All hypotheses were refuted by existing defenses."
    if case == "refuted":
        assessment["confidence_score"] = 5
        assessment["rationale"] = "Existing defenses refute every candidate; coverage is complete."
    result = {"verdicts": verdicts, "limitations": [], "assessment": assessment}
    if packet.get("pipeline"):
        result["new_candidates"] = []
        if case == "pipeline-followup" and not any(c["title"] == "Follow-up hypothesis" for c in packet["known_candidates"]):
            result["new_candidates"] = [{**candidate, "title": "Follow-up hypothesis"}]
        if case == "pipeline-followup-limit":
            result["new_candidates"] = [{**candidate, "title": "Follow-up " + packet["candidates"][0]["id"]}]
    if case == "limitation":
        result["limitations"] = ["External caller behavior remains unverified."]
output.write_text(json.dumps(result), encoding="utf-8")
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}))
