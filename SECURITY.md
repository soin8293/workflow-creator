# Security and private data

For a vulnerability or accidental exposure, use [Report a vulnerability](https://github.com/soin8293/workflow-creator/security/advisories/new). Private vulnerability reporting is enabled for this repo. If you cannot use that page, open an issue asking for a private contact route without sharing the details.

For a normal bug, use [issues](https://github.com/soin8293/workflow-creator/issues) with fake data. Never attach real project files, prompts, private messages, keys, database files, or full local logs. Remove private paths from a small reproduction before you share it.

This is an early-release project. Fixes target the current release; there is no long-term support promise or guaranteed response time. Check the [changelog](CHANGELOG.md) for changes.

The installer and included runtime work offline. The installer checks file hashes, saves an old installation before replacement, and checks the installed skill and runtime. File hashes detect changes relative to a trusted manifest; they are not a signature that proves who made the download.

A workflow controls actions through its own runner. It cannot block every other tool on your computer or prove that a person told the truth. Review the task's output and authorize outside actions through your own rules. Local tests do not certify the security of the whole host.
