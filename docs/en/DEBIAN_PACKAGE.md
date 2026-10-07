# Server Manager as Debian Package

## Installation on a New Server

Debian 13 with systemd, network access to the Debian package repositories and administrative privileges:

    sudo apt install ./Server_Manager.deb

APT installs the required system and Python packages, including Apache and HTTPS tools. The package starts one Waitress process with eight threads as `server-manager.service` on internal port 9877, bound exclusively to 127.0.0.1. The service runs as root because management functions handle system services, disks and users. Additional applications such as Nextcloud, MariaDB, Samba or Docker are not installed automatically.

The installer displays HTTPS addresses using the hostname and server IP. Import the public root certificate on clients after verifying its fingerprint. Initial login: user ADMIN, password ADMIN. Then set a personal password under Settings → Access and check Server & Module Paths. Automatic sleep actions are disabled in a new data store. See RELEASE_INSTALLATION.txt for details and troubleshooting.

Program: `/opt/server-manager`, Settings: `/etc/server-manager`, Database/Status: `/var/lib/server-manager`, Python Cache: `/var/cache/server-manager`. The service port can be adjusted in `/etc/server-manager/server-manager.env`. Afterwards run `sudo systemctl restart server-manager`.

## Updates and Removal

    sudo apt install ./Server_Manager.deb
    sudo apt remove server-manager

The package contains neither existing credentials nor databases, certificates, DynDNS profiles, app configurations, or backups. The admin account and configuration are initialized only if files are missing. Updates as well as remove/purge preserve the generated settings and status data. Create a backup of this data before an update.

An existing manual installation under `/opt/server-manager` is detected on the first package installation attempt and not overwritten. Your migration requires separate handling. The package was not installed on the current production server.

## Build Package Yourself

    python3 tools/build_deb.py --output dist/Server_Manager.deb

Building requires Python 3 and `dpkg-deb`; neither root nor network access is needed. Before building, set the full package version including its Debian revision in `version.py` and in the German and English documentation. A conflicting `--revision` value is rejected. Newly published source changes require a higher revision. `SOURCE_DATE_EPOCH` sets the reproducible timestamp (default 0).

The Builder creates a SHA-256 checksum file. A whitelist restricts the package contents to source code, web resources, helper scripts, and documentation. Runtime data, backups, hidden directories, symlinks, and secret files are excluded. The package includes `package-manifest.json` with the source code checksums.

Module-specific external tools and existing external helper scripts are not copied from the running server. Set up additional services via their respective module installers. Existing Git update functions do not replace Debian package updates.

## Port selection starting with package revision 0.12-2

With `sudo apt install ./Server_Manager.deb`, debconf asks for the desired TCP port (1–65535, default 9877). Ports already in use are rejected; the running Manager’s own port is allowed during an update. The chosen port is permanently saved in `/etc/server-manager/server-manager.env`. Updates use the existing port as the default.

Pre-configure for unattended first installation on a new server:

    printf 'server-manager server-manager/port string 9988\n' | sudo debconf-set-selections
    sudo DEBIAN_FRONTEND=noninteractive apt install ./Server_Manager.deb

Without a free port specification, the package configuration reports an error instead of displacing another service. Use the same approach with graphical installation programs that lack an input dialog. Subsequently: change `sudo dpkg-reconfigure server-manager` or Settings → Server & Module Paths → Webport. The interface checks the port, stores it, and restarts only the server manager; it then displays a link to the new address.

Internal backup/update timers read the central port file even if older units still contain `--port 9877`. A login Fail2ban rule created by the Web & Security module is adjusted and checked. External login rules must be manually verified before a port change. Your own router, firewall, and reverse proxy rules are to be adapted separately.
