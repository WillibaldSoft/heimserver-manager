from server_settings import get as host_setting
import shlex
# -*- coding: utf-8 -*-
from pathlib import Path
import json
import hashlib
from datetime import datetime
from .runner import sh
from .restore_check import check_backup
import socket



def _file_sha256(path):
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _docker_networks(container):
    r = sh(
        f"docker inspect -f '{{{{json .NetworkSettings.Networks}}}}' {container} 2>/dev/null || true",
        timeout=10
    )
    txt = r.get("stdout") or ""
    try:
        data = json.loads(txt) if txt else {}
    except Exception:
        data = {}
    return sorted(data.keys())


def _path_mount_info(path):
    p = Path(path or "")
    info = {
        "path": str(p),
        "exists": p.exists(),
        "readable": False,
        "writable": False,
        "is_mount": False,
        "filesystem": "",
        "free": "",
        "size": "",
    }

    if not path:
        return info

    info["readable"] = sh(f"test -r {str(p)!r} && echo yes || echo no", timeout=5).get("stdout") == "yes"
    info["writable"] = sh(f"test -w {str(p)!r} && echo yes || echo no", timeout=5).get("stdout") == "yes"
    info["is_mount"] = sh(f"findmnt -T {str(p)!r} >/dev/null 2>&1 && echo yes || echo no", timeout=5).get("stdout") == "yes"
    info["filesystem"] = sh(f"findmnt -T {str(p)!r} -no FSTYPE 2>/dev/null || true", timeout=5).get("stdout")
    info["free"] = sh(f"df -h {str(p)!r} 2>/dev/null | awk 'NR==2{{print $4}}' || true", timeout=5).get("stdout")
    info["size"] = sh(f"du -sh {str(p)!r} 2>/dev/null | awk '{{print $1}}' || true", timeout=30).get("stdout")

    return info


def _backup_mounts_from_inspect(backup_path, containers):
    result = {}
    backup_extra = Path(backup_path) / "extra"

    for key, name in containers.items():
        inspect_file = backup_extra / f"inspect-{name}.json"
        mounts = []

        if inspect_file.exists():
            try:
                raw = inspect_file.read_text(encoding="utf-8", errors="replace")
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    mounts_raw = parsed[0].get("Mounts") or []
                    for m in mounts_raw:
                        mounts.append({
                            "type": m.get("Type"),
                            "source": m.get("Source"),
                            "destination": m.get("Destination"),
                            "rw": m.get("RW"),
                        })
            except Exception:
                pass

        result[key] = {
            "container": name,
            "mounts": mounts,
        }

    return result


def _docker_mounts(container):
    r = sh(
        f"docker inspect -f '{{{{json .Mounts}}}}' {container} 2>/dev/null || true",
        timeout=10
    )
    txt = r.get("stdout") or ""
    try:
        data = json.loads(txt) if txt else []
    except Exception:
        data = []
    return [
        {
            "type": m.get("Type"),
            "source": m.get("Source"),
            "destination": m.get("Destination"),
            "rw": m.get("RW"),
        }
        for m in data
    ]


def _compose_services(compose_file):
    p = Path(compose_file)
    if not p.exists():
        return []
    r = sh(f"docker compose -f {str(p)!r} config --services 2>/dev/null || true", timeout=20)
    return [x.strip() for x in (r.get("stdout") or "").splitlines() if x.strip()]


def _cmd_exists(cmd):
    r = sh(f"command -v {cmd} >/dev/null 2>&1 && echo yes || echo no", timeout=5)
    return (r.get("stdout") or "").strip() == "yes"


def _host_check():
    details = {
        "hostname": socket.gethostname(),
        "docker": _cmd_exists("docker"),
        "tar": _cmd_exists("tar"),
        "gzip": _cmd_exists("gzip"),
        "sha256sum": _cmd_exists("sha256sum"),
        "kernel": sh("uname -r", timeout=5).get("stdout"),
        "os": sh("PRETTY_NAME=''; . /etc/os-release 2>/dev/null; echo $PRETTY_NAME", timeout=5).get("stdout"),
        "backup_root_free": sh("df -h " + shlex.quote(host_setting("backup_root")) + " 2>/dev/null | awk 'NR==2{print $4}'", timeout=5).get("stdout"),
    }

    compose = sh("docker compose version 2>/dev/null || true", timeout=10).get("stdout")
    details["docker_compose"] = bool(compose)
    details["docker_compose_version"] = compose
    details["docker_version"] = sh("docker --version 2>/dev/null || true", timeout=5).get("stdout")

    errors = []
    warnings = []

    for key in ("docker", "docker_compose", "tar", "gzip", "sha256sum"):
        if not details.get(key):
            errors.append(f"{key} fehlt")

    return {
        "name": "host",
        "ok": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "details": details,
    }


