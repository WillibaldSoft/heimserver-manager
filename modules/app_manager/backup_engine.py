from server_settings import get as host_setting
# -*- coding: utf-8 -*-
import json
import os
import shutil
import socket
import tarfile
from datetime import datetime
from pathlib import Path

from .runner import sh
from .database_engine import run_database_backup

BACKUP_ROOT = Path(host_setting("backup_root"))

DEFAULT_BACKUP_PROFILES = {
    "system": {
        "id": "system",
        "label": "Systembackup",
        "description": "Sichert Konfiguration, Datenbank und Zusatzinformationen.",
        "config": True,
        "data": False,
        "database": True,
        "extra": True,
        "incremental": False,
    },
    "data": {
        "id": "data",
        "label": "Datenbackup (inkrementell)",
        "description": "Sichert nur Nutzdaten. Inkrementelle Sicherung ist vorbereitet.",
        "config": False,
        "data": True,
        "database": False,
        "extra": False,
        "incremental": True,
    },
    "full": {
        "id": "full",
        "label": "Komplettbackup",
        "description": "Sichert Konfiguration, Daten, Datenbank und Zusatzinformationen.",
        "config": True,
        "data": True,
        "database": True,
        "extra": True,
        "incremental": False,
    },
}


def get_backup_profiles(manager=None):
    profiles = dict(DEFAULT_BACKUP_PROFILES)
    custom = getattr(manager, "backup_profiles", None) if manager else None
    if isinstance(custom, dict):
        for key, value in custom.items():
            if isinstance(value, dict):
                base = dict(profiles.get(key, {}))
                base.update(value)
                profiles[key] = base
    return profiles


def get_backup_profile(manager, profile):
    profiles = get_backup_profiles(manager)
    profile = str(profile or "system").strip().lower()
    if profile not in profiles:
        profile = "system"
    return profiles[profile]




def _session_path(work_dir):
    return Path(work_dir) / "session.json"


def _new_session(manager, work_dir, ts, profile_data=None):
    now_s = datetime.now().isoformat(timespec="seconds")
    return {
        "id": "{}_{}_{}".format(_safe_name(getattr(manager, "app_id", "app")), ts, socket.gethostname()),
        "app_id": _safe_name(getattr(manager, "app_id", "app")),
        "label": getattr(manager, "label", ""),
        "mode": "backup",
        "profile": (profile_data or {}).get("id", "system"),
        "profile_label": (profile_data or {}).get("label", "Systembackup"),
        "profile_incremental": bool((profile_data or {}).get("incremental", False)),
        "state": "created",
        "current_step": None,
        "current_action": None,
        "started_at": now_s,
        "updated_at": now_s,
        "finished_at": None,
        "work_dir": str(work_dir),
        "archive": None,
        "steps": [],
        "statistics": {
            "total": 0,
            "ok": 0,
            "failed": 0,
            "blocked": 0,
            "skipped": 0,
            "simulated": 0,
        },
    }


def _session_update(session, work_dir, state=None, current_step=None, current_action=None):
    if state:
        session["state"] = state
    session["current_step"] = current_step
    session["current_action"] = current_action
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_session_path(work_dir), session)


def _session_progress(session, work_dir, **kwargs):
    for k, v in kwargs.items():
        session[k] = v
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_session_path(work_dir), session)


def _session_add_step(session, work_dir, step):
    session["steps"].append(step)
    stats = session["statistics"]
    stats["total"] += 1

    status = step.get("status")
    if status == "executed":
        stats["ok"] += 1
    elif status == "failed":
        stats["failed"] += 1
    elif status == "blocked":
        stats["blocked"] += 1
    elif status == "skipped":
        stats["skipped"] += 1
    elif status == "simulated":
        stats["simulated"] += 1

    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_session_path(work_dir), session)


