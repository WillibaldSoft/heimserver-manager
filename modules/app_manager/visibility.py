# -*- coding: utf-8 -*-
import json
from pathlib import Path

CONFIG_FILE = Path("/etc/server-manager/app_manager_visibility.json")


def _load():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"hidden": [], "removed": []}


def _save(data):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hidden_apps():
    data = _load()
    return set(data.get("hidden") or [])


def is_hidden(app_id):
    return app_id in hidden_apps()


def set_hidden(app_id, hidden=True):
    data = _load()
    hidden_set = set(data.get("hidden") or [])

    if hidden:
        hidden_set.add(app_id)
    else:
        hidden_set.discard(app_id)

    data["hidden"] = sorted(hidden_set)
    _save(data)
    return data


def removed_apps():
    data = _load()
    return set(data.get("removed") or [])


def is_removed(app_id):
    return app_id in removed_apps()


def set_removed(app_id, removed=True):
    data = _load()
    removed_set = set(data.get("removed") or [])

    if removed:
        removed_set.add(app_id)
        # entfernte Apps müssen nicht zusätzlich hidden sein
        hidden_set = set(data.get("hidden") or [])
        hidden_set.discard(app_id)
        data["hidden"] = sorted(hidden_set)
    else:
        removed_set.discard(app_id)

    data["removed"] = sorted(removed_set)
    _save(data)
    return data
