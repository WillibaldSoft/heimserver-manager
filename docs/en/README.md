# Heimserver Manager · Home Server Manager

**Web-based home server administration for Debian: applications, backups, file sharing, KVM and energy-saving server operation.**

**BETA:** A development version for testing. Features may contain errors or change. Back up your data before installation and updates. Debian 13 is the primary target; Mint 22.x and the Windows client are additionally experimental.

[Deutsch](../../README.md) · [Download ZIP & DEB](https://github.com/WillibaldSoft/heimserver-manager/releases) · [Installation](RELEASE_INSTALLATION.txt) · [Full feature overview](Home_Server_Manager_Features.txt) · [Questions & bug reports](https://github.com/WillibaldSoft/heimserver-manager/issues)

A self-hosted home server dashboard for Debian Linux and homelabs. Manage applications, backups and recovery, Samba/SMB and NFS shares, users, KVM/libvirt virtual machines, DynDNS, and Wake-on-LAN with presence-based sleep control. German and English web interface.

## See the interface

[Screenshot gallery: seven key areas](SCREENSHOTS.md)

<details>
<summary>Show dashboard (anonymized)</summary>

![Home Server Manager – anonymized dashboard](../screenshots/01-uebersicht.jpg)

</details>

## Who is it for?

People running a Linux home server or homelab who want a shared web interface for services, storage and backups. The interface supports desktop and smartphone use. The Manager complements the existing Linux system; available functions depend on installed services, hardware and configuration.

## Features

| Area | Capabilities |
| --- | --- |
| Apps & updates | Install and manage applications; APT packages, Docker and app-specific update checks. Integrations include Nextcloud, Immich, Jellyfin, Plex, Pi-hole, Open WebUI and Ollama. |
| Backup & recovery | Server and application backups, a daily incremental backup chain, external aggregate backups and client backup. Coverage and restore procedures depend on the selected profile. |
| Shares & users | Samba/SMB and NFS, local users and groups, access rights, separate Linux/SMB passwords and administrator-protected sudo membership. |
| Virtual machines | KVM/libvirt: create and import VMs, start/stop, back up and restore; download and upload backups. |
| Sleep & wake | Schedules, presence detection, client sleep blockers, Wake-on-LAN and an optional power/recovery API. |
| Network & HTTPS | LAN overview, DynDNS, targets and services, redirects/reverse proxy and certificate status. |
| Storage & alerts | Mount points, disk status, SMART checks and ntfy notifications. |
| Media & data | TVheadend EPG and recordings, photo tools, downloads/uploads and a scanner API for Home Assistant. |
| Client agents | Linux DEB and experimental Windows EXE: report server demand, wake the server, personal profiles and backup functions. Capabilities differ by platform. |

[All features and limitations](Home_Server_Manager_Features.txt) · [Version history](Home_Server_Manager_Version_History.txt)

## Download and get started

1. Open the desired beta version under **[Releases](https://github.com/WillibaldSoft/heimserver-manager/releases)** and expand **Assets**.
2. For initial installation, download the matching **Debian_Komplett.zip** or **Mint_Komplett.zip**. It includes the DEB, `install_deb.sh`, installation instructions, licenses and documentation.
3. Read the installation instructions, back up existing data and run the installer on the target machine. Install additional applications in the Manager as needed.
4. Update an existing package installation with the matching **DEB** via **Settings → Update Manager**. Manual source installations require a planned migration.

**“Code → Download ZIP” contains source code. Installable packages are under Releases.** Checksums are provided with the downloads and inside each complete bundle.

| Platform | Status |
| --- | --- |
| Debian 13 | Primary platform, beta |
| Linux Mint 22.x | Separate experimental package; not approved for production |
| Linux/Windows client | Separate client packages; Windows experimental |

## Documentation and contributions

- [Documentation index](DOCUMENTATION.md) and [German documentation](../../README.md)
- [Platform limitations](PLATTFORMEN.md) and [release builds](GITHUB_RELEASE.md)
- Use [Issues](https://github.com/WillibaldSoft/heimserver-manager/issues) for bugs, questions and feature requests. Include the version, operating system and reproducible steps; remove passwords, tokens, private domains and personal data from logs.
- Code and translation improvements via pull requests are welcome. Star the project to find it again later.

## Technology and license

Python/Flask web interface with Linux system services. Service: `server-manager.service`; program: `/opt/server-manager`; configuration: `/etc/server-manager`; runtime data: `/var/lib/server-manager`. Release build: `python3 tools/build_release.py`; version source: `version.py`.

Copyright (C) 2026 Andreas Willibald. Original project components: **GPL-3.0-or-later**. [License](../../LICENSE) · [License notice](LICENSE_NOTICE.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
