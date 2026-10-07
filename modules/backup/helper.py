# -*- coding: utf-8 -*-
import os
import subprocess

SCRIPTS = {
    "nextcloud-full": "/usr/local/bin/nextcloud-full-backup.sh",
    "nextcloud-db": "/usr/local/sbin/nextcloud-db-backup.sh",
    "immich": "/usr/local/sbin/immich-backup.sh",
    "oscam": "/usr/local/sbin/oscam-backup.sh",
}

def script_status():
    return {
        name: {
            "path": path,
            "exists": os.path.exists(path),
            "executable": os.path.exists(path) and os.access(path, os.X_OK),
        }
        for name, path in SCRIPTS.items()
    }

def run_script(name):
    path = SCRIPTS.get(name)
    if not path:
        return {"ok": False, "error": "unknown script"}
    if not os.path.exists(path):
        return {"ok": False, "error": "script missing", "path": path}
    if not os.access(path, os.X_OK):
        return {"ok": False, "error": "script not executable", "path": path}

    p = subprocess.run(["sudo", "-n", path], text=True, capture_output=True, timeout=14400)
    return {
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "stdout": (p.stdout or "")[-30000:],
        "stderr": (p.stderr or "")[-30000:],
        "path": path,
    }
