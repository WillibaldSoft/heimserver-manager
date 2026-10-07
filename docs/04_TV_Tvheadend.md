# TV / Tvheadend

## Ziel

Das TV-Modul wird als eigenes Manager-Plugin aufgebaut.

## Funktionen in Phase TV

- `/tv`
- `/tv/status`
- `/tv/streams`
- `/tv/recordings`
- `/tv/upcoming`
- `/api/tv/status`

## Datenbanktabellen

### tvheadend_status

Key/Value Statuswerte:

- `tvheadend_service`
- `streams_active`
- `recordings_active`
- `next_recording`

### tvheadend_events

Allgemeine TV-Ereignisse:

- aktive Streams
- aktive Aufnahmen
- kommende Aufnahmen
- fertige Aufnahmen
- RTC-relevante Aufnahmen

## Keine privaten Daten im Code

Tvheadend-Zugangsdaten werden später über Konfiguration geladen.

Geplant:

```text
/etc/server-manager/tvheadend.conf
/etc/server-manager/secrets/tvheadend.token
```

## Integration mit Server-Control

Spätere Phasen:

1. Aktive Streams erzeugen Server-Control-Blocker.
2. Aktive Aufnahmen erzeugen Server-Control-Blocker.
3. Kommende Aufnahmen erzeugen RTC-Wakeup-Ereignisse.
4. Nach Aufnahmeende darf Server-Control wieder schlafen/ausschalten.

## V11-Funktionen, die später übernommen werden

- EPG mit Senderfilter
- EPG Suche
- Aufnehmen
- Serienaufnahme
- Kalender statt Recordings als Hauptansicht
- OSCam separat
- DVB Digital Devices Diagnose
