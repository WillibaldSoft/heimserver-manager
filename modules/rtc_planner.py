# -*- coding: utf-8 -*-
import importlib
import subprocess
import time
import datetime

RTC_PROVIDERS = [
    "modules.app_manager.backup_rtc",
    "modules.fotolabor.scheduling",
    "modules.sleep_engine.rtc_provider",
    "modules.tvheadend.rtc_provider",
]

WAKEALARM = "/sys/class/rtc/rtc0/wakealarm"

def collect_candidates(ctx=None):
    out = []
    for modname in RTC_PROVIDERS:
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "get_rtc_candidates"):
                rows = mod.get_rtc_candidates(ctx)
                if rows:
                    out.extend(rows)
        except Exception as e:
            out.append({
                "source": "rtc-planner",
                "title": modname,
                "error": str(e),
                "priority": 999,
            })
    return out

def valid_candidates(ctx=None):
    now = int(time.time())
    rows = []
    for c in collect_candidates(ctx):
        ts = c.get("ts")
        if not ts and c.get("wake_time"):
            try:
                dt = datetime.datetime.strptime(c["wake_time"], "%Y-%m-%d %H:%M:%S")
                ts = int(dt.timestamp())
                c["ts"] = ts
            except Exception:
                continue
        if ts and int(ts) > now:
            rows.append(c)
    return sorted(rows, key=lambda x: int(x["ts"]))

def select_next(ctx=None):
    rows = valid_candidates(ctx)
    return rows[0] if rows else None

def read_wakealarm():
    try:
        with open(WAKEALARM, "r", encoding="utf-8") as f:
            value = f.read().strip()
        return int(value or "0")
    except Exception:
        return 0

def set_wakealarm(ts):
    ts = int(ts)

    # Wakealarm löschen und neu setzen.
    with open(WAKEALARM, "w", encoding="utf-8") as f:
        f.write("0")
    with open(WAKEALARM, "w", encoding="utf-8") as f:
        f.write(str(ts))

    return read_wakealarm()

def sync(ctx=None, dry_run=True):
    selected = select_next(ctx)
    current = read_wakealarm()

    if not selected:
        return {
            "ok": True,
            "changed": False,
            "reason": "no candidate",
            "current": current,
            "selected": None,
        }

    target = int(selected["ts"])

    if abs(current - target) <= 60:
        return {
            "ok": True,
            "changed": False,
            "reason": "already set",
            "current": current,
            "target": target,
            "selected": selected,
        }

    if dry_run:
        return {
            "ok": True,
            "changed": False,
            "reason": "dry-run",
            "current": current,
            "target": target,
            "selected": selected,
        }

    new_value = set_wakealarm(target)
    return {
        "ok": True,
        "changed": True,
        "reason": "set",
        "current": current,
        "target": target,
        "new": new_value,
        "selected": selected,
    }