def _safe_name(value):
    s = str(value or "app").strip().lower()
    out = []
    for c in s:
        if c.isalnum() or c in ("-", "_"):
            out.append(c)
        else:
            out.append("_")
    return "".join(out).strip("_") or "app"


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_file(src, dst_dir):
    src = Path(src)
    dst_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        return {"source": str(src), "ok": False, "error": "missing"}

    dst = dst_dir / src.name
    try:
        shutil.copy2(src, dst)
        return {"source": str(src), "target": str(dst), "ok": True}
    except Exception as e:
        return {"source": str(src), "target": str(dst), "ok": False, "error": str(e)}


def _copy_dir(src, dst_dir):
    src = Path(src)
    dst_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        return {"source": str(src), "ok": False, "error": "missing"}

    dst = dst_dir / src.name

    try:
        if dst.exists():
            shutil.rmtree(dst)

        def _ignore_errors(directory, names):
            ignored = []
            for name in names:
                p = Path(directory) / name
                try:
                    # typische problematische Laufzeit-/Lock-Dateien nicht hart scheitern lassen
                    if p.is_socket() or p.is_fifo():
                        ignored.append(name)
                except Exception:
                    ignored.append(name)
            return ignored

        shutil.copytree(src, dst, symlinks=True, ignore=_ignore_errors)
        return {"source": str(src), "target": str(dst), "ok": True}
    except Exception as e:
        return {"source": str(src), "target": str(dst), "ok": False, "error": str(e)}


def _database_dump(manager, out_dir):
    db = getattr(manager, "database", None)
    if not db:
        return {"supported": False, "message": "Keine Datenbankdefinition"}

    out_dir.mkdir(parents=True, exist_ok=True)

    db_type = db.get("type")
    container = db.get("container")
    database = db.get("database")
    user = db.get("user")
    dump_cmd = db.get("dump")

    if db_type == "postgresql" and container and dump_cmd:
        target = out_dir / "{}.sql".format(_safe_name(database))
        cmd = "docker exec {} sh -lc {} > {}".format(
            container,
            json.dumps(dump_cmd),
            json.dumps(str(target)),
        )
        r = sh(cmd, timeout=900)
        return {
            "supported": True,
            "type": db_type,
            "container": container,
            "database": database,
            "user": user,
            "target": str(target),
            "ok": r.get("returncode") == 0,
            "returncode": r.get("returncode"),
            "stderr": r.get("stderr"),
        }

    return {
        "supported": False,
        "message": "Datenbanktyp noch nicht unterstützt",
        "definition": db,
    }


def _file_snapshot(path_root):
    root = Path(path_root)
    items = {}

    if not root.exists():
        return items

    if root.is_file():
        st = root.stat()
        items[root.name] = {
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "type": "file",
        }
        return items

    for p in root.rglob("*"):
        try:
            rel = str(p.relative_to(root))
            st = p.stat()
            if p.is_file():
                items[rel] = {
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "type": "file",
                }
            elif p.is_dir():
                items[rel] = {
                    "size": 0,
                    "mtime": int(st.st_mtime),
                    "type": "dir",
                }
        except Exception:
            continue

    return items


