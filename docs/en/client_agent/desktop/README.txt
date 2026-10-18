HEIMSERVER MANAGER CLIENT – Desktop App 0.4.38

Debian 13 / LMDE 7 / Linux Mint 22.x, graphical user session with systemd.
Installation: sudo apt install ./Heimserver_Manager_Client_0.4.38_all.deb
Then open "Home Server Manager Client" in the start menu.

In the manager under Network / Client Agents download the desktop profile of the matching client. In the app, select "Import Profile", verify details, click "Save", and choose "Activate Agent / Take Over". The profile contains THE PERSONAL AGENT TOKEN: do not share or leave it publicly accessible.
The general DEB package does not include a server address or credentials.

Existing configuration: ~/.config/server-manager-client/config
The app reads this as data without executing shell code. Complex individually adapted shell configurations are not adopted; use the JSON profile.
Upon takeover, existing systemd user units and the configuration under ~/.local/state/heimserver-manager-client/before-... are backed up.
The existing unit names remain intact. No second agent is started.

Features: Settings, wake server, report server demand, release share,
wake and connect, prepare access, status, log, user auto-start.
Operating modes: with server, without server, explicit Wake-on-access call.
Wake via Recovery URL, Wake-on-LAN, both methods or none at all.
The actions and heartbeats originate from the existing manager client script.
Wake-on-access does NOT automatically monitor file access; the action must
be called explicitly. One-time demand/release notifications are overwritten by
the configured operating mode on the next heartbeat.

The timer runs after user login, even with a closed window.
No system-wide root agent and no changes to sudo groups.
Status icon: Ayatana AppIndicator; depending on the desktop environment,
display of status icons must be supported/activated. GNOME may require an extension.
A green symbol means server reachable, not token successfully verified.
A desktop endpoint can also terminate the systemd user session.

Disable: in the app "Deactivate Agent" recommended before uninstallation.
Remove package: sudo apt remove heimserver-manager-client
Personal configuration and backups are preserved. Package installation
does not activate an agent and does not start a wake action without user setup.

Limits: no automatic mount management, no new Home Assistant or IPMI server installations.
These remain separate manager functions. Repeated waking can take time.
Before production use on the respective desktop check status icon, login,
network switching and sleep behavior.

Client version 0.1.1 – September 30, 2026
Startup errors fixed: The GTK startup function was replaced by an action method.
Window construction and program start on the GTK test display were verified.
Update an existing 0.1.0 package by installing this DEB.
User settings are preserved.

Client version 0.4.32 – September 30, 2026
The status icon starts automatically upon graphical user login as soon as the client configuration is present—even for previous script-based clients.
Without configuration, automatic startup remains silent. The agent is thereby not activated and no wake-up action is executed. Manual opening remains possible.
"Disable Agent" also disables the icon auto-startup for this user.
"Activate Agent / Take Over" reactivates it.


NEW IN CLIENT 0.4.32
Own file backups and restore in the client; server backups only via renewed manager administrator login in the browser. Private HTTPS with verified root certificate, optional hostname entry, and administrator approval.
First set up backups in the Manager desktop client security section and use a separate JSON profile per user. File backups are not complete system images.
Links, special files, ACLs, and operating system state are not fully backed up.
Details: docs/CLIENT_BACKUP_ACCESS.md in the manager source package.

CLIENT 0.3.4 – USER LOGIN (October 3, 2026)
- In the client choose "Log in to Manager / Own Backups".
- Administrator: Settings → Manager User → release Linux account,
  select Role User and scope Own Client Backups.
- Login with Linux password via validated HTTPS. Password and session
  are not stored on disk; must log in again after restart.
- Users may start their own backups and restore them.
  Read-only permission allows restoring existing personal backups only.
- Account backups are separated from legacy agent backups. Old snapshots
  remain accessible within the current profile; do not share profiles between users.
- Server backups reserved for administrators. Revocation of rights or session expiry ends access;
  no automatic fallback to tokens occurs.
- The existing JSON profile continues to be required for server address, HTTPS,
  and agent functions. USB backups remain possible offline.
- Complete Linux system restore remains only in live system;
  normal users thus gain no local administrator rights.
- This extension applies to the Linux DEB; Windows EXE unchanged.

