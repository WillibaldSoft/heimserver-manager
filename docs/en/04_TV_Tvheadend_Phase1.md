# TV / Tvheadend Phase 1

Rebuilding the Tvheadend module as a clean modular structure.

## Files

- `config.py` reads `/etc/server-manager/tvheadend.conf`
- `api.py` encapsulates Tvheadend HTTP/API
- `formatter.py` normalizes language fields and times
- `models.py` normalizes streams, recordings, and EPG
- `cache.py` simple module cache base
- `plugin.py` provides WebUI and API

## No private data in the code

Credentials are stored exclusively in:

```text
/etc/server-manager/tvheadend.conf
```

## Important Pages

- `/tv`
- `/tv/status`
- `/tv/streams`
- `/tv/recordings`
- `/tv/upcoming`
- `/tv/epg`
- `/api/tv/status`
