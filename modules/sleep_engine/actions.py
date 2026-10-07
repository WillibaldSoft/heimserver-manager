# -*- coding: utf-8 -*-
import subprocess

def run_systemctl(action):
    allowed = {
        "suspend": ["systemctl", "suspend"],
        "hibernate": ["systemctl", "hibernate"],
        "poweroff": ["systemctl", "poweroff"],
    }
    if action not in allowed:
        return {"ok": False, "result": "unknown action"}

    try:
        p = subprocess.run(allowed[action], text=True, capture_output=True, timeout=20)
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
        }
    except Exception as exc:
        return {"ok": False, "result": str(exc)}

def dry_run(action):
    return {
        "ok": True,
        "dry_run": True,
        "action": action,
        "result": "not executed",
    }