def _empty_check(name):
    return {
        "name": name,
        "ok": True,
        "warnings": [],
        "errors": [],
        "details": {},
    }



def _application_check(manager, backup_path):
    details = {}
    errors = []
    warnings = []

    compose_dir = getattr(manager, "compose_dir", None)
    compose_file = None

    if compose_dir:
        compose_path = Path(compose_dir)
        compose_file = compose_path / "docker-compose.yml"
        if not compose_file.exists():
            alt = compose_path / "compose.yml"
            compose_file = alt if alt.exists() else compose_file

        details["compose_dir"] = str(compose_path)
        details["compose_dir_exists"] = compose_path.exists()
        details["compose_file"] = str(compose_file)
        details["compose_file_exists"] = compose_file.exists()

        if not compose_path.exists():
            errors.append("Compose-Verzeichnis fehlt")
        if not compose_file.exists():
            errors.append("Compose-Datei fehlt")

        if compose_path.exists():
            ps = sh(f"cd {str(compose_path)!r} && docker compose ps --format json 2>/dev/null || true", timeout=20)
            details["compose_ps_raw"] = ps.get("stdout")
            if not (ps.get("stdout") or "").strip():
                warnings.append("docker compose ps liefert keine Containerdaten")

        backup_compose = Path(backup_path) / "config" / "docker-compose.yml"
        if not backup_compose.exists():
            alt_backup_compose = Path(backup_path) / "config" / "compose.yml"
            backup_compose = alt_backup_compose if alt_backup_compose.exists() else backup_compose

        current_services = _compose_services(compose_file)
        backup_services = _compose_services(backup_compose)

        compose_compare = {
            "current_file": str(compose_file),
            "backup_file": str(backup_compose),
            "current_exists": compose_file.exists(),
            "backup_exists": backup_compose.exists(),
            "current_sha256": _file_sha256(compose_file),
            "backup_sha256": _file_sha256(backup_compose),
            "file_equal": bool(compose_file.exists() and backup_compose.exists() and _file_sha256(compose_file) == _file_sha256(backup_compose)),
            "current_services": current_services,
            "backup_services": backup_services,
            "services_equal": sorted(current_services) == sorted(backup_services),
            "services_missing_current": sorted(set(backup_services) - set(current_services)),
            "services_new_current": sorted(set(current_services) - set(backup_services)),
        }
        details["compose_compare"] = compose_compare

        if backup_compose.exists() and compose_file.exists() and not compose_compare["file_equal"]:
            warnings.append("Compose-Datei unterscheidet sich vom Backup")

        if backup_services and current_services and not compose_compare["services_equal"]:
            warnings.append("Compose-Services unterscheiden sich vom Backup")

    containers = getattr(manager, "containers", {}) or {}
    details["containers"] = {}
    for key, name in containers.items():
        inspect = sh(
            "docker inspect -f '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' "
            + str(name) + " 2>/dev/null || true",
            timeout=10
        ).get("stdout")
        exists = bool(inspect)
        running = " running " in f" {inspect} "
        details["containers"][key] = {
            "name": name,
            "exists": exists,
            "running": running,
            "inspect": inspect,
        }
        if not exists:
            errors.append(f"Container fehlt: {name}")
        elif not running:
            warnings.append(f"Container läuft nicht: {name}")

    # Container- und Netzwerkprüfung
    container_networks = {}
    container_mounts = {}

    for key, name in containers.items():
        networks = _docker_networks(name)
        mounts = _docker_mounts(name)

        container_networks[key] = {
            "container": name,
            "networks": networks,
        }
        container_mounts[key] = {
            "container": name,
            "mounts": mounts,
        }

        if not networks:
            warnings.append(f"Container hat kein Docker-Netzwerk: {name}")

    details["container_networks"] = container_networks
    details["container_mounts"] = container_mounts

    # Volume-/Mountprüfung
    backup_mounts = _backup_mounts_from_inspect(backup_path, containers)
    mount_checks = {}
    mount_compare = {}

    for key, current in container_mounts.items():
        current_mounts = current.get("mounts") or []
        backup_mount_list = (backup_mounts.get(key) or {}).get("mounts") or []

        current_by_dest = {m.get("destination"): m for m in current_mounts if m.get("destination")}
        backup_by_dest = {m.get("destination"): m for m in backup_mount_list if m.get("destination")}

        checked = []
        for m in current_mounts:
            src = m.get("source")
            if src:
                info = _path_mount_info(src)
                info["destination"] = m.get("destination")
                info["type"] = m.get("type")
                info["rw"] = m.get("rw")
                checked.append(info)

                if not info["exists"]:
                    errors.append(f"Mount-Quelle fehlt: {src}")
                elif m.get("rw") and not info["writable"]:
                    warnings.append(f"Mount-Quelle nicht beschreibbar: {src}")

        mount_checks[key] = {
            "container": current.get("container"),
            "mounts": checked,
        }

        mount_compare[key] = {
            "container": current.get("container"),
            "current_destinations": sorted(current_by_dest.keys()),
            "backup_destinations": sorted(backup_by_dest.keys()),
            "destinations_equal": sorted(current_by_dest.keys()) == sorted(backup_by_dest.keys()),
            "missing_current": sorted(set(backup_by_dest.keys()) - set(current_by_dest.keys())),
            "new_current": sorted(set(current_by_dest.keys()) - set(backup_by_dest.keys())),
        }

        if backup_by_dest and current_by_dest and sorted(current_by_dest.keys()) != sorted(backup_by_dest.keys()):
            warnings.append(f"Container-Mounts unterscheiden sich: {current.get('container')}")

    details["mount_checks"] = mount_checks
    details["mount_compare"] = mount_compare

    # Netzwerkvergleich mit Backup-Inspect
    network_compare = {}
    backup_extra = Path(backup_path) / "extra"

    for key, name in containers.items():
        inspect_file = backup_extra / f"inspect-{name}.json"
        backup_networks = []

        if inspect_file.exists():
            try:
                raw = inspect_file.read_text(encoding="utf-8", errors="replace")
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    nets = ((parsed[0].get("NetworkSettings") or {}).get("Networks") or {})
                    backup_networks = sorted(nets.keys())
            except Exception as e:
                warnings.append(f"Backup-Netzwerke nicht lesbar: {name}: {e}")

        current_networks = container_networks.get(key, {}).get("networks", [])
        network_compare[key] = {
            "container": name,
            "current": current_networks,
            "backup": backup_networks,
            "equal": sorted(current_networks) == sorted(backup_networks),
            "missing_current": sorted(set(backup_networks) - set(current_networks)),
            "new_current": sorted(set(current_networks) - set(backup_networks)),
        }

        if backup_networks and current_networks and sorted(backup_networks) != sorted(current_networks):
            warnings.append(f"Docker-Netzwerke abweichend für {name}")

    details["network_compare"] = network_compare

    try:
        status = manager.status()
    except Exception as e:
        status = {"ok": False, "error": str(e)}
        errors.append("Manager status() fehlgeschlagen")

    try:
        health = manager.health()
    except Exception as e:
        health = {"ok": False, "error": str(e)}
        warnings.append("Manager health() fehlgeschlagen")

    details["status"] = status
    details["health"] = health

    web = status.get("web") if isinstance(status, dict) else None
    if isinstance(web, dict) and web.get("configured") and not web.get("ok"):
        warnings.append("Web/API aktuell nicht erreichbar")

    # Versionen / Images vergleichen
    versions = {
        "current_images": {},
        "backup_images": {},
        "comparison": {},
        "warnings": [],
    }

    for key, name in containers.items():
        img = sh(
            f"docker inspect -f '{{{{.Config.Image}}}}' {name} 2>/dev/null || true",
            timeout=10
        ).get("stdout")
        labels = sh(
            f"docker inspect -f '{{{{json .Config.Labels}}}}' {name} 2>/dev/null || true",
            timeout=10
        ).get("stdout")
        versions["current_images"][key] = {
            "container": name,
            "image": img,
            "labels": labels,
        }

    # Backup-Images aus extra/inspect-*.json lesen und vergleichen
    backup_extra = Path(backup_path) / "extra"
    for key, name in containers.items():
        inspect_file = backup_extra / f"inspect-{name}.json"
        backup_item = {
            "container": name,
            "inspect_file": str(inspect_file),
            "exists": inspect_file.exists(),
        }

        if inspect_file.exists():
            try:
                raw = inspect_file.read_text(encoding="utf-8", errors="replace")
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    cfg = parsed[0].get("Config") or {}
                    labels = cfg.get("Labels") or {}
                    backup_item["image"] = cfg.get("Image") or ""
                    backup_item["labels"] = labels
                    backup_item["app_version"] = labels.get("org.opencontainers.image.version", "")
                    backup_item["compose_version"] = labels.get("com.docker.compose.version", "")
                    backup_item["compose_service"] = labels.get("com.docker.compose.service", "")
            except Exception as e:
                backup_item["error"] = str(e)
                versions["warnings"].append(f"Backup-Inspect nicht lesbar: {name}")

        versions["backup_images"][key] = backup_item

        cur = versions["current_images"].get(key, {})
        cur_labels = {}
        try:
            cur_labels = json.loads(cur.get("labels") or "{}")
        except Exception:
            cur_labels = {}

        cur_image = cur.get("image") or ""
        bak_image = backup_item.get("image") or ""

        cur_app_version = cur_labels.get("org.opencontainers.image.version", "")
        bak_app_version = backup_item.get("app_version", "")

        cur_compose_version = cur_labels.get("com.docker.compose.version", "")
        bak_compose_version = backup_item.get("compose_version", "")

        comparison = {
            "image_equal": bool(cur_image) and bool(bak_image) and cur_image == bak_image,
            "version_equal": bool(cur_app_version) and bool(bak_app_version) and cur_app_version == bak_app_version,
            "compose_equal": bool(cur_compose_version) and bool(bak_compose_version) and cur_compose_version == bak_compose_version,
        }
        versions["comparison"][key] = comparison

        if not comparison["image_equal"] and bak_image:
            versions["warnings"].append(
                f"Image abweichend für {name}: Backup={bak_image}, aktuell={cur_image}"
            )

        if not comparison["version_equal"] and bak_app_version:
            versions["warnings"].append(
                f"App-Version abweichend für {name}: Backup={bak_app_version}, aktuell={cur_app_version}"
            )

        if not comparison["compose_equal"] and bak_compose_version:
            versions["warnings"].append(
                f"Compose-Version abweichend für {name}: Backup={bak_compose_version}, aktuell={cur_compose_version}"
            )

    warnings.extend(versions["warnings"])
    details["versions"] = versions

    return {
        "name": "application",
        "ok": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "details": details,
    }


