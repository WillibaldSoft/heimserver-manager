# -*- coding: utf-8 -*-

def database_check(manager):
    db = getattr(manager, "database", None)
    if not db:
        return {
            "supported": False,
            "message": "Keine Datenbankdefinition hinterlegt",
        }

    return {
        "supported": True,
        "mode": "read-only",
        "type": db.get("type", ""),
        "container": db.get("container", ""),
        "database": db.get("database", ""),
        "user": db.get("user", ""),
        "dump": db.get("dump", ""),
        "message": "Phase 5.1: Datenbank-Dump vorbereitet, Ausführung noch deaktiviert",
    }
