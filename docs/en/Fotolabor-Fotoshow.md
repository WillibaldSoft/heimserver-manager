# Photo Show in the Photo Lab

Call: Photo Lab → Create Photo Show (`/fotolabor/fotoshow`). The basis is the provided script `Fotoshow erstellen.sh`.

1. Open source folders in the photo lab by clicking and add them via checkbox or "Select this folder". Multiple folders can be combined. "Entire Photo Lab" is explicitly selectable.
2. Optionally enable subfolders; choose file names, seconds per image (0.1–3600), random order, and image adjustment.
3. Create in the background. The job page shows capture progress, copy progress, package building, and package validation; cancellation is possible.
4. Download the finished `.run` file. The browser determines the local target folder. Start on a Linux desktop: `bash Fotoshow.run` (use selected file names).

Playback requires feh and X11/XWayland. No software is installed on the playback computer without consent. Arrow keys switch images, Escape ends the photo show. The temporarily unpacked package is removed by makeself upon normal termination. A hard system shutdown may leave temporary files behind.

## Files and Security

Only JPG/JPEG, no symlinks. Source paths are limited to `/srv/fotolabor` and opened component-wise without symlink following. Overlapping selections are deduplicated based on relative paths. Names with spaces, umlauts, quotation marks, and line breaks are copied correctly. Images in the package receive numbered file names; `Bildliste.json` receives the mapping to original relative paths. These paths thus become part of the downloaded package.

Sources remain unchanged. During copying, file type, identity, size, timestamp, and JPEG header are checked. This is not a full image integrity check; for that purpose, the photo lab offers its existing checks. Errors result in a visible failure instead of an incomplete photo show.

Maximum 100 selected folders and 100,000 images per job. Before copying, at least twice the source data volume plus 256 MiB reserve is required. Packages are created with low gzip compression, validated by makeself, and documented with SHA-256.

## Integration

Persistence: `fotolabor_slideshows` in the existing SQLite database. Shared lock `fotolabor.lock` prevents overlap with check/repair/delete jobs. Central photo lab blocker prevents automatic sleep during creation. After restart, incomplete jobs are marked as interrupted and their temporary copies removed.

Server output: `STATE_DIR/fotoshows/<Auftrag>/fotoshow.run`, defaulting to `/var/lib/server-manager/fotoshows`. Completed packages remain available for re-downloads. There is no automatic dispatch and no automatic deletion of completed packages.

New files: `slideshow.py`, `slideshow_ui.py`, `vendor/makeself/`, tests, and this documentation. Minor additions in `plugin.py` and `blocker_provider.py`.

## Package Generator

If makeself is installed system-wide, it will be used. Otherwise, the official Debian-Trixie package content `makeself 2.5.0-1` remains unchanged, including copyright and GPL-2 license. No system-wide package installation is required. The archives created by the generator are not automatically licensed under GPL according to its licensing notice.

Source: https://makeself.io/ · feh documentation: https://man.finalrewind.org/1/feh/

Tests: `python3 -m unittest discover -s tests -p 'test_fotolabor_slideshow.py' -v`. Including actual package creation/validation, extraction, download, special characters, path-traversal/symlink protection, deduplication, interruption, lockout, and restart. The tests use exclusively temporary test images.
