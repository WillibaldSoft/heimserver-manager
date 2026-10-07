# Code and Release Verification

Testbed: 2026-09-25, Home Server Manager V0.12.

## Cleanup and Bug Fixes

- Neutral settings for users, LAN, SSH, scanner, app, and backup paths. Host values belong exclusively in local configuration. No personal users or device-specific scanner credentials as delivery standard.
- Public provider URLs and neutral documentation examples remain included. Historical mount names in the backup compatibility logic denote supported directory structures, not access data.
- Explicit release file list in `packaging/source-manifest.json`. Unlisted files are neither added to the Debian package nor the server installer archive. New source files must be consciously added to the list.
- Obsolete, versioned `.bak` source copies removed. Runtime data, Git history, local configuration, logs, databases, and snapshot folders do not belong in releases.
- Source archives with neutral owner and timestamp. Standard app installer downloads use portable profile paths instead of local host paths.
- Tvheadend initial setup with real line breaks and configurable config directory.
- Saving the TV wake-up sequence only via POST and CSRF check; invalid minute values return a understandable 400 response instead of a server error.
- Recording lists are fully loaded page by page; an incomplete list does not allow deletion.
- SSH presence checks use local SSH connections instead of a fixed host address.
- Obsolete tests on login and portable install paths adjusted; photo lab test states isolated from each other.

## Verification

- Entire existing suite including new regressions: 508 tests successful.
- Python syntax check and syntax check of the six shell scripts.
- Debian test package built and unpacked, not installed.
- Release files checked for private keys, known token formats, and credentials in URLs; no hits found.
- Standard app installation archives checked for paths and neutral owner data.
- Existing local paths explicitly backed up before migration; during rollout compared with unchanged configuration state.

`python3 tools/privacy_check.py` is a heuristic additional control, not a guarantee. With `--forbidden-file /geschuetzter/pfad`, a **non-versioned** list of own hostnames, users, or addresses can be checked. Hits only output filenames and rule types.

## Limits and Release

No full penetration test is performed, nor is there any guarantee that every hardware combination will work. Real re-installations, restore to empty storage media, power-off/power-on cycles, certificate issuance, package upgrades, and recording deletions were not triggered on the production server for testing. Such processes require additional tests on a disposable system.

The old Git history and packages already generated earlier are not retroactively anonymized by this cleanup. For distribution, use only newly built, validated release artifacts or a cleaned source state separately check the Git history before public release; it will not be automatically rewritten.

Intentionally personal operational exports (e.g., client backup packages with identity assignment or custom Nextcloud domain configurations) are not public installation packages and must remain private. The administrator's chosen initial login remains in place; set your own password before external accessibility.
