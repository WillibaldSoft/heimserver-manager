# File Upload and Manager Package Update

Under Data → Downloads, the file selection loads a single file into the download main folder specified in Settings → Server & Module Paths. An currently open subfolder does not change this target. Maximum 512 MiB per file; existing names are not overwritten. Hidden names, path components, links, and system areas are not allowed as upload targets. The finished file is published atomically, receives the owner/group of the main folder, and mode 0640. An abort before publication leaves no visible partial file.

Under Settings → Manager Update, a DEB (maximum 256 MiB) can be uploaded. Before confirmation, package name server-manager, architecture, version, and SHA256 are displayed. Older versions are rejected; the same version can be used for reinstallation. These checks are not signature verification: only own or trusted packages install. DEB maintainer scripts run with root rights.

The confirmed job runs in its own systemd unit via existing app job management and remains active after a web service restart. Running App, Backup, APT, Scanner, and Web installation jobs block startup. APT may not remove packages and retains existing Conffiles. The package installer takes over the existing port configuration.

Beforehand, program and configuration are backed up as program-config.tar.gz and the manager SQLite database via SQLite backup. Storage: SERVER_MANAGER_STATE/manager-updates/<Upload-ID>/before-update.
The backup does not include external app data. The job keeps its log under SERVER_MANAGER_STATE/app-installers/jobs/<Job-ID>/install.log.

After installation, package status/target version, service status, and local health URL are checked. In case of errors, the job remains failed; package changes may have occurred partially. There is no automatic rollback. Before manual recovery, stop the service and check cause/log. Used packages and backups remain preserved; unused upload previews are removed after 24 hours on next upload. Previews valid for one hour; started packages cannot be sent a second time.

Integration tests simulate package installation and restart. A real upgrade on a separate Debian test machine remains the appropriate acceptance test for a new DEB version.
