# Heimserver Manager / Home Server Manager

**BETA – Entwicklungsstand zur Erprobung.** Funktionen können Fehler enthalten oder sich ändern. Vor Installation und Aktualisierung Daten sichern. Debian 13 ist die primäre Zielplattform; Mint 22.x und der Windows-Client sind zusätzlich experimentell.

[English documentation](docs/en/README.md) · [Downloads / Releases](https://github.com/WillibaldSoft/heimserver-manager/releases)

**BETA – development version for testing.** Features may contain errors or change. Back up your data before installation or updates. Debian 13 is the primary target; Mint 22.x and the Windows client are additionally experimental.

Weboberfläche zur Verwaltung von Anwendungen, Diensten, Speicher, Freigaben und weiteren Serverfunktionen.

Die Produktversion steht ausschließlich unter **Einstellungen → Info**. Versionsquelle für neue Releases: `version.py`.

Aktive Installation:

- Dienst: `server-manager.service`
- Programm: `/opt/server-manager`
- Laufzeitdaten: `/var/lib/server-manager`
- Datenbank: `/var/lib/server-manager/server-manager.sqlite3`
- Konfiguration: `/etc/server-manager`

Veröffentlichungspakete: `python3 tools/build_release.py`. Details unter
[GitHub-Releases](docs/GITHUB_RELEASE.md) und [Installation](docs/RELEASE_INSTALLATION.txt).
Die DEB enthält den Manager; optionale Zusatzprogramme werden über APT installiert.

## Lizenz

Copyright (C) 2026 Andreas Willibald. Eigene Projektbestandteile stehen unter
**GNU GPL Version 3 oder neuer (`GPL-3.0-or-later`)**.
Siehe [Lizenzhinweis](LICENSE_NOTICE.md), [Lizenztext](LICENSE) und
[Fremdkomponenten](THIRD_PARTY_NOTICES.md).

## Experimentelle Mint-Entwicklung
Dieser Zweig erweitert den Debian-Stand um getrennte, gegenseitig gesperrte
Plattformpakete. Unterstützungsgrenzen und Testanforderungen stehen in
[PLATTFORMEN.md](docs/PLATTFORMEN.md). Noch keine Mint-Produktivfreigabe.

## Dokumentation / Documentation

[Deutsche Dokumentationsübersicht](docs/DOCUMENTATION.md) · [English documentation](docs/en/README.md)
