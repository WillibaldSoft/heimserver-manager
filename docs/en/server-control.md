# Server Control Module Manager

## Purpose

The server control module decides whether the server must stay awake or is allowed to sleep/shutdown.

It serves as the central point for:

- schedules
- client agents
- Tvheadend streams
- Tvheadend recordings
- RTC wakeups
- manual locks
- future external blockers

## Architecture

```text
modules/server_control/
- state.py       DB-Tabellen, Status, Blocker, Aktionen
- policy.py      Entscheidung: schlafen erlaubt?
- clients.py     Client-Agenten als Blocker
- tvheadend.py   Tvheadend Streams/Aufnahmen
- rtc.py         RTC-Wakeup Planung
- api.py         gemeinsame Statusfunktion
```

## Database Tables

### server_control_status

Key/Value status values.

### server_control_blockers

Active reasons why the server must stay awake.

Sources:

```text
client
tvheadend
schedule
manual
rtc
system
```

### server_control_schedules

Schedules for wake/sleep/shutdown logic.

### server_control_rtc_events

Planned Wakeups, e.g., for Tvheadend recordings.

### server_control_actions

Audit log for actions:

```text
suspend
hibernate
poweroff
rtc-set
manual-release
```

## Decision Logic

The server may sleep or be shut down if no active blockers exist.

Blockers are:

- Client requires Server
- SSH/NFS/SMB requirement via client agent
- Tvheadend stream active
- Tvheadend recording active
- Recording starting soon
- Schedule demands staying awake
- Manual lockout active

## API

```text
GET /api/server-control/status
```

## WebUI

```text
/server-control
```

## Phase 2 Status

This module is initially a skeleton with database, API, UI and documentation.
