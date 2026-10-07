# -*- coding: utf-8 -*-
import gzip
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .runner import sh


def _safe_name(value):
    s = str(value or "database").strip().lower()
    out = []
    for c in s:
        if c.isalnum() or c in ("-", "_"):
            out.append(c)
        else:
            out.append("_")
    return "".join(out).strip("_") or "database"


def _size(path):
    return sh(f"du -sh {str(path)!r} 2>/dev/null | awk '{{print $1}}' || true", timeout=30)["stdout"]


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _gzip_file(src):
    src = Path(src)
    dst = src.with_suffix(src.suffix + ".gz")
    with open(src, "rb") as fin, gzip.open(dst, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    src.unlink()
    return dst


def _write_checksum(path):
    checksum = _sha256(path)
    checksum_file = Path(str(path) + ".sha256")
    checksum_file.write_text(f"{checksum}  {Path(path).name}\n", encoding="utf-8")
    return checksum, checksum_file


def _postgres_version(container):
    if not container:
        return ""
    return sh(
        f"docker exec {container} sh -lc 'pg_dump --version 2>/dev/null || psql --version 2>/dev/null || true'",
        timeout=15
    )["stdout"]


def _mariadb_version(container=None):
    if container:
        return sh(
            f"docker exec {container} sh -lc 'mariadb-dump --version 2>/dev/null || mysqldump --version 2>/dev/null || true'",
            timeout=15
        )["stdout"]
    return sh("mariadb-dump --version 2>/dev/null || mysqldump --version 2>/dev/null || true", timeout=15)["stdout"]


def run_database_backup(manager, target_dir):
    db = getattr(manager, "database", None)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().isoformat(timespec="seconds")

    if not db:
        result = {
            "supported": False,
            "ok": True,
            "message": "Keine Datenbankdefinition hinterlegt",
            "created_at": created_at,
        }
        _write_json(target / "database-result.json", result)
        return result

    db_type = db.get("type")
    container = db.get("container")
    database = db.get("database") or "database"
    user = db.get("user")
    dump_cmd = db.get("dump")
    source_file = db.get("file")

    raw_sql = target / f"{_safe_name(database)}.sql"

    result = {
        "supported": True,
        "ok": False,
        "type": db_type,
        "database": database,
        "user": user,
        "container": container,
        "created_at": created_at,
        "compressed": True,
        "compression": "gzip",
    }

    if db_type == "nextcloud-docker":
        return manager.database_backup(target)

    if db_type in ("postgresql", "mariadb"):
        if not container or not dump_cmd:
            result.update({
                "supported": False,
                "message": f"{db_type} benötigt container und dump",
                "definition": db,
            })
        else:
            cmd = "docker exec {} sh -lc {} > {}".format(
                container,
                json.dumps(dump_cmd),
                json.dumps(str(raw_sql)),
            )
            r = sh(cmd, timeout=1800)
            result.update({
                "command": cmd,
                "returncode": r.get("returncode"),
                "stderr": r.get("stderr"),
                "engine_version": _postgres_version(container) if db_type == "postgresql" else _mariadb_version(container),
            })

            if r.get("returncode") == 0 and raw_sql.exists():
                gz = _gzip_file(raw_sql)
                checksum, checksum_file = _write_checksum(gz)
                result.update({
                    "ok": True,
                    "file": str(gz),
                    "size": _size(gz),
                    "sha256": checksum,
                    "sha256_file": str(checksum_file),
                })

    elif db_type == "mariadb-local":
        if not dump_cmd:
            result.update({
                "supported": False,
                "message": "mariadb-local benötigt dump",
                "definition": db,
            })
        else:
            cmd = "{} > {}".format(dump_cmd, json.dumps(str(raw_sql)))
            r = sh(cmd, timeout=1800)
            result.update({
                "command": cmd,
                "returncode": r.get("returncode"),
                "stderr": r.get("stderr"),
                "engine_version": _mariadb_version(None),
            })

            if r.get("returncode") == 0 and raw_sql.exists():
                gz = _gzip_file(raw_sql)
                checksum, checksum_file = _write_checksum(gz)
                result.update({
                    "ok": True,
                    "file": str(gz),
                    "size": _size(gz),
                    "sha256": checksum,
                    "sha256_file": str(checksum_file),
                })

    elif db_type == "sqlite":
        result["compression"] = "none"
        result["compressed"] = False
        if not source_file:
            result.update({
                "supported": False,
                "message": "SQLite benötigt file",
                "definition": db,
            })
        else:
            src = Path(source_file)
            dst = target / src.name
            if src.exists():
                try:
                    with sqlite3.connect(src.resolve().as_uri()+'?mode=ro',uri=True,timeout=30) as source_db, sqlite3.connect(dst) as backup_db:
                        source_db.backup(backup_db)
                        if backup_db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise sqlite3.DatabaseError('Integritätsprüfung fehlgeschlagen')
                    dst.chmod(0o600)
                except (sqlite3.Error,OSError) as exc:
                    result.update(message='SQLite-Sicherung fehlgeschlagen: '+str(exc))
                    _write_json(target / 'database-result.json', result)
                    return result
                checksum, checksum_file = _write_checksum(dst)
                result.update({
                    "ok": True,
                    "file": str(dst),
                    "size": _size(dst),
                    "source": str(src),
                    "sha256": checksum,
                    "sha256_file": str(checksum_file),
                })
            else:
                result.update({
                    "message": "SQLite-Datei fehlt",
                    "source": str(src),
                })

    else:
        result.update({
            "supported": False,
            "message": "Datenbanktyp nicht unterstützt",
            "definition": db,
        })

    _write_json(target / "database-result.json", result)
    return result
