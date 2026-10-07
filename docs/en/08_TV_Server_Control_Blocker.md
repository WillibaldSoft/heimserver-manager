# Tvheadend Server-Control Blocker

Tvheadend events prevent sleep/shutdown.

## Blockers

- active streams
- ongoing recordings
- upcoming recording within the lead-in window

## Setting

Default:

```text
tv_recording_prewake_minutes = 30
```

Stored in:

```text
tvheadend_settings
```

## Effect

When a blocker is active, Server-Control provides:

```text
may_sleep=false
```
