# TV / Tvheadend

## Goal

The TV module is built as its own manager plugin.

## Features in Phase TV

- `/tv`
- `/tv/status`
- `/tv/streams`
- `/tv/recordings`
- `/tv/upcoming`
- `/api/tv/status`

## Database Tables

### tvheadend_status

Key/Value status values:

- `tvheadend_service`
- `streams_active`
- `recordings_active`
- `next_recording`

### tvheadend_events

General TV Events:

- active streams
- active recordings
- upcoming recordings
- completed recordings
- RTC-relevant recordings

## No private data in the code

Tvheadend credentials will be loaded later via configuration.

Planned:

```text
/etc/server-manager/tvheadend.conf
/etc/server-manager/secrets/tvheadend.token
```

## Integration with Server Control

Later phases:

1. Active streams generate server control sleep blockers.
2. Active recordings generate server control sleep blockers.
3. Upcoming recordings generate RTC wakeup events.
4. After recording ends, the server control may go to sleep or shut down again.

## V11 features that will be adopted later

- EPG with channel filter
- EPG search
- Recording
- Series recording
- Calendar instead of recordings as main view
- OSCam separate
- DVB Digital Devices diagnostics
