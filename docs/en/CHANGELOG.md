# CHANGELOG

Current version: **0.13-8** (Beta). Full changes are available in the
[English version history](Home_Server_Manager_Version_History.txt) and the
[German version history](../Heimserver_Manager_Versionsaenderungen.txt).

## Historical baseline

### Core
- Plugin Loader
- Module Overview
- Project Status Tools
- Migration Table

### Home Network
- IPv4/IPv6 Display
- Device Naming
- Device Types
- Offline Detection During Scan
- Soft Delete
- Adoption as Client Agent

### Client Agent
- Token-Based Agent
- Installer Download
- Set/Clear Requirement
- Server Control Blocker

### Server Control
- Blocker API
- Tvheadend Blocker
- Client Agent Blocker
- RTC Display

### TV / Tvheadend
- API Integration
- Streams
- Recordings
- Status Provider
- Blocker Provider
- RTC Recordings

### Sleep
- Sleep Engine
- Runtime
- Schedules
- Automatic Switches
- Dry Run / Actual Execution

## 0.13-3 – October 11, 2026 – Beta
- Linux client 0.4.36: readability preflight for HTTPS system and personal backups. List inaccessible paths, exclude them for this run only after explicit confirmation, and record exclusions in the inventory. New read errors during transfer still fail the backup. Local per-user exclusions remain supported; packages contain no private exclusions.
- Show incomplete incremental uploads and retire them after confirmation while preserving blocks and completed snapshots. Read files again and reuse identical blocks. Other devices, running verification, changed uploads and activity within ten minutes prevent retirement. Do not replace paused uploads.
- Background checksum verification with status polling and verification progress instead of one long HTTP request. Mark complete only after successful verification. A lost connection or service restart leaves completion unconfirmed; do not discard data prematurely.
- Personal inventory shows the home filesystem and excluded nested mounts. Clear read errors without an additional desktop crash report.
- Update manager and client together; manager changes require a checked restart. Run-scoped authentication requires the updated running manager. Package builds do not change running services or backups. Windows and simple folder/USB backup modes do not receive these Linux HTTPS extensions.

## 0.13-4 – October 11, 2026 – Beta
- Linux client 0.4.37: content-defined block boundaries for incremental HTTPS system and personal backups. Insertions and deletions no longer permanently shift all subsequent boundaries. SHA-256 verification and byte-exact restoration remain in place; no local temporary archive.
- The first run after migration may create many new blocks; older snapshots remain readable and unchanged. Files are still read in full. Previous reading positions are not resumed. Blocks range from 1 to 4 MiB, with a smaller final block; maximum 262144 blocks per snapshot, so capacity depends on block sizes.
- Configured local offline copies of all normal users are excluded from new shared system snapshots by default, including size estimation. A visible option allows inclusion and requires a new system snapshot. Additional filesystems still require separate selection. User homes remain separate; existing system snapshots are unchanged.
- Tests cover insertion, deletion, different input fragment sizes, absent content anchors, server-side verification and restoration. Windows, simple folder backups and the USB assistant are unchanged.

## 0.13-5 – October 11, 2026 – Beta
- Linux client 0.4.38: backup workflow organized by account, scope, actions and progress. Advanced options collapse; signing in no longer opens duplicate dialogs. Long status messages scroll separately to keep actions accessible.
- Wide scrollbars appear only when needed and remain visible while content overflows. Larger initial settings, offline-file, backup and restore windows fit the monitor work area.
- Cancelling block-based backups retains uploaded blocks for the next incremental run. All source files are still read; only unknown blocks are uploaded. Simple folder/ZIP backups and the USB assistant remain unchanged.
- Delete completed server snapshots after account sign-in and explicit confirmation. Shared blocks and system baselines referenced by personal snapshots are protected. Active downloads lock their storage against concurrent deletion.
- Administrator tool re-indexes existing block archives without changing archive size, SHA-256 or snapshot ID. Requires a maintenance window and temporary additional storage. Package installation never automatically migrates or deletes existing backups.
- Matching backup UI and implementation shipped together, including incomplete-upload confirmation, offline-copy exclusion and content-defined chunking.

0.13-6 – October 18, 2026 – Beta
- Linux client 0.4.39: clear message when synchronization is already running; shared live progress for automatic and manual sync. Sign-in & setup appears at the bottom, with no reserved blank space while collapsed; compact main window.
- SMB deletions retain the original file by renaming it within the share. Ownership and permissions remain intact; Samba rights are not bypassed. Updates to existing files still use the previous ACL-checked recovery-copy method and may fail when permissions are insufficient.
- Update runs refresh status and results automatically; completion checks refresh app cards. Backup preparation continues polling after a connection failure without starting another job.
- Running app update checks prevent automatic shutdown; interrupted checks are detected after a manager restart. Open WebUI blockers observe locks without competing for them.
- Direct manager restart under Settings retains existing job checks. Visible, copyable client download addresses still require sign-in.
- Windows client 0.2.12 rebuilt from current source; remains experimental. The new GTK layout and Linux SMB fixes are Linux-specific. No native Windows runtime test for this release.

0.13-7 – October 18, 2026 – Beta
- Linux client 0.4.40: new server-side offline recovery copies are stored in hidden .hsm-history directories, grouped by UTC timestamp and unique ID, retaining full original filenames.
- History directories remain excluded from offline synchronization. SMB deletions and HTTPS replacements retain the original inode, ownership, file permissions and ACLs. SMB replacements still use a verified ACL copy; insufficient permissions are not bypassed.
- Legacy recovery copies are retained; installation does not automatically migrate or delete them. Original filenames cannot reliably be reconstructed without an existing mapping.
- Windows client remains unchanged at 0.2.12 (experimental). The new client-side SMB layout applies to Linux.

0.13-8 – October 18, 2026 – Beta
- Linux client 0.4.41: clickable software download link at the bottom left, derived from the configured manager address. Without a valid address, the example link remains disabled.
- Version number shown only in the window title; duplicate version line removed. German and English labels.
- Includes the history layout and all documented fixes from interim releases 0.13-4 through 0.13-7. Windows client remains 0.2.12 (experimental).
