# Server Control Modul Manager

## Zweck

Das Server-Control-Modul entscheidet, ob der Server wach bleiben muss oder schlafen/ausschalten darf.

Es ist die zentrale Stelle fuer:

- Zeitplaene
- Client-Agenten
- Tvheadend Streams
- Tvheadend Aufnahmen
- RTC-Wakeup
- manuelle Sperren
- spaetere externe Blocker

## Architektur

```text
modules/server_control/
- state.py       DB-Tabellen, Status, Blocker, Aktionen
- policy.py      Entscheidung: schlafen erlaubt?
- clients.py     Client-Agenten als Blocker
- tvheadend.py   Tvheadend Streams/Aufnahmen
- rtc.py         RTC-Wakeup Planung
- api.py         gemeinsame Statusfunktion
```

## Datenbanktabellen

### server_control_status

Key/Value Statuswerte.

### server_control_blockers

Aktive Gruende, warum der Server wach bleiben muss.

Quellen:

```text
client
tvheadend
schedule
manual
rtc
system
```

### server_control_schedules

Zeitplaene fuer Wach-/Schlaf-/Ausschaltlogik.

### server_control_rtc_events

Geplante Wakeups, z. B. fuer Tvheadend-Aufnahmen.

### server_control_actions

Audit-Log fuer Aktionen:

```text
suspend
hibernate
poweroff
rtc-set
manual-release
```

## Entscheidungslogik

Der Server darf schlafen oder ausgeschaltet werden, wenn keine aktiven Blocker existieren.

Blocker sind:

- Client benoetigt Server
- SSH/NFS/SMB Bedarf ueber Client-Agent
- Tvheadend Stream aktiv
- Tvheadend Aufnahme aktiv
- Aufnahme startet bald
- Zeitplan verlangt wach bleiben
- manuelle Sperre aktiv

## API

```text
GET /api/server-control/status
```

## WebUI

```text
/server-control
```

## Phase 2 Status

Dieses Modul ist zunaechst ein Skeleton mit Datenbank, API, UI und Doku.
