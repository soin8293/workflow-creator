from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .compiler import compile_file
from .generator import generate_file, write_starter_brief
from .protocol import ExternalAgentProtocol, write_context_bundle
from .runtime import SQLiteRuntime


def _object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON value must be an object")
    return parsed


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _array(value: str | None) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise argparse.ArgumentTypeError("JSON value must be an array")
    return parsed


def _file_object(path: str) -> dict[str, Any]:
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON file must contain an object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflow-foundry")
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("spec")
    generate = sub.add_parser("generate", help="compile a task brief into an adaptive workflow object")
    generate.add_argument("--brief", required=True)
    generate.add_argument("--output", required=True)
    initialize = sub.add_parser("init-brief", help="create a reusable coding-task brief")
    initialize.add_argument("--output", required=True)
    initialize.add_argument("--workflow-id", required=True)
    initialize.add_argument("--objective", required=True)
    initialize.add_argument("--requirement", action="append", required=True)
    start = sub.add_parser("start")
    start.add_argument("--db", required=True)
    start.add_argument("--spec", required=True)
    start.add_argument("--run-id", required=True)
    start.add_argument("--input-json")
    for name in ("inspect", "replay"):
        command = sub.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--run-id", required=True)
    complete = sub.add_parser("complete")
    complete.add_argument("--db", required=True)
    complete.add_argument("--run-id", required=True)
    complete.add_argument("--outcome", required=True)
    complete.add_argument("--expected-revision", required=True, type=int)
    complete.add_argument("--result-json")
    resume = sub.add_parser("resume")
    resume.add_argument("--db", required=True)
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--event-type", required=True)
    resume.add_argument("--correlation-key", required=True)
    resume.add_argument("--outcome", required=True)
    resume.add_argument("--expected-revision", required=True, type=int)
    resume.add_argument("--payload-json")
    effect = sub.add_parser("request-effect")
    effect.add_argument("--db", required=True)
    effect.add_argument("--run-id", required=True)
    effect.add_argument("--expected-revision", required=True, type=int)
    effect.add_argument("--payload-json")
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--db", required=True)
    receipt.add_argument("--run-id", required=True)
    receipt.add_argument("--action-key", required=True)
    receipt.add_argument("--outcome", required=True)
    receipt.add_argument("--receipt-json", required=True)
    receipt.add_argument("--expected-revision", required=True, type=int)

    register = sub.add_parser("agent-register", help="register an external coding-agent session")
    register.add_argument("--db", required=True)
    register.add_argument("--session-id", required=True)
    register.add_argument("--provider", required=True)
    register.add_argument("--model", required=True)
    register.add_argument("--actor", required=True)
    register.add_argument("--capabilities-json", default="[]")
    register.add_argument("--metadata-json")
    for name in ("agent-heartbeat", "agent-end"):
        command = sub.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--session-id", required=True)
    frontier = sub.add_parser("frontier", help="inspect the exact executable obligation")
    frontier.add_argument("--db", required=True)
    frontier.add_argument("--run-id", required=True)
    claim = sub.add_parser("claim", help="claim the current obligation under a fenced lease")
    claim.add_argument("--db", required=True)
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--session-id", required=True)
    claim.add_argument("--expected-revision", required=True, type=int)
    claim.add_argument("--lease-seconds", type=int)
    claim.add_argument("--bundle-dir")
    renew = sub.add_parser("renew")
    renew.add_argument("--db", required=True)
    renew.add_argument("--claim-id", required=True)
    renew.add_argument("--fence-token", required=True)
    renew.add_argument("--expected-revision", required=True, type=int)
    renew.add_argument("--lease-seconds", type=int)
    journal = sub.add_parser("journal-action")
    journal.add_argument("--db", required=True)
    journal.add_argument("--claim-id", required=True)
    journal.add_argument("--fence-token", required=True)
    journal.add_argument("--action-type", required=True)
    journal.add_argument("--resource", required=True)
    journal.add_argument("--mutation", action="store_true")
    journal.add_argument("--receipt-json")
    submit = sub.add_parser("agent-submit")
    submit.add_argument("--db", required=True)
    submit.add_argument("--submission-file", required=True)
    failure = sub.add_parser("agent-fail")
    failure.add_argument("--db", required=True)
    failure.add_argument("--claim-id", required=True)
    failure.add_argument("--fence-token", required=True)
    failure.add_argument("--expected-revision", required=True, type=int)
    failure.add_argument("--code", required=True)
    failure.add_argument("--message", required=True)
    failure.add_argument("--retryable", action="store_true")
    failure.add_argument("--evidence-json", default="[]")
    release = sub.add_parser("release")
    release.add_argument("--db", required=True)
    release.add_argument("--claim-id", required=True)
    release.add_argument("--fence-token", required=True)
    release.add_argument("--expected-revision", required=True, type=int)
    release.add_argument("--checkpoint-json", required=True)
    release.add_argument("--handoff-to")
    inspect_agent = sub.add_parser("agent-inspect")
    inspect_agent.add_argument("--db", required=True)
    inspect_agent.add_argument("--run-id", required=True)
    propose = sub.add_parser("lesson-propose")
    propose.add_argument("--db", required=True)
    propose.add_argument("--lesson-file", required=True)
    for name in ("lesson-activate", "lesson-retire"):
        command = sub.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--lesson-id", required=True)
        command.add_argument("--version", required=True, type=int)
        command.add_argument("--actor", required=True)
        command.add_argument("--evidence-json", required=True)
    lessons = sub.add_parser("lessons")
    lessons.add_argument("--db", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "compile":
        workflow = compile_file(args.spec)
        _print({"digest": workflow.digest, "workflow_id": workflow.spec["workflow_id"], "valid": True})
        return
    if args.command == "generate":
        workflow = generate_file(args.brief, args.output)
        _print({
            "digest": workflow.digest,
            "workflow_id": workflow.spec["workflow_id"],
            "output": str(Path(args.output).resolve()),
            "valid": True,
        })
        return
    if args.command == "init-brief":
        brief = write_starter_brief(
            args.output, args.workflow_id, args.objective, args.requirement
        )
        _print({"brief": brief, "output": str(Path(args.output).resolve())})
        return
    runtime = SQLiteRuntime(args.db)
    protocol = ExternalAgentProtocol(runtime)
    if args.command == "start":
        _print(runtime.start_run(compile_file(args.spec), args.run_id, _object(args.input_json)))
    elif args.command == "inspect":
        _print(runtime.inspect(args.run_id))
    elif args.command == "replay":
        _print(runtime.replay(args.run_id))
    elif args.command == "complete":
        _print(runtime.complete_node(args.run_id, args.outcome, args.expected_revision, _object(args.result_json)))
    elif args.command == "resume":
        _print(runtime.resume_wait(
            args.run_id, args.event_type, args.correlation_key, args.outcome,
            args.expected_revision, _object(args.payload_json),
        ))
    elif args.command == "request-effect":
        _print(runtime.request_effect(args.run_id, args.expected_revision, _object(args.payload_json)))
    elif args.command == "receipt":
        _print(runtime.record_effect_receipt(
            args.run_id, args.action_key, args.outcome, _object(args.receipt_json), args.expected_revision,
        ))
    elif args.command == "agent-register":
        _print(protocol.register_session(
            args.session_id, args.provider, args.model, args.actor,
            _array(args.capabilities_json), _object(args.metadata_json),
        ))
    elif args.command == "agent-heartbeat":
        _print(protocol.heartbeat_session(args.session_id))
    elif args.command == "agent-end":
        _print(protocol.end_session(args.session_id))
    elif args.command == "frontier":
        _print(protocol.frontier(args.run_id))
    elif args.command == "claim":
        claimed = protocol.claim(
            args.run_id, args.session_id, args.expected_revision, lease_seconds=args.lease_seconds
        )
        if args.bundle_dir:
            claimed["bundle"] = write_context_bundle(claimed["context_pack"], args.bundle_dir)
        _print(claimed)
    elif args.command == "renew":
        _print(protocol.renew(
            args.claim_id, args.fence_token, args.expected_revision, lease_seconds=args.lease_seconds
        ))
    elif args.command == "journal-action":
        _print(protocol.record_action(
            args.claim_id, args.fence_token, args.action_type, args.resource,
            mutation=args.mutation, receipt=_object(args.receipt_json),
        ))
    elif args.command == "agent-submit":
        submission = _file_object(args.submission_file)
        _print(protocol.submit(
            submission["claim_id"], submission["fence_token"], submission["expected_revision"],
            submission["outcome"], submission.get("result", {}), submission.get("evidence", []),
            summary=submission.get("summary", ""),
        ))
    elif args.command == "agent-fail":
        _print(protocol.fail(
            args.claim_id, args.fence_token, args.expected_revision, args.code, args.message,
            retryable=args.retryable, evidence=_array(args.evidence_json),
        ))
    elif args.command == "release":
        _print(protocol.release(
            args.claim_id, args.fence_token, args.expected_revision,
            _object(args.checkpoint_json), handoff_to=args.handoff_to,
        ))
    elif args.command == "agent-inspect":
        _print(protocol.inspect(args.run_id))
    elif args.command == "lesson-propose":
        lesson = _file_object(args.lesson_file)
        _print(protocol.propose_lesson(
            lesson["lesson_id"], lesson.get("scope", "global"), lesson.get("trigger_tags", []),
            lesson["prevention"], lesson.get("source_refs", []),
            lesson.get("proposal_evidence", {}), lesson["proposed_by"],
        ))
    elif args.command == "lesson-activate":
        _print(protocol.activate_lesson(
            args.lesson_id, args.version, args.actor, _object(args.evidence_json)
        ))
    elif args.command == "lesson-retire":
        _print(protocol.retire_lesson(
            args.lesson_id, args.version, args.actor, _object(args.evidence_json)
        ))
    elif args.command == "lessons":
        _print(protocol.list_lessons())


if __name__ == "__main__":
    main()
