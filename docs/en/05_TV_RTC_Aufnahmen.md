# TV / Tvheadend RTC Recordings

## Goal

Upcoming Tvheadend recordings are registered in Server-Control as RTC wakeup schedules.

## Functions

- read the next upcoming recording
- calculate Wake time: recording start minus lead-in period
- entry in `server_control_rtc_events`
- display under `/tv/rtc`
- API at `/api/tv/rtc`

## Not yet active

This phase does not set a real kernel wake alarm and does not shut down the server.

That follows in the Sleep/Power phase.

## Data Flow

```text
Tvheadend upcoming DVR
 -> nächster Start
 -> Wake-Zeit
 -> server_control_rtc_events
 -> später rtcwake / wakealarm
```
