import server_settings as host_settings
# -*- coding: utf-8 -*-
import json
import secrets
import string
from pathlib import Path

CONFIG_FILE = host_settings.CONFIG_DIR / "app_manager.json"

DEFAULT_SETTINGS = {
    "backup_root": "/srv/backups/apps",
    "restore_log_root": "/srv/backups/apps/restore_runs",
    "update_log_root": "/srv/backups/apps/update_runs",

    "restore_execution_enabled": False,
    "restore_confirm_token": "RESTORE",
    "restore_require_token": True,
    "restore_require_rollback": True,

    "update_execution_enabled": False,
    "update_confirm_token": "UPDATE",
    "update_require_token": True,

    "live_refresh_seconds": 2,
    "show_json_details": True,
}


def load_settings():
    data = dict(DEFAULT_SETTINGS)

    try:
        if CONFIG_FILE.exists():
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
    except Exception:
        pass

    for key in ("backup_root", "restore_log_root", "update_log_root"):
        data[key] = host_settings.get(key)
    return data


def save_settings(data):
    current = load_settings()
    current.update(data or {})

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        CONFIG_FILE.chmod(0o640)
    except Exception:
        pass

    return current


def get_setting(key, default=None):
    return load_settings().get(key, default)


def bool_setting(key, default=False):
    return bool(load_settings().get(key, default))


def generate_token(length=12):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(int(length or 12)))


def ensure_config():
    if not CONFIG_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
    return load_settings()
