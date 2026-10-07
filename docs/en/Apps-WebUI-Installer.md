# Open WebUI and App Installer

Open WebUI (Ollama interface) is integrated as an app via `open_webui`. The manager reads the existing container `open-webui`, detects its state and image, checks the WebUI on port 3000, and displays the local Ollama service under Health. The existing single-container installation and its volume remain unchanged.

## Interface

- `/apps`: Open WebUI in the existing app cards; "Open WebUI" and
  "Installer" per app.
- `/apps/open_webui`: regular app detail view with status and health.
- `/apps/installers`: all ten app profiles including currently uninstalled apps. Uninstalled apps remain hidden from the main overview according to existing visibility settings unless explicitly shown.
- `/apps/<id>/installer`: installation type, target, inventory/port check, WebUI address,
  and ZIP download. Loopback links are rewritten to the server name in the current browser
  Nextcloud opens `/nextcloud/` instead of `status.php`.
- `/apps/installers/new`: register a new single-container app with image, ports, and persistent data path. The app manager and installer are immediately available without restart.

Existing WebUI addresses are inherited from the app profiles. Only HTTP(S) without embedded credentials and local module paths are allowed; open links with `noopener`.
Profile changes and installation starts are POST actions with CSRF protection. Custom profiles and WebUI URLs
are stored atomically in `/var/lib/server-manager/app-installers/profiles.json`.
The selection of an image is a trust decision by the administrator.

## Executable Installer Packages

ZIP contains `installer.py`, `profile.json`, `README.txt`, `SHA256SUMS` and optionally
local program files. Extract and first run `python3 installer.py --check`.
Only then install via `sudo python3 installer.py --install --bind <Server-IPv4>`. Containers and ComfyUI loopback do not use a bind address without one. Packages are not executed by calling a website, preview, or download. Explicit installation via the button runs as a visible background job.

The target must not already exist. Existing services, containers, app paths,
port assignments, and symlinks in the target path prevent re-installation. Installations
do not replace existing data. Restoration is performed via the existing
backup/restore functions. After errors, new files are retained for diagnosis;
nothing is automatically deleted. A completion marker is written only after successful execution.

### Profiles

- Open WebUI: official image, persistent data, enabled login, newly generated
  WebUI key and Ollama connection via `host.docker.internal`. Ollama must be reachable there;
  its bind address and firewall rules are not changed.
- Immich: associated Compose/ENV files from the same official release; own library/database
  and a random database password.
- Paperless-ngx: app, PostgreSQL, and Redis; persistent data and random keys.
  Admin user created interactively after installation via `createsuperuser`.
- Stirling PDF: official image with persistent configuration and working directories.
- Nextcloud: new Docker installation with MariaDB. No migration of the existing native
  Apache installation. Initial setup is performed afterward in the WebUI.
- ComfyUI: official Git repository, venv, CPU PyTorch, and service as user
  `comfyui`. GPU drivers, CUDA/ROCm, and models are set up separately.
- Tvheadend: installation from already configured APT sources. One package candidate
  must be present; no external package repositories will be added without consent.
- Mounts/Shares: `cifs-utils` and `nfs-common`; no changes to `/etc/fstab`.
- OSCam: local binary for the same architecture, new minimal WebIF configuration
  with a random password and initial access limited to localhost only. No reader/user data included.
- Server Manager: code bootstrap from versioned repository files plus current installer modules, venv and a systemd service with a new session key. Host services, module configuration and data require their own setup or backups. This does not clone the complete production server.

The target platform for packages is Debian 13 / Python 3.13. Docker profiles require the Docker
Engine with Compose; this foundation will not be installed automatically via an external shell
script. Tags/upstream releases are loaded at installation time.
OSCam bundles are additionally architecture- and runtime-dependent. For Server Manager
and OSCam, their existing service bindings apply; `--bind` does not alter these.

## Checks

`tests/test_app_installers.py`: host/IPv6 link resolution, URL/profile validation, CSRF,
integrity protection, port/symlink check, package content, dynamic registration, Docker
status, persistent Compose data, key generation, and simulated execution.
No test installation replaces a running app. A fresh complete installation on a separate Debian system is not claimed as tested.

Sources for the templates:
- https://docs.openwebui.com/getting-started/quick-start/
- https://docs.immich.app/install/docker-compose/
- https://docs.paperless-ngx.com/setup/
- https://docs.stirlingpdf.com/Installation/Docker%20Install/
- https://hub.docker.com/_/nextcloud
- https://docs.comfy.org/installation/manual_install


## Direct Installation in the Apps Module

The installer now starts missing apps via "Install on this server now".
Existing apps receive no installation button. The server-side inventory check is performed again
on POST and immediately before execution.
A separate systemd job runs the installer and survives a restart of the Server Manager.
Status and logs appear on the jobs page.
At most one installation runs simultaneously; during this time, a sleep blocker is active.
Failed or interrupted jobs are explicitly indicated; existing data remains intact. Downloads remain as an additional option.
The additional WebUI configuration in the installer has been removed; JSON links have been
removed from app cards and header actions; the diagnostic API remains available.

## Open-WebUI Updates

The version check reads `/api/version` of the running app and compares it with the
latest official stable release. A Docker tag like `main` is not a version number.
Network errors are displayed as "Not verifiable" along with the cause.

The confirmed live run uses the existing prepare/backup mechanism.
For the detected single container with exactly one local named data volume
and bridge network, a dedicated update path is implemented:

1. Check container, available capacity, and exclusive use of the volume.
2. Fully download the specific stable image; no interruption yet.
3. Stop the old container and fully copy the data volume via rsync.
4. Keep the old container with disabled autostart as a fallback snapshot.
5. Start the new container with previous user settings and the data copy.
   Old image default values are not copied over to new image defaults.
6. Check expected app version and Docker health status.
7. In case of an error, remove the new container and start the original container
   with unchanged original volume and original restart policy.

Other mount/network variants are explicitly blocked before any change.
Protected transaction data resides under
`/var/lib/server-manager/open-webui-updates/<id>/` (including original configuration,
n readable only by root). They are not displayed in public update logs.
Upon success, the old container and old data volume remain preserved as a fallback state.
The regular app backups subsequently follow the volume of the current container.
a sleep blocker is active throughout the entire update.

The existing app update engine executes the process; an interruption during the switch
requires inspection of the transaction file and possibly manual restart of the received original container. There is no automatic cleanup of fallback states or data volumes.
