# Use Workflow Foundry

First check whether the project has a suitable engine to run its steps. If it does, reuse it. Otherwise use the Foundry 0.2.0 copy included with this skill. It needs Python 3.11 or newer and no pip packages.

## Find the runtime

From this `references/` folder, the runtime is at `../runtime/`. Its README, code, license, and tests are there. The command script is at `../scripts/foundry.py`.

Use the actual skill path in commands:

```text
python /path/to/skill/scripts/foundry.py --help
python /path/to/skill/scripts/foundry.py --self-test
```

An explicit project setting can choose another trusted Foundry copy. Other places to check are `WORKFLOW_FOUNDRY_HOME`, tool setup notes, or an installed `workflow_foundry` Python package. Read that copy's README and help. Check its version before using its methods.

On Windows, an open app may still have old settings. To read a saved user setting, run:

```powershell
[Environment]::GetEnvironmentVariable('WORKFLOW_FOUNDRY_HOME', 'User')
```

If the runtime is missing, report the gap. Do not invent a download URL or build a new engine to replace it.

## Build the graph and tool links

Use Foundry's `workflow_foundry_v0` graph format. Set its goal, version, first step, routes, end steps, limits, and any data rules the steps need. Check the file with `workflow_foundry.compiler.compile_file` or the `compile` command.

The built-in coding-task generator fits some coding tasks. Use a task-specific graph when its steps do not fit the project.

Use `SQLiteRuntime` to start runs, read current steps, advance steps, wait, save events, and replay them. Keep all run-state changes in that runtime. Do not edit its database with SQL or keep another file that tries to track the same current step.

Add a small helper only for tool calls, output checks, or choices the built-in commands cannot handle. Show actions that are valid at the current step. Keep the engine path as a setting. Python helpers can add the chosen runtime folder to `sys.path` before importing it. Reuse the installed runtime instead of copying one into each project.

Put step instructions and source links beside the graph. Leave working commands to start, inspect, and resume it.

## Choose who does the work

For work guided by a person, use `human_wait` steps to save reports with the name of who gave them. A local helper can run code steps and checks. Set the worker policy to match this setup. A person's report does not prove a live website or API state.

For separate agent workers, turn on the worker protocol. Use its register, frontier, claim, journal, and submit steps with real worker IDs. A claim records who may act on a step. Do not bypass a required claim by marking the step done directly. Different IDs alone do not prove that two separate agents reviewed the work.

The `start` command creates saved state. The workflow still needs a driver: the current agent, a person using commands, or another set-up tool. That driver must read the next allowed step, do it or wait, report its result, and repeat until the run ends or pauses. Use a short command loop or the agent's tools where they fit. Add a scheduler only when the task needs one.

## Check failures and saved progress

Use separate temporary databases for tests. Check the normal path, missing or wrong input, an action at the wrong step, an old revision, a repair, and reopening the saved run.

Tie each check to the files it read, using hashes or the project's file records. If those inputs or outputs change, the old check must no longer count. Keep fake outside responses in test databases. Never show them as results from a real run.

For general database reads, follow the host's SQLite rules. The runtime's own code should use its methods. Put a notes file beside the database that says which tool may write to it and what the saved state proves.

If the host uses AODB notes, check its format and use the fields `about` and `writes`. AODB ignores `writer` on its own, which can leave the wrong default write guidance. Keep writes routed through Foundry.

Deliver the graph, the working command, the test results, and the steps that still need a person. A graph can block a bad step change through its own tools. It cannot control all other host tools or prove that a reported result is true.
