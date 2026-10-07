# -*- coding: utf-8 -*-
import importlib
import pkgutil

from . import managers
from .visibility import is_hidden, is_removed

PREFERRED_ORDER = [
    "open_webui",
    "oscam",
    "immich",
    "paperless",
    "comfyui",
    "stirling",
    "nextcloud",
    "server_manager",
    "tvheadend",
    "shares_mounts",
]

SKIP_MODULES = {
    "base",
    "docker_compose",
}


def _load_managers():
    loaded = []

    for modinfo in pkgutil.iter_modules(managers.__path__):
        name = modinfo.name

        if name.startswith("_") or name in SKIP_MODULES:
            continue

        try:
            mod = importlib.import_module(f"{managers.__name__}.{name}")
            cls = getattr(mod, "Manager", None)
            if cls is None:
                continue

            inst = cls()
            loaded.append((name, inst))
        except Exception as e:
            # Defekte Manager sollen nicht den gesamten App Manager abschießen.
            class BrokenManager:
                app_id = name
                label = name
                kind = "broken"

                def status(self):
                    return {
                        "ok": False,
                        "warnings": [str(e)],
                        "installation": {
                            "installed": False,
                            "state": "broken",
                            "reason": str(e),
                            "checks": [],
                        },
                    }

                def info(self):
                    return {
                        "app_id": self.app_id,
                        "label": self.label,
                        "kind": self.kind,
                        "error": str(e),
                    }

                def health(self):
                    return self.status()

            loaded.append((name, BrokenManager()))

    def sort_key(item):
        name, inst = item
        app_id = getattr(inst, "app_id", name)
        if app_id in PREFERRED_ORDER:
            return (PREFERRED_ORDER.index(app_id), app_id)
        if name in PREFERRED_ORDER:
            return (PREFERRED_ORDER.index(name), name)
        return (999, app_id)

    loaded.sort(key=sort_key)
    return [inst for name, inst in loaded]


MANAGERS = _load_managers()


def _installation_state(manager):
    from .lifecycle import installation
    return installation(manager).get('state', 'unknown')


def current_managers():
    from .installed_apps import managers as installed
    dynamic={m.app_id:m for m in installed()}
    from .nextcloud_variants import combine
    return combine(MANAGERS, dynamic)


def all_managers(include_hidden=False, include_missing=False, include_removed=False):
    result = []

    for m in current_managers():
        state = _installation_state(m)

        if not include_removed and is_removed(m.app_id):
            continue

        if not include_hidden and is_hidden(m.app_id):
            continue

        if not include_missing and state != "installed":
            continue

        result.append(m)

    return result


def get_manager(app_id):
    for m in current_managers():
        if m.app_id == app_id:
            return m
    return None
