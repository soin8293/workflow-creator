# A small workflow you can run

This example shows the files and behavior a project workflow needs. It uses fake counts: two accepted items and one rejected item. The output must copy those counts and give a total of three.

The graph is in [workflow.json](workflow.json). The small [demo.py](demo.py) script connects file actions and checks to the included Foundry runtime. This is a hand-written example, not a new test of an AI agent.

From the repo folder, run:

```text
python examples/demo.py run ../workflow-demo --bad-output
python examples/demo.py status ../workflow-demo
```

The first command writes valid JSON with a wrong total of four. The check rejects it. The saved run waits at `repair`. The status command opens that same run in a new process; it does not restart the work.

Fix and resume it with:

```text
python examples/demo.py repair ../workflow-demo
python examples/demo.py status ../workflow-demo
```

The script writes the correct total and reports the repair as `demo-script`. The run ends with `report_checked`. The status output should show no validation errors and `replay_matches: true`.

Read `../workflow-demo/output.json` to check the actual result. The case folder also holds its input and saved progress. Keep it out of the source repo. Use a new folder name for another run; the example will not overwrite an old case.

To try the normal path, run `python examples/demo.py run ../workflow-demo-good`. It should finish with the correct output on its first try. A check also rejects an input file changed after the run began.