def _read_json_file(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _backup_check(backup_path):
    data = check_backup(str(backup_path))
    warnings = []
    errors = []

    checks = data.get("checks") or {}

    if not data.get("ok"):
        errors.append("Backup-Prüfung fehlgeschlagen")

    for key in ("manifest", "result_json"):
        if checks.get(key) is False:
            errors.append(f"Backup-Datei fehlt oder ungültig: {key}")

    if checks.get("gzip_valid") is False:
        errors.append("Datenbankdump gzip ungültig")

    if checks.get("sha256_valid") is False:
        errors.append("Datenbankdump SHA256 ungültig")

    return {
        "name": "backup",
        "ok": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "details": data,
    }


def _database_check(manager, backup_path):
    db = getattr(manager, "database", None)
    details = {
        "configured": bool(db),
        "definition": db or {},
        "backup": {},
        "current": {},
        "comparison": {},
    }
    warnings = []
    errors = []

    backup_db = _read_json_file(Path(backup_path) / "database" / "database-result.json")
    details["backup"] = backup_db or {}

    if not db:
        return {
            "name": "database",
            "ok": True,
            "warnings": [],
            "errors": [],
            "details": details,
        }

    db_type = db.get("type")
    container = db.get("container")
    database = db.get("database")
    user = db.get("user")

    details["current"] = {
        "type": db_type,
        "container": container,
        "database": database,
        "user": user,
    }

    if db_type in ("postgresql", "mariadb"):
        if not container:
            errors.append("Datenbankcontainer nicht definiert")
        else:
            inspect = sh(
                f"docker inspect -f '{{{{.Name}}}} {{{{.State.Status}}}}' {container} 2>/dev/null || true",
                timeout=10
            ).get("stdout")
            exists = bool(inspect)
            running = " running" in inspect or inspect.endswith(" running")

            details["current"]["container_exists"] = exists
            details["current"]["container_running"] = running
            details["current"]["container_inspect"] = inspect

            if not exists:
                errors.append(f"Datenbankcontainer fehlt: {container}")
            elif not running:
                errors.append(f"Datenbankcontainer läuft nicht: {container}")

            if db_type == "postgresql" and exists:
                version = sh(
                    f"docker exec {container} sh -lc 'pg_dump --version 2>/dev/null || psql --version 2>/dev/null || true'",
                    timeout=15
                ).get("stdout")
                reachable = sh(
                    f"docker exec {container} sh -lc 'pg_isready -U {user} -d {database} >/dev/null 2>&1 && echo yes || echo no'",
                    timeout=15
                ).get("stdout") == "yes"
                db_exists = sh(
                    f"docker exec {container} sh -lc \"psql -U {user} -d postgres -tAc \\\"SELECT 1 FROM pg_database WHERE datname='{database}'\\\" 2>/dev/null\"",
                    timeout=15
                ).get("stdout").strip() == "1"
                user_exists = sh(
                    f"docker exec {container} sh -lc \"psql -U {user} -d postgres -tAc \\\"SELECT 1 FROM pg_roles WHERE rolname='{user}'\\\" 2>/dev/null\"",
                    timeout=15
                ).get("stdout").strip() == "1"

                details["current"].update({
                    "engine_version": version,
                    "reachable": reachable,
                    "database_exists": db_exists,
                    "user_exists": user_exists,
                })

                if not reachable:
                    errors.append("PostgreSQL nicht erreichbar")
                if not db_exists:
                    errors.append(f"PostgreSQL-Datenbank fehlt: {database}")
                if not user_exists:
                    warnings.append(f"PostgreSQL-Benutzer konnte nicht bestätigt werden: {user}")

            elif db_type == "mariadb" and exists:
                version = sh(
                    f"docker exec {container} sh -lc 'mariadb --version 2>/dev/null || mysql --version 2>/dev/null || true'",
                    timeout=15
                ).get("stdout")
                reachable = sh(
                    f"docker exec {container} sh -lc \"mariadb -u {user} -e 'SELECT 1' {database} >/dev/null 2>&1 && echo yes || echo no\"",
                    timeout=15
                ).get("stdout") == "yes"

                details["current"].update({
                    "engine_version": version,
                    "reachable": reachable,
                    "database_exists": reachable,
                    "user_exists": reachable,
                })

                if not reachable:
                    errors.append("MariaDB nicht erreichbar oder Zugang ungültig")

    elif db_type == "mariadb-local":
        version = sh("mariadb --version 2>/dev/null || mysql --version 2>/dev/null || true", timeout=15).get("stdout")
        details["current"]["engine_version"] = version
        if not version:
            errors.append("Lokale MariaDB nicht gefunden")

    elif db_type == "sqlite":
        source = db.get("file")
        exists = Path(source or "").exists()
        details["current"]["file"] = source
        details["current"]["file_exists"] = exists
        if not exists:
            errors.append("SQLite-Datei fehlt")

    else:
        errors.append(f"Datenbanktyp nicht unterstützt: {db_type}")

    if backup_db:
        details["comparison"] = {
            "type_equal": backup_db.get("type") == db_type,
            "database_equal": backup_db.get("database") == database,
            "user_equal": backup_db.get("user") == user,
            "container_equal": backup_db.get("container") == container,
            "backup_engine_version": backup_db.get("engine_version", ""),
            "current_engine_version": details["current"].get("engine_version", ""),
        }

        if backup_db.get("type") and backup_db.get("type") != db_type:
            errors.append("Backup-Datenbanktyp weicht vom aktuellen Ziel ab")
        if backup_db.get("database") and backup_db.get("database") != database:
            errors.append("Backup-Datenbankname weicht vom aktuellen Ziel ab")
        if backup_db.get("container") and backup_db.get("container") != container:
            warnings.append("Backup-Datenbankcontainer weicht vom aktuellen Ziel ab")
    else:
        warnings.append("Kein database-result.json im Backup gefunden")

    return {
        "name": "database",
        "ok": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "details": details,
    }


def _backup_age_info(backup_path):
    manifest = Path(backup_path) / "manifest.json"
    info = {
        "available": False,
        "timestamp": "",
        "age_seconds": None,
        "age_days": None,
        "level": "unknown",
        "message": "Backup-Alter nicht ermittelbar",
    }

    if not manifest.exists():
        return info

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        ts = data.get("timestamp") or ""
        info["timestamp"] = ts

        dt = None
        for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d_%H-%M"):
            try:
                dt = datetime.strptime(ts, fmt)
                break
            except Exception:
                pass

        if not dt:
            return info

        age = datetime.now() - dt
        days = age.total_seconds() / 86400

        info["available"] = True
        info["age_seconds"] = int(age.total_seconds())
        info["age_days"] = round(days, 2)

        if days <= 7:
            info["level"] = "fresh"
            info["message"] = "Backup ist aktuell"
        elif days <= 30:
            info["level"] = "ok"
            info["message"] = "Backup ist nicht neu, aber noch brauchbar"
        elif days <= 180:
            info["level"] = "old"
            info["message"] = "Backup ist älter als 30 Tage"
        else:
            info["level"] = "very_old"
            info["message"] = "Backup ist älter als 6 Monate"

        return info

    except Exception as e:
        info["error"] = str(e)
        return info


def _score_result(result):
    score = 100
    penalties = []

    errors = result.get("errors") or []
    warnings = result.get("warnings") or []

    score -= len(errors) * 25
    score -= len(warnings) * 5

    app = result.get("application", {}).get("details", {})

    compose = app.get("compose_compare") or {}
    if compose and not compose.get("file_equal", True):
        score -= 10
        penalties.append("Compose-Datei weicht ab")
    if compose and not compose.get("services_equal", True):
        score -= 20
        penalties.append("Compose-Services weichen ab")

    versions = ((app.get("versions") or {}).get("comparison") or {})
    for key, cmpv in versions.items():
        if not cmpv.get("image_equal", True):
            score -= 15
            penalties.append(f"Image abweichend: {key}")
        if cmpv.get("version_equal") is False and key in ("webserver", "server", "app"):
            score -= 15
            penalties.append(f"App-Version abweichend: {key}")

    networks = app.get("network_compare") or {}
    for key, net in networks.items():
        if not net.get("equal", True):
            score -= 10
            penalties.append(f"Netzwerk abweichend: {key}")

    mounts = app.get("mount_compare") or {}
    for key, mnt in mounts.items():
        if not mnt.get("destinations_equal", True):
            score -= 20
            penalties.append(f"Mount-Ziele abweichend: {key}")

    score = max(0, min(100, score))

    if errors:
        level = "blocked"
        restore_possible = False
    elif score >= 90:
        level = "good"
        restore_possible = True
    elif score >= 70:
        level = "warning"
        restore_possible = True
    else:
        level = "critical"
        restore_possible = False

    return {
        "score": score,
        "level": level,
        "restore_possible": restore_possible,
        "penalties": penalties,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def _collect(result, section):
    data = result.get(section) or {}
    result["warnings"].extend(data.get("warnings") or [])
    result["errors"].extend(data.get("errors") or [])


def run_restore_check(manager, backup_dir):
    backup_path = Path(backup_dir)

    result = {
        "ok": True,
        "mode": "read-only",
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "backup_dir": str(backup_path),
        "backup_exists": backup_path.exists(),
        "host": _host_check(),
        "application": _application_check(manager, backup_path),
        "database": _database_check(manager, backup_path),
        "backup": _backup_check(backup_path),
        "warnings": [],
        "errors": [],
        "restore_possible": False,
    }

    if not backup_path.exists():
        result["backup"]["ok"] = False
        result["backup"]["errors"].append("Backup-Verzeichnis nicht gefunden")

    result["backup"]["details"]["age"] = _backup_age_info(backup_path)

    age = result["backup"]["details"]["age"]
    if age.get("level") == "old":
        result["backup"]["warnings"].append(age.get("message"))
    elif age.get("level") == "very_old":
        result["backup"]["warnings"].append(age.get("message"))

    for section in ("host", "application", "database", "backup"):
        _collect(result, section)

    result["ok"] = len(result["errors"]) == 0
    result["readiness"] = _score_result(result)
    result["restore_possible"] = result["readiness"]["restore_possible"]

    return result
