# -*- coding: utf-8 -*-

def ensure_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS sleep_engine_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            mode TEXT,
            allowed INTEGER,
            result TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sleep_engine_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()

def get_setting(con, key, default=""):
    ensure_tables(con)
    row = con.execute("SELECT value FROM sleep_engine_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(con, key, value):
    ensure_tables(con)
    con.execute("""
        INSERT INTO sleep_engine_settings(key,value,updated_at)
        VALUES(?,?,datetime('now','localtime'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, str(value)))
    con.commit()

def server_control_status(con, ctx=None):
    try:
        from modules.server_control.api import status
        return status(con, ctx)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "policy": {
                "may_sleep": False,
                "blocker_count": 1,
                "blockers": [{"source": "sleep-engine", "name": "Server-Control Fehler", "reason": str(exc)}],
            },
            "blockers": [],
            "rtc": [],
        }

def evaluate(con, ctx=None):
    ensure_tables(con)
    sc = server_control_status(con, ctx)
    policy = sc.get("policy", {})
    may_sleep = bool(policy.get("may_sleep"))
    blockers = policy.get("blockers") or sc.get("blockers") or []
    rtc_events = sc.get("rtc") or []

    mode = get_setting(con, "default_action", "suspend")
    auto_enabled = get_setting(con, "auto_enabled", "0") == "1"

    return {
        "ok": True,
        "may_sleep": may_sleep,
        "default_action": mode,
        "auto_enabled": auto_enabled,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "rtc_events": rtc_events,
        "server_control": sc,
    }

def record_action(con, action, mode, allowed, result, details=""):
    ensure_tables(con)
    con.execute("""
        INSERT INTO sleep_engine_actions(action,mode,allowed,result,details)
        VALUES(?,?,?,?,?)
    """, (action, mode, int(bool(allowed)), str(result), str(details or "")))
    con.commit()

def recent_actions(con, limit=30):
    ensure_tables(con)
    rows = con.execute("""
        SELECT *
          FROM sleep_engine_actions
         ORDER BY created_at DESC, id DESC
         LIMIT ?
    """, (int(limit),)).fetchall()
    return [dict(r) for r in rows]
