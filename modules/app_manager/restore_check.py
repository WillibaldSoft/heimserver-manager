# -*- coding: utf-8 -*-
import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path


def _read_json(path):
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_gzip(path):
    try:
        with gzip.open(path, "rb") as f:
            f.read(1024 * 64)
        return True, ""
    except Exception as e:
        return False, str(e)


def _check(name, ok, message="", warnings=None, errors=None, details=None):
    return {
        "name": name,
        "ok": bool(ok),
        "message": message or "",
        "warnings": warnings or [],
        "errors": errors or [],
        "details": details or {},
    }


def _restore_hint(db):
    if not db or not db.get("ok"):
        return "Kein gültiger Datenbank-Dump vorhanden."

    db_type = db.get("type")
    file_path = db.get("file")
    container = db.get("container")
    database = db.get("database")
    user = db.get("user")

    if db_type == "postgresql":
        if str(file_path).endswith(".gz"):
            return f"gzip -dc {file_path!r} | docker exec -i {container} psql -U {user} {database}"
        return f"cat {file_path!r} | docker exec -i {container} psql -U {user} {database}"

    if db_type == "mariadb":
        if str(file_path).endswith(".gz"):
            return f"gzip -dc {file_path!r} | docker exec -i {container} mariadb -u {user} {database}"
        return f"cat {file_path!r} | docker exec -i {container} mariadb -u {user} {database}"

    if db_type == "mariadb-local":
        if str(file_path).endswith(".gz"):
            return f"gzip -dc {file_path!r} | mariadb {database}"
        return f"mariadb {database} < {file_path!r}"

    if db_type == "sqlite":
        return f"SQLite-Datei zurückkopieren: {file_path}"

    return "Datenbanktyp nicht unterstützt."


def _path_writable(path):
    try:
        p = Path(path)
        if p.exists():
            return os.access(str(p), os.W_OK)
        parent = p.parent
        return parent.exists() and os.access(str(parent), os.W_OK)
    except Exception:
        return False


def _db_result_from_backup(root, result_json):
    db_result = _read_json(root / "database" / "database-result.json")
    if db_result:
        return db_result

    steps = (result_json or {}).get("steps") or {}
    db = steps.get("database") or {}
    return db if isinstance(db, dict) else {}


def _build_detail_checks(root, manifest, result_json, db_result):
    checks = []

    result_file = root / "result.json"
    manifest_file = root / "manifest.json"
    session_file = root / "session.json"

    checks.append(_check(
        "backup_dir_exists",
        root.exists() and root.is_dir(),
        "Backup-Verzeichnis vorhanden" if root.exists() else "Backup-Verzeichnis fehlt",
        errors=[] if root.exists() else [str(root)],
        details={"path": str(root)},
    ))

    checks.append(_check(
        "manifest_json",
        manifest_file.exists() and manifest is not None,
        "manifest.json vorhanden" if manifest is not None else "manifest.json fehlt oder nicht lesbar",
        errors=[] if manifest is not None else [str(manifest_file)],
    ))

    checks.append(_check(
        "result_json",
        result_file.exists() and result_json is not None,
        "result.json vorhanden" if result_json is not None else "result.json fehlt oder nicht lesbar",
        errors=[] if result_json is not None else [str(result_file)],
    ))

    checks.append(_check(
        "session_json",
        session_file.exists(),
        "session.json vorhanden" if session_file.exists() else "session.json fehlt",
        warnings=[] if session_file.exists() else ["Älteres Backup ohne Session-Datei"],
    ))

    backup_app_id = (manifest or {}).get("app_id") or (result_json or {}).get("app_id")
    checks.append(_check(
        "app_id_present",
        bool(backup_app_id),
        "App-ID im Backup vorhanden" if backup_app_id else "App-ID fehlt im Backup",
        errors=[] if backup_app_id else ["app_id fehlt"],
        details={"app_id": backup_app_id},
    ))

    steps = (result_json or {}).get("steps") or {}

    cfg = steps.get("config_files") or {}
    cfg_ok = isinstance(cfg, dict) and bool(cfg) and all(v.get("ok") for v in cfg.values())
    checks.append(_check(
        "backup_config",
        cfg_ok,
        "{} Konfigurationsdatei(en) im Backup".format(len(cfg) if isinstance(cfg, dict) else 0),
        warnings=[] if cfg_ok else ["Keine oder fehlerhafte Konfigurationsdateien im Backup"],
        details={"count": len(cfg) if isinstance(cfg, dict) else 0},
    ))

    paths = steps.get("paths") or {}
    paths_ok = isinstance(paths, dict) and bool(paths) and all(v.get("ok") for v in paths.values())
    checks.append(_check(
        "backup_data_paths",
        paths_ok,
        "{} Datenpfad(e) im Backup".format(len(paths) if isinstance(paths, dict) else 0),
        warnings=[] if paths_ok else ["Keine oder fehlerhafte Datenpfade im Backup"],
        details={"count": len(paths) if isinstance(paths, dict) else 0},
    ))

    if db_result and db_result.get("supported"):
        db_file = db_result.get("file") or db_result.get("target")
        db_file_ok = bool(db_result.get("ok")) and bool(db_file) and Path(db_file).exists()

        checks.append(_check(
            "backup_database_dump",
            db_file_ok,
            "Datenbank-Dump vorhanden" if db_file_ok else "Datenbank-Dump fehlt oder ist fehlerhaft",
            errors=[] if db_file_ok else ["DB-Datei fehlt: {}".format(db_file or "nicht definiert")],
            details={
                "type": db_result.get("type"),
                "database": db_result.get("database"),
                "file": db_file,
                "size": db_result.get("size"),
            },
        ))

        if db_file and str(db_file).endswith(".gz") and Path(db_file).exists():
            gzip_ok, gzip_error = _check_gzip(db_file)
            checks.append(_check(
                "database_gzip_valid",
                gzip_ok,
                "GZip-Dump lesbar" if gzip_ok else "GZip-Dump fehlerhaft",
                errors=[] if gzip_ok else [gzip_error],
                details={"file": db_file},
            ))

        expected = db_result.get("sha256")
        if expected and db_file and Path(db_file).exists():
            actual = _sha256(db_file)
            checks.append(_check(
                "database_sha256",
                actual == expected,
                "SHA256 korrekt" if actual == expected else "SHA256 stimmt nicht",
                errors=[] if actual == expected else ["expected={}, actual={}".format(expected, actual)],
                details={"expected": expected, "actual": actual},
            ))
    else:
        checks.append(_check(
            "backup_database_dump",
            True,
            "Keine Datenbank im Backup erforderlich",
            details={"supported": False},
        ))

    try:
        usage = shutil.disk_usage(str(root.parent))
        free_gb = round(usage.free / 1024 / 1024 / 1024, 2)
        checks.append(_check(
            "free_space",
            usage.free > 1024 * 1024 * 1024,
            "Freier Speicher: {} GB".format(free_gb),
            warnings=[] if usage.free > 1024 * 1024 * 1024 else ["Weniger als 1 GB frei"],
            details={"free_gb": free_gb},
        ))
    except Exception as e:
        checks.append(_check(
            "free_space",
            False,
            "Freier Speicher konnte nicht geprüft werden",
            errors=[str(e)],
        ))

    return checks


