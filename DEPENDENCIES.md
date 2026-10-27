# Setup and tools

## What you need

Use Python 3.11 or newer. You also need an agent that can load a skill, read project files, run commands, and save its work. We tested this package with Codex.

Workflow Foundry 0.2.0 comes with the skill. It is the runtime: the code that tracks steps and saves progress. It uses Python's built-in tools. You do not need to install pip packages or run a server.

Your task may need other tools. For example, a coding workflow may need the project's own test tools. The agent should check the docs and installed tools before it says one is missing.

## Choose an install folder

From the repo folder, run:

```text
python install.py
python install.py --check
```

The installer uses `~/.codex/skills` by default. If you set `CODEX_HOME`, it uses `$CODEX_HOME/skills`.

To use another folder, pass the same path to both commands:

```text
python install.py --skills-dir /path/to/skills
python install.py --skills-dir /path/to/skills --check
```

Replace `/path/to/skills` with the folder your agent reads. The installer creates a `workflow-creator` folder inside it.

The check command tests the installed runtime. It does not prove that a workflow for your project gives the right result. That workflow needs its own tests.

## Find and check the runtime

The installed skill keeps the runtime in its `runtime/` folder. The Python package inside it is named `workflow_foundry`.

From the downloaded repo, run these commands to see its help and test it:

```text
python skills/workflow-creator/scripts/foundry.py --help
python skills/workflow-creator/scripts/foundry.py --self-test
```

After you install, you can run the same script from the installed skill folder. This script passes commands to Foundry. The self-test checks saved state, step changes, old action rejection, and replay. Replay means rebuilding the current state from its saved events to check that they agree.

## Use another runtime when the project needs it

The agent should reuse a suitable engine that the project already has. An engine is the code that controls the workflow's steps. If the project needs a separate trusted Foundry copy, give its path in project settings or `WORKFLOW_FOUNDRY_HOME`.

Keep that path as a setting. Do not hard-code one person's computer path or copy a new engine into each project. Python helpers can load Foundry from the chosen runtime folder; they do not need a pip install for this setup.

If files are missing or damaged, restore the package from a trusted copy and run the installer again. It does not fetch a replacement from a package site.

## Read saved data

Foundry saves workflow state in SQLite, a local database file. The agent should use Foundry's own methods to change that state.

Some hosts use AODB, a tool for reading databases. If yours does, follow its setup and database notes. You do not need AODB to run Foundry's own state methods. The skill does not install it.
