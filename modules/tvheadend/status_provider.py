# -*- coding: utf-8 -*-
from .config import monitoring_enabled
from . import api, models, rtc

def get_status(ctx=None):
    if not monitoring_enabled():return {"installed":False,"streams_active":0,"recordings_active":0,"next_recording":None,"rtc":None}
    data = {
        "streams_active": 0,
        "recordings_active": 0,
        "next_recording": None,
        "rtc": None,
    }

    try:
        data["streams_active"] = sum(not models.is_epg_grabber(row) for row in api.subscriptions())
    except Exception as e:
        data["streams_error"] = str(e)

    try:
        recordings = []
        for row in api.recordings("grid", 100):
            r = models.normalize_recording(row)
            status = str(r.get("status") or "").lower()
            if status in ("", "running", "recording", "scheduled", "pending"):
                recordings.append(r)
        data["recordings_active"] = len(recordings)
        data["recordings"] = recordings
    except Exception as e:
        data["recordings_error"] = str(e)

    try:
        data["next_recording"] = rtc.get_next_recording(30)
    except Exception as e:
        data["next_recording_error"] = str(e)

    return data
