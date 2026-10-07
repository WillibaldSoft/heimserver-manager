# -*- coding: utf-8 -*-
from .config import monitoring_enabled
import time
from . import api, models, rtc

PREWAKE_MINUTES = 30

def get_blockers(ctx=None):
    if not monitoring_enabled():return []
    blockers = []

    # aktive Streams
    try:
        for row in api.subscriptions():
            if models.is_epg_grabber(row):
                continue
            s = models.normalize_stream(row)
            title = s.get("title") or s.get("channel") or "Stream"
            blockers.append({
                "source": "tvheadend",
                "type": "stream",
                "title": title,
                "reason": "Aktiver Live-TV Stream",
                "priority": 100,
            })
    except Exception as e:
        blockers.append({
            "source": "tvheadend",
            "type": "error",
            "title": "Streams",
            "reason": str(e),
            "priority": 900,
        })

    # laufende Aufnahmen
    try:
        for row in api.recordings("grid", 100):
            r = models.normalize_recording(row)
            status = str(r.get("status") or "").lower()
            if status in ("", "running", "recording", "scheduled", "pending"):
                blockers.append({
                    "source": "tvheadend",
                    "type": "recording",
                    "title": r.get("title") or "Aufnahme",
                    "reason": "Aufnahme läuft",
                    "priority": 50,
                })
    except Exception as e:
        blockers.append({
            "source": "tvheadend",
            "type": "error",
            "title": "Aufnahmen",
            "reason": str(e),
            "priority": 900,
        })

    # kommende Aufnahme im Vorlauf
    try:
        rec = rtc.get_next_recording(PREWAKE_MINUTES)
        if rec and rec.get("wake_ts") and int(time.time()) >= int(rec["wake_ts"]):
            blockers.append({
                "source": "tvheadend",
                "type": "recording-prewake",
                "title": rec.get("title") or "geplante Aufnahme",
                "reason": "Aufnahme beginnt um {}, Vorlauf {} min".format(
                    rec.get("start"), PREWAKE_MINUTES
                ),
                "priority": 60,
            })
    except Exception as e:
        blockers.append({
            "source": "tvheadend",
            "type": "error",
            "title": "Aufnahme-Vorlauf",
            "reason": str(e),
            "priority": 900,
        })

    return blockers
