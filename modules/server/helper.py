# -*- coding: utf-8 -*-
import json
import os
import shutil
import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "tools" / "helpers" / "server-manager-server-helper"

DEFAULT_SERVICES = [
    "server-manager.service",
    "multi-dyndns-update.service",
    "tvheadend.service",
    "oscam.service",
    "docker.service",
    "mariadb.service",
    "apache2.service",
    "smbd.service",
    "nmbd.service",
    "ssh.service",
    "cron.service",
    "libvirtd.service",
    "smartmontools.service",
]

SAFE_SERVICE_RE = r"^[A-Za-z0-9_.@:-]+\\.service$"


def _run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except Exception as e:
        return {"ok": False, "returncode": 99, "stdout": "", "stderr": str(e)}


def _helper(args, timeout=20):
    if HELPER.exists() and os.access(str(HELPER), os.X_OK):
        return _run([str(HELPER)] + list(args), timeout=timeout)
    return _run(["sudo", str(HELPER)] + list(args), timeout=timeout)


def _json_helper(args, fallback=None, timeout=20):
    r = _helper(args, timeout=timeout)
    if not r.get("ok") and not r.get("stdout"):
        return fallback if fallback is not None else {"ok": False, "error": r.get("stderr", "helper failed")}
    try:
        return json.loads(r.get("stdout") or "{}")
    except Exception:
        return fallback if fallback is not None else {"ok": False, "error": "invalid json", "raw": r}


def service_rows():
    return _json_helper(["services"], fallback=[])


def failed_units():
    return _json_helper(["failed"], fallback=[])


def timers():
    return _json_helper(["timers"], fallback=[])


def sockets():
    return _json_helper(["sockets"], fallback=[])


def boot_info():
    return _json_helper(["boot"], fallback={})


def docker_info():
    return _json_helper(["docker"], fallback={})


def kvm_info():
    return _json_helper(["kvm"], fallback={})


def top_processes():
    return _json_helper(["processes"], fallback=[])


def checks():
    return _json_helper(["checks"], fallback=[])


def journal(unit=None, lines=40):
    args = ["journal", str(int(lines or 40))]
    if unit:
        args.append(str(unit))
    return _json_helper(args, fallback={"ok": False, "lines": []}, timeout=20)


def unit_file(unit):
    return _json_helper(["unit", str(unit)], fallback={"ok": False, "content": ""})


def dependencies(unit):
    return _json_helper(["deps", str(unit)], fallback=[])


def service_action(action, unit):
    return _helper(["service-action", str(action), str(unit)], timeout=30)


def system_tool(action):
    return _helper(["tool", str(action)], timeout=60)
