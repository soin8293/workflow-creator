# Tests and results

The trials below were recorded on October 24, 2026. Private project files and full run records stay in their source projects. This page lists what the tests showed and where they stopped.

## Checks of this package

On Windows with Python 3.12, all 43 Foundry tests and all four installer tests passed. The installer tests checked these cases:

1. Install on a clean path with no separate runtime available.
2. Update the skill and keep the old copy in a backup.
3. Reject a changed file before installing it.
4. Keep the current skill if the new runtime fails its check.

We also installed from the ZIP in a separate folder and checked that its skill files matched the source and the installed copy. The installer checks graph rules, step changes, saved state, old action rejection, and replay.

The first Foundry test run failed because the package lacked one example file. We added the unchanged file and ran all 43 tests again. They passed. The code that runs Foundry did not change.

These checks ran on one Windows host. We have not run them on a separate Mac or Linux host. See [RELEASE_CHECKS.json](RELEASE_CHECKS.json) for the saved package check counts.

## Tests with fresh agents

A fresh agent starts without the earlier chat. These trials used one agent to build a workflow and another to follow it. We checked the files and results after the agents finished.

| Trial | What happened | What remains unproved |
|---|---|---|
| Review packet | The agents built a packet of source files for review. We checked file hashes, required source coverage, and rejection of a packet with a source left out. | This was one task. |
| First mobile-app check | The workflow missed a tool that was already installed. We fixed tool lookup. A new agent then ran the workflow. | This run needed help from the test lead. |
| Second mobile-app check | A new builder and follower ran the checks without help from the test lead. | They did not test a real device or app release. |
| Alerting project | The agents chose and ran 92 existing tests. All passed. The report still flagged a gap in rate-limit testing. | The run did not prove full safety or real email delivery. |
| Short prompt | A fresh builder got the skill name, project path, and test folder rules. It found the next task and built a working graph. Its six tests passed when we ran them again. | The project still needed owner choices. |
| Following that workflow | Another fresh agent made a useful draft plan and sample report. It saved progress and waited for those choices without help. | It did not reach an approved plan or the workflow's final step. |

## What these results mean

The tests support using the skill to build and follow local workflows. They do not prove that every new workflow will work or that its final work will be useful. Read the files it makes and check them against your task.

A graph can have valid steps while the answer is wrong. A reviewer name in a file does not prove that a second person reviewed it. A sample report with made-up data does not prove a real-world result.

The core `SKILL.md` is the same one used in the trials. Later package edits added runtime lookup notes, an installer, and a command script. We have tested those parts as listed above. We have not run a new fresh-agent trial of those package edits.

## Run the tests

From the repo folder, run the four installer tests:

```text
python -B -m unittest discover -s tests -v
```

Then open `skills/workflow-creator/runtime` in the terminal and run the 43 Foundry tests:

```text
python -B -m unittest discover -s tests -v
```

Both sets use test data in temporary folders. They need no network or account keys.

The installer rejects files that differ from `MANIFEST.json`. After a planned source edit, the person making the release must update that file before running install tests. It lists each shipped file's SHA-256 hash, except its own. A hash is a file fingerprint; it helps check whether the bytes changed.
