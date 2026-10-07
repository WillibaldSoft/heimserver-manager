# Shares: Create, Edit, Domain and Client Files

## Operation

`/freigaben` shows SMB and NFS separately, with search, access overview and Edit/Client File buttons.

1. Choose **New SMB Share** for Windows, macOS and Linux or **New NFS Share** for Linux/Unix.
2. Enter the data folder directly or select it in the folder picker. A new subfolder can be explicitly created.
3. Select access rights and allowed users/groups (SMB) respectively devices/networks (NFS).
4. **Check Change** generates a preview. Only **Apply Now** activates it.

Edit uses the same wizard with pre-filled values. "Remove" removes only the share definition, never user data. The SMB network name remains stable during an edit.

### Rights

SMB: "Carry over existing rights unchanged" retains existing read/write/admin exceptions. The explicit selection of "Read Only" or "Read and Write" replaces these exceptions with the chosen uniform right. Users or @Groups can be added via button; domain names containing spaces are set in double quotes, e.g., `@"FAMILIE\Domain Users"`.

Existing filesystem rights are not changed recursively. A new SMB folder receives ACLs for the selected locally resolvable accounts/groups. New NFS folders require a common Linux group whose numeric GID matches on clients. For guest access, Samba server settings additionally apply.

NFS: IP addresses and CIDR networks are checked; the interface sets `ro`/`rw`, `sync`, `no_subtree_check` and the chosen root assignment. Extended existing options are replaced only upon explicit selection. In particular, existing Kerberos-/`sec`-options can be removed; this is displayed. NFS with `sec=sys` uses client UID/GID and is not automatically protected by Kerberos via an AD join. The invalid previous `rwx` is marked; during editing, `rw` is prepared. No automatic change of existing exports upon deployment.

## Configuration Protection

- GET pages and downloads do not modify shares.
- All write form routes have Session-CSRF protection.
- Previews are bound to the browser session, applicable once and valid for 15 minutes.
- Before writing, the affected configuration files must still match exactly with the preview.
- Existing SMB sections are edited in their source file; other sections, unknown options and literal includes remain preserved. New shares receive own files and explicit entries in `shares.includes.conf`.
- NFS edits only the chosen line or its continuation lines in `/etc/exports` or `/etc/exports.d/*.exports`; comments and other rules remain preserved.
- Previous content is saved under `STATE_DIR/backups/shares/<Zeit>-<ID>/restore.json`. On this server, the area under `/var/lib/server-manager/backups/shares` lies here.
- Samba is checked with `testparm` and activated via Reload. NFS is activated with `exportfs -ra`. An error restores the previous files and attempts to reload the previous configuration; an error during rollback is also displayed.
- The central sleep blocker is active during check/activation/rollback. Simultaneous changes are locked. A server manager restart during application is marked as interrupted; then check configuration/backups.
- Configuration writes require file permissions for the service account. The existing installation runs as root. A sudo password alone does not give a differently configured service direct file write permissions.

## Client Files

For each SMB share: a Windows PowerShell script to connect an unused drive letter, or a Linux desktop script to open the share in the file manager. For each NFS share: a Linux script to mount it in an empty folder; no automatic `/etc/fstab` entry. Server name/IP can be selected. Credentials are requested only on the target computer. The existing complete Linux mount manager remains available.

## Optional Domain

`/freigaben/domain` stores a **setup profile**, not the current server role. Disabled by default. There are two ways:

- **Member of an existing AD domain:** Server script uses realmd with Samba/Winbind and checks membership. It backs up existing configuration files. Membership is performed interactively on the target server.
- **New AD domain:** Server script for a fresh Debian-13 VM or your own server. It controls hostname, existing IP, AD database, and existing SMB/NFS shares before interactive Samba AD provisioning begins. Existing file servers are not automatically converted. DNS, time service, and AD backup must be configured appropriately. Interrupted provisioning requires checking partial results.

Additionally: Windows and Linux membership scripts plus an interactive AD administration menu for the set-up DC (display and create users/groups, add group members, set passwords). There is no direct web membership, no password storage, and no automatic client restart. Passwords are queried by target tools; server scripts modify systems only after their manual start and confirmation.

Local Linux/Samba users remain manageable under Users/Groups. Password transfer occurs via stdin instead of shell interpolation.

## Verification

`python3 -m unittest discover -s tests -p test_shares.py -v`

Tests use temporary configurations, simulated reloads, and real `testparm` checks plus `bash -n` for generated Linux files. No production shares, accounts, domains, or clients are changed for testing purposes. A genuine AD membership, DC provisioning, and Windows execution require a suitable target environment and are not part of this test.

References: [Debian realm](https://manpages.debian.org/trixie/realmd/realm.8.en.html), [Samba smb.conf](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html), [Samba samba-tool](https://www.samba.org/samba/docs/current/man-html/samba-tool.8.html), [NFS exports](https://manpages.debian.org/trixie/nfs-kernel-server/exports.5.en.html), [Microsoft Add-Computer](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/add-computer).
