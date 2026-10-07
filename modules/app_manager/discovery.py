# -*- coding: utf-8 -*-
from pathlib import Path

from .registry import all_managers
from .runner import sh


COMPOSE_ROOTS = [
    "/opt",
    "/Serverspeicher",
]

EXCLUDE_NAMES = [
    "Backup",
    "backup",
    "data_snapshots",
    "__pycache__",
]

ALIASES = {
    "paperless-ngx": "paperless",
    "paperless_ngx": "paperless",
    "stirling-pdf": "stirling",
    "stirling_pdf": "stirling",
    "server-manager": "server_manager",
    "server-manager": "server_manager",
    "comfyui": "comfyui",
    "tvheadend": "tvheadend",
    "oscam": "oscam",
    "immich": "immich",
}

APP_SERVICES = {
    "tvheadend.service",
    "oscam.service",
    "comfyui.service",
    "server-manager.service",
}


def known_app_ids():
    return {m.app_id for m in all_managers(include_hidden=True, include_missing=True)}


def _norm(name):
    n = str(name or "").strip().lower()
    n = n.replace(".service", "")
    n = n.replace("-", "_")
    return n


def _alias(name):
    raw = str(name or "").strip().lower()
    key1 = raw.replace(".service", "")
    key2 = key1.replace("-", "_")
    return ALIASES.get(key1) or ALIASES.get(key2) or key2


def _managed_by_name(name):
    return _alias(name) in known_app_ids()


def discover_compose():
    found = []

    exclude_expr = " ".join("-name '{}' -o".format(x) for x in EXCLUDE_NAMES).rstrip(" -o")

    for root in COMPOSE_ROOTS:
        rp = Path(root)
        if not rp.exists():
            continue

        cmd = (
            "find {} -maxdepth 4 "
            "\\( {} \\) -prune -o "
            "-type f \\( -name docker-compose.yml -o -name compose.yml \\) "
            "-print 2>/dev/null | head -200"
        ).format(repr(str(rp)), exclude_expr)

        r = sh(cmd, timeout=20)

        for line in (r.get("stdout") or "").splitlines():
            fn = Path(line.strip())
            if not str(fn):
                continue

            d = fn.parent
            found.append({
                "type": "docker-compose",
                "name": d.name,
                "app_id_guess": _alias(d.name),
                "path": str(d),
                "compose_file": str(fn),
                "managed": _managed_by_name(d.name),
            })

    seen = set()
    unique = []
    for item in found:
        key = item["compose_file"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return sorted(unique, key=lambda x: x["path"])


def discover_services():
    out = sh(
        "systemctl list-unit-files --type=service --no-legend --no-pager 2>/dev/null | awk '{print $1}'",
        timeout=20,
    )

    services = []

    for line in (out.get("stdout") or "").splitlines():
        svc = line.strip()

        if not svc.endswith(".service"):
            continue

        if "@." in svc:
            continue

        if "-appbackup-" in svc or "-backup-" in svc:
            continue

        if svc not in APP_SERVICES:
            continue

        active = sh("systemctl is-active {} 2>/dev/null || true".format(svc), timeout=5)

        services.append({
            "type": "systemd",
            "name": svc.replace(".service", ""),
            "app_id_guess": _alias(svc),
            "service": svc,
            "active": (active.get("stdout") or "").strip(),
            "managed": _managed_by_name(svc),
        })

    return sorted(services, key=lambda x: x["service"])


def discover_apps():
    return {
        "compose": discover_compose(),
        "services": discover_services(),
    }
