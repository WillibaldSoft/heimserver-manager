# -*- coding: utf-8 -*-
import datetime
from .config import monitoring_enabled
from . import rtc

def get_rtc_candidates(ctx=None):
    if not monitoring_enabled():return []
    candidates = []

    try:
        rec = rtc.get_next_recording(10)
        if not rec:
            return candidates

        wake = rec.get("wake") or rec.get("wake_time")
        start = rec.get("start") or rec.get("target_time")
        title = rec.get("title") or "Tvheadend Aufnahme"

        if not wake:
            return candidates

        dt = datetime.datetime.strptime(wake, "%Y-%m-%d %H:%M:%S")

        candidates.append({
            "source": "tvheadend",
            "title": title,
            "wake_time": wake,
            "target_time": start or wake,
            "ts": int(dt.timestamp()),
            "priority": 40,
        })
    except Exception as e:
        candidates.append({
            "source": "tvheadend",
            "title": "RTC Fehler",
            "error": str(e),
            "priority": 900,
        })

    return candidates
