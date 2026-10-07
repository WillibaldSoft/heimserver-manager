# TV / Tvheadend Phase 1

Neuaufbau des Tvheadend-Moduls als saubere Modulstruktur.

## Dateien

- `config.py` liest `/etc/server-manager/tvheadend.conf`
- `api.py` kapselt Tvheadend HTTP/API
- `formatter.py` normalisiert Sprachfelder und Zeiten
- `models.py` normalisiert Streams, Aufnahmen und EPG
- `cache.py` einfache Modul-Cache-Basis
- `plugin.py` stellt WebUI und API bereit

## Keine privaten Daten im Code

Zugangsdaten liegen ausschliesslich in:

```text
/etc/server-manager/tvheadend.conf
```

## Wichtige Seiten

- `/tv`
- `/tv/status`
- `/tv/streams`
- `/tv/recordings`
- `/tv/upcoming`
- `/tv/epg`
- `/api/tv/status`
