# -*- coding: utf-8 -*-
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .restore_plan import run_restore_plan
from .runner import sh


def _check(name, ok=True, message="", details=None, warnings=None, errors=None):
    return {
        "name": name,
        "ok": bool(ok),
        "message": message,
        "details": details or {},
        "warnings": warnings or [],
        "errors": errors or [],
    }


def _sha256_file(path):
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_info(path):
    p = Path(path or "")
    info = {
        "path": str(p),
        "exists": p.exists(),
        "is_file": p.is_file(),
        "size": None,
        "sha256": "",
    }

    if p.exists() and p.is_file():
        info["size"] = p.stat().st_size
        info["sha256"] = _sha256_file(p)

    return info


def _dir_info(path):
    p = Path(path or "")
    info = {
        "path": str(p),
        "exists": p.exists(),
        "is_dir": p.is_dir(),
        "readable": False,
        "writable": False,
        "size_human": "",
        "file_count": None,
        "dir_count": None,
    }

    if not p.exists():
        return info

    info["readable"] = sh(f"test -r {str(p)!r} && echo yes || echo no", timeout=10).get("stdout") == "yes"
    info["writable"] = sh(f"test -w {str(p)!r} && echo yes || echo no", timeout=10).get("stdout") == "yes"
    info["size_human"] = sh(f"du -sh {str(p)!r} 2>/dev/null | awk '{{print $1}}' || true", timeout=60).get("stdout")
    info["file_count"] = int((sh(f"find {str(p)!r} -type f 2>/dev/null | wc -l", timeout=60).get("stdout") or "0").strip() or 0)
    info["dir_count"] = int((sh(f"find {str(p)!r} -type d 2>/dev/null | wc -l", timeout=60).get("stdout") or "0").strip() or 0)

    return info


