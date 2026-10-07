# TV / Tvheadend Phase 2

## Goal

Actual subpages for Tvheadend:

- Status
- Streams
- Recordings
- Upcoming recordings
- EPG

## Foundation

The module uses the central API layer from `modules/tvheadend/api.py` and formatting from `formatter.py`/`models.py`.

## Server-Control Integration

In the next phase, active streams and ongoing recordings will be reported to Server-Control as blockers.
