# Contribute

Start with the [README](README.md). Use Python 3.11 or newer. There are no pip requirements for the runtime, installer, or tests.

For a bug, open an [issue](https://github.com/soin8293/workflow-creator/issues). Include your Python and OS versions, the command you ran, what happened, and what you expected. Use a small fake-data example. Keep real project files, prompts, logs, keys, and databases out of the report. See [SECURITY.md](SECURITY.md) for sensitive problems.

## Check an edit

The file list in `release.json` says what ships. If your edit adds or removes a file, review that list too. The release tool refuses files outside the list; it does not add them for you.

After you review your changes, run:

```text
python scripts/release.py manifest
python scripts/check.py
```

The first command updates file hashes. The second checks the files, links, hashes, and all test suites. It fails if a test suite has no tests. It does not change the manifest.

Add a test for a bug you fix. Check the output or saved state, not whether the docs contain your chosen words. Preserve a valid case alongside the case that should fail.

## Prepare a package

Set the next version in `release.json`. Update the [changelog](CHANGELOG.md) and current-version text in the README. Keep the bundled runtime source unchanged unless the runtime update is part of your change. Review its license and source hashes before replacing it.

Run the checks, then build outside the source folder:

```text
python scripts/release.py build --output ../workflow-creator-package.zip
```

The builder checks the manifest first. It packs only the reviewed file list and verifies the ZIP bytes. Choose a new ZIP path; it will not overwrite an old file. Extract that ZIP elsewhere and run `python install.py --skills-dir /path/to/test-skills`, then the same command with `--check`. Use a temporary test folder instead of replacing your real skill while testing.

CI runs the checks on Windows and Ubuntu with Python 3.11 and 3.12. Review its result for your exact commit before merging. Code tests do not prove a fresh agent will make a useful workflow; label any separate agent trial and its limits.

Changes are accepted under the [MIT license](LICENSE). Publishing a branch, a release, or a user's task output are separate actions; a passing check does not grant approval for them.
