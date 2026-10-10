# Offline files (beta)

Under **Network → Client agents → Offline files · Permissions**, the Manager
administrator grants access to an existing data folder for selected paired users
and devices. Old, unpaired tokens are insufficient. The manager limits the folder
scope without adding file permissions. SMB/NFS rules and the paired system user's
Linux permissions are checked. File operations run in a separate process with that
user's UID and groups. Removing a grant prevents further access but does not erase
existing local copies.

In Linux client 0.4.8 or Windows client 0.2.10 and later, open **Offline files**, load
the grants and select a dedicated local subfolder. Do not select a network drive
or the entire user directory. Defaults: download from server only, manual runs,
no deletion propagation and no wake-up. HTTPS with a verified certificate chain
is required.

Optionally enable both directions, deletion propagation, waking before syncing,
a minute interval and a local storage limit. The interval runs only while the
client, including its tray icon, is running; no wake attempts occur when waking
is disabled. Exclusions are comma-separated relative file or folder names, for
example `Videos,Drafts/large.bin`. Wildcards are unsupported. Exclusions do not
remove existing local files.

Synchronization compares SHA-256 against the last confirmed state. Only changed
files are transferred, each in full, without a local aggregate archive. After an
interruption, confirmed files are not transferred again; an interrupted individual
file restarts. There is no block-level delta transfer. A renewed, expiring lease
keeps the server awake during synchronization.

Files changed concurrently remain untouched on both sides; the client reports
the affected paths. Save both versions separately, deliberately reconcile their
contents, then sync again. There is no automatic conflict resolution. The new
common baseline is confirmed only when both sides contain the same contents.
Different new files with the same name also cause a conflict.

Replaced and deleted server files remain as `.hsm-history-*` in their source
folder. The administrator can copy them back while synchronization is paused.
Previous local files are under `.hsm-recovery` in the selected offline folder;
show hidden files in the file manager. Remove unwanted recovery revisions
manually. They do not expire automatically and count towards local storage use.
Synchronization does not replace independent backups.

Limits: at most 5000 regular files per folder with no fixed file size limit. No links,
special files, empty directories, nested mounts or nonportable filenames.
Windows junctions/reparse points and hard links are rejected. System files,
databases and open application data are unsuitable. Close applications before
syncing documents for consistency. Concurrent changes by other programs are
rejected where detectable; this module does not provide a global lock for SMB or
local programs.

A missing folder, changed disk or invalid grant stops synchronization. Server
grants are bound to folder and device identities; the administrator must recreate
the grant after a change. Changing profiles creates a new baseline; differing
existing files are not silently overwritten. The Windows build and logic were
tested under Mono; testing on actual Windows 10/11 remains outstanding.

## Multiple folders (Linux 0.4.7 / Windows 0.2.9)

Enter multiple absolute server paths, one per line, in the Manager. All paths are
validated before saving and become separate grants for the selected clients.
Overlapping paths are rejected. The optional name becomes a prefix when granting
multiple paths.

Check multiple grants in the client and choose “Set up selected folders”. Each
grant receives its own subfolder under a shared local base folder; identically
named grants still receive distinct destinations. Existing destinations and
settings are preserved. New pairs start read-only, manual, without waking or
propagating deletions. Change them using the individual folder selector.
“Sync selected folders” processes configured folders sequentially and reports
each result. A failure does not stop the remaining folders.

Mounted folders and immediate subfolders can be selected together in the manager. Each grant remains separate. Newly granted roots record the filesystem UUID (or network source) and mount path; a missing or changed mount blocks synchronization. Nested mounts must be granted separately. Existing grants retain their previous identity checks.

Offline folder selection and permissions (Linux client 0.4.8 / Windows client 0.2.10):
The manager limits selection to mounts and configured share roots. Clients can browse deeper within that scope and select multiple folders separately.
New grants do not assign extra write permissions. Every request checks SMB/NFS rules and the paired system user's Linux file permissions; file operations run in a separate process with that UID and group memberships. The emergency ADMIN account cannot retrieve offline files. Existing read-only limits remain.
Limits: complex SMB rules, Windows ACLs/VFS, forced identities, NFS hostnames/wildcards and advanced NFS identity rules are refused rather than guessed. When multiple share types apply, permissions are conservatively intersected. Nested mounts need a separate grant. Existing file owners, modes and POSIX ACLs are retained; changes are refused if that user cannot preserve them. Revocation does not automatically erase existing local copies.

- Offline files: select a user/client first, then edit its folder assignments. Only mounts and configured SMB/NFS share roots are selectable; no subdirectories are enumerated. Other clients and existing permissions are preserved.

Access diagnostics: If all assigned folders are blocked, the API reports the rejection reason instead of an apparently empty share list. Under Offline files, the administrator can run an access check for the selected client. This check does not change permissions or assignments.

