from server_settings import get as host_setting
# -*- coding: utf-8 -*-
import os
import glob
import time
import subprocess

BACKUP_ITEMS = host_setting('backup_items')

def _du(path):
    try:
        p = subprocess.run(["du", "-sh", path], text=True, capture_output=True, timeout=20)
        return (p.stdout.split()[0] if p.returncode == 0 and p.stdout else "")
    except Exception:
        return ""

def scan_item(item):
    from .daily import monitored
    scheduled=monitored(item)
    if scheduled is not None:return scheduled
    base = item["path"]
    if not os.path.exists(base):
        return {**item, "state": "FEHLT", "age_h": None, "latest": "", "size": ""}

    # Existing SQL monitoring also accepts its compressed counterpart, but not
    # partial files such as db.sql.gz.tmp or unrelated error logs.
    pattern = item["pattern"]
    patterns = [pattern]
    if pattern.endswith(".sql"):patterns.append(pattern + ".gz")
    elif pattern.endswith(".sql.gz"):patterns.append(pattern[:-3])
    matches = list({m for pat in patterns for m in glob.glob(os.path.join(base, pat))})
    matches = [m for m in matches if os.path.exists(m)]

    if not matches:
        return {**item, "state": "LEER", "age_h": None, "latest": "", "size": ""}

    latest = max(matches, key=lambda p: os.path.getmtime(p))
    age_h = int((time.time() - os.path.getmtime(latest)) / 3600)

    if age_h <= int(item["warn_h"]):
        state = "OK"
    elif age_h <= int(item["crit_h"]):
        state = "WARN"
    else:
        state = "ALT"

    return {
        **item,
        "state": state,
        "age_h": age_h,
        "latest": latest,
        "size": _du(latest),
    }

def backup_status():
    rows = [scan_item(i) for i in host_setting("backup_items")]
    ok = all(r["state"] == "OK" for r in rows if r.get("required", True))
    return {"ok": ok, "items": rows}
