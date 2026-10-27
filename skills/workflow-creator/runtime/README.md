# Workflow Foundry 0.2.0

Foundry is the runtime included with Workflow Creator. It is the code that tracks workflow steps and saves progress. It needs Python 3.11 or newer and uses Python's built-in tools.

This folder has six unchanged Python code files, their tests, and three general test examples. See [LICENSE](LICENSE) for the MIT terms. The repo's `RUNTIME_PROVENANCE.md` explains where the copy came from.

## Run a command

Use the command script inside the installed skill. Replace `/path/to/workflow-creator` with its real folder:

```text
python /path/to/workflow-creator/scripts/foundry.py --help
python /path/to/workflow-creator/scripts/foundry.py --self-test
python /path/to/workflow-creator/scripts/foundry.py compile /path/to/workflow.json
```

The first command shows the available commands. The second tests the runtime. The third checks a graph file. The script passes normal arguments to Foundry's own command tool.

## Connect project tools

A graph lists steps, checks, and routes. A route says which step can come next. Foundry uses the format named `workflow_foundry_v0`. Each graph names its goal, version, first step, routes, end steps, and run limits.

An agent may need a small Python helper to connect a project tool or check. That helper can add this runtime folder to `sys.path`, Python's list of places to look for code. It can then use `workflow_foundry.compiler.compile_file` and `workflow_foundry.runtime.SQLiteRuntime`.

Keep the runtime path as a setting. Reuse the installed copy across projects. Save each project's run data in that project.

## Save and advance a run

Use Foundry's own methods to start a run, read its current step, finish a step, or resume a wait. The methods include `start_run`, `get_run`, `inspect`, `complete_node`, `resume_wait`, and `replay`.

Each step change uses a revision number. It is a version number for the saved run state. An old revision cannot advance the run. This helps block an agent from acting on a step that has already changed.

Starting a run saves state. The agent still needs to read the next step, do the work or wait, then report the allowed result. Foundry does not start an AI model.

## Reports, workers, and limits

A human wait saves a report with the name of who gave it. That name alone does not prove that the reported outside action happened.

When a graph uses separate agent workers, they must follow Foundry's register, frontier, claim, journal, and submit steps. A claim records which worker may act on the current step. Use the command help to inspect this process before building against it.

These checks control changes made through Foundry. They cannot stop someone from using other tools on the host. A graph check also cannot prove that a final answer is true or useful. Add checks of the task's real output.

Foundry stores run data in SQLite, a local database file. Change that data through its own methods. Follow the host's database rules when using other tools to read it.
