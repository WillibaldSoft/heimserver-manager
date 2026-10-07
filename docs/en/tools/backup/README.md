# Server and Client Backup

The package does not contain access credentials. `client.json` contains the original
computer name, the assigned server user, and their UID/GID for comparison.
Changes to accounts, groups, UID or GID do not occur automatically.

## Prerequisites

Linux with Python 3, GNU tar, findmnt. For SMB on desktop: gio and gvfs-backends;
for Live-USB with root: cifs-utils. The SMB user requires access to Backup.
The archive contains private files and possibly keys. Check SMB subfolder permissions in
the Server Manager; the backup area must not be generally readable.

## Back up from Client at Any Time

Extract the package and run `sh install-client.sh` as a normal user.
Then open it in the application menu "Server Backup – Back Up Now". SMB access will
be requested if needed. No permanent root service runs. The start backs up your own home;
it does not create a full system image or consistent backup of running databases.
Close applications with important open files beforehand.
Errors or modified files during reading do not result in a complete state.

Alternatively, in the extracted folder:

    python3 backup_client.py identity
    python3 backup_client.py backup

The last command connects the configured SMB share. For an already connected share `--repository /pfad/zur/Backup-Freigabe`, append.
The storage is linux-client-backup/COMPUTER/USER/TIMESTAMP.
Each state is its own complete archive; old states are not deleted.
If the target is full, a `.partial-…` folder remains, no valid backup snapshot.

## Live-USB

Select the original computer: load the appropriate package in the Server Manager.
Take the Python tool and client.json together on the stick. First mount the installed
Linux via disk management. Example:

sudo python3 backup_client.py backup --source /mnt/linux/home/exampleuser
sudo python3 backup_client.py list
sudo python3 backup_client.py verify --snapshot /mnt/server-manager-backup/linux-client-backup/RECHNER/exampleuser/STAND
sudo python3 backup_client.py restore --snapshot /mnt/server-manager-backup/linux-client-backup/RECHNER/exampleuser/STAND --target /mnt/linux/home/exampleuser-wiederhergestellt --preserve-ids

The restore target must be new. `--preserve-ids` retrieves the original numeric owners and ACLs and requires root. Without this option, files are assigned to the calling user and original ACLs are not preserved. Before transferring into the final home directory, check user and group IDs; additional ACL users will not be generically rewritten onto a single user.
A running user profile is not overwritten by the new tool.

SHA-256 checksums and archive paths are verified before restoration. This does not replace an authenticity signature: only use backups from trusted storage locations.
The Python tool writes SMB heartbeats every 30 seconds during its work; the Server Manager prevents scheduled sleep accordingly, but protection times out after three minutes of connection loss. The SMB share must point to the same central backup location specified in settings.
When using migration.sh directly without the Python tool, pause the sleep schedule for the duration of the work.

## Advanced V20 Migration Tool

`migration.sh` is the provided V20 template with an additional local working directory and computer separation. USB mode remains available. Example:

sudo bash migration.sh --live --source-home /mnt/linux/home/exampleuser --source-user exampleuser --client-id MEIN-PC --storage-dir /mnt/linux/backup-arbeit

The working directory must already exist and reside on a Linux filesystem.
Do not use the V20 tool directly with SMB: its loose files require POSIX permissions. The advanced V20 workflow is interactive and not identical to the Home Archive of the new client tool. For transferring the archive contents of the V20 working directory, use:

sudo python3 backup_client.py migration --live --source /mnt/linux/home/exampleuser --local-user exampleuser --workdir /mnt/linux/backup-arbeit

After exiting the V20 menu, the tool asks whether to transfer the working directory as its own migration snapshot to the server. To restore, unpack the snapshot with `restore --preserve-ids` into a new local Linux working directory and start `migration.sh --storage-dir DIESER_ORDNER --client-id MEIN-PC ...`.
Select individual V20 restoration steps there.
The template script remains a separate, not fully end-to-end tested migration tool. A server configuration archive can be extracted using `list --server SERVERNAME` anzeigen und mit `restore --server SERVERNAME --snapshot ... --target NEUER_ORDNER --preserve-ids`; it is never automatically copied over /.


## Optional: Align Client IDs with the Server

Download the package fresh in the Server Manager so that server IDs are current. On the client, first create a backup, then boot from Live USB.
Mount the installed system separately under /mnt/linux:
Preview:

sudo python3 identity_sync.py --target-root /mnt/linux --local-user exampleuser

Apply after verification and existing backup:

    sudo python3 identity_sync.py --target-root /mnt/linux --local-user exampleuser --apply

Additionally, ANGLEICHEN must be entered. The tool checks UID/GID collisions and shared primary groups. It adjusts the selected user's private primary group, file owner, and numeric ACL entries. Passwords and additional groups are not synchronized.
Backups of passwd/group, ACLs, and a file list are stored in the offline system under /var/lib/server-manager-id-before-ZEIT. In case of an detected error, the tool attempts to reset; this does not protect against power outages.
Root and Home must reside on the same filesystem in this first version. Further mounted filesystems are explicitly rejected so that old IDs do not remain unnoticed there. Online renumbering is disabled.
