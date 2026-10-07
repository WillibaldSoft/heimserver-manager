# -*- coding: utf-8 -*-

def repair_check(manager):
    return {
        "supported": True,
        "mode": "read-only",
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "checks": [
            "Status prüfen",
            "Health prüfen",
            "Konfigurationsdateien prüfen",
            "Datenpfade prüfen",
            "Logs prüfen",
        ],
        "message": "Phase 5.1: Repair-Check vorbereitet, Reparatur-Ausführung noch deaktiviert",
    }
