# TV / Tvheadend Phase 2

## Ziel

Echte Unterseiten fuer Tvheadend:

- Status
- Streams
- Aufnahmen
- kommende Aufnahmen
- EPG

## Grundlage

Das Modul nutzt die zentrale API-Schicht aus `modules/tvheadend/api.py`
und die Formatierung aus `formatter.py`/`models.py`.

## Server-Control Integration

In der naechsten Phase werden aktive Streams und laufende Aufnahmen als
Blocker an Server-Control gemeldet.
