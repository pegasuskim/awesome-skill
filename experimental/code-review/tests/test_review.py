import json
import os
from pathlib import Path
import shutil
from shlex import join as shlex_join
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
CLI = HERE / "review.py"
FAKE = HERE / "tests" / "fake_codex.py"


class ReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        (HERE / "runs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="test-", dir=HERE / "runs")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo spaces 한글"
        self.repo.mkdir()
        self.out = self.root / "results"
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Review Test")
        self.git("config", "user.email", "review-test@example.invalid")
        (self.repo / ".gitignore").write_text("ignored.txt\nruns/\n")
        (self.repo / "logic.py").write_text("def avg(total, count):\n    return total / count if count else 0\n")
        (self.repo / "deleted.py").write_text("before = True\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "feature")
        (self.repo / "logic.py").write_text("def avg(total, count):\n    return total / count\n")
        self.git("add", "logic.py")
        self.git("commit", "-qm", "change")
        self.head = self.git("rev-parse", "HEAD")
        self.codex = self.root / "fake codex"
        shutil.copy2(FAKE, self.codex)
        self.codex.chmod(0o755)

    def git(self, *args):
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(self.repo), *args],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args, case="normal", expected=0):
        env = {**os.environ, "FAKE_CASE": case}
        result = subprocess.run([sys.executable, str(CLI), *args], env=env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def review(self, *args, case="normal", expected=0):
        result = self.cli("review", "--repo", str(self.repo), "--base", "main",
                          "--execution", "serial",
                          "--output-dir", str(self.out), "--codex", str(self.codex),
                          *args, case=case, expected=expected)
        runs = sorted(self.out.iterdir(), key=lambda p: p.stat().st_mtime_ns)
        return runs[-1], result

    def load(self, run, name):
        return json.loads((run / name).read_text())

    def test_review_pins_commits_and_preserves_source(self):
        before = self.git("status", "--porcelain")
        run, _ = self.review()
        manifest = self.load(run, "manifest.json")
        self.assertEqual(manifest["merge_base"], self.base)
        self.assertEqual(manifest["head"], self.head)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(self.load(run, "findings.json")), 1)
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.git("branch", "--show-current"), "feature")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertTrue((run / "report.md").is_file())

    def test_summary_uses_final_verification_and_records_evidence_counts(self):
        run, result = self.review("--depth", "deep")
        summary = self.load(run, "summary.json")
        self.assertEqual(summary["review_summary"], "Final verification: restore the zero guard.")
        self.assertEqual(summary["confidence"]["source_stage"], "verify")
        self.assertEqual(summary["counts"], {"candidates": 2, "confirmed": 1, "refuted": 0,
                                             "unresolved": 0, "duplicate": 1})
        self.assertEqual(summary["priorities"]["P1"], 1)
        self.assertEqual(summary["coverage"]["reviewed"], 1)
        self.assertEqual(summary["validation"]["runtime_confirmed"], 0)
        self.assertEqual(summary["validation"]["static_confirmed"], 1)
        self.assertEqual(len(list(run.glob("*.command.json"))), 3)
        packet = json.loads((run / "verify.prompt.md").read_text().split("REVIEW INPUT (JSON data):\n", 1)[1])
        self.assertEqual(len(packet["prior_reviews"]), 2)
        report = (run / "report.md").read_text()
        self.assertIn("## Confidence Score: 2/5", report)
        self.assertIn("## Summary", report)
        self.assertIn(summary["review_summary"], report)
        self.assertIn("Confidence Score: 2/5", result.stdout)

    def test_confidence_cannot_override_findings_or_runner_evidence_checks(self):
        cases = (("high-score", 0, 2, "confirmed"), ("low-priority", 0, 4, "confirmed"),
                 ("bad-line", 3, 3, "unresolved"), ("unreviewed-empty", 3, 3, None))
        for case, exit_code, score, verdict in cases:
            with self.subTest(case=case):
                run, _ = self.review(case=case, expected=exit_code)
                summary = self.load(run, "summary.json")
                self.assertEqual(summary["confidence"]["model_score"], 5)
                self.assertEqual(summary["confidence"]["score"], score)
                self.assertTrue(summary["confidence"]["adjustments"])
                self.assertNotIn("no further action", (run / "report.md").read_text())
                verdicts = self.load(run, "verdicts.json")
                if verdict:
                    self.assertEqual(verdicts[0]["status"], verdict)
                else:
                    self.assertEqual(verdicts, [])

    def test_low_model_score_is_never_raised_by_score_caps(self):
        run, _ = self.review(case="low-score")
        confidence = self.load(run, "summary.json")["confidence"]
        self.assertEqual(confidence["score"], 1)
        self.assertEqual(confidence["adjustments"], [])

    def test_deep_without_candidates_preserves_lower_score_and_complete_summary(self):
        run, _ = self.review("--depth", "deep", "--run-tests", case="empty-deep")
        summary = self.load(run, "summary.json")
        self.assertEqual(summary["confidence"]["score"], 4)
        self.assertEqual(summary["confidence"]["source_stage"], "discover")
        self.assertEqual(summary["change_summary"], "Complete change summary from the second discovery pass.")
        self.assertEqual(summary["counts"]["candidates"], 0)
        self.assertFalse(summary["validation"]["verification_performed"])
        self.assertEqual(summary["validation"]["runtime_confirmed"], 0)
        self.assertFalse((run / "verify.command.json").exists())
        self.assertEqual(len(list(run.glob("*.command.json"))), 2)

    def test_clean_static_assessment_may_score_five_without_claiming_test_execution(self):
        run, _ = self.review("--run-tests", case="empty")
        summary = self.load(run, "summary.json")
        self.assertEqual(summary["confidence"]["score"], 5)
        self.assertEqual(summary["validation"]["runtime_confirmed"], 0)
        self.assertFalse(summary["validation"]["verification_performed"])

    def test_invalid_score_or_missing_rationale_fails_without_publishing_summary(self):
        for case in ("invalid-score", "blank-rationale"):
            with self.subTest(case=case):
                run, _ = self.review(case=case, expected=2)
                self.assertEqual(self.load(run, "manifest.json")["status"], "failed")
                self.assertFalse((run / "summary.json").exists())
                self.assertNotIn("Confidence Score", (run / "report.md").read_text())

    def test_uncommitted_staged_unstaged_and_untracked_are_frozen(self):
        (self.repo / "logic.py").write_text("def avg(total, count):\n    return total / count\n# staged\n")
        self.git("add", "logic.py")
        with (self.repo / "logic.py").open("a") as stream:
            stream.write("# unstaged\n")
        (self.repo / "new 한글.txt").write_text("untracked\n")
        (self.repo / "ignored.txt").write_text("ignored\n")
        before_status = self.git("status", "--porcelain")
        before_index = self.git("diff", "--cached", "--binary")
        run, _ = self.review("--uncommitted")
        snapshot = run / "checkout"
        self.assertEqual((snapshot / "logic.py").read_text(), (self.repo / "logic.py").read_text())
        self.assertEqual((snapshot / "new 한글.txt").read_text(), "untracked\n")
        self.assertFalse((snapshot / "ignored.txt").exists())
        self.assertIn("new 한글.txt", [c["path"] for c in self.load(run, "manifest.json")["changes"]])
        self.assertEqual(self.git("status", "--porcelain"), before_status)
        self.assertEqual(self.git("diff", "--cached", "--binary"), before_index)

    def test_default_excludes_dirty_changes_and_records_it(self):
        (self.repo / "extra.txt").write_text("dirty\n")
        run, _ = self.review(case="empty")
        self.assertFalse((run / "checkout" / "extra.txt").exists())
        self.assertTrue(any("커밋되지 않은" in s for s in self.load(run, "manifest.json")["limitations"]))
        self.assertEqual(self.load(run, "summary.json")["confidence"]["score"], 4)

    def test_dry_run_never_calls_codex(self):
        run, _ = self.review("--dry-run", case="error")
        self.assertEqual(self.load(run, "manifest.json")["status"], "prepared")
        self.assertTrue((run / "discover.prompt.md").is_file())
        self.assertFalse((run / "discover.events.jsonl").exists())

    def test_deep_candidates_all_accounted_and_deduplicated(self):
        run, _ = self.review("--depth", "deep")
        self.assertEqual(len(self.load(run, "candidates.json")), 2)
        self.assertEqual([v["status"] for v in self.load(run, "verdicts.json")], ["confirmed", "duplicate"])
        self.assertEqual(len(self.load(run, "findings.json")), 1)

    def test_hallucinated_line_is_unresolved(self):
        run, _ = self.review(case="bad-line", expected=3)
        self.assertEqual(self.load(run, "verdicts.json")[0]["status"], "unresolved")
        self.assertEqual(self.load(run, "findings.json"), [])

    def test_runtime_claim_requires_actual_command_event(self):
        run, _ = self.review("--run-tests", case="runtime-missing", expected=3)
        self.assertEqual(self.load(run, "findings.json"), [])

    def test_runtime_reproduction_records_real_failure(self):
        run, _ = self.review("--run-tests", case="runtime")
        evidence = self.load(run, "verify.commands.json")[0]
        self.assertNotEqual(evidence["exit_code"], 0)
        self.assertIn("ZeroDivisionError", evidence["output"])
        self.assertEqual(len(self.load(run, "findings.json")), 1)

    def test_shell_wrapped_execution_is_matched_without_substring_matching(self):
        run, _ = self.review("--run-tests", case="runtime-shell")
        finding = self.load(run, "findings.json")[0]
        self.assertIn("/bin/zsh -lc", finding["execution_evidence"][0]["command"])

    def test_model_limitations_keep_review_incomplete(self):
        run, _ = self.review(case="limitation", expected=3)
        self.assertEqual(self.load(run, "manifest.json")["status"], "incomplete")
        run, _ = self.review(case="empty-limit", expected=3)
        summary = self.load(run, "summary.json")
        self.assertEqual(summary["counts"]["confirmed"], 0)
        self.assertEqual(summary["confidence"]["score"], 3)
        self.assertTrue(summary["limitations"])

    def test_omitted_verdict_fails_entire_review(self):
        run, _ = self.review(case="omit", expected=2)
        self.assertEqual(self.load(run, "manifest.json")["status"], "failed")
        self.assertFalse((run / "findings.json").exists())

    def test_mutating_existing_file_fails_and_original_is_preserved(self):
        before = (self.repo / "logic.py").read_bytes()
        run, _ = self.review("--run-tests", case="mutate", expected=2)
        self.assertEqual(self.load(run, "manifest.json")["status"], "failed")
        self.assertEqual((self.repo / "logic.py").read_bytes(), before)

    def test_recreating_deleted_tracked_file_is_detected(self):
        (self.repo / "deleted.py").unlink()
        run, _ = self.review("--uncommitted", "--run-tests", case="recreate", expected=2)
        self.assertEqual(self.load(run, "manifest.json")["status"], "failed")
        self.assertFalse((self.repo / "deleted.py").exists())

    def test_missing_coverage_is_incomplete(self):
        run, _ = self.review(case="coverage", expected=3)
        self.assertEqual(self.load(run, "manifest.json")["status"], "incomplete")
        self.assertIn("미검토", (run / "report.md").read_text())

    def test_provider_failure_and_timeout_leave_failed_history(self):
        for case, args in (("error", []), ("timeout", ["--timeout", "1"])):
            with self.subTest(case=case):
                run, _ = self.review(*args, case=case, expected=2)
                self.assertEqual(self.load(run, "manifest.json")["status"], "failed")
                self.assertIn("미완료", (run / "report.md").read_text())

    def test_no_change_skips_model(self):
        run, _ = self.review("--head", "main", case="error")
        self.assertEqual(self.load(run, "manifest.json")["changes"], [])
        self.assertFalse((run / "discover.events.jsonl").exists())
        summary = self.load(run, "summary.json")
        self.assertIsNone(summary["confidence"]["score"])
        self.assertEqual(summary["stage_assessments"], [])
        self.assertIn("Confidence Score: 미산정", (run / "report.md").read_text())

    def test_rename_and_merge_base_inventory(self):
        self.git("mv", "deleted.py", "renamed file.py")
        self.git("commit", "-qm", "rename")
        run, _ = self.review("--dry-run")
        entry = next(c for c in self.load(run, "manifest.json")["changes"] if c["path"] == "renamed file.py")
        self.assertTrue(entry["status"].startswith("R"))
        self.assertEqual(entry["old_path"], "deleted.py")

    def test_diverged_base_uses_merge_base_not_latest_target_tree(self):
        self.git("checkout", "-q", "main")
        (self.repo / "target-only.txt").write_text("target branch only\n")
        self.git("add", "target-only.txt")
        self.git("commit", "-qm", "target update")
        self.git("checkout", "-q", "feature")
        run, _ = self.review("--dry-run")
        manifest = self.load(run, "manifest.json")
        self.assertEqual(manifest["merge_base"], self.base)
        self.assertNotEqual(manifest["base_tip"], self.base)
        self.assertNotIn("target-only.txt", [c["path"] for c in manifest["changes"]])

    def test_extra_context_is_saved_and_supplied(self):
        context = self.root / "contracts.md"
        context.write_text("Zero-count input must return zero.\n")
        run, _ = self.review("--context", str(context))
        self.assertIn("Zero-count input", (run / "discover.prompt.md").read_text())
        self.assertEqual(self.load(run, "context.json")[0]["name"], "contracts.md")

    def test_default_base_and_model_overrides(self):
        self.cli("review", "--repo", str(self.repo), "--output-dir", str(self.out),
                 "--execution", "serial",
                 "--codex", str(self.codex), "--model", "test-model", "--reasoning", "high")
        run = next(self.out.iterdir())
        command = self.load(run, "discover.command.json")
        self.assertEqual(self.load(run, "manifest.json")["base_ref"], "main")
        self.assertIn("test-model", command)
        self.assertIn('model_reasoning_effort="high"', command)

    def test_refuted_candidate_not_reported(self):
        run, _ = self.review(case="refuted")
        self.assertEqual(self.load(run, "findings.json"), [])
        self.assertEqual(self.load(run, "verdicts.json")[0]["status"], "refuted")
        summary = self.load(run, "summary.json")
        self.assertEqual(summary["stage_assessments"][0]["confidence_score"], 2)
        self.assertEqual(summary["confidence"]["score"], 5)
        self.assertEqual(summary["confidence"]["source_stage"], "verify")
        self.assertEqual(summary["counts"]["refuted"], 1)

    def test_parallel_verifies_before_global_discovery_finishes(self):
        run, _ = self.review("--execution", "parallel", "--depth", "deep", "--workers", "2", case="pipeline-overlap")
        verification = self.load(run, "verify-001.metrics.json")
        crosscut = self.load(run, "crosscut.metrics.json")
        self.assertLess(verification["started_at"], crosscut["finished_at"])
        self.assertEqual(len(self.load(run, "findings.json")), 1)
        verdicts = self.load(run, "verdicts.json")
        self.assertEqual(sorted(v["status"] for v in verdicts), ["confirmed", "duplicate"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.load(run, "performance.json")["usage"]["input_tokens"], 5)

    def test_parallel_runs_configured_tests_without_candidates(self):
        command = shlex_join([sys.executable, "-c", "from pathlib import Path; Path('.review-repros').mkdir(); Path('.review-repros/check-marker').write_text('passed')"])
        run, _ = self.review("--execution", "parallel", "--run-tests", "--test-command", command, case="empty")
        checks = self.load(run, "checks.json")
        self.assertEqual(checks["tests_status"], "passed")
        self.assertTrue((run / "validation-checkout" / ".review-repros" / "check-marker").exists())
        self.assertFalse((self.repo / ".review-repros").exists())
        self.assertEqual(self.load(run, "summary.json")["counts"]["candidates"], 0)
        self.assertFalse(self.load(run, "summary.json")["validation"]["verification_performed"])

    def test_parallel_setup_failure_skips_tests_and_keeps_static_evidence(self):
        run, _ = self.review("--execution", "parallel", "--run-tests",
            "--setup-command", shlex_join([sys.executable, "-c", "raise SystemExit(9)"]),
            "--test-command", shlex_join([sys.executable, "-c", "print('must not run')"]), expected=3)
        checks = self.load(run, "checks.json")
        self.assertEqual(checks["setup_status"], "failed")
        self.assertEqual(checks["tests"], [])
        packet = json.loads((run / "verify-001.prompt.md").read_text().split("REVIEW INPUT (JSON data):\n", 1)[1])
        self.assertFalse(packet["test_execution_enabled"])
        self.assertEqual(self.load(run, "findings.json")[0]["finding"]["validation"]["method"], "static")

    def test_parallel_repro_checkouts_do_not_collide(self):
        run, _ = self.review("--execution", "parallel", "--depth", "deep", "--run-tests", case="runtime")
        self.assertTrue((run / "validation-checkout" / ".review-repros" / "verify-001" / "repro.py").exists())
        self.assertTrue((run / "validation-checkout" / ".review-repros" / "verify-002" / "repro.py").exists())
        self.assertFalse((run / "checkout" / ".review-repros").exists())
        self.assertEqual(self.load(run, "summary.json")["validation"]["runtime_confirmed"], 1)

    def test_parallel_new_hypothesis_is_registered_and_verified(self):
        run, _ = self.review("--execution", "parallel", case="pipeline-followup")
        candidates = self.load(run, "candidates.json")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[1]["discovery_stage"], "verify-001")
        self.assertEqual(len(self.load(run, "verdicts.json")), 2)
        self.assertTrue((run / "verify-002.command.json").exists())

    def test_parallel_followup_budget_preserves_unverified_candidate(self):
        run, _ = self.review("--execution", "parallel", "--max-followup-rounds", "1",
                             case="pipeline-followup-limit", expected=3)
        self.assertEqual(len(self.load(run, "candidates.json")), 3)
        self.assertEqual(self.load(run, "summary.json")["counts"]["unresolved"], 1)
        self.assertEqual(self.load(run, "verdicts.json")[-1]["candidate_id"], "C0003")

    def test_parallel_omitted_verdict_is_unresolved(self):
        run, _ = self.review("--execution", "parallel", case="omit", expected=3)
        self.assertEqual(self.load(run, "summary.json")["counts"]["unresolved"], 1)
        self.assertIn("실행 실패", self.load(run, "manifest.json")["limitations"][0])

    def test_parallel_explicit_groups_require_unique_assignment(self):
        config = self.root / "checks.json"
        config.write_text(json.dumps({"groups": {"one": ["*.py"], "two": ["logic.py"]}}))
        run, _ = self.review("--execution", "parallel", "--dry-run", "--checks-config", str(config), expected=2)
        self.assertEqual(self.load(run, "manifest.json")["status"], "failed")

    def test_parallel_command_cannot_mutate_frozen_source(self):
        run, _ = self.review("--execution", "parallel", "--run-tests", "--setup-command",
            shlex_join([sys.executable, "-c", "from pathlib import Path; Path('logic.py').write_text('modified')"]), expected=3)
        self.assertEqual(self.load(run, "checks.json")["status"], "failed")
        self.assertEqual((self.repo / "logic.py").read_text(), "def avg(total, count):\n    return total / count\n")

    def test_feedback_latest_label_and_missed_counts(self):
        run, _ = self.review()
        for label in ("false_positive", "true_positive"):
            self.cli("feedback", "--run", str(run), "--candidate", "C0001", "--label", label, "--note", "human evidence")
        self.cli("feedback", "--run", str(run), "--candidate", "M0001", "--label", "missed", "--note", "other real bug")
        result = json.loads(self.cli("stats", "--runs", str(self.out)).stdout)
        self.assertEqual(result["true_positive"], 1)
        self.assertEqual(result["false_positive"], 0)
        self.assertEqual(result["missed"], 1)
        self.assertEqual(result["precision_among_labeled_findings"], 1)
        self.assertEqual(result["detection_among_recorded_bugs"], 0.5)
        self.assertEqual(len((run / "feedback.jsonl").read_text().splitlines()), 3)

    def test_non_root_repository_argument_is_rejected(self):
        child = self.repo / "subdir"
        child.mkdir()
        result = self.cli("review", "--repo", str(child), "--base", "main", "--dry-run", expected=2)
        self.assertIn("루트", result.stderr)


if __name__ == "__main__":
    unittest.main()