Samba checks: Share ACLs and additional Windows file ACLs are checked with Samba access_check. Checks apply during assignment to a user/client and again during file access. The assignment selector shows only folders accessible to the selected user. Saving removes hidden, no longer accessible assignments for this client. Supported: local standalone servers with tdbsam, ordinary allow/deny ACLs and resolvable local identities; unknown rules remain blocked. Direct HTTPS writes remain blocked for Samba folders. Linux client 0.4.14 supports the additional SMB login described below for writing back instead. Samba permissions are not modified. Requires python3-samba and sharesec.

Linux client 0.4.9 (2026-10-10): Existing SMB/NFS mounts are detected and can be associated with an offline share. Transfers continue over HTTPS; no mounts are created or modified. Offline destinations inside, above or equal to known network mounts are rejected; saved associations also protect unmounted paths. Windows client unchanged.

Linux client 0.4.10 (2026-10-10): After explicit confirmation and administrator authorization, a simple SMB/NFS fstab mount can be replaced by a link to the local offline folder. A conflict-free HTTPS synchronization runs first. The existing path remains usable; fstab and the mount directory are backed up. Returning to the network mount requires confirmation and retains local files. Busy mounts are never forcibly detached. Automounts, custom mount services and writable mount parent directories are not automatically converted. Samba offline data currently synchronizes read-only; local edits are not uploaded to the server.

Linux client 0.4.11 (2026-10-10): Confirmed offline switching now supports native systemd automount units and fstab-generated SMB/NFS automounts. A dedicated persistent start condition prevents remounting during offline use. Original units, fstab entries and enablement remain unchanged. Previous active/inactive states are saved and restored when switching back. Busy mounts are never forcibly detached; changed unit configurations and overridden start guards are rejected. A successful conflict-free HTTPS synchronization, confirmation and administrator authorization remain required.

Linux client 0.4.12 (2026-10-10): “Use mount path for offline files” automatically suggests a separate local storage folder. An existing configured local folder is retained; invalid network destinations are rejected. Confirmation shows the usual access path and local storage location before saving settings, synchronizing files or changing mounts. Conflict-free synchronization and administrator authorization remain required.

Fix: Windows ACLs read from security.NTACL are converted losslessly to standalone security descriptors before Samba evaluation. An internal type error is no longer reported as permission denial. Access failures identify the affected path; failed synchronization prevents mount replacement.

Linux client 0.4.13 (2026-10-10): Create or adopt local offline folders directly in the client. Write access is checked before saving or synchronizing; where needed, explicit administrator authorization creates the folder or changes its owner. No recursive permission changes and no client running as root. Network mounts and system folders are excluded. Privileged creation requires an existing protected parent directory.

Linux client 0.4.14 (2026-10-10): Two-way synchronization for supported SMB shares with an additional SMB login. Passwords are stored only in the local keyring; HTTPS read access and existing manager assignments are still required. Samba enforces write and inheritance permissions. Existing files retain their owner and ACL during updates; previous content is retained on the server with verified permissions. Interrupted writes may leave incomplete server content: keep the local file and retained revision, review the conflict and resolve it explicitly. Diverging revisions are never silently overwritten.
Per-folder options remain editable: synchronize at login / client startup and before shutdown. Shutdown never wakes the server; if unreachable, proceed immediately after a brief connection check. Otherwise wait at most 60 seconds, additionally capped by systemd-logind (often 5 seconds). The client must be running; forced power-off cannot be intercepted. Errors and timeouts remain visible as pending. The next startup retries if startup synchronization is enabled. New package dependencies: python3-smbc and libsecret-tools. Windows client unchanged.

ACL correction: Unresolved identities in allowing Samba ACL entries grant no permissions, but no longer block independently established read access. Unknown deny entries remain blocked. Existing file and share permissions are not modified.

Linux client 0.4.15 / Windows client 0.2.11 (2026-10-10): Removed the 256 MiB offline file limit, including support for larger ISO files. Transfers use bounded chunks; storage quotas, free space, permissions and timeouts still apply. Temporary server storage requires the file size plus a 512 MiB reserve. Links and special files remain excluded.

Linux client 0.4.16 (2026-10-10): Selecting a network mount suggests an offline destination matching its folder structure, inserting Offline between the parent directory and mount name. The suggestion remains editable. Existing assignments are retained when opening the dialog; existing files are not moved automatically.

Linux client 0.4.17 (2026-10-10): New “Include all server subfolders” button selects the entire assigned server folder and clears exclusions after confirmation. Files in deeper subfolders are synchronized recursively. Review the destination and save; no immediate sync is started. Permission checks remain in force; empty directories, links and nested mounts are not included.
