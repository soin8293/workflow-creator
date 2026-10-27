---
name: workflow-creator
description: Create or improve runnable project workflows using an existing graph engine, with executable steps, conditional routes, saved progress and meaningful checks. Use when starting a project, organizing recurring work or repairing a workflow. Ordinary task execution should use its existing workflow rather than redesign it.
---

# Workflow Creator

Create workflows an agent or person can actually run. Deliver an executable graph and a working entry command, with concise instructions alongside it. Markdown alone is insufficient for a request to build a workflow. Honor explicit analysis-only or outline-only requests; otherwise complete the runnable deliverable and test it locally within the authorized scope.

When testing workflow creation, treat the supplied information as input and the generated workflow as the deliverable. Review its source fidelity and exercise local paths with fixtures; do not turn that test into operating the user's real task, requesting account access or waiting for recording unless the user wants that operational work. Establish who the workflow supports: a person guided by an agent, an agent doing the work, or a combination.

## Understand the work and reuse what exists

Read the project's entry instructions, current goal and relevant existing procedures. Identify the recurring work, its inputs, expected deliverables, constraints and who or what receives the result. Infer routine details from project evidence; ask only about missing decisions that materially change the workflow.

For a large source folder, inventory first and prioritize task instructions, current checklists, output requirements and dated updates. Reuse existing readable copies/extraction tools, inspect older or supporting material when it resolves a relevant gap, and leave unrelated records alone. Reconcile specific conflicts and note missing coverage without demanding that the user restate information already in the sources.

Carry consequential source requirements into the responsible action and completion check, with a source pointer. Keep this mapping compact and local to the workflow; reuse existing source notes. Explicitly identify requirements that remain unchecked because the relevant source, capability or human judgment is unavailable. Do not silently convert missing coverage into a pass.

Check existing tools, skills, operators, templates and records before proposing additions. Preserve the user's chosen tools. Reference supported interfaces instead of inventing commands or reproducing manuals. Build a helper only for a concrete gap that existing tools cannot cover.

Before making a required check unavailable, inspect its documented launcher and supported configured/local tool locations. Absence from one guessed path does not establish absence of the tool. Where a launcher normally downloads packages, prefer an existing installed or cached runtime, and record what was checked without installing anything outside the task's scope.

For a new project, create workflows for the work it needs now. Reuse its graph engine and runner. When no project engine exists, inspect the available Workflow Foundry installation using [the Foundry reference](references/foundry.md). Use its native compiler/runtime rather than implementing another state machine, event store or scheduler. Add only a thin project adapter for genuinely missing tool connections, checks or interactive choices.

## Build the runnable workflow

Define the graph's inputs/state, work nodes, allowed transitions, conditional checks, human/external waits, terminal outcomes and bounded repair routes. Decide explicitly who executes each node: deterministic code, the current agent, another real worker, or a person. A node named "record" or "validate" does not implement that action.

Connect real tool calls and file checks where available. For external status or human work without an integration, pause for an explicitly attributed report; distinguish it from machine-verified evidence. Never represent an external action as verified merely because a local option was selected. Restrict next actions to the current node and use the engine's revision checks. Keep progress in the engine, with artifacts referenced rather than a second manually synchronized status store.

Provide commands to start, inspect and resume the workflow. For interactive workflows, show the current step, its instructions and allowed choices. For agent-driven workflows, use the engine's native worker/claim/submission protocol. Avoid hidden background agents or claims of unattended execution without a verified driver. External actions remain subject to the user's actual authorization.

Save it in the project's normal location, or choose a clear project-owned location if none exists. Make these things clear in the graph and its supporting instructions:

- **When to use it:** the task or trigger and where to start.
- **Inputs and authority:** where current task requirements, sources and state come from; bind variable paths and names to the current task rather than a single example.
- **Actions:** concrete steps using available tools, with the expected output or condition that permits moving on.
- **Decisions:** consequential branches, applicable exceptions and what to do when a required input or tool is missing. Distinguish required, conditional and optional work.
- **Done:** checks against the actual requested result and how to deliver it. Tool success alone may not establish task completeness or factual correctness.

Include handoff/resume information when the work spans agents or sessions: completed work, current artifact references and the next safe action. Reuse the existing task record; avoid competing status stores. Changes to inputs or outputs invalidate the affected checks.

Leave room for equivalent methods that preserve requirements. Avoid vague steps such as “ensure quality,” unnecessary approvals, and mandatory steps that serve no task outcome. Keep specialized detail in existing domain guidance or a focused reference when needed.

## Improve an existing workflow from evidence

Read a small relevant slice of corrections, failures or task history when available. Compare what was promised with what still needed intervention. Locate the step where the gap should have been caught and propose the smallest useful change.

Inspect whether that rule already exists. If it does, determine whether the problem is discovery, an unclear instruction, skipped execution, an inadequate check or a missing capability. Do not add duplicate wording as the default repair or infer an unsupported cause.

For example, repeated “where are the files?” after completion supports a handoff fix: check the task's expected deliverables, open the final files to confirm identity, and provide direct labeled links. It does not establish that the files' contents were wrong. Keep lessons scoped to the demonstrated problem.

## Make it usable by the next agent

Connect the workflow to the project's existing entrypoint or task instructions when within the authorized scope. A file that nobody encounters is an incomplete handoff. Respect ownership boundaries; if another owner must update the route, identify the exact change needed.

Read the result as an agent without this conversation: can it locate the inputs, choose the applicable steps, use the tools and recognize completion or a genuine blocker? Remove assumptions that depend on the author's memory.

Compile the actual graph and run bounded local tests of its normal path, a failed gate/repair path and saved-state resume. Check that invalid choices and stale revisions cannot advance it. Use synthetic fixtures for external work; never pass a real run with simulated evidence. Test actual tool adapters where feasible and label mocks. Verify a runnable command, not just diagram or document structure. Broader agent-quality comparisons and optimization remain optional separate work.

Exercise at least one plausible wrong result that could survive a superficial check, chosen from this task's requirements. Inspect the actual payload where feasible: an archive listing does not prove its files can be read, and a valid document does not prove it answers the brief. Bind the verdict to the checked artifacts. Correct the responsible gate and rerun the failed case plus a valid case; do not turn one domain's check into a universal implementation requirement.

When evaluating creator reliability, distinguish author self-tests from a fresh executor using the saved workflow without this conversation. Judge source coverage, discoverability, execution, result correctness, recovery and owner intervention separately; note creation time and avoidable custom code. Use the existing test/report location rather than building another evaluation framework. A passing graph test alone cannot establish consistent workflow creation.

Deliver the exact start/resume command, graph location, observed test outcomes and material gaps. Distinguish local graph execution from completed external work. Do not claim reliable adoption or correctness beyond the checks actually performed.
