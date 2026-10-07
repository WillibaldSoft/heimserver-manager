# Sleep Engine

## Ziel

Die Sleep-Engine ist die zentrale Ausführungs- und Diagnoseebene für:

- Sleep-Check
- Suspend
- Hibernate
- Poweroff
- spätere Automatik

## Datenquelle

Die Entscheidung kommt aus Server-Control:

```text
modules.server_control.api.status()
```

Server-Control sammelt Blocker aus:

- Clients
- Tvheadend Streams
- Tvheadend Aufnahmen
- RTC
- Zeitplänen
- manuellen Sperren

## Sicherheitsmodell

In dieser Phase wird nichts automatisch ausgeführt.

Manuelle Aktionen unter `/sleep/actions` sind zunächst Dry-Run.

Echtes Ausführen benötigt:

- Checkbox `wirklich ausführen`
- keine Blocker oder Checkbox `Blocker ignorieren`

## API

```text
GET /api/sleep/status
```

## UI

```text
/sleep
/sleep/check
/sleep/actions
```
