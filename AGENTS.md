# Work on Workflow Creator

Read README.md and CONTRIBUTING.md. Reuse the included runtime and release tools.

Use fake data in tests and examples. Keep private project records, run databases, messages, keys, and machine paths out of the repo. Review new files before adding them to release.json.

After an edit, review the diff, run `python scripts/release.py manifest`, then `python scripts/check.py`. Do not change hashes merely to hide a failed check. Run a real affected path as well as the tests.

Preserve core skill behavior and pinned runtime source unless the task calls for a change. Keep test claims, fresh-agent trials, and live task results separate. Use one repo-level AI-assistance notice; do not add tool signatures to files or commits.

Public actions still need the owner's authority. Passing tests does not authorize publishing someone else's project output.
