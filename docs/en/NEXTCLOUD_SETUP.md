# Guided Nextcloud Reinstallation

Apps → Nextcloud → Installer queries Native/Docker, Domain, Email, Admin Name/Password, application and separate data folder as well as Docker port. Defaults come from Server & Module Paths. The current existing installation is not converted. On the existing server, occupied paths or detected Nextcloud containers block reinstallation.

The complete installer is designed for Debian 13. It supplements Apache/Certbot as well as native PHP, MariaDB, Redis; in Docker it creates a missing Debian Docker engine along with Compose and generates Nextcloud/MariaDB/Redis containers. An existing foreign Docker installation requires a compatible Compose-v2 plugin. Admin and database are set up, domain and proxy trust configured, a five-minute timer activated, and Certbot renewal enabled. Finally, OCC and HTTPS are checked. The data folder must be new and located outside the application folder. Existing data is not overwritten.

DNS and router releases for ports 80/443 must match beforehand. SMTP, external storage, Talk and additional apps are separate configurations. Native uses a SHA-256 verified official current Nextcloud archive; Docker the official stable-apache image with MariaDB 11.4. No reinstallation was performed on the existing production server. A real complete reinstallation run on an empty target server is still pending.

The preview does not show passwords. Temporary entries are stored in protected server state, valid for a maximum of ten minutes; old previews are cleaned up upon the next call. Job credentials are removed after the installation attempt. Docker database and initial admin secrets remain as root-protected files during installation because the Compose configuration uses them. Download packages do not contain passwords; the password is queried hidden in the terminal on the target server.

The installation only changes specifically created app paths and website configurations, but installs system-wide dependencies. It is not a transactional operating system deployment. In case of errors, already generated files/packages remain for diagnosis; existing target paths block blind repetition. A failed certificate or completion test is reported as an error.

Official basics:
- https://docs.nextcloud.com/server/stable/admin_manual/installation/system_requirements.html
- https://docs.nextcloud.com/server/stable/admin_manual/installation/command_line_installation.html
- https://github.com/nextcloud/docker


## Shared Nextcloud Map

The existing native installation retains its manager class, routes and backup history. The map indicates the installation type. A Docker installation set up with the installer receives the same map designation but a separate internal identifier `nextcloud_docker` so that backups and actions are never confused with the native installation. If both exist, separate maps "Nextcloud · Native" and "Nextcloud · Docker" appear.

The installer continues to offer Native and Docker options for a new installation; an existing setup is not migrated or overwritten. Unknown externally installed Docker stacks are not automatically adopted.

Docker uses OCC for operational readiness. Native Apache, database, and updater commands are never used for this purpose. The native backup, restore, and update preparation remain unchanged.

## Docker Backups and Updates

Under Manage Apps, "Nextcloud · Docker" is also available as an uninstalled option. Without installation, no active app card is displayed and no Docker updates or backups run. The installer prefers Docker; a separate instance requires its own domain, free ports, and folders. New Docker installations receive their own Apache and cron files. Existing native profiles and web addresses are not overwritten.

The Compose stack set up by the Manager with services app, db (MariaDB), and redis is supported. Markers, project membership, active mounts, and Nextcloud database configuration are checked before changes. Other stacks are not automatically modified.

System and full backups include a complete logical dump of the Nextcloud database including routines, events, and triggers. The dump is authenticated in the database container using its secret there, compressed, and secured with SHA-256. Passwords do not enter host arguments or logs. Full backups additionally contain program, configuration, secrets, and the separate user data folder; the running MariaDB data directory is not backed up as a file copy. The profile data backup continues to include only files.

For consistent file/SQL backups, maintenance mode is enabled and only the Docker app container is stopped. After the backup, even in case of an exception, it is restarted again and maintenance mode disabled. During this time, this Nextcloud instance is not reachable. Parallel backup/update jobs for the same instance are locked. A power outage/process termination may require manual verification of the container and maintenance mode.

Check Update compares platform-specific image digests in the official Nextcloud repository. Updates within the current major version are supported; no automatic major version changes or downgrades occur. An approved live run requires bound backup preparation and creates a new full backup immediately before the switch. The target image is fixed by digest, its actual version checked, and recreated exclusively with `app` using `--no-deps`. MariaDB and Redis are not updated. OCC version and reachability are then checked. After a possible database migration, no automatic image downgrade occurs: in case of errors, the full backup remains available for conscious joint file/SQL restore. Automatic Docker SQL restore is not part of this process.

Basics: https://github.com/nextcloud/docker and
https://docs.nextcloud.com/server/latest/admin_manual/maintenance/backup.html

## Nextcloud Wake

- Nextcloud Wake: save an inactive preparation without changing services, DNS, router or certificates. Gateway installation remains a separate later action.
- Configurable status path supports Nextcloud in subdirectories; DAV requests and existing URLs are preserved. A blocker profile is required before installation; WebSockets remain unsupported.

### Diagnosing wake and grace-period causes
The gateway records request IDs, pseudonymized source addresses, coarse client/path categories, recovery calls and results in the systemd journal. No complete URLs, headers, tokens or cookies. At most 120 events per minute; suppressed events are counted later. Client categories rely on unverified User-Agent claims. Sleep logs identify current blockers or an awake schedule when the grace period resets. Additional reset records are retained for seven days. Gateway journal retention follows system-wide journald settings. Earlier causes cannot be reconstructed retroactively.
