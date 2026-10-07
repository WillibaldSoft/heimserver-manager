# -*- coding: utf-8 -*-
import subprocess, os, shlex, datetime
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / 'tools/helpers/server-manager-storage-helper'


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {'ok': p.returncode == 0, 'rc': p.returncode, 'out': p.stdout.strip(), 'err': p.stderr.strip()}
    except Exception as e:
        return {'ok': False, 'rc': 999, 'out': '', 'err': str(e)}


def esc_unit(s):
    return str(s or '').replace('\\', '\\\\').replace('"', '\\"')


def bytes_human(n):
    try:
        n = float(n or 0)
    except Exception:
        n = 0
    units = ['B','KB','MB','GB','TB','PB']
    i = 0
    while n >= 1024 and i < len(units)-1:
        n /= 1024.0
        i += 1
    return ('%.1f %s' % (n, units[i])).replace('.0 ', ' ')


def setting(ctx, key, default=''):
    try:
        con = ctx.db()
        try:
            r = con.execute('SELECT value FROM sleep_engine_settings WHERE key=?', (key,)).fetchone()
            if r:
                return r['value']
        finally:
            con.close()
    except Exception:
        pass
    return default


def set_setting(ctx, key, value):
    con = ctx.db()
    try:
        con.execute('''CREATE TABLE IF NOT EXISTS sleep_engine_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )''')
        con.execute('''INSERT INTO sleep_engine_settings(key,value,updated_at)
                       VALUES(?,?,datetime('now','localtime'))
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now','localtime')''', (key, str(value)))
        con.commit()
    finally:
        con.close()


def ntfy_send(ctx, title, message, tags='warning'):
    from modules.alarms.engine import config, publish
    cfg=config(ctx)
    text=str(message) if cfg['details'] else 'Speicherwarnung. Details im Heimserver Manager unter Alarme.'
    return {'ok':publish(cfg,str(title),text)}
