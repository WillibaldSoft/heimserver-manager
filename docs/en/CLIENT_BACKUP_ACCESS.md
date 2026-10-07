# Desktop Clients: HTTPS and Backup & Recovery

Linux Client 0.2.2 and Windows Client 0.2.2 extend the previous agent functions.

## Setup in Manager

Under Data → Backup & Recovery → Desktop Clients Activate Backups,
set storage limit (default 100 GiB per client) and confirm the backup drive.
The filesystem UUID is checked on every transfer. The target
lies under the adjustable central backup folder in desktop-client-backup.
The archive location is also selectable during external full backups. If a source selection has already been saved, check this additional area.

Create an individual entry for each user under Network → Client Agents
and download its JSON profile. Profiles contain secret
client tokens: do not share, do not include in Git or public downloads.
a client profile corresponds to a backup identity. Whoever receives the same token,
can read the same client backups. A token is not an administrator access.
Deactivation of the client entry locks the API; token change retains its states.
deleted client entries do not automatically remove saved data.

## Backup and Restore Your Own Files

Open "Own Backups / Restoration" in the client, select user folders
and confirm backup. Close programs with open files beforehand.
The archive is initially created locally: space must be available in the temporary folder.
Transfer occurs in sections, followed by SHA-256 check on the server. Only complete states appear in the selection.

Interrupted transfers can explicitly be discarded. After 24 hours
they are cleaned up upon next request from this client. Resumption after restart is currently not offered.
During transfer/download/check, the server is reported as needed. An aborted upload blocks for at most
three minutes after its last section.

Restoration downloads the archive, checks its SHA-256 and creates a new folder. Existing targets are rejected.
Errors may leave an incomplete state in the new target; this is not confirmed as a successful restore.
No automatic deletion of older complete states, at most
500 states per client; older states to be archived administratively if needed.

Scope: files, empty directories and file modification times. Linux creates
files under the current user with restricted own permissions.
No full takeover of ACLs, owner IDs, hardlinks, symlinks,
special files or Windows registry. Subfolders on separate Linux mounts and
Windows reparse points are omitted. NTFS alternate streams are not
backed up. This is not a bootable system image and no replacement for the
existing live/migration tool. Windows may reject Linux filenames.

## Server Backups: Administrator Only

"Server Backup (Administrator)" opens the existing backup and recovery page in the browser via a new manager login. There, server backups, status, external full backup, and available restore functions remain accessible.
The administrator password is neither stored on the client nor in the JSON profile. The server routes do not accept normal client tokens. A local administrator account on the client does not grant manager administrator rights.

## Private HTTPS

First, configure private hostname and certificate under Settings → HTTPS Access in Manager. Then download or import a new client profile.
This additionally contains the public root certificate, SHA-256 fingerprint, hostname, and port. It never contains the private key of the certificate.

Open "Private HTTPS" on the client. Compare the fingerprint with the Manager settings page and explicitly confirm import.
Optionally specify a fixed server IP for a marked hosts entry. Leave blank if local DNS already resolves the name. Existing foreign hostname entries are not overwritten. Linux requests administrator approval via Polkit; Windows via UAC.The import applies system-wide and trusts the private certificate authority also for other names signed by it. Trust only self-managed root certificates.

Subsequently, verify the HTTPS connection and adopt the new manager address.
Verification does not disable certificate validation. An HTTP address is not automatically switched; HTTP backups transmit data unencrypted.
"Remove own setup" removes entries managed by the assistant. This can interrupt existing HTTPS connections. Browsers that use their own trust store may require a restart or additional certificate setup. An installation error might leave partial changes behind; then check the message and run or remove the setup again.

## Platform Limits

Linux: GTK 3, Ayatana status icon, OpenSSL, CA tools, and Polkit are included as package dependencies. Start menu entry under Internet/Network.
Windows 10/11: .NET Framework 4.8, without Python; EXE is not digitally signed. Windows build and file transfer tests are automated; real Windows UAC and certificate store tests require a Windows computer. Windows remains experimental until then.

Private HTTPS profiles also support short hostnames without domain suffix.
Public certificates still require a full domain name.