Client 0.3.5 – HTTPS Proxy Fix (October 3, 2026)
- Account backup requests use the session token instead of an
  HTTPS origin comparison with the internal HTTP backend.
- Expiration, missing permissions, and request validation are explained separately.
- Update both server extension and Client 0.3.5 together.

Client 0.3.6 – Distinguish Backup Paths (October 3, 2026)
- Direct HTTPS system backup listed first; no folder selection.
- USB/NFS assistant explicitly labeled and explained before start.
- HTTPS protocol indicates the selected transfer path.


Development status October 4, 2026 – Linux client 0.4.0
- HTTPS system states transfer only new 4-MiB blocks; unchanged blocks are reused per account/profile. No local archive intermediate copy.
All source files are read again; shifted block boundaries can cause additional transfers. Every completed state remains selectable.
- System files, programs, package sources, Flatpak/Snap, user homes,
desktop, UID/GID, ACLs, services and configuration included; additional
local mounts and network profiles optional. Offline source selectable.
- Software/hardware inventory and capture errors in archive documented.
- HTTPS restore: system or components in live system; individual
files/folders without root to new folder. External validation repository required.
- Same distribution/version/architecture for system restore required.
Target fstab/crypttab remain intact. No automatic partitioning,
bootloader installation, cross-platform package migration or deletion of additional target files. No sector-by-sector image. Running databases/VMs
stop beforehand or offline backup. No archive encryption at rest.
- Cleanup on abort retains blocks of completed states. Account/profile separation,
checksums and archive paths are checked. Windows EXE unchanged.
- Guide: docs/HTTPS_SYSTEM_BACKUP.txt; also included in the client package.


Development status as of October 4, 2026 – Linking users and devices
- Linux Client 0.4.1 and Windows Client 0.2.3: own token and own sleep blocker per Manager user, device, and local user identity.
- Import JSON profile, set up HTTPS, log in to the manager, and select link user & device. Linux: in Own Client Backups dialog; Windows: directly in settings. Releasing Own Clients & Backups requires Role User or Administrator. Read-only permission cannot link.
- A single user on multiple PCs and multiple users on a PC can independently report their need. Release only affects the own entry.
- Server MAC is exported in JSON and taken over during linking. If both recovery address and server MAC exist, both wake-up paths are available in JSON.
- Device identification is derived locally from machine-id (Linux) or MachineGuid (Windows); local user identity from UID or SID. The MAC is only supplementary information. A changed system/user account may require relinking if necessary.
- New tokens are bound to these identities; copied profiles do not automatically fit other PCs/accounts. No hardware-based proof of identity: token and system access continue to be protected; identities can be mimicked.
- Account lockout, permission/password change, or disabled agent prevents further reports. Outdated needs expire according to existing heartbeat timeout.
- Old profiles remain visible as Unlinked (Altprofile) and function unchanged. After transitioning all users, disable the shared Altprofile together. Existing backup repositories are not moved; manager account backups remain independent of device linking. Manager logout ends only the web/backup session; disabling agent separately shuts down via agent.
- Windows build and transport tested; native Windows login/Registry SID and the interface have not yet been tested on an actual Windows PC.


Development status as of October 4, 2026 – Personal client setup
- After logging in to manager under https://SERVER:HTTPS-PORT/clients/setup download Linux DEB, Windows EXE and own setup profile.
- Releasing Own Clients & Backups and Role User/Administrator required. No view of foreign profiles or tokens. Read-only can download programs but cannot set up new device linking.
- Profile contains server address, server MAC, possibly private certificate information and a 15-minute valid one-time code. On the server only its hash is stored.
- Linux 0.4.2 / Windows 0.2.4: import profile, save, optionally set up private HTTPS after fingerprint verification; activating agent exchanges the code via verified HTTPS for own user-device token. No password storage.
- Each new profile replaces earlier unused codes of same account. Upon expiration, lost response or failed local storage fetch new profile. Permission change/account lockout also prevents redemption of existing codes.
- Start mode Start without server then select manually. Root certificate and hosts entry continue to be changed only upon explicit confirmation. Backup login remains separate; personal setup grants no server backup rights. Windows remains experimental, native Windows verification pending.