def _summarize_checks(checks):
    ok_count = sum(1 for c in checks if c.get("ok") and not c.get("warnings"))
    failed_count = sum(1 for c in checks if not c.get("ok"))
    warning_count = sum(1 for c in checks if c.get("warnings"))

    return {
        "total": len(checks),
        "ok": ok_count,
        "failed": failed_count,
        "warnings": warning_count,
    }


def check_backup(path):
    root = Path(path)

    result = {
        "ok": False,
        "mode": "read-only",
        "backup_path": str(root),
        "exists": root.exists(),
        "checks": {},
        "detail_checks": [],
        "check_summary": {
            "total": 0,
            "ok": 0,
            "failed": 0,
            "warnings": 0,
        },
        "restore": {},
        "warnings": [],
        "errors": [],
        "restore_possible": False,
        "readiness": {
            "score": 0,
            "level": "error",
        },
    }

    if not root.exists() or not root.is_dir():
        result["error"] = "Backup-Verzeichnis nicht gefunden"
        result["errors"].append(result["error"])
        return result

    manifest = _read_json(root / "manifest.json")
    result_json = _read_json(root / "result.json")
    db_result = _db_result_from_backup(root, result_json)

    result["manifest"] = manifest
    result["result"] = result_json
    result["database"] = db_result

    result["checks"]["manifest"] = manifest is not None
    result["checks"]["result_json"] = result_json is not None
    result["checks"]["database_result"] = bool(db_result)

    db_ok = True
    if db_result and db_result.get("file"):
        dump = Path(db_result["file"])
        result["checks"]["database_file_exists"] = dump.exists()

        if dump.exists() and str(dump).endswith(".gz"):
            gzip_ok, gzip_error = _check_gzip(dump)
            result["checks"]["gzip_valid"] = gzip_ok
            if gzip_error:
                result["checks"]["gzip_error"] = gzip_error
            db_ok = db_ok and gzip_ok

        expected = db_result.get("sha256")
        if expected and dump.exists():
            actual = _sha256(dump)
            result["checks"]["sha256_valid"] = actual == expected
            result["checks"]["sha256_expected"] = expected
            result["checks"]["sha256_actual"] = actual
            db_ok = db_ok and (actual == expected)
    else:
        result["checks"]["database_file_exists"] = None
        result["checks"]["sha256_valid"] = None

    result["restore"]["database_command"] = _restore_hint(db_result)
    result["restore"]["steps"] = [
        "Anwendung stoppen",
        "Backup-Archiv entpacken",
        "Konfigurationsdateien prüfen und bei Bedarf zurückkopieren",
        "Datenverzeichnisse prüfen und bei Bedarf zurückkopieren",
        "Datenbank-Restore-Befehl prüfen",
        "Anwendung starten",
        "Health Check ausführen",
    ]

    detail_checks = _build_detail_checks(root, manifest, result_json, db_result)
    summary = _summarize_checks(detail_checks)

    result["detail_checks"] = detail_checks
    result["checks_list"] = detail_checks
    result["check_summary"] = summary

    for c in detail_checks:
        for e in c.get("errors") or []:
            if e not in result["errors"]:
                result["errors"].append(e)
        for w in c.get("warnings") or []:
            if w not in result["warnings"]:
                result["warnings"].append(w)

    required = ["manifest", "result_json"]
    base_ok = all(result["checks"].get(k) for k in required) and db_ok
    result["ok"] = base_ok and summary["failed"] == 0
    result["restore_possible"] = result["ok"]

    if summary["failed"]:
        result["readiness"] = {
            "score": 60,
            "level": "error",
        }
    elif summary["warnings"]:
        result["readiness"] = {
            "score": 85,
            "level": "warning",
        }
    else:
        result["readiness"] = {
            "score": 100,
            "level": "good",
        }

    return result


# Kompatibilitätsalias für neuere Restore-Engine-Aufrufer
run_restore_check = check_backup

# Kompatibilitätsfunktion für Aufrufer mit (manager, backup_dir)
def run_restore_check(manager_or_path, backup_dir=None):
    path = backup_dir if backup_dir is not None else manager_or_path
    return check_backup(path)
