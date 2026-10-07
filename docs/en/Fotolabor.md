# Photo Lab in Server Manager

Route: `/fotolabor`, fixed content: `/srv/fotolabor`.
Registration via `modules/fotolabor/plugin.py:register(app, ctx)`. Uses
`ctx.page`, `ctx.db`, the existing SQLite database and the central blocker API.
`app.py` receives exclusively the navigation entry.

## Operation

1. Open Photo Lab and check tool status.
2. Start "Full Validation". Results, file types, size, and progress
   are saved. Changing pages does not cancel the job.
3. Open error list or DNG categories; lists are limited to 100 lines per page.
   After a completed validation, "Download Defective Images as Text File"
   provides a UTF-8 report with all defective images, full paths, and
   reasons for defects. The download is not limited to the visible 100 lines
   and includes scan time and count of uncheckable images; these are not
   mixed with confirmed defects. For running or interrupted jobs, the report
   from the last completed validation remains available.
   Paths containing control characters are output as JSON strings for unique display.
   The report reads exclusively saved results.
4. "Create DNG Deletion Preview" checks the entire content and shows count
   and storage size of safe DNGs including XMP. Nothing is deleted during this step.
   Only separate confirmation with `ja` starts targeted safety validation
   and deletion of unchanged, confirmed candidates. No further full scan occurs.
5. Jobs can be paused and resumed. Already validated files remain intact;
   upon upgrade, previously unvalidated WebP images are re-scheduled.
   Interrupted deletion jobs require a new preview and confirmation.
6. Scan history allows selection of earlier results. Targeted re-validation
   combines file type, status, and error group. It creates its own job and does not overwrite the original report.
7. Additionally, a text report for all uncheckable files with paths,
   error groups, and individual reasons is available. Both downloads are accessible after completion or finished preview and contain all matching records.

Debian 13:

```sh
sudo apt install jpeginfo pngcheck libtiff-tools libimage-exiftool-perl libraw-bin webp python3-pil
```

Missing programs block the affected validations; jpeginfo and ExifTool are
mandatory for cleanup. No automatic package installation.

## Validations and Limits

- JPEG: `jpeginfo -c`, warnings also prevent deletion.
- PNG: `pngcheck`. Only the known zlib build/runtime version message is ignored on return value 0; image errors are not ignored.
- TIFF: `tiffinfo -D` reads/decompresses all image data from all TIFF directories.
- DNG/RAW: ExifTool plus `dcraw_emu -q 0 -Z -`; image output is discarded, no converted files are created. Unsupported variants or decoder warnings are reported as uncheckable.
- WebP: `webpinfo -diag` and full Pillow/libwebp decoding of all individual images, even in animations. Decoder errors count as defective, missing support and resource limits as uncheckable.
- Other known image formats are detected but displayed as uncheckable without a matching decoder. Video/non-image files do not belong to the image statistics.
- A successful decoder run proves readability at the check time point, not photographic correctness, completeness of an archive, or absence of earlier unnoticed bit changes. No historical checksum inventory exists.

