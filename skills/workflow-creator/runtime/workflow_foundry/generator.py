from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .compiler import CompiledWorkflow, compile_workflow


class BriefError(ValueError):
    pass


def starter_brief(workflow_id: str, objective: str, requirements: list[str]) -> dict[str, Any]:
    if not workflow_id or not objective.strip() or not requirements:
        raise BriefError("workflow_id, objective, and at least one requirement are required")
    return {
        "schema_version": "workflow_brief_v1",
        "workflow_id": workflow_id,
        "definition_version": "1.0.0",
        "objective": objective.strip(),
        "requirements": requirements,
        "research_required": True,
        "human_review": True,
        "max_recovery_cycles": 3,
        "default_lease_seconds": 1800,
    }


def write_starter_brief(
    output_path: str | Path, workflow_id: str, objective: str, requirements: list[str]
) -> dict[str, Any]:
    brief = starter_brief(workflow_id, objective, requirements)
    Path(output_path).write_text(
        json.dumps(brief, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return brief


def _require_strings(brief: dict[str, Any], field: str) -> list[str]:
    value = brief.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise BriefError(f"{field} must contain non-empty strings")
    return [item.strip() for item in value]


def generate_coding_workflow(raw_brief: dict[str, Any]) -> CompiledWorkflow:
    """Compile a structured task brief into the standard adaptive coding graph."""

    brief = deepcopy(raw_brief)
    if brief.get("schema_version") != "workflow_brief_v1":
        raise BriefError("schema_version must be workflow_brief_v1")
    workflow_id = brief.get("workflow_id")
    objective = brief.get("objective")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise BriefError("workflow_id is required")
    if not isinstance(objective, str) or not objective.strip():
        raise BriefError("objective is required")
    requirements = _require_strings(brief, "requirements")
    if not requirements:
        raise BriefError("requirements must not be empty")
    research_required = brief.get("research_required", True)
    human_review = brief.get("human_review", True)
    if not isinstance(research_required, bool) or not isinstance(human_review, bool):
        raise BriefError("research_required and human_review must be booleans")
    max_recovery_cycles = brief.get("max_recovery_cycles", 3)
    if not isinstance(max_recovery_cycles, int) or isinstance(max_recovery_cycles, bool) or max_recovery_cycles < 1:
        raise BriefError("max_recovery_cycles must be a positive integer")
    effect = brief.get("final_effect")
    if effect is not None and (
        not isinstance(effect, dict)
        or not isinstance(effect.get("idempotency_key"), str)
        or not isinstance(effect.get("receipt_type"), str)
    ):
        raise BriefError("final_effect requires idempotency_key and receipt_type")

    requirement_text = "\n".join(f"- {item}" for item in requirements)
    nodes: list[dict[str, Any]] = []
    if research_required:
        nodes.append(
            {
                "id": "research",
                "kind": "agent",
                "instructions": (
                    "Research the task and current repository authority before design. "
                    "Separate confirmed evidence, assumptions, and unresolved risks.\n" + requirement_text
                ),
                "output_contract": "research_bundle_v1",
                "executor": {
                    "required_capabilities": ["research"],
                    "allowed_actions": ["read", "browse", "analyze"],
                    "forbidden_actions": ["edit", "push", "comment", "merge"],
                    "required_actions": ["analyze"],
                    "risk_tags": ["research", "source_coverage", "stale_authority"],
                },
                "routes": {"success": "plan", "error": "blocked"},
            }
        )
    nodes.append(
        {
            "id": "plan",
            "kind": "agent",
            "instructions": (
                "Produce a complete evidence-linked implementation plan that addresses every requirement "
                "and every applicable active prevention.\n" + requirement_text
            ),
            "output_contract": "implementation_plan_v1",
            "executor": {
                "required_capabilities": ["planning"],
                "allowed_actions": ["read", "analyze", "write_plan"],
                "forbidden_actions": ["edit", "push", "comment", "merge"],
                "required_actions": ["analyze", "write_plan"],
                "risk_tags": ["planning", "requirement_coverage", "mistake_ledger"],
            },
            "routes": {"success": "implement", "error": "blocked"},
        }
    )
    nodes.extend(
        [
            {
                "id": "implement",
                "kind": "agent",
                "instructions": (
                    "Implement the complete current plan, journal every material action, run focused checks, "
                    "and return exact changed-artifact identities.\n" + requirement_text
                ),
                "output_contract": "implementation_result_v1",
                "executor": {
                    "required_capabilities": ["coding"],
                    "allowed_actions": ["read", "edit", "test"],
                    "forbidden_actions": ["push", "comment", "merge"],
                    "required_actions": ["edit", "test"],
                    "risk_tags": ["implementation", "stale_identity", "evidence_scope"],
                },
                "routes": {"success": "validate", "error": "diagnose"},
                "max_visits": max_recovery_cycles + 1,
            },
            {
                "id": "validate",
                "kind": "validation",
                "instructions": (
                    "Independently validate the exact implementation identity against every public requirement, "
                    "the plan, relevant regression tests, and applicable preventions. Do not edit the candidate."
                ),
                "output_contract": "validation_report_v1",
                "executor": {
                    "required_capabilities": ["validation"],
                    "allowed_actions": ["read", "test", "analyze"],
                    "forbidden_actions": ["edit", "push", "comment", "merge"],
                    "required_actions": ["test", "analyze"],
                    "independent_from": ["implement"],
                    "risk_tags": ["validation", "independent_review", "evidence_scope"],
                },
                "routes": {"pass": "review" if human_review else ("publish" if effect else "complete"), "fail": "diagnose", "error": "blocked"},
                "max_visits": max_recovery_cycles + 1,
            },
            {
                "id": "diagnose",
                "kind": "agent",
                "instructions": (
                    "Preserve the failed evidence, identify the earliest cause and prior-gate escape, review "
                    "applicable lessons and already-explored research, then produce one complete remedy plan."
                ),
                "output_contract": "remedy_plan_v1",
                "executor": {
                    "required_capabilities": ["diagnosis", "planning"],
                    "allowed_actions": ["read", "analyze", "write_plan"],
                    "forbidden_actions": ["edit", "push", "comment", "merge"],
                    "required_actions": ["analyze", "write_plan"],
                    "risk_tags": ["recovery", "mistake_ledger", "research_frontier", "prior_gate_escape"],
                },
                "routes": {"success": "implement", "error": "blocked"},
                "max_visits": max_recovery_cycles,
            },
        ]
    )
    if human_review:
        nodes.append(
            {
                "id": "review",
                "kind": "human_wait",
                "wait": {
                    "event_type": "workflow.reviewed",
                    "correlation_key": f"{workflow_id}-review",
                    "requires_actor": True,
                    "required_evidence": ["review_record"],
                },
                "routes": {
                    "approved": "publish" if effect else "complete",
                    "rejected": "diagnose",
                    "error": "blocked",
                },
                "max_visits": max_recovery_cycles + 1,
            }
        )
    if effect:
        nodes.append(
            {
                "id": "publish",
                "kind": "effect",
                "effect": {
                    "idempotency_key": effect["idempotency_key"],
                    "receipt_type": effect["receipt_type"],
                },
                "routes": {"success": "complete", "conflict": "blocked", "error": "blocked"},
            }
        )
    nodes.extend(
        [
            {"id": "complete", "kind": "terminal", "outcome": "complete"},
            {"id": "blocked", "kind": "terminal", "outcome": "blocked"},
        ]
    )
    entry = "research" if research_required else "plan"
    spec = {
        "schema_version": "workflow_foundry_v0",
        "workflow_id": workflow_id,
        "definition_version": brief.get("definition_version", "1.0.0"),
        "objective": objective.strip(),
        "contracts": {
            "research_bundle_v1": {
                "required_fields": ["findings", "sources", "open_risks"],
                "evidence_kinds": ["research"],
                "field_types": {"findings": "array", "sources": "array", "open_risks": "array"},
            },
            "implementation_plan_v1": {
                "required_fields": ["steps", "coverage", "risks"],
                "evidence_kinds": ["plan"],
                "field_types": {"steps": "array", "coverage": "object", "risks": "array"},
            },
            "implementation_result_v1": {
                "required_fields": ["artifact_uri", "artifact_sha256", "changes"],
                "evidence_kinds": ["implementation", "focused_validation"],
                "field_types": {"artifact_uri": "string", "artifact_sha256": "string", "changes": "array"},
            },
            "validation_report_v1": {
                "required_fields": ["candidate_sha256", "checks", "scope", "verdict"],
                "evidence_kinds": ["validation"],
                "field_types": {"candidate_sha256": "string", "checks": "array", "scope": "array", "verdict": "string"},
            },
            "remedy_plan_v1": {
                "required_fields": ["earliest_cause", "prior_gate_escape", "research_frontier", "remedy_steps"],
                "evidence_kinds": ["failure_evidence", "ledger_review", "remedy_plan"],
                "field_types": {
                    "earliest_cause": "string",
                    "prior_gate_escape": "string",
                    "research_frontier": "array",
                    "remedy_steps": "array",
                },
            },
        },
        "entry": entry,
        "terminal_nodes": ["complete", "blocked"],
        "policies": {
            "max_steps": max(20, max_recovery_cycles * 6 + 10),
            "default_lease_seconds": brief.get("default_lease_seconds", 1800),
            "max_claim_attempts": brief.get("max_claim_attempts", max_recovery_cycles + 3),
            "event_context_limit": brief.get("event_context_limit", 50),
            "worker_protocol_required": True,
        },
        "nodes": nodes,
    }
    return compile_workflow(spec)


def generate_file(brief_path: str | Path, output_path: str | Path) -> CompiledWorkflow:
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    if not isinstance(brief, dict):
        raise BriefError("workflow brief must be an object")
    workflow = generate_coding_workflow(brief)
    Path(output_path).write_text(
        json.dumps(workflow.spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return workflow