def _rsync_incremental_data(app_id, ts, paths, progress_cb=None):
    snap_root = BACKUP_ROOT / app_id / "data_snapshots"
    snap_root.mkdir(parents=True, exist_ok=True)

    snapshot_dir = snap_root / ts
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    latest_link = snap_root / "latest"
    previous = None
    if latest_link.exists() or latest_link.is_symlink():
        try:
            previous = latest_link.resolve()
            if not previous.exists():
                previous = None
        except Exception:
            previous = None

    results = {}

    for key, src in (paths or {}).items():
        src_path = Path(src)
        dst_path = snapshot_dir / _safe_name(key)

        if not src_path.exists():
            results[key] = {
                "source": str(src_path),
                "target": str(dst_path),
                "ok": False,
                "error": "source missing",
            }
            continue

        link_dest = ""
        if previous:
            prev_target = previous / _safe_name(key)
            if prev_target.exists():
                link_dest = "--link-dest={}".format(str(prev_target))

        cmd = "rsync -aHAX --numeric-ids --delete --info=stats2,name0 {} {}/ {}/".format(
            link_dest,
            str(src_path).rstrip("/"),
            str(dst_path).rstrip("/"),
        )

        if progress_cb:
            progress_cb({
                "state": "data",
                "current_step": 3,
                "current_action": "paths",
                "current_detail": "rsync läuft",
                "current_path_key": key,
                "current_source": str(src_path),
                "current_target": str(dst_path),
                "current_command": cmd,
            })

        try:
            r = sh(cmd, timeout=86400)
        except Exception as e:
            r = {
                "returncode": 124,
                "stdout": "",
                "stderr": str(e),
            }

        if progress_cb:
            progress_cb({
                "state": "data",
                "current_step": 3,
                "current_action": "paths",
                "current_detail": "rsync abgeschlossen" if r.get("returncode") == 0 else "rsync fehlgeschlagen",
                "current_path_key": key,
                "current_source": str(src_path),
                "current_target": str(dst_path),
                "current_returncode": r.get("returncode"),
            })

        results[key] = {
            "source": str(src_path),
            "target": str(dst_path),
            "ok": r.get("returncode") == 0,
            "returncode": r.get("returncode"),
            "stderr": r.get("stderr"),
            "stdout": r.get("stdout"),
            "link_dest": link_dest,
            "previous_snapshot": str(previous) if previous else None,
        }

    if latest_link.exists() or latest_link.is_symlink():
        try:
            latest_link.unlink()
        except Exception:
            pass

    try:
        latest_link.symlink_to(snapshot_dir)
    except Exception:
        pass

    return {
        "snapshot_root": str(snap_root),
        "snapshot_dir": str(snapshot_dir),
        "previous_snapshot": str(previous) if previous else None,
        "latest": str(latest_link),
        "paths": results,
        "ok": all(x.get("ok") for x in results.values()) if results else True,
    }


def _create_data_snapshot(manager, work_dir, copied_paths, profile_data):
    data_dir = Path(work_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile_data.get("id", "system"),
        "profile_label": profile_data.get("label", ""),
        "incremental": bool(profile_data.get("incremental", False)),
        "paths": {},
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
    }

    for key, info in (copied_paths or {}).items():
        target = info.get("target") if isinstance(info, dict) else None
        source = info.get("source") if isinstance(info, dict) else None
        ok = bool(info.get("ok")) if isinstance(info, dict) else False

        entry = {
            "source": source,
            "target": target,
            "ok": ok,
            "items": {},
            "file_count": 0,
            "dir_count": 0,
            "bytes": 0,
        }

        if ok and target:
            items = _file_snapshot(target)
            entry["items"] = items
            entry["file_count"] = sum(1 for x in items.values() if x.get("type") == "file")
            entry["dir_count"] = sum(1 for x in items.values() if x.get("type") == "dir")
            entry["bytes"] = sum(int(x.get("size", 0) or 0) for x in items.values() if x.get("type") == "file")

        snapshot["paths"][key] = entry
        snapshot["total_files"] += entry["file_count"]
        snapshot["total_dirs"] += entry["dir_count"]
        snapshot["total_bytes"] += entry["bytes"]

    _write_json(data_dir / ".snapshot.json", snapshot)
    return snapshot


def _find_last_full_backup(app_id):
    root = BACKUP_ROOT / app_id
    if not root.exists():
        return None

    candidates = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if data.get("profile") == "full":
                candidates.append((d.stat().st_mtime, d.name, data))
        except Exception:
            continue

    if not candidates:
        return None

    candidates.sort(reverse=True)
    _, run_id, data = candidates[0]
    return {
        "run": run_id,
        "profile": data.get("profile"),
        "profile_label": data.get("profile_label"),
        "archive": data.get("archive"),
        "timestamp": data.get("timestamp"),
    }