Sources: [Debian tiffinfo](https://manpages.debian.org/trixie/libtiff-tools/tiffinfo.1.en.html),
[Debian jpeginfo](https://manpages.debian.org/trixie/jpeginfo/jpeginfo.1.en.html),
[LibRaw dcraw_emu](https://github.com/LibRaw/LibRaw/blob/master/samples/dcraw_emu.cpp).

## Deletion Safety

Only `XMP-xmpMM:HistoryParameters` with
`converted from image/jpeg to image/dng` confirms JPEG origin. The reference file
`/mnt/data/dng-jpeg-checker.sh` was neither locally nor on the server available;
the explicit security requirements of the job were natively implemented.

- Category 2: JPEG healthy. Deletability additionally requires matching resolution,
  confirmed file types. The main feature of assignment is the same exact filename
  in the same folder. Differences in DateTimeOriginal/Make/Model are only hints.
- Category 3: JPEG missing. DNG and XMP remain preserved.
- Category 4: JPEG defective, uncheckable or ambiguous. DNG and XMP remain preserved.
- Category 5: other/RAW-DNGs or unclear origin. No deletion.

Filename is compared exactly; JPEG extensions are case-insensitive.
Multiple JPEG candidates protect the DNG. The DNG itself may not be supported by LibRaw
and can still be a candidate based on clear origin and healthy
JPEG proof; such cases remain visible in the integrity list.

Immediately before deletion: re-decoding of JPEG, origin/resolution check, open
descriptors, inode/size/timestamp and SHA-256 comparison. No symlinks
are followed, even not in parent path components. Tools receive file descriptors instead of shell strings.
JPG/JPEG are never deletion targets.
`.dng.xmp` and same-named `.xmp` are removed only with associated approved DNG.
XMP possibly shared with another RAW/DNG may protect the package.

During cleanup, no other programs must edit the inventory.
POSIX offers no atomic transaction over DNG/JPEG/XMP and foreign write processes.
In case of error after DNG deletion, XMP may remain; the audit shows
individual actions and partial errors. There is no automatic retry.

## Operation and Persistence

Migration `migrations/0003_fotolabor.sql` is applied idempotently on plugin registration;
`0004_fotolabor_resume.sql` supplements job phases, filters and preview fingerprints in two additional detail tables.
Both are marked with SHA-256 in `schema_migrations`. Tables:
`fotolabor_jobs`, `fotolabor_files`, `fotolabor_audit`. Historical results and
deletion logs remain preserved. Size/counters are a scan snapshot; after cleanup
for the new inventory they are scanned again.

Background thread according to existing manager job architecture; no full scan
in HTTP request. Cross-process `flock` lock prevents competing jobs.
The central blocker exists from `queued` until completion/cancellation. On a service restart,
orphed tasks are marked as interrupted, never automatically continued.
Checks can be resumed via the interface; the finished preview holds no sleep blocker.
The existing systemd service terminates its child processes with it.
An uninitializable module conservatively blocks the sleep decision.

## Tests

```sh
python3 -m py_compile app.py modules/blocker_api/registry.py modules/fotolabor/*.py
python3 -m unittest discover -s tests -p 'test_fotolabor*.py' -v
git diff --check
```

All test images and deletions are stored exclusively in temporary folders.
Actual decoder tests additionally require Pillow for test image generation
(`python3-pil`); full WebP validation also requires Pillow during operation.

Known notes regarding the MicrosoftPhoto namespace, skipped large arrays,
and deprecated IPTCDigest do not prevent pairing on their own. Required origin and dimensions must still be proven; optional EXIF deviations have been treated as hints only since 13.09.2026.
Other ExifTool warnings and errors remain blocking. DNG integrity warnings remain visible regardless of the file's deletability.

## Duplicate Search

Under `/fotolabor/duplicates`, a separate read-only search runs on the fixed image set. File size filters candidates; SHA-256 compares full contents.
File names and subfolders may differ. Visual similarity or re-encoded images are not detected. There is no duplicate deletion action.

The existing photo lab worker, central sleep blocker, and job lock
are reused. Starting a new image validation while one is running is blocked.
Pause/Resume retains results. Migration 0005 stores hashes separately from integrity findings; content comparison does not produce an Image-OK.

Groups are retrievable page by page and can be downloaded completely as a text file upon completion. Symlinks are not followed, unreadable or modified during reading files remain excluded. Hardlinks appear with the count of different file objects. Results apply at read time; later changes require a new search. No reclaimable storage is guaranteed.

During integrity checks and cleanup previews, open DNGs are processed before other formats so that large WebP preview sets do not delay their assignment.
The category overview lists unverified DNGs separately.

## Automatic JPEG Metadata Repair

Migration 0006 logs repair cases. During normal checks and previews, JPEGs with successfully decoded image data are examined for ExifTool metadata hints.
Repair rebuilds metadata exclusively in a separate copy. Outputs reside in private `fotolabor-repair-*` folders within the manager state folder,
outside the image set; no original is replaced. No repair attempts occur during deletion runs. ExifTool, jpeginfo and Pillow are required.

Success requires error-free re-validation of JPEGs and metadata as well as identical pixels, color profiles and orientation. Other metadata may be omitted.
Copies appear under `/fotolabor/repairs` with reason and download link; visual inspection remains required. Damaged image data and other formats are not automatically repaired.
All recorded repair cases permanently protect the associated DNG.
Already processed JPEGs require targeted re-checking for candidate selection.

## Archive, Partial Check, Scheduling and Restoration (Migration 0007)

`/fotolabor/tools` offers relative folder selection, exclusions (one path per line), full check, quick check of new/changed files, and checksum-only validation.
Scope and load options are saved per job. Deletion runs use exclusively the confirmed preview.
Gentle operation lowers the priority of the worker thread (and its decoders) and pauses between files. Optionally the worker waits above a configured system load; this is not a fixed CPU percentage limit.

`/fotolabor/archive` displays new, unchanged, and content-modified files.
Initial SHA-256 values are retained; subsequent values/findings are stored separately.
Quick checks only accept previously successful findings for identical
file attributes. They do not detect bit changes in unchanged attributes;
frequent full/checksum verifications are required for this purpose. DNG pairs are
always rechecked again. Old results do not retroactively receive checksums.

Schedules are intentionally created inactive initially unless activated.
Daily start time and weekdays apply in server local time. Due jobs wait
when a worker is occupied; starts are transactionally marked with the next due
date. A new photo lab RTC provider supplies wake times to the existing central
RTC scheduler. Existing sleep/wake settings remain unchanged.

`/fotolabor/compare` compares two completed integrity checks of the same
subinventory: new paths, no longer tracked paths, and status changes, page by page.
Repairs have a direct original/copy image comparison; no replacement.

`/fotolabor/restore` starts an explicit DNG restoration in the same worker.
LibRaw develops a 16-bit TIFF and from that a JPEG, exclusively in private
state subdirectories. Both are fully checked, offered for download and as preview.
Color/tone development may deviate from the historical JPEG. No missing detail is invented; incompatible DNGs remain visible as errors.
Restoration sources are permanently protected against DNG cleanup.

GIF (all frames) and BMP are fully read with Pillow. HEIC/HEIF/AVIF
are decoded with installed `heif-convert` (Debian: `libheif-examples`) including
its output main/additional images. Missing decoders remain
"uncheckable". LibRaw 0.21.4 covers existing RAW endings; unsupported
camera/DNG variants continue not to be claimed as healthy.


Since 13.09.2026, file name assignment takes precedence at explicit request:
divergent recording times, manufacturers or models prevent release even with exact
stem in the same folder. Highly limited MakerNotes diagnoses (offset,
manufacturer data not interpretable, CanonCameraSettings) do not block required
standard metadata en masse. Origin entry, file types, image dimensions and
JPEG decoding remain mandatory. Other warnings/errors as well as ambiguous pairs
remain protected. Repair and restoration sources retain their protection.
The integrity indicator of the DNG remains separate from pair assignment.


Since 13.09.2026, deletion requires no second full scan. It only takes over
released category-2 packages with stored preview fingerprints.
Immediately before each deletion, package identity, JPEG readability, origin,
resolution and repair/restoration protection are rechecked again. New files
outside confirmed candidates are not captured or read. Progress
counter of the delete job refers to DNG packages, not the total inventory.


Persisted previews tolerate since 14.09.2026 a changed device identifier
(st_dev), as it may occur after reboot/reconnection. File number, size,
timestamp, package members and complete SHA-256 contents must remain unchanged.
During actual deletion, the complete filesystem identity including device identifier remains protected against change.


Targeted repair jobs use exclusively JPEG repair cases of a stored DNG preview. Already existing successful copies are retained
and skipped. The repair explicitly retains ICC color profiles; defective MakerNotes/XMP/IPTC may only be removed from the copy.
JPEG/MPO is compared including all individual images. Unreadable MPO second images remain protected. Originals and DNGs are not replaced or released for deletion.


Adoption and delete preparation (Migration 0008): The explicit button
"Adopt Verified Repairs" secures originals in private
`fotolabor-original-*` directories in the manager state directory and replaces them atomically
with separately rechecked repairs. SHA-256, all image frames, color profiles,
orientation, JPEG/metadata verification as well as file stability are controlled.
Hardlinks remain excluded from automatic adoption. Owner, permissions,
timestamps and extended attributes are preserved on the replacement file.
Preliminary adoptions are journaled and can be reconciled after interruption.
Copies and original backup remain intact.

Only explicitly adopted JPEGs that have remained unchanged since then may lose their blanket
repair protection. DNG origin, same names, matching resolution,
JPEG health as well as sidecar/restoration protection remain decisive.
The targeted delete preparation reads exclusively earlier category-2 pairs
and creates a new stored preview. It does not delete any DNGs.


## Targeted MPF Preview Repair
The button under Repairs edits only stored MPO frame errors. A uniquely existing newly added JPEG preview image receives corrected MPF offsets/lengths. If all additional data is missing after the main image, only the MPF-APP2 segment is removed. Other supplementary images, unclear data and damaged main images remain protected. Main image pixels, ICC and orientation are compared; all remaining bytes are preserved. Separate copies are then applied via the existing secured transfer job. Existing other metadata warnings may persist with this change strictly limited to MPF. No DNG is automatically deleted.
