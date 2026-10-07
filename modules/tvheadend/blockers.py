# -*- coding: utf-8 -*-
# Tvheadend -> Server-Control Blocker

from .config import monitoring_enabled
import time

from . import api
from . import models
from . import rtc

SETTING_KEY = "tv_recording_prewake_minutes"
DEFAULT_PREWAKE = 30

def ensure_settings(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS tvheadend_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()

def get_setting(con, key, default):
    ensure_settings(con)
    row = con.execute("SELECT value FROM tvheadend_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else str(default)

def set_setting(con, key, value):
    ensure_settings(con)
    con.execute("""
        INSERT INTO tvheadend_settings(key,value,updated_at)
        VALUES(?,?,datetime('now','localtime'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, str(value)))
    con.commit()

def get_prewake_minutes(con):
    try:
        return int(get_setting(con, SETTING_KEY, DEFAULT_PREWAKE))
    except Exception:
        return DEFAULT_PREWAKE

def ensure_server_control_blockers(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS server_control_blockers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            name TEXT NOT NULL,
            reason TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()

def clear_tv_blockers(con):
    ensure_server_control_blockers(con)
    con.execute("""
        UPDATE server_control_blockers
           SET active=0,
               updated_at=datetime('now','localtime')
         WHERE source='tvheadend'
    """)
    con.commit()

def add_blocker(con, name, reason):
    ensure_server_control_blockers(con)
    con.execute("""
        INSERT INTO server_control_blockers(source,name,reason,active,updated_at)
        VALUES('tvheadend',?,?,1,datetime('now','localtime'))
    """, (name, reason))
    con.commit()

def active_streams():
    out = []
    try:
        for row in api.subscriptions():
            if models.is_epg_grabber(row):
                continue
            out.append(models.normalize_stream(row))
    except Exception:
        pass
    return out

def active_recordings():
    out = []
    try:
        for row in api.recordings("grid", 100):
            rec = models.normalize_recording(row)
            status = str(rec.get("status") or "").lower()
            if status in ("", "running", "recording", "scheduled", "pending"):
                out.append(rec)
    except Exception:
        pass
    return out

def upcoming_within(minutes):
    try:
        rec = rtc.get_next_recording(minutes)
        if not rec:
            return None
        wake_ts = rec.get("wake_ts")
        if wake_ts and int(time.time()) >= int(wake_ts):
            return rec
    except Exception:
        return None
    return None

def sync_blockers(con):
    clear_tv_blockers(con)
    if not monitoring_enabled():return {"prewake_minutes":get_prewake_minutes(con),"streams":[],"recordings":[],"upcoming_blocker":None}
    prewake = get_prewake_minutes(con)

    streams = active_streams()
    for s in streams:
        title = s.get("title") or s.get("channel") or "Stream"
        reason = "Aktiver Tvheadend Stream"
        if s.get("channel"):
            reason += " " + str(s.get("channel"))
        add_blocker(con, "Stream: " + str(title), reason)

    recordings = active_recordings()
    for r in recordings:
        title = r.get("title") or "Aufnahme"
        reason = "Tvheadend Aufnahme läuft"
        if r.get("channel"):
            reason += " " + str(r.get("channel"))
        add_blocker(con, "Aufnahme: " + str(title), reason)

    upcoming = upcoming_within(prewake)
    if upcoming:
        title = upcoming.get("title") or "geplante Aufnahme"
        start = upcoming.get("start") or ""
        add_blocker(
            con,
            "Aufnahme bald: " + str(title),
            "Start um {}, Vorlauf {} min".format(start, prewake),
        )

    return {
        "prewake_minutes": prewake,
        "streams": streams,
        "recordings": recordings,
        "upcoming_blocker": upcoming,
    }
