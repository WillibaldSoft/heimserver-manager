# Heimserver Manager / Home Server Manager

**BETA – development version for testing.** Features may contain errors or change. Back up your data before installation or updates. Debian 13 is the primary target; Mint 22.x and the Windows client are additionally experimental.

Web interface for managing applications, services, storage, shares and other server functions.

The product version is available exclusively under **Settings → Info**. Version source for new releases: `version.py`.

Active installation:

- Service: `server-manager.service`
- Program: `/opt/server-manager`
- Runtime data: `/var/lib/server-manager`
- Database: `/var/lib/server-manager/server-manager.sqlite3`
- Configuration: `/etc/server-manager`

Release packages: `python3 tools/build_release.py`. Details under [GitHub-Releases](GITHUB_RELEASE.md) and [Installation](RELEASE_INSTALLATION.txt).
The DEB contains the manager; optional additional programs are installed via APT.

## License

Copyright (C) 2026 Andreas Willibald. Own project components are under
**GNU GPL Version 3 or newer (`GPL-3.0-or-later`)**.
See [License Notice](LICENSE_NOTICE.md), [License Text](../../LICENSE) and
[Third-Party Components](THIRD_PARTY_NOTICES.md).

## Experimental Mint Development
This branch extends the Debian base with separate, mutually locked platform packages. Support limits and test requirements are documented in [PLATTFORMEN.md](PLATTFORMEN.md)]. No Mint production release yet.

## Documentation / Documentation

[German documentation overview ](DOCUMENTATION.md) · [English documentation](README.md)
