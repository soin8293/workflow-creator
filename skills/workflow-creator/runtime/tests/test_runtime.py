import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from workflow_foundry import ReceiptConflict, RevisionConflict, SQLiteRuntime, compile_workflow


ROOT = Path(__file__).resolve().parents[1]
REVIEW = {"actor": "user", "evidence": [{"kind": "review_record", "id": "review-1"}]}


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "runtime.db"
        self.runtime = SQLiteRuntime(self.database)
        raw = json.loads((ROOT / "examples" / "artifact-correction.json").read_text(encoding="utf-8"))
        raw["policies"]["worker_protocol_required"] = False
        self.workflow = compile_workflow(raw)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_full_wait_effect_and_terminal_flow_replays(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-1", {"topic": "demo"})
        run = self.runtime.complete_node("run-1", "success", run["revision"])
        run = self.runtime.complete_node("run-1", "pass", run["revision"])
        self.assertEqual("waiting", run["status"])
        run = self.runtime.resume_wait(
            "run-1", "artifact.reviewed", "artifact-review", "approved", run["revision"], REVIEW
        )
        pending = self.runtime.request_effect("run-1", run["revision"], {"artifact": "sha256:abc"})
        self.assertEqual("effect_pending", pending["status"])
        finished = self.runtime.record_effect_receipt(
            "run-1", pending["action_key"], "success", {"remote_id": "pub-1"}, pending["revision"]
        )
        self.assertEqual("terminal", finished["status"])
        self.assertEqual("accepted", finished["terminal_outcome"])
        self.assertTrue(self.runtime.replay("run-1")["matches_projection"])

    def test_stale_revision_is_fenced(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-2")
        self.runtime.complete_node("run-2", "success", run["revision"])
        with self.assertRaises(RevisionConflict):
            self.runtime.complete_node("run-2", "success", run["revision"])

    def test_duplicate_identical_receipt_is_idempotent(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-3")
        run = self.runtime.complete_node("run-3", "success", run["revision"])
        run = self.runtime.complete_node("run-3", "pass", run["revision"])
        run = self.runtime.resume_wait(
            "run-3", "artifact.reviewed", "artifact-review", "approved", run["revision"], REVIEW
        )
        pending = self.runtime.request_effect("run-3", run["revision"])
        receipt = {"remote_id": "pub-3"}
        first = self.runtime.record_effect_receipt(
            "run-3", pending["action_key"], "success", receipt, pending["revision"]
        )
        second = self.runtime.record_effect_receipt(
            "run-3", pending["action_key"], "success", receipt, pending["revision"]
        )
        self.assertEqual(first["revision"], second["revision"])

    def test_conflicting_duplicate_receipt_fails_closed(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-4")
        run = self.runtime.complete_node("run-4", "success", run["revision"])
        run = self.runtime.complete_node("run-4", "pass", run["revision"])
        run = self.runtime.resume_wait(
            "run-4", "artifact.reviewed", "artifact-review", "approved", run["revision"], REVIEW
        )
        pending = self.runtime.request_effect("run-4", run["revision"])
        self.runtime.record_effect_receipt(
            "run-4", pending["action_key"], "success", {"remote_id": "one"}, pending["revision"]
        )
        with self.assertRaises(ReceiptConflict):
            self.runtime.record_effect_receipt(
                "run-4", pending["action_key"], "success", {"remote_id": "two"}, pending["revision"]
            )

    def test_projection_can_be_rebuilt_from_events(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-5")
        run = self.runtime.complete_node("run-5", "success", run["revision"])
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE runs SET status = 'corrupt', current_node = 'produce' WHERE run_id = 'run-5'")
            connection.commit()
        self.assertFalse(self.runtime.replay("run-5")["matches_projection"])
        repaired = self.runtime.rebuild_projection("run-5")
        self.assertEqual("validate", repaired["current_node"])
        self.assertTrue(self.runtime.replay("run-5")["matches_projection"])

    def test_wrong_wake_cannot_resume(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-6")
        run = self.runtime.complete_node("run-6", "success", run["revision"])
        run = self.runtime.complete_node("run-6", "pass", run["revision"])
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.runtime.resume_wait("run-6", "other.event", "artifact-review", "approved", run["revision"])

    def test_pending_effect_survives_runtime_restart(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-7")
        run = self.runtime.complete_node("run-7", "success", run["revision"])
        run = self.runtime.complete_node("run-7", "pass", run["revision"])
        run = self.runtime.resume_wait(
            "run-7", "artifact.reviewed", "artifact-review", "approved", run["revision"], REVIEW
        )
        pending = self.runtime.request_effect("run-7", run["revision"], {"artifact": "sha256:restart"})
        restarted = SQLiteRuntime(self.database)
        inspected = restarted.inspect("run-7")
        self.assertEqual("effect_pending", inspected["run"]["status"])
        self.assertEqual("pending", inspected["outbox"][0]["state"])
        finished = restarted.record_effect_receipt(
            "run-7", pending["action_key"], "success", {"remote_id": "after-restart"}, pending["revision"]
        )
        self.assertEqual("accepted", finished["terminal_outcome"])

    def test_event_history_is_database_immutable(self) -> None:
        self.runtime.start_run(self.workflow, "run-8")
        with closing(sqlite3.connect(self.database)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "events are immutable"):
                connection.execute("UPDATE events SET event_type = 'tampered' WHERE run_id = 'run-8'")

    def test_node_visit_budget_stops_repair_loop(self) -> None:
        run = self.runtime.start_run(self.workflow, "run-9")
        for _ in range(2):
            run = self.runtime.complete_node("run-9", "success", run["revision"])
            run = self.runtime.complete_node("run-9", "fail", run["revision"])
        run = self.runtime.complete_node("run-9", "success", run["revision"])
        run = self.runtime.complete_node("run-9", "fail", run["revision"])
        with self.assertRaisesRegex(RuntimeError, "node visit budget exhausted"):
            self.runtime.complete_node("run-9", "success", run["revision"])


if __name__ == "__main__":
    unittest.main()
