# -*- coding: utf-8 -*-
import importlib

BLOCKER_PROVIDERS = [
    "modules.app_manager.apt_jobs",
    "modules.backup.central",
    "modules.downloads.files",
    "modules.web_security.jobs",
    "modules.app_manager.backup_rtc",
    "modules.scanner.engine",
    "modules.app_manager.qwen_models",
    "modules.app_manager.openwebui_update",
    "modules.app_manager.install_jobs",
    "modules.dyndns.blocker_provider",
    "modules.shares.blocker_provider",
    "modules.kvm_manager.blocker_provider",
    "modules.fotolabor.blocker_provider",
    "modules.tvheadend.blocker_provider",
    "modules.heimnetz_client_blocker_provider",
]

def collect_blockers(ctx=None):
    blockers = []

    for modname in BLOCKER_PROVIDERS:
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "get_blockers"):
                result = mod.get_blockers(ctx)
                if result:
                    blockers.extend(result)
        except Exception as e:
            blockers.append({
                "source": "blocker-api",
                "type": "error",
                "title": modname,
                "reason": str(e),
                "priority": 999,
            })

    return blockers
