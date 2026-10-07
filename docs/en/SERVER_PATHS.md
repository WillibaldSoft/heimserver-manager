# Server & Module Paths

Under Settings → Server & Module Paths, data areas, app installation locations, backups, network and storage names are maintained. The scanner keeps its own configuration; App web addresses continue to be managed under Apps.

## Activation

The page writes a validated pre-recording to `server.pending.json` in the configuration folder. The running web process and newly started workers continue using the active snapshot. Only the core start activates the pre-recording atomically after `server.json`; `server.previous.json` contains the previous snapshot. The restart button checks ongoing module jobs. For externally initiated tasks, adjust the maintenance window yourself. No path change displaces user data.

Backup, restore, and update paths uniformly originate from this configuration. Existing settings from `app_manager.json` are adopted as initial values. The old general settings page links to central maintenance.

## Data Migration

The separate migration utility checks source and target folders and creates rsync preview, copy, and comparison commands. All write-enabled apps stop; storage devices and available space are checked; data including owners/ACLs is copied and compared. Afterwards, app services, Docker mounts, VM definitions, and paths are adjusted. The source remains intact and is not automatically deleted. Adjusting app paths in the manager does not reconfigure existing applications.

Photo lab history, validation shares, repairs, and schedules are bound to the image inventory. The first inventory uses the existing database unchanged. Other main folders receive a separate database and their own status folders. Rollback restores the previous history again. Even after copying the image inventory, it must be re-validated at the new location.

## Installation on other servers

- Program location is determined from the source code path.
- `SERVER_MANAGER_CONFIG`: configuration directory, default `/etc/server-manager`.
- `SERVER_MANAGER_STATE`: internal status folder, default `/var/lib/server-manager`.
- `SERVER_MANAGER_DB`: optional core database, otherwise in the status folder.
- `SERVER_MANAGER_PORT`: HTTP port, default 9877.

These variables belong to the systemd environment of the server manager. App installer, scanner, and model workers take them over. External services such as the standalone DynDNS timer require the same directory variables in their own environment. sudoers rules for privileged helpers must point to the actual program location; they are not changed by a path setting.

Default values preserve the existing server. On a new host, network, local users, and data directories must be adjusted before production actions. Existing native app update commands continue to require paths without spaces; central validation enforces this. File browsers and general data paths support spaces. Permission checks in the interface occur as Server Manager, not as the respective app service user.
