# -*- coding: utf-8 -*-
from pathlib import Path
from .runner import sh
from .settings import get_setting

DEFAULT_BACKUP_ROOT = get_setting("backup_root", "/srv/backups/apps")

def path_status(path):
    p = str(path or "")
    return {
        "path": p,
        "exists": Path(p).exists(),
        "is_dir": Path(p).is_dir(),
        "readable": sh(f"test -r {p!r} && echo yes || echo no", timeout=5)["stdout"] == "yes",
        "writable": sh(f"test -w {p!r} && echo yes || echo no", timeout=5)["stdout"] == "yes",
        "size": sh(f"du -sh {p!r} 2>/dev/null | awk '{{print $1}}' || true", timeout=15)["stdout"],
    }

def backup_check(manager):
    config_files = getattr(manager, "config_files", {}) or {}
    paths = getattr(manager, "paths", {}) or {}
    database = getattr(manager, "database", None)

    if isinstance(database, dict):
        database = {
            "configured": True,
            **database,
        }
    else:
        database = {
            "configured": False,
        }

    return {
        "supported": True,
        "mode": "read-only",
        "backup_root": DEFAULT_BACKUP_ROOT,
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "config_files": {
            k: path_status(v)
            for k, v in config_files.items()
        },
        "paths": {
            k: path_status(v)
            for k, v in paths.items()
        },
        "database": database,
        "message": "Phase 5.1: Backup-Check vorbereitet, Backup-Ausführung noch deaktiviert",
    }
