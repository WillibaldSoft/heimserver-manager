import os
from server_settings import BASE_DIR, CONFIG_DIR
# -*- coding: utf-8 -*-
import re
from pathlib import Path

from .runner import sh

SYSTEMD_DIR = Path("/etc/systemd/system")
PREFIX = "server-manager-appbackup"


def _safe(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    return value.strip("-") or "unknown"


def unit_names(app_id, profile):
    app = _safe(app_id)
    prof = _safe(profile)
    base = f"{PREFIX}-{app}-{prof}"
    return base + ".service", base + ".timer"


def on_calendar(frequency, time_value, weekday="Mon"):
    t = str(time_value or "03:00").strip()
    if not re.match(r"^[0-2][0-9]:[0-5][0-9]$", t):
        t = "03:00"

    frequency = str(frequency or "daily").strip().lower()
    weekday = str(weekday or "Mon").strip()[:3].title()

    if frequency == "weekly":
        return f"{weekday} *-*-* {t}:00"
    if frequency == "monthly":
        return f"*-*-01 {t}:00"
    return f"*-*-* {t}:00"


def write_schedule(app_id, profile, frequency="daily", time_value="03:00", weekday="Mon"):
    service_name, timer_name = unit_names(app_id, profile)
    service_path = SYSTEMD_DIR / service_name
    timer_path = SYSTEMD_DIR / timer_name

    app, prof = _safe(app_id), _safe(profile)
    cal = on_calendar(frequency, time_value, weekday)

    service_path.write_text(f"""[Unit]
Description=Server Manager App Backup {app_id} {profile}
After=network-online.target server-manager.service
Wants=network-online.target

[Service]
Type=oneshot
Environment="SERVER_MANAGER_CONFIG={str(CONFIG_DIR).replace('%', '%%')}"
ExecStart=/usr/bin/python3 "{str(BASE_DIR / 'tools/authenticated_request.py').replace('%', '%%')}" backup --app {app} --profile {prof} --port {int(os.environ.get('SERVER_MANAGER_PORT', '9877'))}
""", encoding="utf-8")

    timer_path.write_text(f"""[Unit]
Description=Server Manager App Backup Timer {app_id} {profile}

[Timer]
OnCalendar={cal}
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
""", encoding="utf-8")

    sh("systemctl daemon-reload", timeout=30)
    sh(f"systemctl enable --now {timer_name}", timeout=30)

    return {
        "ok": True,
        "app_id": app_id,
        "profile": profile,
        "frequency": frequency,
        "time": time_value,
        "weekday": weekday,
        "on_calendar": cal,
        "service": service_name,
        "timer": timer_name,
    }


def delete_schedule(app_id, profile):
    service_name, timer_name = unit_names(app_id, profile)

    sh(f"systemctl disable --now {timer_name} 2>/dev/null || true", timeout=30)

    deleted = []
    for name in [timer_name, service_name]:
        p = SYSTEMD_DIR / name
        if p.exists():
            p.unlink()
            deleted.append(str(p))

    sh("systemctl daemon-reload", timeout=30)

    return {
        "ok": True,
        "app_id": app_id,
        "profile": profile,
        "deleted": deleted,
        "service": service_name,
        "timer": timer_name,
    }


def list_schedules(app_id):
    result = []
    app = _safe(app_id)

    for timer in SYSTEMD_DIR.glob(f"{PREFIX}-{app}-*.timer"):
        profile = timer.stem.replace(f"{PREFIX}-{app}-", "", 1)
        service_name = timer.name.replace(".timer", ".service")

        active = sh(f"systemctl is-active {timer.name} 2>/dev/null || true", timeout=10)["stdout"].strip()
        enabled = sh(f"systemctl is-enabled {timer.name} 2>/dev/null || true", timeout=10)["stdout"].strip()
        content = timer.read_text(encoding="utf-8", errors="replace")

        oncal = ""
        for line in content.splitlines():
            if line.startswith("OnCalendar="):
                oncal = line.split("=", 1)[1]

        next_line = sh(
            f"systemctl list-timers --all --no-pager {timer.name} 2>/dev/null | tail -n +2 | head -1 || true",
            timeout=10,
        )["stdout"].strip()

        result.append({
            "profile": profile,
            "timer": timer.name,
            "service": service_name,
            "active": active,
            "enabled": enabled,
            "on_calendar": oncal,
            "next": next_line,
        })

    return sorted(result, key=lambda x: x["profile"])
