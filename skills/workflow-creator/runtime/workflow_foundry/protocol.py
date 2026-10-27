from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .compiler import WORKER_KINDS
from .runtime import RevisionConflict, SQLiteRuntime, WorkflowRuntimeError


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AgentProtocolError(WorkflowRuntimeError):
    pass


class SessionConflict(AgentProtocolError):
    pass


class ClaimConflict(AgentProtocolError):
    pass


class LeaseExpired(AgentProtocolError):
    pass


class ContractViolation(AgentProtocolError):
    pass


class AuthorityViolation(AgentProtocolError):
    pass


class SubmissionConflict(AgentProtocolError):
    pass


class LessonViolation(AgentProtocolError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _moment(at: datetime | None = None) -> datetime:
    current = at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _iso(at: datetime | None = None) -> str:
    return _moment(at).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _json_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _public_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in row.items() if key not in {"capabilities_json", "metadata_json"}},
        "capabilities": _json_list(row["capabilities_json"]),
        "metadata": json.loads(row["metadata_json"]),
    }


class ExternalAgentProtocol:
    """Durable worker protocol for external coding-agent sessions.

    Codex, Claude Code, Gemini CLI, and humans all use the same claim and
    submission contract. The provider is metadata; the database is authority.
    """

    def __init__(self, runtime: SQLiteRuntime):
        self.runtime = runtime

    def register_session(
        self,
        session_id: str,
        provider: str,
        model: str,
        actor: str,
        capabilities: list[str],
        metadata: dict[str, Any] | None = None,
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not all(isinstance(value, str) and value.strip() for value in (session_id, provider, model, actor)):
            raise AgentProtocolError("session_id, provider, model, and actor are required")
        if any(not isinstance(item, str) or not item for item in capabilities) or len(set(capabilities)) != len(capabilities):
            raise AgentProtocolError("capabilities must contain unique non-empty strings")
        metadata = metadata or {}
        capabilities_json = _canonical(sorted(capabilities))
        metadata_json = _canonical(metadata)
        now = _iso(at)
        with self.runtime._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing:
                row = dict(existing)
                same = (
                    row["provider"] == provider
                    and row["model"] == model
                    and row["actor"] == actor
                    and row["capabilities_json"] == capabilities_json
                    and row["metadata_json"] == metadata_json
                )
                if not same or row["state"] != "active":
                    raise SessionConflict("session ID is already bound to different or ended identity")
                connection.execute(
                    "UPDATE agent_sessions SET heartbeat_at = ? WHERE session_id = ?", (now, session_id)
                )
            else:
                connection.execute(
                    "INSERT INTO agent_sessions VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL)",
                    (session_id, provider, model, actor, capabilities_json, metadata_json, now, now),
                )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with closing(self.runtime._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            raise AgentProtocolError(f"session not found: {session_id}")
        return _public_session(dict(row))

    def heartbeat_session(self, session_id: str, *, at: datetime | None = None) -> dict[str, Any]:
        with self.runtime._transaction() as connection:
            updated = connection.execute(
                "UPDATE agent_sessions SET heartbeat_at = ? WHERE session_id = ? AND state = 'active'",
                (_iso(at), session_id),
            ).rowcount
            if not updated:
                raise AgentProtocolError("active session not found")
        return self.get_session(session_id)

    def end_session(self, session_id: str, *, at: datetime | None = None) -> dict[str, Any]:
        now = _iso(at)
        with self.runtime._transaction() as connection:
            active_claim = connection.execute(
                "SELECT claim_id FROM work_claims WHERE session_id = ? AND status = 'active'", (session_id,)
            ).fetchone()
            if active_claim:
                raise ClaimConflict("release the active claim before ending the session")
            updated = connection.execute(
                "UPDATE agent_sessions SET state = 'ended', ended_at = ?, heartbeat_at = ? "
                "WHERE session_id = ? AND state = 'active'",
                (now, now, session_id),
            ).rowcount
            if not updated:
                raise AgentProtocolError("active session not found")
        return self.get_session(session_id)

    @staticmethod
    def _session(connection: Any, session_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row or row["state"] != "active":
            raise AgentProtocolError(f"active session not found: {session_id}")
        return dict(row)

    @staticmethod
    def _claim(connection: Any, claim_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM work_claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if not row:
            raise AgentProtocolError(f"claim not found: {claim_id}")
        return dict(row)

    @staticmethod
    def _active_claim(connection: Any, run_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM work_claims WHERE run_id = ? AND status = 'active'", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def _expire_if_needed(
        self,
        connection: Any,
        run: dict[str, Any],
        active: dict[str, Any] | None,
        now: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not active or _parse(active["lease_expires_at"]) > now:
            return run, active
        closed = now.isoformat()
        connection.execute(
            "UPDATE work_claims SET status = 'expired', closed_at = ? WHERE claim_id = ?",
            (closed, active["claim_id"]),
        )
        sequence = self.runtime._append(
            connection,
            run["run_id"],
            run["revision"],
            "AGENT_CLAIM_EXPIRED",
            run["current_node"],
            {
                "claim_id": active["claim_id"],
                "session_id": active["session_id"],
                "attempt_no": active["attempt_no"],
                "epoch": active["epoch"],
            },
        )
        self.runtime._project(
            connection, run["run_id"], sequence, "ready", run["current_node"], run["step_count"], None
        )
        return {**run, "revision": sequence, "status": "ready"}, None

    def frontier(self, run_id: str, *, at: datetime | None = None) -> dict[str, Any]:
        now = _moment(at)
        with closing(self.runtime._connect()) as connection:
            run = self.runtime._run(connection, run_id)
            spec = self.runtime._definition(connection, run["definition_digest"])
            node = self.runtime._nodes(spec)[run["current_node"]]
            active = self._active_claim(connection, run_id)
            if run["status"] == "terminal":
                disposition = "terminal"
            elif run["status"] == "waiting":
                disposition = "awaiting_event"
            elif run["status"] == "effect_pending":
                disposition = "awaiting_effect_receipt"
            elif active and _parse(active["lease_expires_at"]) <= now:
                disposition = "reclaimable"
            elif active:
                disposition = "claimed"
            elif run["status"] == "ready" and node["kind"] in WORKER_KINDS:
                disposition = "claimable"
            else:
                disposition = "dedicated_protocol_required"
            attempts = connection.execute(
                "SELECT COUNT(*) AS n FROM work_claims WHERE run_id = ? AND node_id = ?",
                (run_id, node["id"]),
            ).fetchone()["n"]
        executor = node.get("executor", {})
        return {
            "disposition": disposition,
            "run": run,
            "node": node,
            "required_capabilities": executor.get("required_capabilities", []),
            "attempts_used": attempts,
            "max_claim_attempts": spec.get("policies", {}).get("max_claim_attempts", 5),
            "active_claim": None if not active else {
                key: active[key]
                for key in ("claim_id", "session_id", "attempt_no", "epoch", "lease_expires_at", "status")
            },
        }

    @staticmethod
    def _lesson_status(connection: Any, lesson_id: str, version: int) -> str:
        row = connection.execute(
            "SELECT event_type FROM lesson_events WHERE lesson_id = ? AND version = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (lesson_id, version),
        ).fetchone()
        return row["event_type"].removeprefix("lesson_") if row else "unknown"

    def _applicable_lessons(
        self, connection: Any, tags: set[str], workflow_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT * FROM lessons ORDER BY lesson_id, version").fetchall()
        selected: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            if self._lesson_status(connection, row["lesson_id"], row["version"]) != "activated":
                continue
            triggers = set(_json_list(row["trigger_tags_json"]))
            in_scope = row["scope"] == "global" or row["scope"] == workflow_id
            if in_scope and (not triggers or triggers & tags):
                selected.append(
                    {
                        "lesson_id": row["lesson_id"],
                        "version": row["version"],
                        "scope": row["scope"],
                        "trigger_tags": sorted(triggers),
                        "prevention": row["prevention"],
                        "source_refs": json.loads(row["source_refs_json"]),
                    }
                )
        return selected

    def _context_pack(
        self,
        connection: Any,
        run: dict[str, Any],
        spec: dict[str, Any],
        node: dict[str, Any],
        session: dict[str, Any],
        claim_id: str,
        fence_token: str,
        attempt_no: int,
        epoch: int,
        lease_expires_at: str,
        resulting_revision: int,
    ) -> dict[str, Any]:
        limit = spec.get("policies", {}).get("event_context_limit", 25)
        event_rows = connection.execute(
            "SELECT sequence, event_type, node_id, payload_json, created_at FROM events "
            "WHERE run_id = ? ORDER BY sequence DESC LIMIT ?",
            (run["run_id"], limit),
        ).fetchall()
        recent_events = [
            {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "node_id": row["node_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in reversed(event_rows)
        ]
        start_row = connection.execute(
            "SELECT payload_json FROM events WHERE run_id = ? AND event_type = 'RUN_STARTED' "
            "ORDER BY sequence LIMIT 1",
            (run["run_id"],),
        ).fetchone()
        start_inputs: dict[str, Any] = (
            json.loads(start_row["payload_json"]).get("inputs", {}) if start_row else {}
        )
        prior = connection.execute(
            "SELECT checkpoint_json, session_id, status, closed_at FROM work_claims "
            "WHERE run_id = ? AND node_id = ? AND checkpoint_json IS NOT NULL "
            "ORDER BY attempt_no DESC LIMIT 1",
            (run["run_id"], node["id"]),
        ).fetchone()
        executor = node.get("executor", {})
        tags = set(executor.get("risk_tags", [])) | {node["kind"], node["id"]}
        contract_id = node.get("output_contract")
        contract = spec.get("contracts", {}).get(contract_id, {}) if contract_id else {}
        return {
            "schema_version": "coding_agent_context_v1",
            "definition": {
                "workflow_id": spec["workflow_id"],
                "definition_version": spec["definition_version"],
                "definition_digest": run["definition_digest"],
                "objective": spec["objective"],
            },
            "run": {
                "run_id": run["run_id"],
                "revision": resulting_revision,
                "step_count": run["step_count"],
                "max_steps": spec["policies"]["max_steps"],
            },
            "claim": {
                "claim_id": claim_id,
                "attempt_no": attempt_no,
                "epoch": epoch,
                "fence_token": fence_token,
                "lease_expires_at": lease_expires_at,
            },
            "session": {
                "session_id": session["session_id"],
                "provider": session["provider"],
                "model": session["model"],
                "actor": session["actor"],
                "capabilities": _json_list(session["capabilities_json"]),
            },
            "obligation": {
                "node_id": node["id"],
                "kind": node["kind"],
                "instructions": node.get("instructions", "Complete the node contract and submit evidence."),
                "allowed_outcomes": sorted(node.get("routes", {})),
                "output_contract": contract_id,
                "required_capabilities": executor.get("required_capabilities", []),
                "allowed_actions": executor.get("allowed_actions", []),
                "forbidden_actions": executor.get("forbidden_actions", []),
                "required_actions": executor.get("required_actions", []),
                "independent_from": executor.get("independent_from", []),
                "risk_tags": sorted(tags),
            },
            "start_inputs": start_inputs,
            "recent_events": recent_events,
            "prior_handoff": None if not prior else {
                "session_id": prior["session_id"],
                "status": prior["status"],
                "closed_at": prior["closed_at"],
                "checkpoint": json.loads(prior["checkpoint_json"]),
            },
            "applicable_lessons": self._applicable_lessons(
                connection, tags, workflow_id=spec["workflow_id"]
            ),
            "submission_contract": {
                "schema_version": "coding_agent_submission_v1",
                "result_required_fields": contract.get("required_fields", []),
                "result_field_types": contract.get("field_types", {}),
                "required_evidence_kinds": contract.get("evidence_kinds", []),
                "evidence_manifest_required_fields": ["kind", "uri", "sha256", "summary"],
                "failure_required_fields": ["code", "message", "retryable"],
            },
        }

    def claim(
        self,
        run_id: str,
        session_id: str,
        expected_revision: int,
        *,
        lease_seconds: int | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _moment(at)
        with self.runtime._transaction() as connection:
            run = self.runtime._run(connection, run_id)
            self.runtime._assert_revision(run, expected_revision)
            active = self._active_claim(connection, run_id)
            run, active = self._expire_if_needed(connection, run, active, now)
            if active:
                raise ClaimConflict(f"run already claimed by session {active['session_id']}")
            if run["status"] != "ready":
                raise ClaimConflict(f"run is {run['status']}, not claimable")
            spec = self.runtime._definition(connection, run["definition_digest"])
            node = self.runtime._nodes(spec)[run["current_node"]]
            if node["kind"] not in WORKER_KINDS:
                raise ClaimConflict(f"{node['kind']} uses a dedicated protocol")
            session = self._session(connection, session_id)
            executor = node.get("executor", {})
            capabilities = set(_json_list(session["capabilities_json"]))
            missing = set(executor.get("required_capabilities", [])) - capabilities
            if missing:
                raise AuthorityViolation(f"session lacks required capabilities: {sorted(missing)}")
            for producer in executor.get("independent_from", []):
                prior = connection.execute(
                    "SELECT payload_json FROM events WHERE run_id = ? AND node_id = ? "
                    "AND event_type = 'AGENT_SUBMITTED' ORDER BY sequence DESC LIMIT 1",
                    (run_id, producer),
                ).fetchone()
                if prior and json.loads(prior["payload_json"]).get("session_id") == session_id:
                    raise AuthorityViolation(
                        f"node requires a different session from producer {producer}"
                    )
            attempts = connection.execute(
                "SELECT COUNT(*) AS n FROM work_claims WHERE run_id = ? AND node_id = ?",
                (run_id, node["id"]),
            ).fetchone()["n"]
            max_attempts = spec.get("policies", {}).get("max_claim_attempts", 5)
            if attempts >= max_attempts:
                raise ClaimConflict(f"claim attempt budget exhausted for {node['id']}")
            configured_lease = executor.get(
                "lease_seconds", spec.get("policies", {}).get("default_lease_seconds", 900)
            )
            duration = configured_lease if lease_seconds is None else lease_seconds
            if not isinstance(duration, int) or isinstance(duration, bool) or duration < 5:
                raise AgentProtocolError("lease_seconds must be an integer of at least 5")
            if duration > configured_lease:
                raise AuthorityViolation(
                    f"requested lease exceeds configured maximum of {configured_lease} seconds"
                )
            attempt_no = attempts + 1
            epoch = attempt_no
            claim_id = str(uuid.uuid4())
            fence_token = uuid.uuid4().hex
            expires = (now + timedelta(seconds=duration)).isoformat()
            resulting_revision = run["revision"] + 1
            context = self._context_pack(
                connection, run, spec, node, session, claim_id, fence_token,
                attempt_no, epoch, expires, resulting_revision,
            )
            context_digest = _digest(context)
            connection.execute(
                "INSERT INTO work_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, ?, NULL, NULL)",
                (
                    claim_id, run_id, node["id"], resulting_revision, attempt_no, epoch,
                    session_id, fence_token, expires, context_digest, _canonical(context), now.isoformat(),
                ),
            )
            sequence = self.runtime._append(
                connection,
                run_id,
                run["revision"],
                "AGENT_CLAIMED",
                node["id"],
                {
                    "claim_id": claim_id,
                    "session_id": session_id,
                    "attempt_no": attempt_no,
                    "epoch": epoch,
                    "lease_expires_at": expires,
                    "context_digest": context_digest,
                },
            )
            self.runtime._project(
                connection, run_id, sequence, "claimed", node["id"], run["step_count"], None
            )
        return {
            "run": self.runtime.get_run(run_id),
            "claim": {
                "claim_id": claim_id,
                "fence_token": fence_token,
                "attempt_no": attempt_no,
                "epoch": epoch,
                "lease_expires_at": expires,
                "context_digest": context_digest,
            },
            "context_pack": context,
        }

    @staticmethod
    def _assert_live_claim(
        claim: dict[str, Any], fence_token: str, now: datetime
    ) -> None:
        if claim["fence_token"] != fence_token:
            raise ClaimConflict("fencing token does not match the claim")
        if claim["status"] != "active":
            raise ClaimConflict(f"claim is {claim['status']}, not active")
        if _parse(claim["lease_expires_at"]) <= now:
            raise LeaseExpired("claim lease has expired")

    def renew(
        self,
        claim_id: str,
        fence_token: str,
        expected_revision: int,
        *,
        lease_seconds: int | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _moment(at)
        with self.runtime._transaction() as connection:
            claim = self._claim(connection, claim_id)
            self._assert_live_claim(claim, fence_token, now)
            run = self.runtime._run(connection, claim["run_id"])
            self.runtime._assert_revision(run, expected_revision)
            spec = self.runtime._definition(connection, run["definition_digest"])
            node = self.runtime._nodes(spec)[claim["node_id"]]
            configured = node.get("executor", {}).get(
                "lease_seconds", spec.get("policies", {}).get("default_lease_seconds", 900)
            )
            duration = configured if lease_seconds is None else lease_seconds
            if not isinstance(duration, int) or duration < 5 or duration > configured:
                raise AuthorityViolation(f"renewal must be between 5 and {configured} seconds")
            expires = (now + timedelta(seconds=duration)).isoformat()
            sequence = self.runtime._append(
                connection,
                run["run_id"],
                run["revision"],
                "AGENT_LEASE_RENEWED",
                claim["node_id"],
                {"claim_id": claim_id, "session_id": claim["session_id"], "lease_expires_at": expires},
            )
            connection.execute(
                "UPDATE work_claims SET lease_expires_at = ?, renewed_at = ?, run_revision = ? "
                "WHERE claim_id = ?",
                (expires, now.isoformat(), sequence, claim_id),
            )
            self.runtime._project(
                connection, run["run_id"], sequence, "claimed", run["current_node"], run["step_count"], None
            )
        return {"run": self.runtime.get_run(claim["run_id"]), "claim_id": claim_id, "lease_expires_at": expires}

    def record_action(
        self,
        claim_id: str,
        fence_token: str,
        action_type: str,
        resource: str,
        *,
        mutation: bool = False,
        receipt: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not action_type or not resource:
            raise AgentProtocolError("action_type and resource are required")
        now = _moment(at)
        receipt = receipt or {}
        with self.runtime._transaction() as connection:
            claim = self._claim(connection, claim_id)
            self._assert_live_claim(claim, fence_token, now)
            run = self.runtime._run(connection, claim["run_id"])
            spec = self.runtime._definition(connection, run["definition_digest"])
            node = self.runtime._nodes(spec)[claim["node_id"]]
            executor = node.get("executor", {})
            allowed = set(executor.get("allowed_actions", []))
            forbidden = set(executor.get("forbidden_actions", []))
            if action_type in forbidden or (allowed and action_type not in allowed):
                raise AuthorityViolation(f"action {action_type!r} is outside node authority")
            if mutation and not any(key in receipt for key in ("sha256", "receipt_id", "evidence")):
                raise ContractViolation("mutating actions require a content or external receipt")
            sequence = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_actions WHERE claim_id = ?", (claim_id,)
            ).fetchone()["n"] + 1
            action_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO agent_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim_id, sequence, action_id, action_type, resource,
                    int(mutation), _canonical(receipt), now.isoformat(),
                ),
            )
        return {
            "action_id": action_id,
            "claim_id": claim_id,
            "sequence": sequence,
            "action_type": action_type,
            "resource": resource,
            "mutation": mutation,
            "receipt": receipt,
        }

    @staticmethod
    def _validate_evidence(evidence: list[dict[str, Any]], required_kinds: set[str]) -> None:
        if not isinstance(evidence, list):
            raise ContractViolation("evidence must be an array")
        observed: set[str] = set()
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise ContractViolation(f"evidence[{index}] must be an object")
            missing = {"kind", "uri", "sha256", "summary"} - set(item)
            if missing:
                raise ContractViolation(f"evidence[{index}] is missing {sorted(missing)}")
            if not all(isinstance(item[key], str) and item[key] for key in ("kind", "uri", "summary")):
                raise ContractViolation(f"evidence[{index}] has empty string fields")
            if not isinstance(item["sha256"], str) or not SHA256_RE.fullmatch(item["sha256"].lower()):
                raise ContractViolation(f"evidence[{index}].sha256 must be a hexadecimal SHA-256")
            observed.add(item["kind"])
        missing_kinds = required_kinds - observed
        if missing_kinds:
            raise ContractViolation(f"submission lacks evidence kinds: {sorted(missing_kinds)}")

    def submit(
        self,
        claim_id: str,
        fence_token: str,
        expected_revision: int,
        outcome: str,
        result: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        summary: str = "",
        at: datetime | None = None,
    ) -> dict[str, Any]:
        envelope = {"outcome": outcome, "result": result, "evidence": evidence, "summary": summary}
        submission_digest = _digest(envelope)
        now = _moment(at)
        with self.runtime._transaction() as connection:
            existing = connection.execute(
                "SELECT submission_digest, run_id FROM agent_submissions WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if existing:
                if existing["submission_digest"] != submission_digest:
                    raise SubmissionConflict("claim already has a different submission")
                return self.runtime._run(connection, existing["run_id"])
            claim = self._claim(connection, claim_id)
            self._assert_live_claim(claim, fence_token, now)
            run = self.runtime._run(connection, claim["run_id"])
            self.runtime._assert_revision(run, expected_revision)
            if run["status"] != "claimed" or run["current_node"] != claim["node_id"]:
                raise ClaimConflict("claim is not bound to the current run obligation")
            spec = self.runtime._definition(connection, run["definition_digest"])
            nodes = self.runtime._nodes(spec)
            node = nodes[claim["node_id"]]
            if outcome not in node.get("routes", {}):
                raise ContractViolation(f"outcome {outcome!r} is not valid for {node['id']}")
            if not isinstance(result, dict) or not isinstance(summary, str):
                raise ContractViolation("result must be an object and summary must be a string")
            contract = spec.get("contracts", {}).get(node.get("output_contract"), {})
            if outcome == "error":
                missing_fields = {"code", "message", "retryable"} - set(result)
            else:
                missing_fields = set(contract.get("required_fields", [])) - set(result)
            if missing_fields:
                raise ContractViolation(f"result lacks required fields: {sorted(missing_fields)}")
            wrong_types = sorted(
                field
                for field, expected_type in contract.get("field_types", {}).items()
                if field in result and not _matches_type(result[field], expected_type)
            )
            if wrong_types:
                raise ContractViolation(f"result fields have invalid types: {wrong_types}")
            required_evidence = set() if outcome == "error" else set(contract.get("evidence_kinds", []))
            self._validate_evidence(evidence, required_evidence)
            required_actions = (
                set() if outcome == "error" else set(node.get("executor", {}).get("required_actions", []))
            )
            action_rows = connection.execute(
                "SELECT action_type FROM agent_actions WHERE claim_id = ?", (claim_id,)
            ).fetchall()
            observed_actions = {row["action_type"] for row in action_rows}
            if required_actions - observed_actions:
                raise ContractViolation(
                    f"claim lacks required journaled actions: {sorted(required_actions - observed_actions)}"
                )
            step_count = self.runtime._assert_step_budget(run, spec)
            self.runtime._assert_visit_budget(
                connection, run["run_id"], node, "AGENT_SUBMITTED", spec["policies"]["max_steps"]
            )
            session = self._session(connection, claim["session_id"])
            connection.execute(
                "INSERT INTO agent_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim_id, run["run_id"], node["id"], claim["session_id"], outcome,
                    submission_digest, _canonical(result), _canonical(evidence), summary, now.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE work_claims SET status = 'completed', closed_at = ? WHERE claim_id = ?",
                (now.isoformat(), claim_id),
            )
            target = node["routes"][outcome]
            sequence = self.runtime._append(
                connection,
                run["run_id"],
                run["revision"],
                "AGENT_SUBMITTED",
                node["id"],
                {
                    "claim_id": claim_id,
                    "session_id": claim["session_id"],
                    "provider": session["provider"],
                    "model": session["model"],
                    "actor": session["actor"],
                    "outcome": outcome,
                    "next_node": target,
                    "submission_digest": submission_digest,
                    "result": result,
                    "evidence": evidence,
                    "summary": summary,
                },
            )
            sequence, status, terminal = self.runtime._enter(
                connection, run["run_id"], nodes, target, sequence
            )
            self.runtime._project(
                connection, run["run_id"], sequence, status, target, step_count, terminal
            )
        return self.runtime.get_run(run["run_id"])

    def fail(
        self,
        claim_id: str,
        fence_token: str,
        expected_revision: int,
        code: str,
        message: str,
        *,
        retryable: bool,
        evidence: list[dict[str, Any]] | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        return self.submit(
            claim_id,
            fence_token,
            expected_revision,
            "error",
            {"code": code, "message": message, "retryable": retryable},
            evidence or [],
            summary=message,
            at=at,
        )

    def release(
        self,
        claim_id: str,
        fence_token: str,
        expected_revision: int,
        checkpoint: dict[str, Any],
        *,
        handoff_to: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        now = _moment(at)
        if not isinstance(checkpoint, dict) or not checkpoint:
            raise ContractViolation("release requires a non-empty checkpoint object")
        with self.runtime._transaction() as connection:
            claim = self._claim(connection, claim_id)
            self._assert_live_claim(claim, fence_token, now)
            run = self.runtime._run(connection, claim["run_id"])
            self.runtime._assert_revision(run, expected_revision)
            if handoff_to:
                self._session(connection, handoff_to)
            connection.execute(
                "UPDATE work_claims SET status = 'released', checkpoint_json = ?, closed_at = ? "
                "WHERE claim_id = ?",
                (_canonical(checkpoint), now.isoformat(), claim_id),
            )
            sequence = self.runtime._append(
                connection,
                run["run_id"],
                run["revision"],
                "AGENT_CLAIM_RELEASED",
                claim["node_id"],
                {
                    "claim_id": claim_id,
                    "session_id": claim["session_id"],
                    "handoff_to": handoff_to,
                    "checkpoint": checkpoint,
                },
            )
            self.runtime._project(
                connection, run["run_id"], sequence, "ready", run["current_node"], run["step_count"], None
            )
        return self.runtime.get_run(run["run_id"])

    def propose_lesson(
        self,
        lesson_id: str,
        scope: str,
        trigger_tags: list[str],
        prevention: str,
        source_refs: list[dict[str, Any]],
        proposal_evidence: dict[str, Any],
        proposed_by: str,
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not lesson_id or not scope or not prevention.strip() or not proposed_by:
            raise LessonViolation("lesson_id, scope, prevention, and proposed_by are required")
        if any(not isinstance(tag, str) or not tag for tag in trigger_tags) or len(set(trigger_tags)) != len(trigger_tags):
            raise LessonViolation("trigger_tags must contain unique non-empty strings")
        now = _iso(at)
        with self.runtime._transaction() as connection:
            latest = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM lessons WHERE lesson_id = ?",
                (lesson_id,),
            ).fetchone()["version"]
            version = latest + 1
            connection.execute(
                "INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson_id, version, scope, _canonical(sorted(trigger_tags)), prevention.strip(),
                    _canonical(source_refs), _canonical(proposal_evidence), proposed_by, now,
                ),
            )
            connection.execute(
                "INSERT INTO lesson_events (lesson_id, version, event_type, actor, evidence_json, created_at) "
                "VALUES (?, ?, 'lesson_proposed', ?, ?, ?)",
                (lesson_id, version, proposed_by, _canonical(proposal_evidence), now),
            )
        return self.get_lesson(lesson_id, version)

    def activate_lesson(
        self,
        lesson_id: str,
        version: int,
        actor: str,
        evidence: dict[str, Any],
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        required = {"regression", "held_out", "rollback"}
        if required - set(evidence) or any(not evidence[key] for key in required):
            raise LessonViolation(f"activation evidence requires {sorted(required)}")
        with self.runtime._transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM lessons WHERE lesson_id = ? AND version = ?", (lesson_id, version)
            ).fetchone()
            if not row:
                raise LessonViolation("lesson version not found")
            status = self._lesson_status(connection, lesson_id, version)
            if status == "activated":
                return self.get_lesson(lesson_id, version)
            if status != "proposed":
                raise LessonViolation(f"lesson is {status}, not proposed")
            connection.execute(
                "INSERT INTO lesson_events (lesson_id, version, event_type, actor, evidence_json, created_at) "
                "VALUES (?, ?, 'lesson_activated', ?, ?, ?)",
                (lesson_id, version, actor, _canonical(evidence), _iso(at)),
            )
        return self.get_lesson(lesson_id, version)

    def retire_lesson(
        self,
        lesson_id: str,
        version: int,
        actor: str,
        evidence: dict[str, Any],
        *,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not evidence:
            raise LessonViolation("retirement requires evidence")
        with self.runtime._transaction() as connection:
            if self._lesson_status(connection, lesson_id, version) != "activated":
                raise LessonViolation("only an activated lesson can be retired")
            connection.execute(
                "INSERT INTO lesson_events (lesson_id, version, event_type, actor, evidence_json, created_at) "
                "VALUES (?, ?, 'lesson_retired', ?, ?, ?)",
                (lesson_id, version, actor, _canonical(evidence), _iso(at)),
            )
        return self.get_lesson(lesson_id, version)

    def get_lesson(self, lesson_id: str, version: int) -> dict[str, Any]:
        with closing(self.runtime._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM lessons WHERE lesson_id = ? AND version = ?", (lesson_id, version)
            ).fetchone()
            if not row:
                raise LessonViolation("lesson version not found")
            events = connection.execute(
                "SELECT sequence, event_type, actor, evidence_json, created_at FROM lesson_events "
                "WHERE lesson_id = ? AND version = ? ORDER BY sequence",
                (lesson_id, version),
            ).fetchall()
        item = dict(row)
        return {
            "lesson_id": item["lesson_id"],
            "version": item["version"],
            "scope": item["scope"],
            "trigger_tags": json.loads(item["trigger_tags_json"]),
            "prevention": item["prevention"],
            "source_refs": json.loads(item["source_refs_json"]),
            "proposal_evidence": json.loads(item["proposal_evidence_json"]),
            "proposed_by": item["proposed_by"],
            "created_at": item["created_at"],
            "status": events[-1]["event_type"].removeprefix("lesson_") if events else "unknown",
            "events": [
                {
                    "sequence": event["sequence"],
                    "event_type": event["event_type"],
                    "actor": event["actor"],
                    "evidence": json.loads(event["evidence_json"]),
                    "created_at": event["created_at"],
                }
                for event in events
            ],
        }

    def list_lessons(self) -> list[dict[str, Any]]:
        with closing(self.runtime._connect()) as connection:
            rows = connection.execute(
                "SELECT lesson_id, version FROM lessons ORDER BY lesson_id, version"
            ).fetchall()
        return [self.get_lesson(row["lesson_id"], row["version"]) for row in rows]

    def inspect(self, run_id: str) -> dict[str, Any]:
        base = self.runtime.inspect(run_id)
        with closing(self.runtime._connect()) as connection:
            claims = [dict(row) for row in connection.execute(
                "SELECT * FROM work_claims WHERE run_id = ? ORDER BY claimed_at", (run_id,)
            )]
            submissions = [dict(row) for row in connection.execute(
                "SELECT * FROM agent_submissions WHERE run_id = ? ORDER BY created_at", (run_id,)
            )]
            actions = [dict(row) for row in connection.execute(
                "SELECT a.* FROM agent_actions a JOIN work_claims c ON c.claim_id = a.claim_id "
                "WHERE c.run_id = ? ORDER BY a.created_at, a.sequence", (run_id,)
            )]
        for claim in claims:
            claim["context"] = json.loads(claim.pop("context_json"))
            claim["fence_token"] = "<redacted>"
            if "claim" in claim["context"]:
                claim["context"]["claim"]["fence_token"] = "<redacted>"
            claim["checkpoint"] = None if claim["checkpoint_json"] is None else json.loads(claim["checkpoint_json"])
            claim.pop("checkpoint_json")
        for submission in submissions:
            submission["result"] = json.loads(submission.pop("result_json"))
            submission["evidence"] = json.loads(submission.pop("evidence_json"))
        for action in actions:
            action["receipt"] = json.loads(action.pop("receipt_json"))
            action["mutation"] = bool(action["mutation"])
        return {**base, "claims": claims, "agent_actions": actions, "agent_submissions": submissions}


def write_context_bundle(context_pack: dict[str, Any], output_directory: str | Path) -> dict[str, Any]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    context_path = output / "context-pack.json"
    instructions_path = output / "AGENT_INSTRUCTIONS.md"
    submission_path = output / "submission-template.json"
    context_text = json.dumps(context_pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    context_path.write_text(context_text, encoding="utf-8")
    provider = context_pack["session"]["provider"]
    obligation = context_pack["obligation"]
    instructions_path.write_text(
        "# Workflow Foundry obligation\n\n"
        f"Provider: {provider}  \n"
        f"Run: `{context_pack['run']['run_id']}` at revision `{context_pack['run']['revision']}`  \n"
        f"Node: `{obligation['node_id']}` (`{obligation['kind']}`)  \n"
        f"Lease expires: `{context_pack['claim']['lease_expires_at']}`\n\n"
        "Read `context-pack.json` as the complete authoritative context for this obligation. "
        "Do not infer workflow state from prior chat. Journal every material action, stay within "
        "the allowed action list, and do not perform forbidden actions. Submit only observed "
        "results and content-addressed evidence matching `submission-template.json`. If the work "
        "cannot finish before lease expiry, renew or release it with a durable checkpoint.\n\n"
        f"## Exact obligation\n\n{obligation['instructions']}\n",
        encoding="utf-8",
    )
    submission_path.write_text(
        json.dumps(
            {
                "schema_version": "coding_agent_submission_v1",
                "claim_id": context_pack["claim"]["claim_id"],
                "fence_token": context_pack["claim"]["fence_token"],
                "expected_revision": context_pack["run"]["revision"],
                "outcome": "REPLACE_WITH_ALLOWED_OUTCOME",
                "result": {field: None for field in context_pack["submission_contract"]["result_required_fields"]},
                "evidence": [
                    {"kind": kind, "uri": "", "sha256": "", "summary": ""}
                    for kind in context_pack["submission_contract"]["required_evidence_kinds"]
                ],
                "summary": "",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "output_directory": str(output.resolve()),
        "context_pack": str(context_path.resolve()),
        "instructions": str(instructions_path.resolve()),
        "submission_template": str(submission_path.resolve()),
        "context_sha256": hashlib.sha256(context_text.encode("utf-8")).hexdigest(),
    }
