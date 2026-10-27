import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow_foundry import (
    AuthorityViolation,
    ClaimConflict,
    ContractViolation,
    ExternalAgentProtocol,
    LeaseExpired,
    LessonViolation,
    RevisionConflict,
    SQLiteRuntime,
    SessionConflict,
    SubmissionConflict,
    compile_file,
    write_context_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
IMPLEMENTATION_EVIDENCE = [
    {"kind": "implementation", "uri": "file:///artifact.json", "sha256": "a" * 64, "summary": "artifact bytes"}
]
VALIDATION_EVIDENCE = [
    {"kind": "validation", "uri": "file:///validation.json", "sha256": "b" * 64, "summary": "independent checks"}
]


class FaultyRuntime(SQLiteRuntime):
    fail_on_event = None

    def _append(self, connection, run_id, sequence, event_type, node_id, payload):
        if event_type == self.fail_on_event:
            raise RuntimeError(f"injected crash before {event_type}")
        return super()._append(connection, run_id, sequence, event_type, node_id, payload)


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "foundry.db"
        self.runtime = SQLiteRuntime(self.database)
        self.protocol = ExternalAgentProtocol(self.runtime)
        self.workflow = compile_file(ROOT / "examples" / "artifact-correction.json")
        self.run = self.runtime.start_run(self.workflow, "run", {"request": "build artifact"})
        self.protocol.register_session(
            "codex-1", "codex", "gpt", "operator", ["coding", "validation"], at=T0
        )
        self.protocol.register_session(
            "claude-1", "claude-code", "sonnet", "reviewer", ["validation"], at=T0
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _claim_producer(self, session_id: str = "codex-1", at: datetime = T0):
        run = self.runtime.get_run("run")
        return self.protocol.claim("run", session_id, run["revision"], at=at)

    def _journal_producer(self, claimed, at: datetime = T0):
        claim = claimed["claim"]
        self.protocol.record_action(
            claim["claim_id"], claim["fence_token"], "edit", "artifact.json",
            mutation=True, receipt={"sha256": "a" * 64}, at=at,
        )
        self.protocol.record_action(
            claim["claim_id"], claim["fence_token"], "test", "tests",
            receipt={"evidence": "unit tests passed"}, at=at,
        )

    def _submit_producer(self, claimed, at: datetime = T0):
        self._journal_producer(claimed, at)
        claim = claimed["claim"]
        revision = self.runtime.get_run("run")["revision"]
        return self.protocol.submit(
            claim["claim_id"], claim["fence_token"], revision, "success",
            {"artifact_uri": "file:///artifact.json", "artifact_sha256": "a" * 64},
            IMPLEMENTATION_EVIDENCE, summary="artifact created", at=at,
        )

    def _reach_review(self):
        produced = self._claim_producer()
        self._submit_producer(produced)
        run = self.runtime.get_run("run")
        validation = self.protocol.claim("run", "claude-1", run["revision"], at=T0)
        claim = validation["claim"]
        self.protocol.record_action(
            claim["claim_id"], claim["fence_token"], "test", "artifact.json",
            receipt={"evidence": "independent validation"}, at=T0,
        )
        return self.protocol.submit(
            claim["claim_id"], claim["fence_token"], self.runtime.get_run("run")["revision"],
            "pass", {"candidate_sha256": "a" * 64, "checks_passed": ["schema", "content"]},
            VALIDATION_EVIDENCE, at=T0,
        )

    def test_session_registration_is_idempotent_and_identity_bound(self) -> None:
        same = self.protocol.register_session(
            "codex-1", "codex", "gpt", "operator", ["coding", "validation"], at=T0
        )
        self.assertEqual("active", same["state"])
        with self.assertRaises(SessionConflict):
            self.protocol.register_session(
                "codex-1", "claude-code", "sonnet", "operator", ["coding"], at=T0
            )

    def test_frontier_and_single_owner_claim(self) -> None:
        self.assertEqual("claimable", self.protocol.frontier("run", at=T0)["disposition"])
        claimed = self._claim_producer()
        self.assertEqual("claimed", self.protocol.frontier("run", at=T0)["disposition"])
        with self.assertRaises(ClaimConflict):
            self.protocol.claim("run", "codex-1", claimed["run"]["revision"], at=T0)

    def test_required_worker_protocol_cannot_be_bypassed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "claim protocol"):
            self.runtime.complete_node("run", "success", self.run["revision"])

    def test_claim_requires_capability_and_fences_token(self) -> None:
        self.protocol.register_session("weak", "codex", "gpt", "reader", ["read"], at=T0)
        with self.assertRaises(AuthorityViolation):
            self.protocol.claim("run", "weak", self.run["revision"], at=T0)
        claimed = self._claim_producer()
        with self.assertRaises(ClaimConflict):
            self.protocol.record_action(
                claimed["claim"]["claim_id"], "wrong", "read", "artifact.json", at=T0
            )

    def test_renewal_advances_revision_and_rejects_stale_revision(self) -> None:
        claimed = self._claim_producer()
        claim = claimed["claim"]
        renewed = self.protocol.renew(
            claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
            lease_seconds=300, at=T0 + timedelta(seconds=30),
        )
        self.assertGreater(renewed["run"]["revision"], claimed["run"]["revision"])
        with self.assertRaises(RevisionConflict):
            self.protocol.renew(
                claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
                lease_seconds=300, at=T0 + timedelta(seconds=60),
            )

    def test_expired_claim_is_replaced_and_old_worker_is_fenced(self) -> None:
        first = self._claim_producer()
        self.protocol.register_session(
            "codex-2", "codex", "gpt", "replacement", ["coding"], at=T0
        )
        replacement = self.protocol.claim(
            "run", "codex-2", first["run"]["revision"], at=T0 + timedelta(seconds=901)
        )
        self.assertEqual(2, replacement["claim"]["attempt_no"])
        with self.assertRaises(ClaimConflict):
            self.protocol.record_action(
                first["claim"]["claim_id"], first["claim"]["fence_token"],
                "read", "artifact.json", at=T0 + timedelta(seconds=901),
            )

    def test_active_claim_survives_runtime_restart(self) -> None:
        claimed = self._claim_producer()
        restarted = ExternalAgentProtocol(SQLiteRuntime(self.database))
        frontier = restarted.frontier("run", at=T0)
        self.assertEqual("claimed", frontier["disposition"])
        self.assertEqual(claimed["claim"]["claim_id"], frontier["active_claim"]["claim_id"])

    def test_context_bundle_is_content_addressed_and_provider_neutral(self) -> None:
        claimed = self._claim_producer()
        context = claimed["context_pack"]
        self.assertEqual("coding_agent_context_v1", context["schema_version"])
        self.assertEqual({"request": "build artifact"}, context["start_inputs"])
        expected = hashlib.sha256(
            json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected, claimed["claim"]["context_digest"])
        bundle = write_context_bundle(context, Path(self.temp.name) / "bundle")
        self.assertTrue(Path(bundle["context_pack"]).is_file())
        self.assertIn("codex", Path(bundle["instructions"]).read_text(encoding="utf-8"))

    def test_action_authority_and_mutation_receipt_are_enforced(self) -> None:
        claimed = self._claim_producer()
        claim = claimed["claim"]
        with self.assertRaises(AuthorityViolation):
            self.protocol.record_action(
                claim["claim_id"], claim["fence_token"], "push", "origin", at=T0
            )
        with self.assertRaises(ContractViolation):
            self.protocol.record_action(
                claim["claim_id"], claim["fence_token"], "edit", "artifact.json",
                mutation=True, at=T0,
            )

    def test_submission_requires_result_evidence_and_journaled_actions(self) -> None:
        claimed = self._claim_producer()
        claim = claimed["claim"]
        with self.assertRaises(ContractViolation):
            self.protocol.submit(
                claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
                "success", {}, [], at=T0,
            )
        with self.assertRaises(ContractViolation):
            self.protocol.submit(
                claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
                "success", {"artifact_uri": 7, "artifact_sha256": "a" * 64},
                IMPLEMENTATION_EVIDENCE, at=T0,
            )
        with self.assertRaises(ContractViolation):
            self.protocol.submit(
                claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
                "success", {"artifact_uri": "x", "artifact_sha256": "a" * 64},
                IMPLEMENTATION_EVIDENCE, at=T0,
            )

    def test_identical_submission_is_idempotent_and_changed_duplicate_conflicts(self) -> None:
        claimed = self._claim_producer()
        self._journal_producer(claimed)
        claim = claimed["claim"]
        result = {"artifact_uri": "file:///artifact.json", "artifact_sha256": "a" * 64}
        revision = self.runtime.get_run("run")["revision"]
        first = self.protocol.submit(
            claim["claim_id"], claim["fence_token"], revision, "success",
            result, IMPLEMENTATION_EVIDENCE, summary="done", at=T0,
        )
        second = self.protocol.submit(
            claim["claim_id"], claim["fence_token"], revision, "success",
            result, IMPLEMENTATION_EVIDENCE, summary="done", at=T0,
        )
        self.assertEqual(first["revision"], second["revision"])
        with self.assertRaises(SubmissionConflict):
            self.protocol.submit(
                claim["claim_id"], claim["fence_token"], revision, "success",
                result, IMPLEMENTATION_EVIDENCE, summary="changed", at=T0,
            )

    def test_validation_can_require_a_different_session(self) -> None:
        claimed = self._claim_producer()
        self._submit_producer(claimed)
        self.protocol.register_session(
            "codex-validator", "codex", "gpt", "operator", ["validation"], at=T0
        )
        with self.assertRaises(AuthorityViolation):
            self.protocol.claim(
                "run", "codex-1", self.runtime.get_run("run")["revision"], at=T0
            )
        validated = self.protocol.claim(
            "run", "codex-validator", self.runtime.get_run("run")["revision"], at=T0
        )
        self.assertEqual("validate", validated["context_pack"]["obligation"]["node_id"])

    def test_release_handoff_preserves_checkpoint_for_replacement(self) -> None:
        claimed = self._claim_producer()
        self.protocol.register_session(
            "codex-2", "codex", "gpt", "replacement", ["coding"], at=T0
        )
        released = self.protocol.release(
            claimed["claim"]["claim_id"], claimed["claim"]["fence_token"],
            claimed["run"]["revision"], {"completed": ["read"], "next": "edit"},
            handoff_to="codex-2", at=T0,
        )
        replacement = self.protocol.claim(
            "run", "codex-2", released["revision"], at=T0
        )
        self.assertEqual("edit", replacement["context_pack"]["prior_handoff"]["checkpoint"]["next"])

    def test_typed_human_approval_requires_actor_and_evidence(self) -> None:
        waiting = self._reach_review()
        with self.assertRaisesRegex(RuntimeError, "actor"):
            self.runtime.resume_wait(
                "run", "artifact.reviewed", "artifact-review", "approved", waiting["revision"], {}
            )
        approved = self.runtime.resume_wait(
            "run", "artifact.reviewed", "artifact-review", "approved", waiting["revision"],
            {"actor": "user", "evidence": [{"kind": "review_record", "uri": "review://1"}]},
        )
        self.assertEqual("publish", approved["current_node"])

    def test_frontier_distinguishes_wait_effect_and_terminal_states(self) -> None:
        waiting = self._reach_review()
        self.assertEqual("awaiting_event", self.protocol.frontier("run", at=T0)["disposition"])
        approved = self.runtime.resume_wait(
            "run", "artifact.reviewed", "artifact-review", "approved", waiting["revision"],
            {"actor": "user", "evidence": [{"kind": "review_record", "uri": "review://2"}]},
        )
        pending = self.runtime.request_effect("run", approved["revision"], {"sha256": "a" * 64})
        self.assertEqual(
            "awaiting_effect_receipt", self.protocol.frontier("run", at=T0)["disposition"]
        )
        terminal = self.runtime.record_effect_receipt(
            "run", pending["action_key"], "success", {"receipt_id": "published"}, pending["revision"]
        )
        self.assertEqual("terminal", terminal["status"])
        self.assertEqual("terminal", self.protocol.frontier("run", at=T0)["disposition"])

    def test_lessons_require_governed_activation_and_enter_matching_context(self) -> None:
        lesson = self.protocol.propose_lesson(
            "stale_identity", "global", ["stale_identity"],
            "Recompute and bind the candidate digest immediately before validation.",
            [{"uri": "ledger://F4-007"}], {"incident": "identity drift"}, "operator", at=T0,
        )
        with self.assertRaises(LessonViolation):
            self.protocol.activate_lesson(
                "stale_identity", lesson["version"], "reviewer", {"regression": "pass"}, at=T0
            )
        active = self.protocol.activate_lesson(
            "stale_identity", lesson["version"], "reviewer",
            {"regression": "pass", "held_out": "pass", "rollback": "documented"}, at=T0,
        )
        self.assertEqual("activated", active["status"])
        claimed = self._claim_producer()
        self.assertEqual("stale_identity", claimed["context_pack"]["applicable_lessons"][0]["lesson_id"])
        released = self.protocol.release(
            claimed["claim"]["claim_id"], claimed["claim"]["fence_token"],
            claimed["run"]["revision"], {"next": "replacement"}, at=T0,
        )
        retired = self.protocol.retire_lesson(
            "stale_identity", lesson["version"], "reviewer", {"reason": "superseded"}, at=T0
        )
        self.assertEqual("retired", retired["status"])
        replacement = self.protocol.claim("run", "codex-1", released["revision"], at=T0)
        self.assertEqual([], replacement["context_pack"]["applicable_lessons"])

    def test_claim_release_and_submission_events_replay(self) -> None:
        claimed = self._claim_producer()
        released = self.protocol.release(
            claimed["claim"]["claim_id"], claimed["claim"]["fence_token"],
            claimed["run"]["revision"], {"next": "retry"}, at=T0,
        )
        claimed = self.protocol.claim("run", "codex-1", released["revision"], at=T0)
        self._submit_producer(claimed)
        self.assertTrue(self.runtime.replay("run")["matches_projection"])

    def test_agent_journal_and_submission_are_database_immutable(self) -> None:
        claimed = self._claim_producer()
        self._submit_producer(claimed)
        with closing(sqlite3.connect(self.database)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "agent actions are immutable"):
                connection.execute("UPDATE agent_actions SET action_type = 'push'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "agent submissions are immutable"):
                connection.execute("DELETE FROM agent_submissions")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "work claim identity is immutable"):
                connection.execute("UPDATE work_claims SET context_digest = ?", ("0" * 64,))
            with self.assertRaisesRegex(sqlite3.IntegrityError, "agent session identity is immutable"):
                connection.execute("UPDATE agent_sessions SET actor = 'other'")

    def test_claim_and_submission_transactions_rollback_on_injected_crash(self) -> None:
        crash_db = Path(self.temp.name) / "crash.db"
        runtime = FaultyRuntime(crash_db)
        protocol = ExternalAgentProtocol(runtime)
        workflow = compile_file(ROOT / "examples" / "artifact-correction.json")
        run = runtime.start_run(workflow, "crash-run")
        protocol.register_session(
            "worker", "codex", "gpt", "operator", ["coding"], at=T0
        )
        runtime.fail_on_event = "AGENT_CLAIMED"
        with self.assertRaisesRegex(RuntimeError, "injected crash"):
            protocol.claim("crash-run", "worker", run["revision"], at=T0)
        self.assertEqual("claimable", protocol.frontier("crash-run", at=T0)["disposition"])
        runtime.fail_on_event = None
        claimed = protocol.claim("crash-run", "worker", run["revision"], at=T0)
        claim = claimed["claim"]
        protocol.record_action(
            claim["claim_id"], claim["fence_token"], "edit", "artifact.json",
            mutation=True, receipt={"sha256": "a" * 64}, at=T0,
        )
        protocol.record_action(
            claim["claim_id"], claim["fence_token"], "test", "tests", at=T0,
        )
        runtime.fail_on_event = "AGENT_SUBMITTED"
        with self.assertRaisesRegex(RuntimeError, "injected crash"):
            protocol.submit(
                claim["claim_id"], claim["fence_token"], claimed["run"]["revision"],
                "success", {"artifact_uri": "file:///artifact.json", "artifact_sha256": "a" * 64},
                IMPLEMENTATION_EVIDENCE, at=T0,
            )
        self.assertEqual("claimed", runtime.get_run("crash-run")["status"])
        with closing(sqlite3.connect(crash_db)) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM agent_submissions").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
