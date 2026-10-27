from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,127}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
REQUIRED_OUTCOMES = {
    "activity": {"success", "error"},
    "agent": {"success", "error"},
    "decision": {"true", "false", "unknown", "error"},
    "validation": {"pass", "fail", "error"},
    "human_wait": {"approved", "rejected", "error"},
    "external_wait": {"success", "expired", "error"},
    "effect": {"success", "conflict", "error"},
    "terminal": set(),
}
WORKER_KINDS = {"activity", "agent", "decision", "validation"}


class CompileError(ValueError):
    def __init__(self, diagnostics: list[str]):
        self.diagnostics = diagnostics
        super().__init__("workflow compilation failed:\n- " + "\n- ".join(diagnostics))


@dataclass(frozen=True)
class CompiledWorkflow:
    spec: dict[str, Any]
    digest: str
    nodes: dict[str, dict[str, Any]]

    def canonical_json(self) -> str:
        return json.dumps(self.spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical(spec: dict[str, Any]) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, set()) - seen)
    return seen


def _can_reach(start: str, target: str, graph: dict[str, set[str]]) -> bool:
    stack = list(graph.get(start, set()))
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(graph.get(node, set()) - seen)
    return False


def compile_workflow(raw_spec: dict[str, Any]) -> CompiledWorkflow:
    spec = deepcopy(raw_spec)
    diagnostics: list[str] = []

    if spec.get("schema_version") != "workflow_foundry_v0":
        diagnostics.append("SCHEMA_VERSION: schema_version must be workflow_foundry_v0")
    workflow_id = spec.get("workflow_id")
    if not isinstance(workflow_id, str) or not ID_RE.fullmatch(workflow_id):
        diagnostics.append("WORKFLOW_ID: workflow_id must be a stable lowercase identifier")
    version = spec.get("definition_version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        diagnostics.append("DEFINITION_VERSION: definition_version must be semantic-version shaped")
    if not isinstance(spec.get("objective"), str) or not spec["objective"].strip():
        diagnostics.append("OBJECTIVE_REQUIRED: objective must state an observable outcome")

    raw_contracts = spec.get("contracts", {})
    if not isinstance(raw_contracts, dict):
        diagnostics.append("CONTRACTS_TYPE: contracts must be an object")
        raw_contracts = {}
    for contract_id, contract in raw_contracts.items():
        if not isinstance(contract_id, str) or not ID_RE.fullmatch(contract_id):
            diagnostics.append(f"CONTRACT_ID: invalid contract identifier {contract_id!r}")
            continue
        if not isinstance(contract, dict):
            diagnostics.append(f"CONTRACT_TYPE: {contract_id} must be an object")
            continue
        for field in ("required_fields", "evidence_kinds"):
            value = contract.get(field, [])
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item for item in value)
                or len(set(value)) != len(value)
            ):
                diagnostics.append(f"CONTRACT_{field.upper()}: {contract_id}.{field} must contain unique strings")
        field_types = contract.get("field_types", {})
        supported_types = {"string", "integer", "number", "boolean", "object", "array", "null"}
        if (
            not isinstance(field_types, dict)
            or any(not isinstance(key, str) or value not in supported_types for key, value in field_types.items())
        ):
            diagnostics.append(f"CONTRACT_FIELD_TYPES: {contract_id}.field_types contains an invalid type")
        elif set(contract.get("required_fields", [])) - set(field_types):
            diagnostics.append(
                f"CONTRACT_FIELD_TYPES: {contract_id} must type every required field "
                f"{sorted(set(contract.get('required_fields', [])) - set(field_types))}"
            )

    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        diagnostics.append("NODES_REQUIRED: nodes must be a non-empty array")
        raise CompileError(diagnostics)

    nodes: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            diagnostics.append(f"NODE_TYPE: nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not ID_RE.fullmatch(node_id):
            diagnostics.append(f"NODE_ID: nodes[{index}].id is invalid")
            continue
        if node_id in nodes:
            diagnostics.append(f"DUPLICATE_NODE: {node_id}")
            continue
        nodes[node_id] = node

    entry = spec.get("entry")
    if entry not in nodes:
        diagnostics.append(f"ENTRY_MISSING: entry {entry!r} does not name a node")

    terminals = spec.get("terminal_nodes")
    if not isinstance(terminals, list) or not terminals:
        diagnostics.append("TERMINALS_REQUIRED: terminal_nodes must be a non-empty array")
        terminals = []
    terminal_set = set(terminals)
    if len(terminal_set) != len(terminals):
        diagnostics.append("DUPLICATE_TERMINAL: terminal_nodes contains duplicates")

    graph: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    actual_terminals: set[str] = set()
    for node_id, node in nodes.items():
        kind = node.get("kind")
        if kind not in REQUIRED_OUTCOMES:
            diagnostics.append(f"NODE_KIND: {node_id} has unsupported kind {kind!r}")
            continue
        routes = node.get("routes", {})
        if not isinstance(routes, dict):
            diagnostics.append(f"ROUTES_TYPE: {node_id}.routes must be an object")
            routes = {}
        if kind == "terminal":
            actual_terminals.add(node_id)
            if routes:
                diagnostics.append(f"TERMINAL_ROUTES: terminal {node_id} may not have outgoing routes")
            if not isinstance(node.get("outcome"), str):
                diagnostics.append(f"TERMINAL_OUTCOME: terminal {node_id} needs an outcome")
        else:
            missing = REQUIRED_OUTCOMES[kind] - set(routes)
            if missing:
                diagnostics.append(f"OUTCOME_COVERAGE: {node_id} is missing routes {sorted(missing)}")
        if kind in {"human_wait", "external_wait"}:
            wait = node.get("wait")
            if not isinstance(wait, dict) or not wait.get("event_type") or not wait.get("correlation_key"):
                diagnostics.append(f"WAIT_CONTRACT: {node_id} needs event_type and correlation_key")
            elif (
                not isinstance(wait.get("required_evidence", []), list)
                or any(not isinstance(item, str) or not item for item in wait.get("required_evidence", []))
            ):
                diagnostics.append(f"WAIT_EVIDENCE: {node_id}.wait.required_evidence must contain strings")
        if kind == "effect":
            effect = node.get("effect")
            if not isinstance(effect, dict) or not effect.get("idempotency_key") or not effect.get("receipt_type"):
                diagnostics.append(f"EFFECT_CONTRACT: {node_id} needs idempotency_key and receipt_type")
        output_contract = node.get("output_contract")
        if output_contract is not None:
            if not isinstance(output_contract, str) or not output_contract:
                diagnostics.append(f"OUTPUT_CONTRACT: {node_id}.output_contract must be a contract ID")
            elif output_contract not in raw_contracts:
                diagnostics.append(f"UNKNOWN_OUTPUT_CONTRACT: {node_id} references {output_contract!r}")
        if kind == "agent":
            if not isinstance(output_contract, str) or not output_contract:
                diagnostics.append(f"AGENT_OUTPUT_CONTRACT: {node_id} needs an independently checkable output_contract")
        if kind in WORKER_KINDS:
            executor = node.get("executor", {})
            if not isinstance(executor, dict):
                diagnostics.append(f"EXECUTOR_TYPE: {node_id}.executor must be an object")
                executor = {}
            for field in (
                "required_capabilities",
                "allowed_actions",
                "forbidden_actions",
                "required_actions",
                "risk_tags",
            ):
                values = executor.get(field, [])
                if (
                    not isinstance(values, list)
                    or any(not isinstance(item, str) or not item for item in values)
                    or len(set(values)) != len(values)
                ):
                    diagnostics.append(f"EXECUTOR_{field.upper()}: {node_id}.{field} must contain unique strings")
            overlap = set(executor.get("allowed_actions", [])) & set(executor.get("forbidden_actions", []))
            if overlap:
                diagnostics.append(f"EXECUTOR_AUTHORITY_CONFLICT: {node_id} both allows and forbids {sorted(overlap)}")
            lease_seconds = executor.get("lease_seconds")
            if lease_seconds is not None and (
                not isinstance(lease_seconds, int)
                or isinstance(lease_seconds, bool)
                or not 5 <= lease_seconds <= 86400
            ):
                diagnostics.append(f"EXECUTOR_LEASE: {node_id}.lease_seconds must be between 5 and 86400")
            independent_from = executor.get("independent_from", [])
            if (
                not isinstance(independent_from, list)
                or any(not isinstance(item, str) or not item for item in independent_from)
                or len(set(independent_from)) != len(independent_from)
            ):
                diagnostics.append(f"EXECUTOR_INDEPENDENCE: {node_id}.independent_from must contain unique node IDs")
        for outcome, target in routes.items():
            if not isinstance(outcome, str) or not outcome:
                diagnostics.append(f"ROUTE_OUTCOME: {node_id} has an invalid outcome name")
            if target not in nodes:
                diagnostics.append(f"DANGLING_ROUTE: {node_id}.{outcome} targets {target!r}")
            else:
                graph[node_id].add(target)

    if terminal_set != actual_terminals:
        diagnostics.append(
            "TERMINAL_MISMATCH: terminal_nodes must equal nodes whose kind is terminal "
            f"(declared={sorted(terminal_set)}, actual={sorted(actual_terminals)})"
        )

    for node_id, node in nodes.items():
        executor = node.get("executor", {}) if isinstance(node.get("executor", {}), dict) else {}
        for producer in executor.get("independent_from", []):
            if producer not in nodes:
                diagnostics.append(f"INDEPENDENCE_TARGET: {node_id} references missing node {producer!r}")
            elif producer == node_id:
                diagnostics.append(f"INDEPENDENCE_SELF: {node_id} cannot be independent from itself")

    if entry in nodes:
        unreachable = set(nodes) - _reachable(entry, graph)
        if unreachable:
            diagnostics.append(f"UNREACHABLE_NODES: {sorted(unreachable)}")
        reverse: dict[str, set[str]] = {node_id: set() for node_id in nodes}
        for source, targets in graph.items():
            for target in targets:
                reverse[target].add(source)
        can_finish: set[str] = set()
        for terminal in terminal_set & set(nodes):
            can_finish |= _reachable(terminal, reverse)
        no_terminal_path = set(nodes) - can_finish
        if no_terminal_path:
            diagnostics.append(f"NO_TERMINAL_PATH: {sorted(no_terminal_path)}")

    for node_id, node in nodes.items():
        if node.get("kind") != "terminal" and _can_reach(node_id, node_id, graph):
            max_visits = node.get("max_visits")
            if not isinstance(max_visits, int) or isinstance(max_visits, bool) or max_visits < 1:
                diagnostics.append(f"UNBOUNDED_CYCLE: cyclic node {node_id} needs positive max_visits")

    policies = spec.get("policies")
    if not isinstance(policies, dict) or not isinstance(policies.get("max_steps"), int) or policies.get("max_steps", 0) < 1:
        diagnostics.append("MAX_STEPS: policies.max_steps must be a positive integer")
    elif policies:
        if "worker_protocol_required" in policies and not isinstance(policies["worker_protocol_required"], bool):
            diagnostics.append("POLICY_WORKER_PROTOCOL_REQUIRED: must be a boolean")
        for field, lower, upper in (
            ("default_lease_seconds", 5, 86400),
            ("max_claim_attempts", 1, 1000),
            ("event_context_limit", 1, 1000),
        ):
            value = policies.get(field)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper
            ):
                diagnostics.append(f"POLICY_{field.upper()}: must be between {lower} and {upper}")

    if diagnostics:
        raise CompileError(diagnostics)
    canonical = _canonical(spec)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return CompiledWorkflow(spec=spec, digest=digest, nodes=nodes)


def compile_file(path: str | Path) -> CompiledWorkflow:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise CompileError(["ROOT_TYPE: workflow document must be an object"])
    return compile_workflow(raw)
