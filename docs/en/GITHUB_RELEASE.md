# GitHub Releases

A call builds all release files:

```bash
python3 tools/build_release.py --output-root dist
```

Before `version.py`, update the feature overview and version history.
The entire existing version history is automatically converted to `RELEASE_NOTES.md`,
with the newest version first. The feature overview must additionally include a section
`NEU UND GEÄNDERT IN VERSION <Version>` in addition to the current header line.
Existing release folders are not overwritten. The release file list
in `packaging/source-manifest.json` is mandatory; missing files will break the build.
Optionally check private search terms with `--forbidden-file`.
Never commit this file. Heuristic checks do not replace a review.

Result: DEB, individual checksums, installer with additional modes, installation notes,
feature overview, version history, release notes, source archive,
file manifest, complete ZIP and SHA256SUMS. All builds use by default
SOURCE_DATE_EPOCH=0. Byte-identical results require the same build tools.

For a new public repository, use the generated source archive as the starting point.
The existing server repository contains historical context files and personal data:
does not upload its complete working tree or Git history without review. The project license is GPL-3.0-or-later.
`LICENSE`, `LICENSE_NOTICE.md` and
`THIRD_PARTY_NOTICES.md` are included in all release packages. The author note remains intact.

After setting up the GitHub repository, commit the reviewed state and tag it with
`v<Version>`, for example `v0.12-42`. Push the tag. The workflow
checks version and tag, builds twice, compares checksums, and creates a
release draft with all files. Publish the draft after review.
A manual workflow start must also occur on the version tag day.
Existing releases are not automatically replaced. The workflow uses
GITHUB_TOKEN with contents: write; no separate personal tokens needed.

GitHub additionally creates its own source code archives of the complete tag.
For this reason, only the reviewed source state belongs in the published repository.

Documentation:
https://cli.github.com/manual/gh_release_create
https://github.com/actions/checkout

## Platform Status
Debian 13 is the regular development and release state.
Linux Mint 22.x remains experimental. Both profiles are built separately with --target.
The status is in the package and in the respective release manifest.
The workflow creates a regular draft; Mint assets and platform notes
are explicitly marked as experimental. Release only after review.
Version numbers are assigned sequentially, without platform suffixes.
Version 0.12-47 remains an unchanged backup snapshot.

## German and English Documentation
Maintain all descriptions under docs as well as README, CHANGELOG,
and legal explanations in docs/en.
The feature overview, complete version history, and installation instructions must
contain the same version and content changes in both languages.
The release build checks docs/en/translation-manifest.json against source texts and
English files. After each change, verify the translation and update the manifest with
python3 tools/check_documentation.py --refresh. This command
does not translate automatically; it only confirms the previously verified mapping.
A normal build fails if translations are missing or outdated.
The packages are additionally provided with English release notes and a
bilingual documentation ZIP. Do not include personal server values in documentation,
manifest, or source archive.
