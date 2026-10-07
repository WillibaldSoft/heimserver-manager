# -*- coding: utf-8 -*-
import datetime
import time

from . import api
from . import models

DEFAULT_PRE_WAKE_MINUTES = 10

def parse_tv_time(value):
    """
    Tvheadend liefert start/start_real teils als Unix-Timestamp.
    Gibt lokale datetime zurück.
    """
    if value in ("", None):
        return None
    try:
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(int(value))
    except Exception:
        pass
    return None

def timestamp_from_dt(dt):
    if not dt:
        return None
    return int(time.mktime(dt.timetuple()))

def get_next_recording(prewake_minutes=DEFAULT_PRE_WAKE_MINUTES):
    rows = api.recordings("grid_upcoming", 100)
    items = []
    now = datetime.datetime.now()

    for raw in rows:
        rec = models.normalize_recording(raw)
        start_raw = raw.get("start_real") or raw.get("start")
        stop_raw = raw.get("stop_real") or raw.get("stop")
        start_dt = parse_tv_time(start_raw)
        stop_dt = parse_tv_time(stop_raw)
        if not start_dt:
            continue
        if start_dt < now:
            continue
        wake_dt = start_dt - datetime.timedelta(minutes=int(prewake_minutes))
        items.append({
            "title": rec.get("title") or "",
            "channel": rec.get("channel") or "",
            "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "stop": stop_dt.strftime("%Y-%m-%d %H:%M:%S") if stop_dt else "",
            "wake": wake_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "wake_ts": timestamp_from_dt(wake_dt),
            "prewake_minutes": int(prewake_minutes),
            "status": rec.get("status") or "",
            "raw": raw,
        })

    items.sort(key=lambda x: x["wake_ts"] or 0)
    return items[0] if items else None

def plan_next_recording(con, prewake_minutes=DEFAULT_PRE_WAKE_MINUTES):
    next_rec = get_next_recording(prewake_minutes)
    if not next_rec:
        return {"ok": True, "planned": False, "reason": "no upcoming recording"}

    con.execute("""
        CREATE TABLE IF NOT EXISTS server_control_rtc_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            wake_time TEXT,
            target_time TEXT,
            status TEXT DEFAULT 'planned',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # alte tvheadend planned Events deaktivieren, damit genau eine nächste Aufnahme aktiv ist
    con.execute("""
        UPDATE server_control_rtc_events
           SET status='superseded'
         WHERE source='tvheadend'
           AND status='planned'
    """)

    con.execute("""
        INSERT INTO server_control_rtc_events(source,title,wake_time,target_time,status)
        VALUES('tvheadend',?,?,?,'planned')
    """, (
        next_rec["title"],
        next_rec["wake"],
        next_rec["start"],
    ))
    con.commit()

    return {
        "ok": True,
        "planned": True,
        "recording": next_rec,
    }

def current_rtc_events(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS server_control_rtc_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            wake_time TEXT,
            target_time TEXT,
            status TEXT DEFAULT 'planned',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    rows = con.execute("""
        SELECT *
          FROM server_control_rtc_events
         WHERE source='tvheadend'
         ORDER BY created_at DESC, wake_time DESC
         LIMIT 20
    """).fetchall()
    return [dict(r) for r in rows]

def read_kernel_wakealarm():
    paths = [
        "/sys/class/rtc/rtc0/wakealarm",
        "/proc/driver/rtc",
    ]
    out = {}
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                out[p] = f.read().strip()
        except Exception as e:
            out[p] = "error: " + str(e)
    return out
