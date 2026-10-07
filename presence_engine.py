
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime
import sqlite3
import os
import subprocess

STATE_DIR = Path(os.environ.get("SERVER_MANAGER_STATE", "/var/lib/server-manager"))
DB_PATH = Path(os.environ.get("SERVER_MANAGER_DB", str(STATE_DIR / "server-manager.sqlite3")))

def db():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    return con

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def detect_ssh(server_ip=None):
    try:
        p = subprocess.run(["ss", "-tn", "state", "established"], text=True, capture_output=True, timeout=3)
        for line in (p.stdout or '').splitlines():
            columns=line.split()
            if len(columns)<4:continue
            local=columns[-2]
            if local.endswith(':22') and (server_ip is None or local.rsplit(':',1)[0].strip('[]')==server_ip):return True
        return False
    except Exception:
        return False

def detect_nfs():
    return False

def detect_smb():
    return False

def server_required():
    ssh = detect_ssh()
    nfs = detect_nfs()
    smb = detect_smb()
    return {
        "required": bool(ssh or nfs or smb),
        "ssh": ssh,
        "nfs": nfs,
        "smb": smb,
    }
