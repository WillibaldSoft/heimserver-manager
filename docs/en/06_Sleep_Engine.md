# Sleep Engine

## Goal

The sleep engine is the central execution and diagnostics layer for:

- sleep check
- suspend
- hibernate
- poweroff
- future automation

## Data Source

The decision originates from Server-Control:

```text
modules.server_control.api.status()
```

Server-Control collects blockers from:

- Clients
- Tvheadend Streams
- Tvheadend Recordings
- RTC
- Schedules
- Manual locks

## Security Model

Nothing is executed automatically in this phase.

Manual actions under `/sleep/actions` are initially Dry-Run.

Actual execution requires:

- Checkbox `wirklich ausführen`
- No blockers or checkbox `Blocker ignorieren`

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
