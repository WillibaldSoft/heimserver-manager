# TV / Tvheadend RTC-Aufnahmen

## Ziel

Kommende Tvheadend-Aufnahmen werden als RTC-Wakeup-Planung in Server-Control eingetragen.

## Funktionen

- nächste kommende Aufnahme lesen
- Wake-Zeit berechnen: Aufnahmebeginn minus Vorlauf
- Eintrag in `server_control_rtc_events`
- Anzeige unter `/tv/rtc`
- API unter `/api/tv/rtc`

## Noch nicht aktiv

Diese Phase setzt noch keinen echten Kernel-Wakealarm und fährt den Server nicht herunter.

Das folgt in der Sleep-/Power-Phase.

## Datenfluss

```text
Tvheadend upcoming DVR
 -> nächster Start
 -> Wake-Zeit
 -> server_control_rtc_events
 -> später rtcwake / wakealarm
```
