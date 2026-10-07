# -*- coding: utf-8 -*-
import os
import re
import subprocess

DEFAULT_UNITS = [
    "server-manager.service",
    "tvheadend.service",
    "oscam.service",
    "smbd.service",
    "nmbd.service",
    "winbind.service",
    "nfs-server.service",
    "docker.service",
    "mariadb.service",
    "apache2.service",
    "php8.4-fpm.service",
    "redis-server.service",
    "pihole-FTL.service",
    "scanner-api.service",
    "scanbd.service",
    "ollama.service",
    "xrdp.service",
    "fail2ban.service",
    "smartmontools.service",
    "libvirtd.service",
]

SAFE_ACTIONS = {"start", "stop", "restart", "reload", "try-restart", "enable", "disable"}
UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.(service|timer|socket)$")

CRITICAL_STOP_BLOCKLIST = {
    "ssh.service",
    "sshd.service",
    "server-manager.service",
}

RELOAD_PREFERRED = {
    "apache2.service": "reload",
    "smbd.service": "reload",
    "nmbd.service": "reload",
    "nfs-server.service": "reload",
    "fail2ban.service": "reload",
}

HEALTH_HINTS = {
    "apache2.service": ["apachectl", "configtest"],
    "smbd.service": ["testparm", "-s"],
    "docker.service": ["docker", "ps", "--format", "table {{.Names}}\\t{{.Status}}"],
    "mariadb.service": ["mysqladmin", "ping"],
    "pihole-FTL.service": ["pihole", "status"],
    "tvheadend.service": ["systemctl", "is-active", "tvheadend.service"],
    "oscam.service": ["systemctl", "is-active", "oscam.service"],
}


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": (p.stdout or "").strip(), "stderr": (p.stderr or "").strip(), "cmd": cmd}
    except Exception as e:
        return {"ok": False, "returncode": 999, "stdout": "", "stderr": str(e), "cmd": cmd}


def valid_unit(unit):
    return bool(UNIT_RE.match(str(unit or "")))


def normalize_unit(unit):
    unit = str(unit or "").strip()
    if "." not in unit:
        unit += ".service"
    return unit


def unit_allowed(unit):
    unit = normalize_unit(unit)
    return valid_unit(unit)


def list_units():
    units = list(DEFAULT_UNITS)
    extra = os.environ.get("SERVER_MANAGER_SERVICE_UNITS", "")
    for u in extra.split(","):
        u = normalize_unit(u.strip())
        if unit_allowed(u) and u not in units:
            units.append(u)
    return units


def unit_status(unit):
    unit = normalize_unit(unit)
    active = run(["systemctl", "is-active", unit], 4)
    enabled = run(["systemctl", "is-enabled", unit], 4)
    load = run(["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,UnitFileState,Description,MainPID,ExecMainStatus,RestartUSec,FragmentPath", "--no-page"], 5)
    props = {}
    for line in (load["stdout"] or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return {
        "unit": unit,
        "active": active["stdout"] or "unknown",
        "enabled": enabled["stdout"] or "unknown",
        "description": props.get("Description", ""),
        "load_state": props.get("LoadState", ""),
        "active_state": props.get("ActiveState", ""),
        "sub_state": props.get("SubState", ""),
        "unit_file_state": props.get("UnitFileState", ""),
        "main_pid": props.get("MainPID", ""),
        "exec_status": props.get("ExecMainStatus", ""),
        "fragment_path": props.get("FragmentPath", ""),
    }


def all_status():
    return [unit_status(u) for u in list_units()]


def failed_units():
    r = run(["systemctl", "--failed", "--no-legend", "--plain"], 8)
    rows = []
    for line in (r["stdout"] or "").splitlines():
        parts = line.split(None, 4)
        if parts:
            rows.append({"unit": parts[0], "line": line})
    return rows


def timers():
    r = run(["systemctl", "list-timers", "--all", "--no-pager", "--plain"], 8)
    return r["stdout"] or r["stderr"]


def sockets():
    r = run(["systemctl", "list-sockets", "--all", "--no-pager", "--plain"], 8)
    return r["stdout"] or r["stderr"]


def journal(unit, lines=120):
    unit = normalize_unit(unit)
    if not unit_allowed(unit):
        return {"ok": False, "stderr": "Ungültige Unit"}
    lines = max(20, min(500, int(lines or 120)))
    return run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--no-hostname"], 12)


def unit_cat(unit):
    unit = normalize_unit(unit)
    if not unit_allowed(unit):
        return {"ok": False, "stderr": "Ungültige Unit"}
    return run(["systemctl", "cat", unit, "--no-pager"], 8)


def unit_deps(unit):
    unit = normalize_unit(unit)
    if not unit_allowed(unit):
        return {"ok": False, "stderr": "Ungültige Unit"}
    return run(["systemctl", "list-dependencies", unit, "--no-pager", "--plain"], 8)


def health_check(unit):
    unit = normalize_unit(unit)
    cmd = HEALTH_HINTS.get(unit)
    if not cmd:
        return {"ok": True, "stdout": "Kein spezieller Prüfbefehl hinterlegt.", "stderr": "", "cmd": []}
    return run(cmd, 15)


def service_action(unit, action, force=False):
    unit = normalize_unit(unit)
    action = str(action or "").strip()
    if action not in SAFE_ACTIONS:
        return {"ok": False, "error": "Nicht erlaubte Aktion"}
    if not unit_allowed(unit):
        return {"ok": False, "error": "Ungültige Unit"}
    if action in ("stop", "restart", "try-restart") and unit in CRITICAL_STOP_BLOCKLIST and not force:
        return {"ok": False, "error": "Kritische Unit: Stop/Restart nur mit force=1"}
    if action == "reload":
        # reload-or-restart ist bei Diensten ohne Reload sicherer für die Bedienung.
        cmd = ["systemctl", "reload-or-restart", unit]
    else:
        cmd = ["systemctl", action, unit]
    return run(cmd, 30)