def _read_json_file(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _health_checks(manager):
    checks = []

    errors = []
    warnings = []
    details = {}

    if not hasattr(manager, "health"):
        checks.append(_check(
            "health",
            ok=True,
            message="Kein Health-Check definiert",
            details={"supported": False},
        ))
        return checks

    try:
        health = manager.health()

        details = health if isinstance(health, dict) else {"result": health}

        ok = bool(details.get("ok", True))

        if not ok:
            errors.append("Health-Check meldet Fehler")

        checks.append(_check(
            "health",
            ok=ok,
            message="Health-Check ausgeführt",
            details=details,
            warnings=warnings,
            errors=errors,
        ))

    except Exception as e:
        checks.append(_check(
            "health",
            ok=False,
            message="Health-Check fehlgeschlagen",
            details={},
            errors=[str(e)],
        ))

    return checks


def _database_checks(manager, backup_dir):
    checks = []
    db = getattr(manager, "database", None)
    backup_db = _read_json_file(Path(backup_dir) / "database" / "database-result.json")

    if not db:
        checks.append(_check(
            "database",
            ok=True,
            message="Keine Datenbank für diese App definiert",
            details={"configured": False},
        ))
        return checks

    details = {
        "configured": True,
        "definition": db,
        "backup": backup_db or {},
        "current": {},
        "comparison": {},
    }

    errors = []
    warnings = []

    if not backup_db:
        errors.append("Backup-Datenbankresultat fehlt")
    elif not backup_db.get("ok"):
        errors.append("Backup-Datenbankdump war nicht erfolgreich")

    db_type = db.get("type")
    container = db.get("container")
    database = db.get("database")
    user = db.get("user")

    if backup_db:
        dump_file = backup_db.get("file")
        if dump_file:
            dump_path = Path(dump_file)
            details["dump_file"] = {
                "path": str(dump_path),
                "exists": dump_path.exists(),
                "size": dump_path.stat().st_size if dump_path.exists() else None,
            }
            if not dump_path.exists():
                errors.append("Datenbankdump-Datei fehlt")
        else:
            errors.append("Datenbankdump-Datei nicht im Backup-Resultat angegeben")

    if db_type in ("postgresql", "mariadb"):
        if not container:
            errors.append("Datenbankcontainer nicht definiert")
        else:
            inspect = sh(
                "docker inspect -f '{{.Name}} {{.State.Status}}' " + str(container) + " 2>/dev/null || true",
                timeout=10
            ).get("stdout")
            exists = bool(inspect)
            running = " running" in inspect

            details["current"]["container"] = {
                "name": container,
                "exists": exists,
                "running": running,
                "inspect": inspect,
            }

            if not exists:
                errors.append("Datenbankcontainer fehlt")
            elif not running:
                errors.append("Datenbankcontainer läuft nicht")

        if container and db_type == "postgresql":
            reachable = sh(
                f"docker exec {container} sh -lc 'pg_isready -U {user} -d {database}' >/dev/null 2>&1 && echo yes || echo no",
                timeout=15
            ).get("stdout") == "yes"
            details["current"]["reachable"] = reachable
            if not reachable:
                errors.append("PostgreSQL nicht erreichbar")

        if container and db_type == "mariadb":
            reachable = sh(
                f"docker exec {container} sh -lc 'mariadb-admin ping -u {user} --silent' >/dev/null 2>&1 && echo yes || echo no",
                timeout=15
            ).get("stdout") == "yes"
            details["current"]["reachable"] = reachable
            if not reachable:
                errors.append("MariaDB nicht erreichbar")

    if backup_db:
        details["comparison"] = {
            "type_equal": backup_db.get("type") == db_type,
            "database_equal": backup_db.get("database") == database,
            "user_equal": backup_db.get("user") == user,
            "container_equal": backup_db.get("container") == container,
        }

        for key, label in (
            ("type_equal", "Datenbanktyp weicht ab"),
            ("database_equal", "Datenbankname weicht ab"),
            ("user_equal", "Datenbankuser weicht ab"),
            ("container_equal", "Datenbankcontainer weicht ab"),
        ):
            if details["comparison"].get(key) is False:
                warnings.append(label)

    checks.append(_check(
        "database",
        ok=len(errors) == 0,
        message="Datenbank geprüft",
        details=details,
        warnings=warnings,
        errors=errors,
    ))

    return checks


def _data_path_checks(plan):
    checks = []

    for step in plan.get("steps") or []:
        if step.get("action") != "restore_data":
            continue

        paths = ((step.get("details") or {}).get("paths") or [])

        if not paths:
            checks.append(_check(
                "data_paths",
                ok=True,
                message="Keine Datenpfade im Restore-Plan",
                details={},
            ))
            continue

        for item in paths:
            backup_path = item.get("backup_path")
            target_path = item.get("target_path")

            binfo = _dir_info(backup_path)
            tinfo = _dir_info(target_path)

            errors = []
            warnings = []

            if not binfo["exists"]:
                errors.append("Backup-Datenpfad fehlt")
            elif not binfo["is_dir"]:
                errors.append("Backup-Datenpfad ist kein Verzeichnis")

            if not tinfo["exists"]:
                warnings.append("Ziel-Datenpfad fehlt aktuell")
            elif not tinfo["is_dir"]:
                warnings.append("Ziel-Datenpfad ist kein Verzeichnis")

            if binfo["exists"] and not binfo["readable"]:
                errors.append("Backup-Datenpfad nicht lesbar")

            if tinfo["exists"] and not tinfo["writable"]:
                warnings.append("Ziel-Datenpfad nicht beschreibbar")

            file_count_equal = (
                binfo["file_count"] is not None
                and tinfo["file_count"] is not None
                and binfo["file_count"] == tinfo["file_count"]
            )

            checks.append(_check(
                "data_path",
                ok=len(errors) == 0,
                message="Datenpfad geprüft",
                details={
                    "key": item.get("key"),
                    "backup_path": binfo,
                    "target_path": tinfo,
                    "file_count_equal": file_count_equal,
                    "command": item.get("command", ""),
                },
                warnings=warnings,
                errors=errors,
            ))

    return checks


def _config_checks(plan):
    checks = []

    for step in plan.get("steps") or []:
        if step.get("action") != "restore_config":
            continue

        files = ((step.get("details") or {}).get("files") or [])

        if not files:
            checks.append(_check(
                "config_files",
                ok=True,
                message="Keine Konfigurationsdateien im Restore-Plan",
                details={},
            ))
            continue

        for item in files:
            backup_file = item.get("backup_file")
            target_file = item.get("target_file")

            binfo = _file_info(backup_file)
            tinfo = _file_info(target_file)

            errors = []
            warnings = []

            if not binfo["exists"]:
                errors.append("Backup-Konfigurationsdatei fehlt")
            if not tinfo["exists"]:
                warnings.append("Ziel-Konfigurationsdatei fehlt aktuell")

            size_equal = (
                binfo["size"] is not None
                and tinfo["size"] is not None
                and binfo["size"] == tinfo["size"]
            )

            sha_equal = (
                bool(binfo["sha256"])
                and bool(tinfo["sha256"])
                and binfo["sha256"] == tinfo["sha256"]
            )

            checks.append(_check(
                "config_file",
                ok=len(errors) == 0,
                message="Konfigurationsdatei geprüft",
                details={
                    "key": item.get("key"),
                    "backup_file": binfo,
                    "target_file": tinfo,
                    "size_equal": size_equal,
                    "sha256_equal": sha_equal,
                    "command": item.get("command", ""),
                },
                warnings=warnings,
                errors=errors,
            ))

    return checks


def _summary(checks):
    total = len(checks)
    ok = len([c for c in checks if c.get("ok")])
    failed = total - ok
    warnings = sum(len(c.get("warnings") or []) for c in checks)
    errors = sum(len(c.get("errors") or []) for c in checks)

    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "warnings": warnings,
        "errors": errors,
    }


