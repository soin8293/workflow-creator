# Workflow Creator

Give your agent a project folder full of docs. Workflow Creator helps it turn those docs into a workflow you can run.

The agent reads the goal, finds the rules, and builds the steps. It adds checks, saves progress, and shows what to do next. You can ask it to create a workflow with one prompt:

> Use workflow-creator.

## 1. Install it

You need Python 3.11 or newer and an agent that can read files and run local commands. We tested it with Codex.

Download this repo or clone it. Open a terminal in its folder. Run:

```text
python install.py
python install.py --check
```

On some computers, the Python command is `python3` or `py -3`. Use that name in place of `python`.

The first command installs the skill and the code that runs its workflows. The second checks the installed copy. It tests saved progress, step changes, and checks that block old actions. Both commands work offline. They use the tools built into Python.

The default install folder is `~/.codex/skills/workflow-creator`. If you set `CODEX_HOME`, the installer uses its `skills` folder instead. Open a new agent session after you install it.

## 2. Open your project

Keep your docs in the project folder. They can include a brief, plans, task rules, notes, and past results. Use the same folders you already use.

Open the project in your agent and say:

> Use workflow-creator.

If the agent has more than one project to choose from, add the project name or path. You do not need to list each step or tell it how to build the workflow.

The agent should read the docs before it asks you to explain them. It should ask when a missing choice would change the work. For example, the docs may name several goals but leave you to choose one.

## 3. Review what it builds

You should get these files in your project:

- A graph: a file that lists the steps and the paths between them. Each check decides which path can come next.
- A way to run those steps with your existing tools. The agent adds a small helper only where one is needed.
- Start and resume commands, with a clear file to open first.
- Tests of the normal path, failed checks, repairs, and saved progress.
- Notes on gaps that the agent could not check.

The workflow should say who does each step: the agent, you, or a tool. It should also say what result lets that step pass. A file's name or the words “tests passed” may not be enough to show the task is done.

Creating the workflow is its own task. Tell the agent when you want it to begin the main work.

## 4. Run it and pick up where you left off

Open the start file that the agent made. Follow its start command. The workflow saves the current step and shows the next allowed action.

For later work, use its status or resume command. Keep the saved run so the next agent can see where to start. The exact commands depend on the project; the agent must leave working ones with the workflow.

If a step needs your choice or work outside the agent's tools, the workflow should pause. It should save the draft and name what is missing. A paused draft is still unfinished work. The agent must not fill the gap with made-up approval.

## What runs the steps

Workflow Creator first looks for a tool your project already uses to run workflows. If none fits, it uses the included Workflow Foundry 0.2.0 code. This code is called the runtime. It tracks steps, saves progress, and checks which actions can advance the run.

You do not need a separate runtime download, pip install, service, or account. The agent still has to do the work in each step, or wait for you. Starting a saved run does not start an AI model.

See [setup and tools](DEPENDENCIES.md) for custom install paths and commands for the runtime.

## Update or remove it

Run `python install.py` from a newer trusted copy to update. Before it replaces the old skill, the installer checks the new one and saves the old folder under `skill-backups/`. That folder sits next to your `skills` folder. The installer restores the old copy if the final folder change fails.

To undo an update, move the new skill out of `skills`. Move the saved backup back into `skills` and name it `workflow-creator`. To uninstall, remove the installed `workflow-creator` folder. Your project files and saved runs stay in their projects.

## Tests and license

Fresh agents have built and followed workflows in several local trials. One early workflow missed an installed tool; that failure led to a fix. A later planning workflow produced useful drafts and paused for choices that only the owner could make. That trial did not reach final approval. Read [test results and limits](TESTING.md) for the details.

This package uses the [MIT license](LICENSE). Read [where the runtime came from](RUNTIME_PROVENANCE.md) for its source records. The current package is `0.1.0-rc.2`.

The installer compares files with the hashes in `MANIFEST.json`. A hash is a file fingerprint. This check can catch changed or damaged files. It cannot prove who made the download, so install a copy from a source you trust.