def _write_data_manifest(manager, work_dir, result, profile_data, snapshot=None):
    app_id = result.get("app_id")
    data_dir = Path(work_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    mode = "none"
    if profile_data.get("data"):
        mode = "incremental-prepared" if profile_data.get("incremental") else "full"

    base_backup = _find_last_full_backup(app_id) if profile_data.get("incremental") else None

    inc = result.get("incremental_result") or {}

    data_backup = {
        "enabled": bool(profile_data.get("data", False)),
        "mode": mode,
        "incremental": bool(profile_data.get("incremental", False)),
        "base_backup": base_backup,
        "incremental_snapshot": inc,
        "snapshot_dir": inc.get("snapshot_dir"),
        "previous_snapshot": inc.get("previous_snapshot"),
        "snapshot_created": bool(snapshot),
        "snapshot_file": str(data_dir / ".snapshot.json") if snapshot else None,
        "manifest_file": str(data_dir / "manifest.json"),
        "changed_files": 0,
        "deleted_files": 0,
        "total_files": (snapshot or {}).get("total_files", 0),
        "total_dirs": (snapshot or {}).get("total_dirs", 0),
        "total_bytes": (snapshot or {}).get("total_bytes", 0),
        "message": "Inkrementelle Sicherung vorbereitet" if profile_data.get("incremental") else (
            "Vollständige Datensicherung vorbereitet" if profile_data.get("data") else "Profil enthält keine Datenpfade"
        ),
    }

    _write_json(data_dir / "manifest.json", data_backup)

    if profile_data.get("id") == "full":
        last = {
            "run": Path(work_dir).name,
            "profile": "full",
            "profile_label": profile_data.get("label"),
            "archive": result.get("archive"),
            "timestamp": result.get("timestamp"),
            "work_dir": str(work_dir),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_json(BACKUP_ROOT / app_id / "last_full_backup.json", last)

    return data_backup


def _make_tar(src_dir):
    src_dir = Path(src_dir)
    archive = src_dir.with_suffix(".tar.gz")
    fd=os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        with tarfile.open(fileobj=stream,mode='w:gz') as tar:
            tar.add(src_dir, arcname=src_dir.name)
    return archive


def _manifest(manager, result):
    steps = result.get("steps", {})
    contains = []
    for key in ("config_files", "paths", "database", "extra"):
        if key in steps:
            contains.append(key)

    return {
        "backup_version": "5.3",
        "app_id": result.get("app_id"),
        "label": result.get("label"),
        "timestamp": result.get("timestamp"),
        "hostname": result.get("hostname"),
        "profile": result.get("profile"),
        "profile_label": result.get("profile_label"),
        "profile_incremental": result.get("profile_incremental"),
        "contains": contains,
        "archive": result.get("archive"),
        "archive_size": result.get("archive_size"),
        "database": steps.get("database"),
        "data_backup": result.get("data_backup", {}),
    }


def run_backup(manager, profile="system"):
    # Existing managers use exactly the original path. Docker Nextcloud additionally
    # needs a consistent database/files snapshot while its application is stopped.
    hook=getattr(manager,"backup_context",None)
    if hook is None:
        return _run_backup(manager,profile)
    result=None
    try:
        with hook():
            result=_run_backup(manager,profile)
        return result
    except Exception:
        if result is not None:
            result['ok']=False
            session=result['session']
            _session_add_step(session,Path(result['work_dir']),dict(order=7,title='Dienst wieder starten',action='resume',status='failed',changed=True,message='Dienst oder Wartungsmodus nach Sicherung nachprüfen.'))
            _session_update(session,Path(result['work_dir']),state='failed',current_action='resume')
            _write_json(Path(result['work_dir'])/'result.json',result)
        raise


def _run_backup(manager, profile="system"):
    profile_data = get_backup_profile(manager, profile)
    profile_id = profile_data.get("id", "system")
    profile_label = profile_data.get("label", "Systembackup")

    app_id = _safe_name(getattr(manager, "app_id", "app"))
    label = getattr(manager, "label", app_id)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    work_dir = BACKUP_ROOT / app_id / ts
    work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    session = _new_session(manager, work_dir, ts, profile_data)
    _session_update(session, work_dir, state="created")

    result = {
        "ok": True,
        "mode": "executed",
        "profile": profile_id,
        "profile_label": profile_label,
        "profile_incremental": bool(profile_data.get("incremental", False)),
        "app_id": app_id,
        "label": label,
        "timestamp": ts,
        "work_dir": str(work_dir),
        "archive": None,
        "hostname": socket.gethostname(),
        "data_backup": {},
        "steps": {},
    }

    try:
        status = manager.status()
    except Exception as e:
        status = {"ok": False, "error": str(e)}
    try:
        info = manager.info()
    except Exception as e:
        info = {"ok": False, "error": str(e)}
    try:
        health = manager.health()
    except Exception as e:
        health = {"ok": False, "error": str(e)}
    try:
        logs = manager.logs(500)
    except Exception as e:
        logs = {"ok": False, "error": str(e)}

    _session_update(session, work_dir, state="collecting", current_step=1, current_action="collect_metadata")

    _write_json(work_dir / "backup-info.json", {
        "app_id": app_id,
        "label": label,
        "timestamp": ts,
        "hostname": socket.gethostname(),
        "backup_root": str(BACKUP_ROOT),
        "profile": profile_id,
        "profile_label": profile_label,
        "profile_incremental": bool(profile_data.get("incremental", False)),
    })
    _write_json(work_dir / "status.json", status)
    _write_json(work_dir / "info.json", info)
    _write_json(work_dir / "health.json", health)

    _session_add_step(session, work_dir, {
        "order": 1,
        "title": "Metadaten sichern",
        "action": "collect_metadata",
        "risk": "low",
        "status": "executed",
        "changed": True,
        "message": "Status, Info und Health gesichert",
    })

    (work_dir / "logs").mkdir(exist_ok=True)
    if isinstance(logs, str):
        (work_dir / "logs" / "logs.txt").write_text(logs, encoding="utf-8", errors="replace")
    else:
        _write_json(work_dir / "logs" / "logs.json", logs)

    _session_update(session, work_dir, state="config", current_step=2, current_action="config_files")

    copied_config = {}
    if profile_data.get("config", True):
        for key, path in (getattr(manager, "config_files", {}) or {}).items():
            copied_config[key] = _copy_file(path, work_dir / "config")
        result["steps"]["config_files"] = copied_config
        ok_config = all(x.get("ok") for x in copied_config.values()) if copied_config else True
    else:
        ok_config = True
    _session_add_step(session, work_dir, {
        "order": 2,
        "title": "Konfiguration sichern",
        "action": "config_files",
        "risk": "low",
        "status": "executed" if ok_config else "failed",
        "changed": bool(profile_data.get("config", True)),
        "message": "{} Konfigurationsdateien verarbeitet".format(len(copied_config)) if profile_data.get("config", True) else "Profil überspringt Konfiguration",
    })

    _session_update(session, work_dir, state="data", current_step=3, current_action="paths")

    copied_paths = {}
    incremental_result = None

    if profile_data.get("data", True):
        app_paths = dict(
            getattr(manager, "paths", {}) or {}
        )

        # Ein Profil kann seine Datensicherung auf bestimmte
        # manager.paths beschränken.
        #
        # Ohne path_keys bleibt das bisherige Verhalten erhalten:
        # alle definierten Datenpfade werden gesichert.
        path_keys = profile_data.get("path_keys")

        if isinstance(path_keys, (list, tuple, set)):
            selected_keys = [
                str(key)
                for key in path_keys
            ]

            app_paths = {
                key: value
                for key, value in app_paths.items()
                if key in selected_keys
            }

        if profile_data.get("incremental", False):
            def _progress(info):
                _session_progress(session, work_dir, **info)

            incremental_result = _rsync_incremental_data(app_id, ts, app_paths, progress_cb=_progress)
            copied_paths = incremental_result.get("paths") or {}
        else:
            for key, path in app_paths.items():
                copy_hook=getattr(manager,'copy_backup_path',None)
                copied_paths[key] = copy_hook(path,work_dir/'data',key) if copy_hook else _copy_dir(path, work_dir / "data")

        result["steps"]["paths"] = copied_paths
        ok_paths = all(x.get("ok") for x in copied_paths.values()) if copied_paths else True
    else:
        ok_paths = True
    _session_add_step(session, work_dir, {
        "order": 3,
        "title": "Datenpfade sichern",
        "action": "paths",
        "risk": "medium",
        "status": "executed" if ok_paths else "failed",
        "changed": bool(profile_data.get("data", True)),
        "message": "{} Datenpfade verarbeitet".format(len(copied_paths)) if profile_data.get("data", True) else "Profil überspringt Datenpfade",
    })

    data_snapshot = None
    if profile_data.get("data", True):
        data_snapshot = _create_data_snapshot(manager, work_dir, copied_paths, profile_data)

    if incremental_result:
        result["incremental_result"] = incremental_result

    result["data_backup"] = _write_data_manifest(
        manager,
        work_dir,
        result,
        profile_data,
        snapshot=data_snapshot,
    )
    session["data_backup"] = result["data_backup"]
    _write_json(_session_path(work_dir), session)

    _session_update(session, work_dir, state="database", current_step=4, current_action="database")

    if profile_data.get("database", True):
        result["steps"]["database"] = run_database_backup(manager, work_dir / "database")
        db_result = result["steps"]["database"] or {}
    else:
        db_result = {"supported": False, "ok": True, "message": "Profil überspringt Datenbank"}
    _session_add_step(session, work_dir, {
        "order": 4,
        "title": "Datenbank sichern",
        "action": "database",
        "risk": "medium",
        "status": "executed" if db_result.get("ok") else "failed",
        "changed": bool(db_result.get("supported", False)),
        "message": db_result.get("message") or ("Datenbankdump erstellt" if db_result.get("ok") else "Datenbankdump fehlgeschlagen"),
    })

    _session_update(session, work_dir, state="extra", current_step=5, current_action="extra")

    extra_dir = work_dir / "extra"
    extra_dir.mkdir(parents=True, exist_ok=True)
    if profile_data.get("extra", True):
        try:
            extra = manager.extra_backup(str(extra_dir))
        except Exception as e:
            extra = {"ok": False, "error": str(e)}
        result["steps"]["extra"] = extra
        _write_json(work_dir / "extra-backup.json", extra)
    else:
        extra = {"ok": True, "message": "Profil überspringt Zusatzinformationen", "files": []}

    _session_add_step(session, work_dir, {
        "order": 5,
        "title": "Zusatzinformationen sichern",
        "action": "extra",
        "risk": "low",
        "status": "executed" if extra.get("ok") else "failed",
        "changed": True,
        "message": extra.get("message") or extra.get("error") or "",
    })

    result["ok"] = not (session["statistics"].get("failed") or session["statistics"].get("blocked"))
    _write_json(work_dir / "result.json", result)
    _write_json(work_dir / "manifest.json", _manifest(manager, result))

    _session_update(session, work_dir, state="archive", current_step=6, current_action="archive")

    archive = _make_tar(work_dir)
    archive.chmod(0o600)
    result["archive"] = str(archive)
    result["archive_size"] = sh(f"du -sh {str(archive)!r} | awk '{{print $1}}'", timeout=20)["stdout"]

    if profile_data.get("id") == "full":
        result["data_backup"] = _write_data_manifest(
            manager,
            work_dir,
            result,
            profile_data,
            snapshot=data_snapshot if "data_snapshot" in locals() else None,
        )

    _session_add_step(session, work_dir, {
        "order": 6,
        "title": "Archiv erzeugen",
        "action": "archive",
        "risk": "low",
        "status": "executed",
        "changed": True,
        "message": "Archiv erstellt: {}".format(result["archive_size"]),
    })

    result["session"] = session
    session["archive"] = result["archive"]
    session["finished_at"] = datetime.now().isoformat(timespec="seconds")
    result["ok"] = not (session["statistics"].get("failed") or session["statistics"].get("blocked"))
    _session_update(session, work_dir, state="completed" if result["ok"] else "failed", current_step=None, current_action=None)

    _write_json(work_dir / "session.json", session)
    _write_json(work_dir / "result.json", result)
    _write_json(work_dir / "manifest.json", _manifest(manager, result))

    return result
