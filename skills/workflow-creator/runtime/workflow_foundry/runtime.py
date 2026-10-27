from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .compiler import CompiledWorkflow


class WorkflowRuntimeError(RuntimeError):
    pass


class RevisionConflict(WorkflowRuntimeError):
    pass


class ReceiptConflict(WorkflowRuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRuntime:
    def __init__(self, database: str | Path):
        self.database = str(database)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS definitions (
                    digest TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    definition_version TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    definition_digest TEXT NOT NULL REFERENCES definitions(digest),
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    current_node TEXT NOT NULL,
                    step_count INTEGER NOT NULL,
                    terminal_outcome TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    node_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS waits (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                    node_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    correlation_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    action_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    node_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    action_key TEXT PRIMARY KEY REFERENCES outbox(action_key),
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    node_id TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS work_claims (
                    claim_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    node_id TEXT NOT NULL,
                    run_revision INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    epoch INTEGER NOT NULL,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id),
                    fence_token TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    context_digest TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    checkpoint_json TEXT,
                    claimed_at TEXT NOT NULL,
                    renewed_at TEXT,
                    closed_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_claim_per_run
                ON work_claims(run_id) WHERE status = 'active';
                CREATE TABLE IF NOT EXISTS agent_actions (
                    claim_id TEXT NOT NULL REFERENCES work_claims(claim_id),
                    sequence INTEGER NOT NULL,
                    action_id TEXT NOT NULL UNIQUE,
                    action_type TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    mutation INTEGER NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (claim_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS agent_submissions (
                    claim_id TEXT PRIMARY KEY REFERENCES work_claims(claim_id),
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    node_id TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id),
                    outcome TEXT NOT NULL,
                    submission_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    lesson_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    trigger_tags_json TEXT NOT NULL,
                    prevention TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    proposal_evidence_json TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (lesson_id, version)
                );
                CREATE TABLE IF NOT EXISTS lesson_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (lesson_id, version) REFERENCES lessons(lesson_id, version)
                );
                CREATE TRIGGER IF NOT EXISTS definitions_no_update
                BEFORE UPDATE ON definitions BEGIN SELECT RAISE(ABORT, 'definitions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS definitions_no_delete
                BEFORE DELETE ON definitions BEGIN SELECT RAISE(ABORT, 'definitions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS receipts_no_update
                BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS receipts_no_delete
                BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS agent_actions_no_update
                BEFORE UPDATE ON agent_actions BEGIN SELECT RAISE(ABORT, 'agent actions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS agent_actions_no_delete
                BEFORE DELETE ON agent_actions BEGIN SELECT RAISE(ABORT, 'agent actions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS agent_submissions_no_update
                BEFORE UPDATE ON agent_submissions BEGIN SELECT RAISE(ABORT, 'agent submissions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS agent_submissions_no_delete
                BEFORE DELETE ON agent_submissions BEGIN SELECT RAISE(ABORT, 'agent submissions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS agent_sessions_identity_no_update
                BEFORE UPDATE ON agent_sessions
                WHEN NEW.provider != OLD.provider OR NEW.model != OLD.model OR NEW.actor != OLD.actor
                  OR NEW.capabilities_json != OLD.capabilities_json OR NEW.metadata_json != OLD.metadata_json
                  OR NEW.registered_at != OLD.registered_at
                BEGIN SELECT RAISE(ABORT, 'agent session identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS work_claims_identity_no_update
                BEFORE UPDATE ON work_claims
                WHEN NEW.run_id != OLD.run_id OR NEW.node_id != OLD.node_id
                  OR NEW.attempt_no != OLD.attempt_no OR NEW.epoch != OLD.epoch
                  OR NEW.session_id != OLD.session_id OR NEW.fence_token != OLD.fence_token
                  OR NEW.context_digest != OLD.context_digest OR NEW.context_json != OLD.context_json
                  OR NEW.claimed_at != OLD.claimed_at
                BEGIN SELECT RAISE(ABORT, 'work claim identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS outbox_identity_no_update
                BEFORE UPDATE ON outbox
                WHEN NEW.run_id != OLD.run_id OR NEW.node_id != OLD.node_id
                  OR NEW.payload_json != OLD.payload_json OR NEW.created_at != OLD.created_at
                BEGIN SELECT RAISE(ABORT, 'outbox identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS waits_identity_no_update
                BEFORE UPDATE ON waits
                WHEN NEW.node_id != OLD.node_id OR NEW.event_type != OLD.event_type
                  OR NEW.correlation_key != OLD.correlation_key OR NEW.created_at != OLD.created_at
                BEGIN SELECT RAISE(ABORT, 'wait identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lessons_no_update
                BEFORE UPDATE ON lessons BEGIN SELECT RAISE(ABORT, 'lessons are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lessons_no_delete
                BEFORE DELETE ON lessons BEGIN SELECT RAISE(ABORT, 'lessons are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lesson_events_no_update
                BEFORE UPDATE ON lesson_events BEGIN SELECT RAISE(ABORT, 'lesson events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lesson_events_no_delete
                BEFORE DELETE ON lesson_events BEGIN SELECT RAISE(ABORT, 'lesson events are immutable'); END;
                """
            )

    def register_definition(self, workflow: CompiledWorkflow) -> None:
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT spec_json FROM definitions WHERE digest = ?", (workflow.digest,)
            ).fetchone()
            canonical = workflow.canonical_json()
            if existing and existing["spec_json"] != canonical:
                raise WorkflowRuntimeError("definition digest collision")
            connection.execute(
                "INSERT OR IGNORE INTO definitions VALUES (?, ?, ?, ?, ?)",
                (
                    workflow.digest,
                    workflow.spec["workflow_id"],
                    workflow.spec["definition_version"],
                    canonical,
                    _now(),
                ),
            )

    def _definition(self, connection: sqlite3.Connection, digest: str) -> dict[str, Any]:
        row = connection.execute("SELECT spec_json FROM definitions WHERE digest = ?", (digest,)).fetchone()
        if not row:
            raise WorkflowRuntimeError(f"definition not found: {digest}")
        return json.loads(row["spec_json"])

    def _run(self, connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise WorkflowRuntimeError(f"run not found: {run_id}")
        return dict(row)

    @staticmethod
    def _assert_revision(run: dict[str, Any], expected_revision: int) -> None:
        if run["revision"] != expected_revision:
            raise RevisionConflict(f"expected revision {expected_revision}, found {run['revision']}")

    @staticmethod
    def _nodes(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {node["id"]: node for node in spec["nodes"]}

    @staticmethod
    def _assert_step_budget(run: dict[str, Any], spec: dict[str, Any]) -> int:
        step_count = run["step_count"] + 1
        if step_count > spec["policies"]["max_steps"]:
            raise WorkflowRuntimeError("workflow max_steps budget exhausted")
        return step_count

    @staticmethod
    def _assert_visit_budget(
        connection: sqlite3.Connection,
        run_id: str,
        node: dict[str, Any],
        event_type: str,
        default_max: int,
    ) -> None:
        visits = connection.execute(
            "SELECT COUNT(*) AS n FROM events WHERE run_id = ? AND node_id = ? AND event_type = ?",
            (run_id, node["id"], event_type),
        ).fetchone()["n"] + 1
        if visits > node.get("max_visits", default_max):
            raise WorkflowRuntimeError(f"node visit budget exhausted: {node['id']}")

    def _append(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        sequence: int,
        event_type: str,
        node_id: str | None,
        payload: dict[str, Any],
    ) -> int:
        next_sequence = sequence + 1
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, next_sequence, str(uuid.uuid4()), event_type, node_id, _json(payload), _now()),
        )
        return next_sequence

    def _enter(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        nodes: dict[str, dict[str, Any]],
        node_id: str,
        sequence: int,
    ) -> tuple[int, str, str | None]:
        node = nodes[node_id]
        if node["kind"] == "terminal":
            sequence = self._append(
                connection, run_id, sequence, "RUN_TERMINAL", node_id, {"outcome": node["outcome"]}
            )
            return sequence, "terminal", node["outcome"]
        if node["kind"] in {"human_wait", "external_wait"}:
            wait = node["wait"]
            connection.execute(
                "INSERT OR REPLACE INTO waits VALUES (?, ?, ?, ?, 'active', NULL, ?, NULL)",
                (run_id, node_id, wait["event_type"], wait["correlation_key"], _now()),
            )
            sequence = self._append(connection, run_id, sequence, "WAIT_REGISTERED", node_id, wait)
            return sequence, "waiting", None
        return sequence, "ready", None

    def _project(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        revision: int,
        status: str,
        node_id: str,
        step_count: int,
        terminal_outcome: str | None,
    ) -> None:
        connection.execute(
            "UPDATE runs SET revision = ?, status = ?, current_node = ?, step_count = ?, "
            "terminal_outcome = ?, updated_at = ? WHERE run_id = ?",
            (revision, status, node_id, step_count, terminal_outcome, _now(), run_id),
        )

    def start_run(
        self,
        workflow: CompiledWorkflow,
        run_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.register_definition(workflow)
        with self._transaction() as connection:
            now = _now()
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, 0, 'starting', ?, 0, NULL, ?, ?)",
                (run_id, workflow.digest, workflow.spec["entry"], now, now),
            )
            sequence = self._append(
                connection,
                run_id,
                0,
                "RUN_STARTED",
                workflow.spec["entry"],
                {"entry": workflow.spec["entry"], "inputs": inputs or {}},
            )
            sequence, status, terminal = self._enter(
                connection, run_id, workflow.nodes, workflow.spec["entry"], sequence
            )
            self._project(connection, run_id, sequence, status, workflow.spec["entry"], 0, terminal)
        return self.get_run(run_id)

    def complete_node(
        self,
        run_id: str,
        outcome: str,
        expected_revision: int,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            run = self._run(connection, run_id)
            self._assert_revision(run, expected_revision)
            if run["status"] != "ready":
                raise WorkflowRuntimeError(f"run is {run['status']}, not ready")
            spec = self._definition(connection, run["definition_digest"])
            nodes = self._nodes(spec)
            node = nodes[run["current_node"]]
            if spec.get("policies", {}).get("worker_protocol_required") and node["kind"] in {
                "activity", "agent", "decision", "validation"
            }:
                raise WorkflowRuntimeError("current node requires the external agent claim protocol")
            if node["kind"] in {"terminal", "human_wait", "external_wait", "effect"}:
                raise WorkflowRuntimeError(f"{node['kind']} requires its dedicated protocol")
            if outcome not in node["routes"]:
                raise WorkflowRuntimeError(f"outcome {outcome!r} is not valid for {node['id']}")
            step_count = self._assert_step_budget(run, spec)
            self._assert_visit_budget(
                connection, run_id, node, "NODE_COMPLETED", spec["policies"]["max_steps"]
            )
            target = node["routes"][outcome]
            sequence = self._append(
                connection,
                run_id,
                run["revision"],
                "NODE_COMPLETED",
                node["id"],
                {"outcome": outcome, "next_node": target, "result": result or {}},
            )
            sequence, status, terminal = self._enter(connection, run_id, nodes, target, sequence)
            self._project(connection, run_id, sequence, status, target, step_count, terminal)
        return self.get_run(run_id)

    def resume_wait(
        self,
        run_id: str,
        event_type: str,
        correlation_key: str,
        outcome: str,
        expected_revision: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            run = self._run(connection, run_id)
            self._assert_revision(run, expected_revision)
            if run["status"] != "waiting":
                raise WorkflowRuntimeError(f"run is {run['status']}, not waiting")
            wait = connection.execute("SELECT * FROM waits WHERE run_id = ?", (run_id,)).fetchone()
            if not wait or wait["state"] != "active":
                raise WorkflowRuntimeError("active wait not found")
            if wait["event_type"] != event_type or wait["correlation_key"] != correlation_key:
                raise WorkflowRuntimeError("wake event does not match the registered wait")
            spec = self._definition(connection, run["definition_digest"])
            nodes = self._nodes(spec)
            node = nodes[run["current_node"]]
            if outcome not in node["routes"]:
                raise WorkflowRuntimeError(f"outcome {outcome!r} is not valid for {node['id']}")
            wake_payload = payload or {}
            wait_contract = node.get("wait", {})
            if wait_contract.get("requires_actor") and (
                not isinstance(wake_payload.get("actor"), str) or not wake_payload["actor"].strip()
            ):
                raise WorkflowRuntimeError("wait contract requires a non-empty actor")
            required_evidence = set(wait_contract.get("required_evidence", []))
            evidence = wake_payload.get("evidence", [])
            observed_evidence = {
                item.get("kind") for item in evidence if isinstance(item, dict) and item.get("kind")
            } if isinstance(evidence, list) else set()
            if required_evidence - observed_evidence:
                raise WorkflowRuntimeError(
                    f"wait payload lacks evidence kinds: {sorted(required_evidence - observed_evidence)}"
                )
            step_count = self._assert_step_budget(run, spec)
            self._assert_visit_budget(
                connection, run_id, node, "WAIT_RESUMED", spec["policies"]["max_steps"]
            )
            target = node["routes"][outcome]
            sequence = self._append(
                connection,
                run_id,
                run["revision"],
                "WAIT_RESUMED",
                node["id"],
                {"outcome": outcome, "next_node": target, "payload": wake_payload},
            )
            connection.execute(
                "UPDATE waits SET state = 'consumed', payload_json = ?, consumed_at = ? WHERE run_id = ?",
                (_json(wake_payload), _now(), run_id),
            )
            sequence, status, terminal = self._enter(connection, run_id, nodes, target, sequence)
            self._project(connection, run_id, sequence, status, target, step_count, terminal)
        return self.get_run(run_id)

    def request_effect(
        self,
        run_id: str,
        expected_revision: int,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            run = self._run(connection, run_id)
            self._assert_revision(run, expected_revision)
            if run["status"] != "ready":
                raise WorkflowRuntimeError(f"run is {run['status']}, not ready")
            spec = self._definition(connection, run["definition_digest"])
            node = self._nodes(spec)[run["current_node"]]
            if node["kind"] != "effect":
                raise WorkflowRuntimeError("current node is not an effect")
            visit = connection.execute(
                "SELECT COUNT(*) AS n FROM events WHERE run_id = ? AND node_id = ? AND event_type = 'EFFECT_RECORDED'",
                (run_id, node["id"]),
            ).fetchone()["n"] + 1
            logical = f"{run['definition_digest']}:{run_id}:{node['id']}:{visit}:{node['effect']['idempotency_key']}"
            action_key = hashlib.sha256(logical.encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT INTO outbox VALUES (?, ?, ?, ?, 'pending', ?, NULL)",
                (action_key, run_id, node["id"], _json(payload or {}), _now()),
            )
            sequence = self._append(
                connection,
                run_id,
                run["revision"],
                "EFFECT_REQUESTED",
                node["id"],
                {"action_key": action_key, "payload": payload or {}},
            )
            self._project(
                connection, run_id, sequence, "effect_pending", node["id"], run["step_count"], None
            )
        state = self.get_run(run_id)
        state["action_key"] = action_key
        return state

    def record_effect_receipt(
        self,
        run_id: str,
        action_key: str,
        outcome: str,
        receipt: dict[str, Any],
        expected_revision: int,
    ) -> dict[str, Any]:
        receipt_json = _json(receipt)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT receipt_json FROM receipts WHERE action_key = ?", (action_key,)
            ).fetchone()
            if existing:
                if existing["receipt_json"] != receipt_json:
                    raise ReceiptConflict("the logical action already has a different receipt")
                return self._run(connection, run_id)
            run = self._run(connection, run_id)
            self._assert_revision(run, expected_revision)
            if run["status"] != "effect_pending":
                raise WorkflowRuntimeError(f"run is {run['status']}, not awaiting an effect receipt")
            outbox = connection.execute(
                "SELECT * FROM outbox WHERE action_key = ? AND run_id = ?", (action_key, run_id)
            ).fetchone()
            if not outbox or outbox["node_id"] != run["current_node"]:
                raise WorkflowRuntimeError("effect action is not bound to the current run node")
            spec = self._definition(connection, run["definition_digest"])
            nodes = self._nodes(spec)
            node = nodes[run["current_node"]]
            if outcome not in node["routes"]:
                raise WorkflowRuntimeError(f"outcome {outcome!r} is not valid for {node['id']}")
            step_count = self._assert_step_budget(run, spec)
            self._assert_visit_budget(
                connection, run_id, node, "EFFECT_RECORDED", spec["policies"]["max_steps"]
            )
            connection.execute(
                "INSERT INTO receipts VALUES (?, ?, ?, ?, ?)",
                (action_key, run_id, node["id"], receipt_json, _now()),
            )
            connection.execute(
                "UPDATE outbox SET state = 'delivered', delivered_at = ? WHERE action_key = ?",
                (_now(), action_key),
            )
            target = node["routes"][outcome]
            sequence = self._append(
                connection,
                run_id,
                run["revision"],
                "EFFECT_RECORDED",
                node["id"],
                {"action_key": action_key, "outcome": outcome, "next_node": target, "receipt": receipt},
            )
            sequence, status, terminal = self._enter(connection, run_id, nodes, target, sequence)
            self._project(connection, run_id, sequence, status, target, step_count, terminal)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            return self._run(connection, run_id)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sequence, event_id, event_type, node_id, payload_json, created_at "
                "FROM events WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
        return [
            {**{key: row[key] for key in row.keys() if key != "payload_json"}, "payload": json.loads(row["payload_json"])}
            for row in rows
        ]

    @staticmethod
    def reduce(events: list[dict[str, Any]]) -> dict[str, Any]:
        state: dict[str, Any] = {
            "revision": 0,
            "status": "absent",
            "current_node": None,
            "step_count": 0,
            "terminal_outcome": None,
        }
        for event in events:
            payload = event["payload"]
            state["revision"] = event["sequence"]
            if event["event_type"] == "RUN_STARTED":
                state.update(status="ready", current_node=payload["entry"])
            elif event["event_type"] == "NODE_COMPLETED":
                state.update(status="ready", current_node=payload["next_node"], step_count=state["step_count"] + 1)
            elif event["event_type"] == "WAIT_REGISTERED":
                state["status"] = "waiting"
            elif event["event_type"] == "WAIT_RESUMED":
                state.update(status="ready", current_node=payload["next_node"], step_count=state["step_count"] + 1)
            elif event["event_type"] == "EFFECT_REQUESTED":
                state["status"] = "effect_pending"
            elif event["event_type"] == "EFFECT_RECORDED":
                state.update(status="ready", current_node=payload["next_node"], step_count=state["step_count"] + 1)
            elif event["event_type"] == "AGENT_CLAIMED":
                state["status"] = "claimed"
            elif event["event_type"] == "AGENT_LEASE_RENEWED":
                state["status"] = "claimed"
            elif event["event_type"] in {"AGENT_CLAIM_EXPIRED", "AGENT_CLAIM_RELEASED"}:
                state["status"] = "ready"
            elif event["event_type"] == "AGENT_SUBMITTED":
                state.update(status="ready", current_node=payload["next_node"], step_count=state["step_count"] + 1)
            elif event["event_type"] == "RUN_TERMINAL":
                state.update(status="terminal", current_node=event["node_id"], terminal_outcome=payload["outcome"])
        return state

    def replay(self, run_id: str) -> dict[str, Any]:
        projection = self.get_run(run_id)
        rebuilt = self.reduce(self.events(run_id))
        comparable = {key: projection[key] for key in rebuilt}
        return {"matches_projection": comparable == rebuilt, "rebuilt": rebuilt, "projection": comparable}

    def rebuild_projection(self, run_id: str) -> dict[str, Any]:
        rebuilt = self.reduce(self.events(run_id))
        with self._transaction() as connection:
            connection.execute(
                "UPDATE runs SET revision = ?, status = ?, current_node = ?, step_count = ?, "
                "terminal_outcome = ?, updated_at = ? WHERE run_id = ?",
                (
                    rebuilt["revision"], rebuilt["status"], rebuilt["current_node"],
                    rebuilt["step_count"], rebuilt["terminal_outcome"], _now(), run_id,
                ),
            )
        return self.get_run(run_id)

    def inspect(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            waits = [dict(row) for row in connection.execute("SELECT * FROM waits WHERE run_id = ?", (run_id,))]
            outbox = [dict(row) for row in connection.execute("SELECT * FROM outbox WHERE run_id = ?", (run_id,))]
            receipts = [dict(row) for row in connection.execute("SELECT * FROM receipts WHERE run_id = ?", (run_id,))]
        return {
            "run": self.get_run(run_id),
            "events": self.events(run_id),
            "waits": waits,
            "outbox": outbox,
            "receipts": receipts,
            "replay": self.replay(run_id),
        }
