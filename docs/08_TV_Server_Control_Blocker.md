# Tvheadend Server-Control Blocker

Tvheadend-Ereignisse verhindern Schlaf/Ausschalten.

## Blocker

- aktive Streams
- laufende Aufnahmen
- kommende Aufnahme innerhalb des Vorlauf-Fensters

## Einstellung

Standard:

```text
tv_recording_prewake_minutes = 30
```

Gespeichert in:

```text
tvheadend_settings
```

## Wirkung

Wenn ein Blocker aktiv ist, liefert Server-Control:

```text
may_sleep=false
```
