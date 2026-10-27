# Where the runtime came from

Workflow Creator includes Workflow Foundry 0.2.0, the code that runs and saves its workflow steps. Both use the [MIT license](LICENSE). A copy of the license also comes with the installed skill and runtime.

## Source records

Foundry was built locally before this package. Its existing package settings name version 0.2.0, Python 3.11 or newer, and the MIT license. Dated local records describe how it was built and tested, including a package build and an offline install.

We copied these files without changing their contents:

- Six Python code files that make up the runtime.
- Five test files.
- Three general example files used by those tests.

The file [runtime-source.json](runtime-source.json) lists a SHA-256 hash for each of these 14 files. A hash is a file fingerprint. We compared them with the local source copy when we built the release.

The short runtime guide, installer, command script, and release docs were added for this package. The original Foundry folder was left unchanged. This package ships a copy of version 0.2.0; it does not claim to be a new Foundry version.

## What comes with the download

The runtime source comes in this repo so you can install it offline. You do not need a separate package site, runtime URL, or pip download. The source records do not name a public upstream repo, so we do not claim one exists.

Private project records, old chat logs, saved runs, keys, and computer paths are left out. The three included examples use general test tasks.

## License checks

The owner asked for this package to be prepared for public use. MIT was chosen for the release. We kept its full notice in [LICENSE](LICENSE), using the [Open Source Initiative's MIT text](https://opensource.org/license/mit).

We found no other copyright notice in the copied code, tests, or examples that called for a different license. Python's own license still applies to Python. This check covered the files and records listed here; it was not a full legal review of their history.

Before a future runtime update, compare the new source, review its license records, and run the tests again. Keep the source-file hashes with the release.