def run_restore_verification(manager, backup_dir, run_dir=None):
    """
    Verification-Engine Phase 5.5.1.

    Prüft noch nicht tief, sondern erzeugt einen standardisierten
    Verifikationsreport als Grundlage für spätere Prüfungen.
    """

    backup_path = Path(backup_dir)
    run_path = Path(run_dir) if run_dir else None

    checks = []

    checks.append(_check(
        "backup_dir",
        ok=backup_path.exists() and backup_path.is_dir(),
        message="Backup-Verzeichnis vorhanden" if backup_path.exists() else "Backup-Verzeichnis fehlt",
        details={"path": str(backup_path)},
        errors=[] if backup_path.exists() else ["Backup-Verzeichnis fehlt"],
    ))

    if run_path:
        checks.append(_check(
            "run_dir",
            ok=run_path.exists() and run_path.is_dir(),
            message="Restore-Run-Verzeichnis vorhanden" if run_path.exists() else "Restore-Run-Verzeichnis fehlt",
            details={"path": str(run_path)},
            errors=[] if run_path.exists() else ["Restore-Run-Verzeichnis fehlt"],
        ))

    plan = None
    try:
        plan = run_restore_plan(manager, str(backup_path))
        checks.append(_check(
            "restore_plan",
            ok=bool(plan.get("restore_possible")),
            message="Restore-Plan ist verfügbar",
            details={
                "restore_possible": plan.get("restore_possible"),
                "steps": len(plan.get("steps") or []),
                "summary": plan.get("summary") or {},
            },
            warnings=plan.get("warnings") or [],
            errors=plan.get("errors") or [],
        ))

        checks.extend(_config_checks(plan))
        checks.extend(_data_path_checks(plan))
        checks.extend(_database_checks(manager, backup_path))
        checks.extend(_health_checks(manager))
    except Exception as e:
        checks.append(_check(
            "restore_plan",
            ok=False,
            message="Restore-Plan konnte nicht erzeugt werden",
            errors=[str(e)],
        ))

    summary = _summary(checks)
    errors = []
    warnings = []

    for c in checks:
        errors.extend(c.get("errors") or [])
        warnings.extend(c.get("warnings") or [])

    return {
        "ok": summary["errors"] == 0 and summary["failed"] == 0,
        "mode": "verification",
        "phase": "5.5.1",
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "backup_dir": str(backup_path),
        "run_dir": str(run_path) if run_path else "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
