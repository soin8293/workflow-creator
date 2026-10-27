import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> dict:
        completed = subprocess.run(
            [sys.executable, "-m", "workflow_foundry.cli", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_external_agent_cli_vertical_slice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "foundry.db"
            brief = root / "brief.json"
            workflow = root / "workflow.json"
            bundle = root / "bundle"
            self._run(
                "init-brief", "--output", str(brief), "--workflow-id", "cli_workflow",
                "--objective", "Build a tested CLI feature.",
                "--requirement", "Inspect repository authority.",
                "--requirement", "Return content-addressed evidence.",
            )
            generated = self._run(
                "generate", "--brief", str(brief), "--output", str(workflow),
            )
            self.assertTrue(generated["valid"])
            run = self._run(
                "start", "--db", str(database), "--spec", str(workflow),
                "--run-id", "cli-run", "--input-json", '{"repository":"demo"}',
            )
            self._run(
                "agent-register", "--db", str(database), "--session-id", "claude-session",
                "--provider", "claude-code", "--model", "sonnet", "--actor", "operator",
                "--capabilities-json", '["research"]',
            )
            claimed = self._run(
                "claim", "--db", str(database), "--run-id", "cli-run",
                "--session-id", "claude-session", "--expected-revision", str(run["revision"]),
                "--bundle-dir", str(bundle),
            )
            self.assertTrue((bundle / "context-pack.json").is_file())
            self._run(
                "journal-action", "--db", str(database),
                "--claim-id", claimed["claim"]["claim_id"],
                "--fence-token", claimed["claim"]["fence_token"],
                "--action-type", "analyze", "--resource", "repository",
            )
            submission = json.loads((bundle / "submission-template.json").read_text(encoding="utf-8"))
            submission.update(
                outcome="success",
                result={"findings": ["fact"], "sources": ["repo://README"], "open_risks": []},
                evidence=[
                    {"kind": "research", "uri": "repo://README", "sha256": "c" * 64, "summary": "repository evidence"}
                ],
                summary="research threshold met",
            )
            submission_path = root / "submission.json"
            submission_path.write_text(json.dumps(submission), encoding="utf-8")
            advanced = self._run(
                "agent-submit", "--db", str(database), "--submission-file", str(submission_path)
            )
            self.assertEqual("plan", advanced["current_node"])
            self.assertEqual("claimable", self._run(
                "frontier", "--db", str(database), "--run-id", "cli-run"
            )["disposition"])


if __name__ == "__main__":
    unittest.main()
