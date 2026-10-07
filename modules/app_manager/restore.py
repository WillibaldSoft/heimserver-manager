# -*- coding: utf-8 -*-

def restore_info(manager):
    return {
        "supported": True,
        "mode": "documentation-only",
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "steps": [
            "Dienst/Container stoppen",
            "Konfiguration wiederherstellen",
            "Datenverzeichnisse wiederherstellen",
            "Datenbank-Dump zurückspielen, falls vorhanden",
            "Dienst/Container starten",
            "Health Check ausführen",
        ],
        "warning": "Phase 5.1: Restore ist nur dokumentiert, automatische Wiederherstellung ist deaktiviert",
    }
