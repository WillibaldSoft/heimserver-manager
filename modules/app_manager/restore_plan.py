# -*- coding: utf-8 -*-
from pathlib import Path

from .restore_engine import run_restore_check


def _step(order, title, action, command=None, risk="low", details=None):
    return {
        "order": order,
        "title": title,
        "action": action,
        "command": command or "",
        "risk": risk,
        "details": details or {},
    }


def _compose_cmd(manager, cmd):
    compose_dir = getattr(manager, "compose_dir", None)

    if compose_dir:
        return f"cd {compose_dir!r} && docker compose {cmd}"

    service = getattr(manager, "service", None)

    if service:
        # Docker-Compose-Kommandos aus dem generischen Plan auf
        # die entsprechenden systemd-Aktionen abbilden.
        if cmd in ("down", "stop"):
            return f"systemctl stop {service}"

        if cmd in ("up -d", "start"):
            return f"systemctl start {service}"

        return f"systemctl {cmd} {service}"

    return ""


def _config_steps(result):
    steps = []
    backup_result = (((result.get("backup") or {}).get("details") or {}).get("result") or {})
    config_files = (((backup_result.get("steps") or {}).get("config_files")) or {})

    for key, item in config_files.items():
        src = item.get("target")
        dst = item.get("source")
        if src and dst:
            steps.append({
                "key": key,
                "backup_file": src,
                "target_file": dst,
                "command": f"cp -a {src!r} {dst!r}",
            })
    return steps


def _data_steps(result):
    steps = []
    backup_result = (((result.get("backup") or {}).get("details") or {}).get("result") or {})
    paths = (((backup_result.get("steps") or {}).get("paths")) or {})

    for key, item in paths.items():
        src = item.get("target")
        dst = item.get("source")
        if src and dst:
            steps.append({
                "key": key,
                "backup_path": src,
                "target_path": dst,
                "command": f"rsync -a --delete {src.rstrip('/')!r}/ {dst.rstrip('/')!r}/",
            })
    return steps


def run_restore_plan(manager, backup_dir):
    """
    Erstellt einen vollständigen Restore-Plan.
    Es werden keinerlei Änderungen am System vorgenommen.
    """

    backup_path = Path(backup_dir)
    readiness = run_restore_check(manager, backup_path)

    backup_details = readiness.get("backup", {}).get("details", {})
    db_command = (
        (backup_details.get("restore") or {})
        .get("database_command")
        or ""
    )

    database_details = (
        readiness.get("database", {}).get("details", {})
        or {}
    )

    database_backup = (
        database_details.get("backup")
        or {}
    )

    database_definition = (
        database_details.get("definition")
        or database_backup.get("definition")
        or {}
    )

    db_type = str(
        database_definition.get("type")
        or database_backup.get("type")
        or ""
    ).strip().lower()

    # Nur Datenbank-Restores einplanen, die vom aktuellen
    # Restore-Executor tatsächlich als Shell-Befehl ausgeführt
    # werden können.
    #
    # Ein Hinweistext wie "Datenbanktyp nicht unterstützt." darf
    # keinesfalls als Restore-Befehl interpretiert werden.
    executable_db_types = {
        "postgresql",
        "mariadb",
        "mariadb-local",
    }

    database_restore = bool(
        database_backup.get("supported") is True
        and database_backup.get("ok") is True
        and db_type in executable_db_types
        and db_command
    )

    config_steps = _config_steps(readiness)
    data_steps = _data_steps(readiness)

    steps = [
        _step(
            1,
            "Anwendung stoppen",
            "stop_application",
            _compose_cmd(manager, "down") or _compose_cmd(manager, "stop"),
            "medium",
        ),
        _step(
            2,
            "Rollback-Punkt erzeugen",
            "create_rollback_backup",
            "",
            "low",
            {
                "description": "Vor einem echten Restore sollte automatisch ein aktuelles Backup erzeugt werden.",
                "planned": True,
            },
        ),
        _step(
            3,
            "Konfiguration wiederherstellen",
            "restore_config",
            "",
            "medium",
            {"files": config_steps},
        ),
        _step(
            4,
            "Datenverzeichnisse wiederherstellen",
            "restore_data",
            "",
            "high",
            {"paths": data_steps},
        ),
    ]

    if database_restore:
        steps.append(
            _step(
                5,
                "Datenbank wiederherstellen",
                "restore_database",
                db_command,
                "high",
                {
                    "available": True,
                    "database": database_details,
                },
            )
        )

    steps.extend([
        _step(
            6,
            "Anwendung starten",
            "start_application",
            _compose_cmd(manager, "up -d") or _compose_cmd(manager, "start"),
            "medium",
        ),
        _step(
            7,
            "Health Check ausführen",
            "health_check",
            "",
            "low",
            {
                "current_health": readiness.get("application", {}).get("details", {}).get("health", {}),
            },
        ),
    ])

    summary = {
        "config_files": len(config_steps),
        "data_paths": len(data_steps),
        "database_restore": database_restore,
        "database_type": db_type or None,
        "risk": (
            "high"
            if data_steps or database_restore
            else "medium"
        ),
        "estimated_duration": "abhängig von Datenmenge",
    }

    return {
        "mode": "dry-run",
        "restore_possible": readiness.get("restore_possible", False),
        "readiness": readiness.get("readiness", {}),
        "backup": str(backup_path),
        "steps": steps,
        "summary": summary,
        "warnings": readiness.get("warnings", []),
        "errors": readiness.get("errors", []),
    }
