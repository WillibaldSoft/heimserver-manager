
from datetime import datetime

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db(con):
    con.execute('''
        CREATE TABLE IF NOT EXISTS server_control_status (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS server_control_blockers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            name TEXT NOT NULL,
            reason TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS server_control_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            type TEXT DEFAULT 'keep-awake',
            days TEXT,
            start_time TEXT,
            end_time TEXT,
            action TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS server_control_rtc_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            wake_time TEXT,
            target_time TEXT,
            status TEXT DEFAULT 'planned',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS server_control_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            source TEXT,
            result TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    con.commit()

def set_status(con, key, value):
    con.execute('''
        INSERT INTO server_control_status(key,value,updated_at)
        VALUES(?,?,datetime('now','localtime'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    ''', (key, str(value)))
    con.commit()

def get_status(con):
    rows = con.execute("SELECT key,value,updated_at FROM server_control_status ORDER BY key").fetchall()
    return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}

def active_blockers(con):
    return con.execute('''
        SELECT source,name,reason,updated_at
          FROM server_control_blockers
         WHERE active=1
         ORDER BY source,name
    ''').fetchall()

def record_action(con, action, source="server-control", result="planned", details=""):
    con.execute('''
        INSERT INTO server_control_actions(action,source,result,details)
        VALUES(?,?,?,?)
    ''', (action, source, result, details))
    con.commit()