Language / Language
German for German desktop display language, otherwise English. Selection at program startup; after changing the desktop language restart the client.
The language in the manager browser and the JSON profile do not change this selection.
Install new client version; existing settings remain intact.
Own names, paths, technical protocols and output of external programs
(including the USB/NFS migration script) remain unchanged.

German for a German desktop display language; English for all other languages.
Restart the client after changing the desktop language. Browser language and
JSON profiles do not override this setting. Install the new client release;
exiting settings are preserved. Names, paths, technical logs and external
program output (including the USB/NFS migration script) remain unchanged.

Client 0.4.32: During an account-authenticated backup, an expired session opens a new sign-in dialog. The running transfer pauses and resumes the same request and upload after sign-in with the same account and server. Uploaded blocks stay intact. Wrong passwords can be retried; revoked permissions do not bypass authorization. Passwords are not stored. Keep the client running while paused. Closing the client or stopping the transfer does not provide automatic recovery after restart; existing incomplete backups are not retroactively resumed.

Client 0.4.33 – October 11, 2026
- Unattended HTTPS backups use a separate, revocable credential bound to the account, client device and backup run. Active transfers continue after the ordinary login expires, including shared system and personal components. The credential is closed at the end and expires after 24 hours without API activity. Account restrictions still apply. Requires the matching manager update; no passwords are stored. This does not automatically resume previously terminated transfers.

Client 0.4.34 – October 11, 2026
- Linux HTTPS system backups display estimated progress from 0 to 100 percent, weighted across the new system and personal components. An existing reused system snapshot is excluded from the new workload. Sent and reused blocks both count; server verification is shown separately and 100 percent appears only after successful completion. A metadata scan uses the same mount exclusions; sparse files and archive metadata make the estimate approximate. No temporary local archive is created. The separate USB assistant and simple folder-backup flow are unchanged.

Client 0.4.38 – October 11, 2026
- Offline files: a known local deletion remains pending instead of being downloaded again when two-way sync or deletion propagation is disabled. Both options are required to delete the server copy. Concurrent server changes remain conflicts; files without a previous sync baseline are treated as new server files. Existing folder settings are not changed automatically.

0.13-3 – October 11, 2026 – Beta
- Linux client 0.4.38: readability preflight for HTTPS system and personal backups. List inaccessible paths, exclude them for this run only after explicit confirmation, and record exclusions in the inventory. New read errors during transfer still fail the backup. Local per-user exclusions remain supported; packages contain no private exclusions.
- Show incomplete incremental uploads and retire them after confirmation while preserving blocks and completed snapshots. Read files again and reuse identical blocks. Other devices, running verification, changed uploads and activity within ten minutes prevent retirement. Do not replace paused uploads.
- Background checksum verification with status polling and verification progress instead of one long HTTP request. Mark complete only after successful verification. A lost connection or service restart leaves completion unconfirmed; do not discard data prematurely.
- Personal inventory shows the home filesystem and excluded nested mounts. Clear read errors without an additional desktop crash report.
- Update manager and client together; manager changes require a checked restart. Run-scoped authentication requires the updated running manager. Package builds do not change running services or backups. Windows and simple folder/USB backup modes do not receive these Linux HTTPS extensions.

0.13-4 – October 11, 2026 – Beta
- Linux client 0.4.38: content-defined block boundaries for incremental HTTPS system and personal backups. Insertions and deletions no longer permanently shift all subsequent boundaries. SHA-256 verification and byte-exact restoration remain in place; no local temporary archive.
- The first run after migration may create many new blocks; older snapshots remain readable and unchanged. Files are still read in full. Previous reading positions are not resumed. Blocks range from 1 to 4 MiB, with a smaller final block; maximum 262144 blocks per snapshot, so capacity depends on block sizes.
- Configured local offline copies of all normal users are excluded from new shared system snapshots by default, including size estimation. A visible option allows inclusion and requires a new system snapshot. Additional filesystems still require separate selection. User homes remain separate; existing system snapshots are unchanged.
- Tests cover insertion, deletion, different input fragment sizes, absent content anchors, server-side verification and restoration. Windows, simple folder backups and the USB assistant are unchanged.

0.13-5 – October 11, 2026 – Beta
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
