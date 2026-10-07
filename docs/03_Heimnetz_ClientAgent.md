# Manager Phase 3 - Heimnetz und Client-Agent

## Ziel

Aufbau der Manager-Heimnetz- und Client-Agent-Basis.

## Funktionen

- Heimnetzscan
- Heimnetzgerät als Client übernehmen
- Client-Agent Tabelle
- Token-Erzeugung
- Installer als Hostname.sh
- Betriebsarten:
  - auto
  - connected
  - release-only
  - disabled
- Bedarfsmeldung an Server-Control:
  - need-server
  - release-server

## Abhängigkeiten

- Server-Control Phase 2
- client_agents Tabelle
- home_clients Tabelle
- Server-Control Blocker API

## Sicherheitsziel

Keine privaten Daten im Code.
Tokens nur in lokaler Datenbank oder Client-Konfigurationsdatei.

## Nächste Schritte

1. Phase 3 Skript installieren.
2. /heimnetz prüfen.
3. Gerät aus Heimnetz als Client übernehmen.
4. Installer herunterladen.
5. Client installieren.
6. need-server/release-server testen.
