# -*- coding: utf-8 -*-
import json
import threading
import socket
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .backup_engine import run_backup
from .settings import get_setting, bool_setting


UPDATE_LOG_ROOT = get_setting("update_log_root", "/srv/backups/apps/update_runs")
# Execution permission is read at each check, so saved settings apply immediately.
UPDATE_CONFIRM_TOKEN = get_setting("update_confirm_token", "UPDATE")


def _now():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")


def _write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_id(manager):
    return "{}_{}_{}".format(
        getattr(manager, "app_id", "app"),
        _now(),
        socket.gethostname(),
    )


def _compose_cmd(manager, cmd):
    compose_dir = getattr(manager, "compose_dir", None)
    if compose_dir:
        return "cd {} && docker compose {}".format(repr(compose_dir), cmd)
    service = getattr(manager, "service", None)
    if service:
        return "systemctl {} {}".format(cmd, service)
    return ""


def _manager_update_check(manager):
    try:
        return manager.update_check()
    except Exception as e:
        return {"ok": False, "error": str(e), "message": "Update-Check fehlgeschlagen"}


def _new_session(manager, rid, run_dir, mode):
    now_s = datetime.now().isoformat(timespec="seconds")
    return {
        "id": rid,
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "mode": mode,
        "state": "created",
        "current_step": None,
        "current_action": None,
        "started_at": now_s,
        "updated_at": now_s,
        "finished_at": None,
        "run_dir": str(run_dir),
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


def _session_update(session, state=None, current_step=None, current_action=None):
    if state:
        session["state"] = state
    session["current_step"] = current_step
    session["current_action"] = current_action
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")


def _session_add_step(session, step):
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


def _validate_request(mode, confirm_token=""):
    errors = []
    warnings = []
    simulate = confirm_token == "SIMULATE"

    if mode == "execute":
        if simulate:
            warnings.append("Simulation erlaubt: Feature-Flag für echte Updates wird nicht benötigt.")
        else:
            if confirm_token != UPDATE_CONFIRM_TOKEN:
                errors.append("Sicherheitsbestätigung fehlt oder ist ungültig. Erwartet: UPDATE oder SIMULATE")


    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "simulate": simulate,
    }


def run_update_plan(manager):
    try:
        plan = manager.update_plan()
    except Exception as e:
        plan = {
            "supported": False,
            "ok": False,
            "app_id": getattr(manager, "app_id", ""),
            "label": getattr(manager, "label", ""),
            "kind": getattr(manager, "kind", ""),
            "message": "Update-Plan fehlgeschlagen: {}".format(e),
            "steps": [],
            "errors": [str(e)],
        }

    plan.setdefault("ok", True)
    plan.setdefault("mode", "plan")
    plan.setdefault("phase", "5.14.4")
    plan.setdefault("app_id", getattr(manager, "app_id", ""))
    plan.setdefault("label", getattr(manager, "label", ""))
    plan.setdefault("kind", getattr(manager, "kind", ""))
    plan.setdefault("warnings", [])
    plan.setdefault("errors", [])
    plan.setdefault("summary", {
        "step_count": len(plan.get("steps") or []),
        "requires_backup": bool(plan.get("requires_backup", True)),
        "execution_enabled": bool_setting("update_execution_enabled", False),
        "confirm_token": UPDATE_CONFIRM_TOKEN,
        "risk": "high",
    })

    return plan


def run_update_prepare(manager):
    rid = _run_id(manager)
    run_dir = Path(UPDATE_LOG_ROOT) / getattr(manager, "app_id", "app") / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    plan = run_update_plan(manager)
    session = _new_session(manager, rid, run_dir, "prepare")

    session["run_type"] = "prepare"
    session["created_by"] = "webui"
    session["cleanup_eligible"] = False
    _write_json(run_dir / "session.json", session)

    result = {
        "ok": False,
        "mode": "prepare",
        "run_id": rid,
        "run_dir": str(run_dir),
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "plan": plan,
        "update_guard": plan.get("update_guard", {}),
        "auto_update_blocked": plan.get("auto_update_blocked", False),
        "pinned_update_tags": plan.get("pinned_update_tags", []),
        "backup": None,
        "warnings": [],
        "errors": [],
    }

    try:
        _session_update(session, state="backup", current_step=2, current_action="pre_update_backup")
        _write_json(run_dir / "session.json", session)

        backup_profile = str(
            getattr(
                manager,
                "update_backup_profile",
                "system",
            )
            or "system"
        ).strip()

        backup = run_backup(
            manager,
            profile=backup_profile,
        )

        result["backup"] = backup
        result["backup_profile"] = backup_profile

        step = {
            "order": 2,
            "title": "Backup vor Update erzeugen",
            "action": "pre_update_backup",
            "risk": "medium",
            "status": "executed" if backup.get("ok") else "failed",
            "changed": bool(backup.get("ok")),
            "message": "Pre-Update-Backup erzeugt" if backup.get("ok") else "Pre-Update-Backup fehlgeschlagen",
            "archive": backup.get("archive"),
            "archive_size": backup.get("archive_size"),
        }
        _session_add_step(session, step)

        if backup.get("ok"):
            result["ok"] = True
        else:
            result["errors"].append("Pre-Update-Backup fehlgeschlagen")
    except Exception as e:
        result["errors"].append("Pre-Update-Backup Ausnahme: {}".format(e))
        _session_add_step(session, {
            "order": 2,
            "title": "Backup vor Update erzeugen",
            "action": "pre_update_backup",
            "risk": "medium",
            "status": "failed",
            "changed": False,
            "message": str(e),
        })

    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _session_update(session, state="completed" if result["ok"] else "failed", current_step=None, current_action=None)
    session["finished_at"] = result["finished_at"]
    result["session"] = session

    _write_json(run_dir / "plan.json", plan)
    _write_json(run_dir / "session.json", session)
    _write_json(run_dir / "result.json", result)

    return result




def run_update_safety_check(manager, session=None):
    """
    Sicherheitsprüfung vor echtem Update.

    Phase 5.15.1
    - keine Änderungen
    - keine Container-Aktionen
    """

    result = {
        "ok": True,
        "checks": [],
        "errors": [],
        "warnings": [],
    }


    simulate = False

    if isinstance(session, dict):
        simulate = bool(
            session.get("simulate", False)
        )


    result["checks"].append({
        "name": "simulation",
        "ok": True,
        "value": simulate
    })


    if simulate:
        result["warnings"].append(
            "Simulation: Sicherheitsprüfung ohne Echtlauf."
        )


    compose_dir = getattr(
        manager,
        "compose_dir",
        None
    )


    if compose_dir:

        path_ok = Path(
            compose_dir
        ).exists()

        result["checks"].append({
            "name": "compose_dir",
            "ok": path_ok,
            "value": compose_dir
        })

        if not path_ok:
            result["ok"] = False
            result["errors"].append(
                "Compose-Verzeichnis nicht gefunden: {}".format(
                    compose_dir
                )
            )


    if compose_dir:
        try:
            compose = subprocess.run(
                [
                    "docker",
                    "compose",
                    "version"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )

            compose_ok = compose.returncode == 0

            result["checks"].append({
                "name": "docker_compose",
                "ok": compose_ok,
                "value": (
                    (compose.stdout or "")
                    + "\n"
                    + (compose.stderr or "")
                ).strip(),
            })

            if not compose_ok:
                result["ok"] = False
                result["errors"].append(
                    "Docker Compose ist nicht verfügbar."
                )

        except Exception as e:
            result["ok"] = False
            result["checks"].append({
                "name": "docker_compose",
                "ok": False,
                "value": str(e),
            })
            result["errors"].append(
                "Docker Compose Prüfung fehlgeschlagen: {}".format(e)
            )
    else:
        result["checks"].append({
            "name": "docker_compose",
            "ok": True,
            "skipped": True,
            "reason": "App verwendet kein Docker Compose",
        })


    if isinstance(session, dict):

        session["safety_check"] = result


    return result



def run_update_preflight(manager, session=None):
    """
    Phase 5.15.2:
    Vorprüfung vor echtem Update.

    Keine Änderungen.
    Keine Docker-Aktionen.
    """

    result = {
        "ok": True,
        "checks": [],
        "errors": [],
        "warnings": [],
        "pre_state": {},
    }


    compose_dir = getattr(manager, "compose_dir", None)

    if compose_dir:
        exists = Path(compose_dir).exists()

        result["checks"].append({
            "name": "compose_dir",
            "ok": exists,
            "value": compose_dir,
        })

        if not exists:
            result["ok"] = False
            result["errors"].append(
                "Compose-Verzeichnis fehlt: {}".format(compose_dir)
            )


    if compose_dir:
        try:
            docker = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            docker_ok = docker.returncode == 0

            result["checks"].append({
                "name": "docker",
                "ok": docker_ok,
                "value": (
                    (docker.stdout or "")
                    + "\n"
                    + (docker.stderr or "")
                ).strip(),
            })

            result["pre_state"]["docker_available"] = docker_ok

            if not docker_ok:
                result["ok"] = False
                result["errors"].append(
                    "Docker nicht verfügbar"
                )

        except Exception as e:
            result["ok"] = False
            result["pre_state"]["docker_available"] = False
            result["checks"].append({
                "name": "docker",
                "ok": False,
                "value": str(e),
            })
            result["errors"].append(
                "Docker Prüfung fehlgeschlagen: {}".format(e)
            )
    else:
        result["checks"].append({
            "name": "docker",
            "ok": True,
            "skipped": True,
            "reason": "App verwendet kein Docker",
        })
        result["pre_state"]["docker_available"] = None


    result["pre_state"]["compose_dir"] = compose_dir


    if isinstance(session, dict):
        session["preflight_required"] = True
        session["preflight_ok"] = result["ok"]
        session["pre_state"] = result["pre_state"]


    return result



def run_update_backup_check(manager, session=None):
    """
    Prüft das für den Update-Lauf gültige Pre-Update-Backup.

    Echtlauf:
        Es wird ausschließlich der Prepare-Run verwendet, der
        explizit über session["source_prepare_run_id"] an die
        Execute-Session gebunden wurde.

    Simulation:
        Wenn keine Prepare-ID gebunden ist, darf zur Kompatibilität
        weiterhin der neueste erfolgreiche Prepare-Run verwendet
        werden.

    Keine Änderungen.
    """

    result = {
        "ok": False,
        "checks": [],
        "errors": [],
        "backup": None,
        "source_prepare_run_id": None,
        "binding_mode": None,
    }

    app_id = getattr(
        manager,
        "app_id",
        "app",
    )

    root = Path(UPDATE_LOG_ROOT) / app_id

    simulate = bool(
        isinstance(session, dict)
        and session.get("simulate", False)
    )

    source_prepare_run_id = None

    if isinstance(session, dict):
        source_prepare_run_id = str(
            session.get("source_prepare_run_id")
            or ""
        ).strip() or None

    result["source_prepare_run_id"] = (
        source_prepare_run_id
    )

    def load_prepare(run_id):
        """
        Lädt und validiert exakt einen Prepare-Run.
        """

        if not run_id:
            return None, (
                "Keine Prepare-Run-ID angegeben."
            )

        # Keine Pfadbestandteile aus Benutzerinput zulassen.
        if (
            Path(run_id).name != run_id
            or "/" in run_id
            or "\\" in run_id
            or run_id in (".", "..")
        ):
            return None, (
                "Ungültige Prepare-Run-ID."
            )

        run_dir = root / run_id
        result_file = run_dir / "result.json"

        if run_dir.is_symlink() or not run_dir.is_dir():
            return None, (
                "Gebundener Prepare-Run existiert nicht."
            )

        if not result_file.is_file():
            return None, (
                "Gebundener Prepare-Run besitzt "
                "kein result.json."
            )

        try:
            data = json.loads(
                result_file.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as e:
            return None, (
                "Gebundener Prepare-Run konnte "
                "nicht gelesen werden: {}"
            ).format(e)

        if data.get("mode") != "prepare":
            return None, (
                "Gebundener Run ist kein Prepare-Run."
            )

        if data.get("run_id") != run_id:
            return None, (
                "Prepare-Run-ID stimmt nicht mit "
                "result.json überein."
            )

        if data.get("app_id") != app_id:
            return None, (
                "Prepare-Run gehört zu einer anderen App."
            )

        if not data.get("ok"):
            return None, (
                "Gebundener Prepare-Run war nicht erfolgreich."
            )

        backup = data.get("backup") or {}

        if not backup.get("ok"):
            return None, (
                "Backup des gebundenen Prepare-Runs "
                "war nicht erfolgreich."
            )

        # App-ID auch im Backup selbst kontrollieren,
        # sofern der Backup-Engine-Datensatz sie enthält.
        backup_app_id = backup.get("app_id")

        if (
            backup_app_id
            and backup_app_id != app_id
        ):
            return None, (
                "Backup des Prepare-Runs gehört "
                "zu einer anderen App."
            )

        return {
            "run_id": run_id,
            "backup": backup,
        }, None


    # --------------------------------------------------------
    # Explizite Bindung vorhanden:
    # ausschließlich diesen Prepare-Run verwenden.
    # --------------------------------------------------------

    if source_prepare_run_id:

        result["binding_mode"] = "explicit"

        prepared, error = load_prepare(
            source_prepare_run_id
        )

        if prepared:
            result["ok"] = True
            result["backup"] = prepared

            result["checks"].append({
                "name": "pre_update_backup",
                "ok": True,
                "run_id": source_prepare_run_id,
                "binding": "explicit",
            })

        else:
            result["errors"].append(error)

            result["checks"].append({
                "name": "pre_update_backup",
                "ok": False,
                "run_id": source_prepare_run_id,
                "binding": "explicit",
                "error": error,
            })


    # --------------------------------------------------------
    # Echtlauf ohne Bindung:
    # grundsätzlich blockieren.
    # --------------------------------------------------------

    elif not simulate:

        result["binding_mode"] = "required"

        error = (
            "Kein Prepare-Run an diesen echten "
            "Update-Lauf gebunden."
        )

        result["errors"].append(error)

        result["checks"].append({
            "name": "pre_update_backup",
            "ok": False,
            "binding": "missing",
            "error": error,
        })


    # --------------------------------------------------------
    # Simulation ohne Bindung:
    # bisherigen Fallback beibehalten.
    # --------------------------------------------------------

    else:

        result["binding_mode"] = "simulation_fallback"

        candidates = []

        if root.exists():
            for run_dir in root.iterdir():
                if run_dir.is_symlink() or not run_dir.is_dir():
                    continue

                prepared, error = load_prepare(
                    run_dir.name
                )

                if prepared:
                    candidates.append(
                        prepared
                    )

        if candidates:
            latest = sorted(
                candidates,
                key=lambda x: x["run_id"],
                reverse=True,
            )[0]

            result["ok"] = True
            result["backup"] = latest

            result["checks"].append({
                "name": "pre_update_backup",
                "ok": True,
                "run_id": latest["run_id"],
                "binding": "simulation_fallback",
            })

        else:
            error = (
                "Kein erfolgreiches Pre-Update-Backup "
                "für die Simulation gefunden."
            )

            result["errors"].append(error)

            result["checks"].append({
                "name": "pre_update_backup",
                "ok": False,
                "binding": "simulation_fallback",
            })


    if isinstance(session, dict):
        session["backup_check"] = result

    return result


def run_update_execution_gate(manager, session=None, preflight=None, backup_check=None):
    """
    Phase 5.15.4:
    Letzte Freigabe vor echter Update-Ausführung.

    Keine Änderungen.
    Nur Prüfung.
    """

    result = {
        "ok": True,
        "checks": [],
        "errors": [],
        "warnings": [],
    }


    if not isinstance(session, dict):
        result["ok"] = False
        result["errors"].append(
            "Keine Update-Session vorhanden"
        )
        return result


    simulate = bool(
        session.get("simulate", False)
    )


    result["checks"].append({
        "name": "simulation_disabled",
        "ok": not simulate,
        "value": simulate,
    })

    if simulate:
        result["warnings"].append(
            "Simulation: Execution Gate übersprungen"
        )


    authorized = bool(
        session.get("execution_authorized", False)
    )

    result["checks"].append({
        "name": "execution_authorized",
        "ok": authorized or simulate,
        "value": authorized,
    })

    if not authorized and not simulate:
        result["ok"] = False
        result["errors"].append(
            "Keine echte Update-Autorisierung vorhanden"
        )


    flag = bool_setting(
        "update_execution_enabled",
        False
    )

    result["checks"].append({
        "name": "execution_enabled",
        "ok": flag or simulate,
        "value": flag,
    })

    if not flag and not simulate:
        result["ok"] = False
        result["errors"].append(
            "Update-Ausführung per Feature-Flag deaktiviert"
        )


    if isinstance(preflight, dict):

        pf_ok = bool(
            preflight.get("ok", False)
        )

        result["checks"].append({
            "name": "preflight",
            "ok": pf_ok or simulate,
            "value": pf_ok,
        })

        if not pf_ok and not simulate:
            result["ok"] = False
            result["errors"].append(
                "Preflight fehlgeschlagen"
            )


    if isinstance(backup_check, dict):

        backup_ok = bool(
            backup_check.get("ok", False)
        )

        result["checks"].append({
            "name": "backup_check",
            "ok": backup_ok or simulate,
            "value": backup_ok,
        })

        if not backup_ok and not simulate:
            result["ok"] = False
            result["errors"].append(
                "Kein gültiges Backup vor Update vorhanden"
            )


    session["execution_gate"] = result

    return result



def analyze_update_execute_result(execute_result):
    """
    Bewertet die echte Update-Ausführung.

    Rollback wird nur dann automatisch empfohlen, wenn ein tatsächlich
    fehlgeschlagener Schritt selbst Änderungen am produktiven Zustand
    durchgeführt hat.

    Ein späterer Verify-Fehler nach einem zuvor erfolgreichen Update darf
    nicht allein wegen früherer Änderungen automatisch einen Rollback
    auslösen.
    """

    result = {
        "status": "unknown",
        "category": None,
        "rollback_required": False,
        "rollback_reason": None,
        "recommendation": None,
        "failed_steps": [],
    }

    if not isinstance(execute_result, dict):
        result["status"] = "invalid"
        result["category"] = "internal_error"
        result["recommendation"] = (
            "Ungültiges Ergebnis der Update-Ausführung prüfen."
        )
        return result

    if execute_result.get("ok"):
        result["status"] = "success"
        return result

    steps = execute_result.get("steps") or []

    failed_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("status") == "failed"
    ]

    result["failed_steps"] = failed_steps
    result["status"] = "failed"

    if execute_result.get("rollback_succeeded") is True:
        result["category"] = "update_rolled_back"
        result["rollback_required"] = False
        result["rollback_reason"] = "Der ursprüngliche Container mit Originaldaten wurde bereits wieder gestartet."
        result["recommendation"] = "Update fehlgeschlagen; ursprünglicher Stand wiederhergestellt. Ursache im fehlgeschlagenen Schritt prüfen."
        return result

    combined_output = "\n".join(
        "{}\n{}".format(
            str(step.get("output") or ""),
            str(step.get("message") or ""),
        )
        for step in failed_steps
    ).lower()

    # Spezifische Ursachen müssen vor allgemeinen Netzwerkbegriffen
    # ausgewertet werden.
    if (
        "permission denied" in combined_output
        or "operation not permitted" in combined_output
        or "not allowed to execute" in combined_output
    ):
        result["category"] = "permission_error"
        result["recommendation"] = (
            "Berechtigungen, Eigentümer und ACL des betroffenen "
            "Pfads prüfen."
        )

    elif (
        "there are more files than the downloaded archive"
        in combined_output
        or "verify integrity failed" in combined_output
        or "integrity check failed" in combined_output
    ):
        result["category"] = "integrity_error"
        result["recommendation"] = (
            "Integritätsprüfung fehlgeschlagen. Temporäre Download- "
            "oder Update-Reste prüfen und das Update anschließend "
            "erneut ausführen."
        )

    elif "no space left" in combined_output:
        result["category"] = "disk_full"
        result["recommendation"] = (
            "Freien Speicherplatz auf den beteiligten Dateisystemen prüfen."
        )

    elif "429 too many requests" in combined_output:
        result["category"] = "docker_registry_rate_limit"
        result["recommendation"] = (
            "Docker Hub Rate Limit erreicht. "
            "Später erneut versuchen oder Docker Login verwenden."
        )

    elif (
        "temporary failure resolving" in combined_output
        or "name or service not known" in combined_output
        or "could not resolve host" in combined_output
    ):
        result["category"] = "dns_error"
        result["recommendation"] = (
            "DNS-Auflösung und Netzwerkverbindung prüfen."
        )

    elif (
        "timeout" in combined_output
        or "timed out" in combined_output
        or "operation timed out" in combined_output
    ):
        result["category"] = "network_error"
        result["recommendation"] = (
            "Netzwerkverbindung und möglichen Timeout prüfen."
        )

    elif "manifest unknown" in combined_output:
        result["category"] = "image_not_found"
        result["recommendation"] = (
            "Docker-Image beziehungsweise Image-Tag prüfen."
        )

    elif failed_steps:
        result["category"] = "update_error"
        result["recommendation"] = (
            "Fehlgeschlagenen Update-Schritt und dessen Protokoll prüfen."
        )

    else:
        result["category"] = "update_error"
        result["recommendation"] = (
            "Update meldet einen Fehler ohne explizit fehlgeschlagenen "
            "Schritt. Ergebnisprotokoll prüfen."
        )

    # Entscheidend ist nicht, ob irgendwann zuvor etwas geändert wurde,
    # sondern ob DER FEHLGESCHLAGENE SCHRITT selbst Änderungen vorgenommen
    # hat.
    failed_changed_steps = [
        step
        for step in failed_steps
        if bool(step.get("changed"))
    ]

    if failed_changed_steps:
        result["rollback_required"] = True
        result["rollback_reason"] = (
            "Mindestens ein fehlgeschlagener Update-Schritt hat "
            "Änderungen am System durchgeführt."
        )

    elif failed_steps:
        result["rollback_required"] = False

        failed_ids = {
            str(step.get("id") or "").strip().lower()
            for step in failed_steps
        }

        verify_ids = {
            "occ_verify",
            "service_verify",
            "verify",
            "health_verify",
            "web_verify",
        }

        if failed_ids and failed_ids.issubset(verify_ids):
            result["rollback_reason"] = (
                "Nur eine nachgelagerte Verifikation ist fehlgeschlagen. "
                "Der aktuelle Anwendungszustand soll erneut geprüft werden; "
                "ein automatischer Rollback ist nicht erforderlich."
            )
            result["recommendation"] = (
                "Anwendungsstatus erneut prüfen. Bei stabilem Dienst und "
                "korrekter Version ist kein Rollback erforderlich."
            )
        else:
            result["rollback_reason"] = (
                "Der fehlgeschlagene Schritt hat selbst keine Änderungen "
                "durchgeführt."
            )

    else:
        result["rollback_required"] = False
        result["rollback_reason"] = (
            "Keine fehlgeschlagenen Änderungsschritte erkannt."
        )

    return result



def analyze_update_verify_result(execute_result, verify_result):
    """
    Bewertet eine fehlgeschlagene Verifikation nach der Update-Ausführung.

    Ein Verify-Fehler ist rollback-relevant, wenn die vorherige echte
    Update-Ausführung den produktiven Zustand bereits verändert hat.
    """

    result = {
        "status": "unknown",
        "category": None,
        "rollback_required": False,
        "rollback_reason": None,
        "recommendation": None,
        "changed_steps": [],
    }

    if not isinstance(verify_result, dict):
        result["status"] = "invalid"
        result["category"] = "internal_error"
        result["recommendation"] = (
            "Ungültiges Ergebnis der Update-Verifikation prüfen."
        )
        return result

    if verify_result.get("ok"):
        result["status"] = "success"
        result["category"] = "verify_success"
        result["rollback_reason"] = (
            "Update-Verifikation erfolgreich."
        )
        return result

    steps = []

    if isinstance(execute_result, dict):
        steps = execute_result.get("steps") or []

    changed_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and bool(step.get("changed"))
        and step.get("status") in (
            "executed",
            "success",
            "completed",
            "ok",
        )
    ]

    result["status"] = "failed"
    result["category"] = "post_update_verify_error"
    result["changed_steps"] = changed_steps

    if changed_steps:
        result["rollback_required"] = True
        result["rollback_reason"] = (
            "Die Update-Ausführung hat den produktiven Zustand verändert "
            "und die anschließende Verifikation ist fehlgeschlagen."
        )
        result["recommendation"] = (
            "Anwendungszustand und Verifikationsfehler prüfen. "
            "Wenn die Anwendung nach dem Update nicht stabil "
            "betriebsbereit ist, auf den gesicherten Zustand zurückrollen."
        )
    else:
        result["rollback_required"] = False
        result["rollback_reason"] = (
            "Die Verifikation ist fehlgeschlagen, es wurden jedoch keine "
            "produktiven Änderungen durch die Update-Ausführung erkannt."
        )
        result["recommendation"] = (
            "Verifikationsfehler prüfen; ein Rollback ist aufgrund der "
            "protokollierten Update-Schritte nicht erforderlich."
        )

    return result



def _background_update_worker(
    manager,
    confirm_token,
    run_id,
    prepare_run_id=None,
):

    try:
        run_update_execute(
            manager,
            confirm_token=confirm_token,
            run_id=run_id,
            prepare_run_id=prepare_run_id,
        )

    except Exception as e:
        import traceback

        print("Background Update Fehler:", e)
        traceback.print_exc()



def start_background_update(
    manager,
    confirm_token="",
    prepare_run_id=None,
):

    rid = _run_id(manager)

    prepare_run_id = str(
        prepare_run_id or ""
    ).strip() or None

    thread = threading.Thread(
        name="app-update-" + rid,
        target=_background_update_worker,
        args=(
            manager,
            confirm_token,
            rid,
            prepare_run_id,
        ),
        daemon=True,
    )

    thread.start()

    return {
        "ok": True,
        "started": True,
        "run_id": rid,
        "prepare_run_id": prepare_run_id,
        "message": "Update wurde im Hintergrund gestartet.",
    }



def run_update_execute(
    manager,
    confirm_token="",
    run_id=None,
    prepare_run_id=None,
):
    rid = run_id or _run_id(manager)
    run_dir = Path(UPDATE_LOG_ROOT) / getattr(manager, "app_id", "app") / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    plan = run_update_plan(manager)
    request_check = _validate_request("execute", confirm_token=confirm_token)

    update_guard = plan.get("update_guard") or {}

    guard_override = False

    if (
        update_guard.get("blocked")
        and update_guard.get("reason") == "pinned_version"
        and confirm_token == UPDATE_CONFIRM_TOKEN
        and not request_check.get("simulate")
    ):
        guard_override = True

    if (
        update_guard.get("blocked")
        and not guard_override
        and not request_check.get("simulate")
    ):
        result = {
            "ok": False,
            "mode": "execute",
            "blocked": True,
            "message": "Update durch Update Guard blockiert.",
            "run_id": rid,
            "run_dir": str(run_dir),
            "app_id": getattr(manager, "app_id", ""),
            "label": getattr(manager, "label", ""),
            "plan": plan,
            "update_guard": update_guard,
            "errors": [
                "Update durch Sicherheits-Guard blockiert."
            ],
        }

        _write_json(run_dir / "plan.json", plan)
        _write_json(run_dir / "result.json", result)

        return result

    session = _new_session(manager, rid, run_dir, "execute")

    session["update_guard_override"] = guard_override

    session["source_prepare_run_id"] = (
        str(prepare_run_id or "").strip()
        or None
    )

    session["simulate"] = bool(request_check.get("simulate"))
    session["execution_enabled"] = bool(bool_setting("update_execution_enabled", False))

    session["execution_authorized"] = (
        not session["simulate"]
        and confirm_token == UPDATE_CONFIRM_TOKEN
    )

    session["authorization_source"] = "webui"
    session["preflight_required"] = True

    if session["simulate"]:
        session["run_type"] = "simulation"
    else:
        session["run_type"] = "execute"

    session["created_by"] = "webui"
    session["cleanup_eligible"] = True

    result = {
        "ok": False,
        "mode": "execute",
        "blocked": not request_check.get("ok"),
        "run_id": rid,
        "run_dir": str(run_dir),
        "source_prepare_run_id": session.get(
            "source_prepare_run_id"
        ),
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "message": "",
        "request_check": request_check,
        "simulate": bool(request_check.get("simulate")),
        "plan": plan,
        "update_guard": update_guard,
        "update_guard_override": guard_override,
        "execute_result": None,
        "verify": None,
        "update_check": None,
        "steps": [],
        "warnings": [],
        "errors": list(request_check.get("errors") or []),
        "session": session,
    }

    _write_json(run_dir / "plan.json", plan)
    _write_json(run_dir / "session.json", session)

    if not request_check.get("ok"):
        _session_update(session, state="blocked", current_step=0, current_action="request_check")
        step = {
            "order": 0,
            "title": "Sicherheitscheck",
            "action": "request_check",
            "risk": "low",
            "status": "blocked",
            "changed": False,
            "message": "; ".join(request_check.get("errors") or ["Update-Ausführung blockiert"]),
        }
        _session_add_step(session, step)
        result["steps"].append(step)
        result["message"] = "Update-Ausführung blockiert."
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        session["finished_at"] = result["finished_at"]
        _session_update(session, state="blocked", current_step=None, current_action=None)
        result["session"] = session

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)
        return result

    _session_update(
        session,
        state="checking",
        current_step=1,
        current_action="safety_check"
    )
    _write_json(run_dir / "session.json", session)

    safety = run_update_safety_check(
        manager,
        session
    )

    result["safety_check"] = safety

    _session_update(
        session,
        state="preflight",
        current_step=2,
        current_action="update_preflight"
    )
    _write_json(run_dir / "session.json", session)

    preflight = run_update_preflight(
        manager,
        session
    )

    result["preflight"] = preflight

    _session_update(
        session,
        state="backup_check",
        current_step=3,
        current_action="backup_check"
    )
    _write_json(run_dir / "session.json", session)

    backup_check = run_update_backup_check(
        manager,
        session
    )

    result["backup_check"] = backup_check

    if (
        not session.get("simulate")
        and not session.get("execution_authorized")
    ):
        result["ok"] = False
        result["blocked"] = True
        result["message"] = "Echte Ausführung nicht autorisiert."

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)

        return result


    if (
        not session.get("simulate")
        and not backup_check.get("ok")
    ):
        result["ok"] = False
        result["blocked"] = True
        result["message"] = "Backup-Prüfung fehlgeschlagen."
        result["errors"].extend(
            backup_check.get("errors") or []
        )

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)

        return result


    if not preflight.get("ok"):
        result["ok"] = False
        result["blocked"] = True
        result["message"] = "Update durch Preflight blockiert."
        result["errors"].extend(
            preflight.get("errors") or []
        )

        session["state"] = "blocked"

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)

        return result


    if not safety.get("ok"):
        result["ok"] = False
        result["blocked"] = True
        result["message"] = "Update durch Sicherheitsprüfung blockiert."
        result["errors"].extend(
            safety.get("errors") or []
        )

        session["state"] = "blocked"
        session["finished_at"] = datetime.now().isoformat(timespec="seconds")
        session["safety_check"] = safety

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)

        return result


    execution_gate = run_update_execution_gate(
        manager,
        session,
        preflight,
        backup_check
    )

    result["execution_gate"] = execution_gate


    _session_update(
        session,
        state="execution_gate",
        current_step=4,
        current_action="execution_gate"
    )
    _write_json(run_dir / "session.json", session)

    if not execution_gate.get("ok"):
        result["ok"] = False
        result["blocked"] = True
        result["message"] = "Update durch Execution Gate blockiert."
        result["errors"].extend(
            execution_gate.get("errors") or []
        )

        session["state"] = "blocked"
        session["execution_gate"] = execution_gate

        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)

        return result


    session["execution_gate_passed"] = True
    session["execution_gate_time"] = datetime.now().isoformat(timespec="seconds")


    try:
        _session_update(session, state="executing", current_step=1, current_action="manager_update_execute")
        _write_json(run_dir / "session.json", session)

        execute_result = manager.update_execute(session=session)

        result["execute_result"] = execute_result
        result["steps"] = execute_result.get("steps") or []


        execute_analysis = analyze_update_execute_result(
            execute_result
        )

        result["execute_analysis"] = execute_analysis
        session["execute_analysis"] = execute_analysis


        _write_json(
            run_dir / "session.json",
            session
        )

        _write_json(
            run_dir / "result.json",
            result
        )


        for step in result["steps"]:
            _session_add_step(session, step)

        if execute_result.get("ok"):
            _session_update(
                session,
                state="verifying",
                current_step=6,
                current_action="update_verify"
            )
            _write_json(run_dir / "session.json", session)
            verify = manager.update_verify()
            result["verify"] = verify

            if not verify.get("ok", True):
                verify_analysis = analyze_update_verify_result(
                    execute_result,
                    verify,
                )

                result["execute_analysis"] = verify_analysis
                session["execute_analysis"] = verify_analysis

            _session_update(
                session,
                state="checking",
                current_step=7,
                current_action="update_check"
            )
            _write_json(run_dir / "session.json", session)
            uc = _manager_update_check(manager)
            result["update_check"] = uc

            result["ok"] = bool(verify.get("ok", True))
            result["message"] = execute_result.get("message") or "Update-Ausführung abgeschlossen."
        else:
            result["ok"] = False
            result["message"] = execute_result.get("message") or "Update-Ausführung fehlgeschlagen."
            if execute_result.get("error"):
                result["errors"].append(str(execute_result.get("error")))

    except Exception as e:
        result["ok"] = False
        result["message"] = "Update-Ausführung Ausnahme: {}".format(e)
        result["errors"].append(str(e))
        _session_add_step(session, {
            "order": 999,
            "title": "Update-Ausführung",
            "action": "manager_update_execute",
            "risk": "high",
            "status": "failed",
            "changed": False,
            "message": str(e),
        })

    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    session["finished_at"] = result["finished_at"]
    _session_update(session, state="completed" if result["ok"] else "failed", current_step=None, current_action=None)
    result["session"] = session

    _write_json(run_dir / "session.json", session)
    _write_json(run_dir / "result.json", result)

    return result



def list_update_runs(app_id):
    """
    Listet Update-Runs einer Anwendung.
    """
    root = Path(UPDATE_LOG_ROOT) / app_id

    runs = []

    if not root.exists():
        return runs

    for run_dir in sorted(
        root.iterdir(),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    ):
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue

        item = {
            "run_id": run_dir.name,
            "path": str(run_dir),
            "run_type": "unknown",
            "cleanup_eligible": False,
            "created": None,
            "state": "unknown",
            "size_bytes": 0,
            "size_mb": 0,
        }

        session_file = run_dir / "session.json"

        try:
            if session_file.exists():
                session = json.loads(
                    session_file.read_text(
                        encoding="utf-8"
                    )
                )

                item["state"] = session.get("state", "unknown")
                item["run_type"] = session.get(
                    "run_type",
                    "unknown"
                )

                item["cleanup_eligible"] = bool(
                    session.get(
                        "cleanup_eligible",
                        False
                    )
                )

                item["created"] = session.get(
                    "started_at"
                )

        except Exception:
            pass

        try:
            total_size = 0

            for f in run_dir.rglob("*"):
                if f.is_file():
                    total_size += f.stat().st_size

            item["size_bytes"] = total_size
            item["size_mb"] = round(
                total_size / 1024 / 1024,
                2
            )

        except Exception:
            pass

        runs.append(item)

    return runs



def cleanup_update_runs(app_id, max_runs=20, delete=False, scope="simulation", run_ids=None):
    """Remove only terminal update logs; preparations remain available for updates."""
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 0:
        raise ValueError("Anzahl aufzubewahrender Läufe muss mindestens 0 sein.")
    if scope not in ("simulation", "finished"):
        raise ValueError("Unbekannte Auswahl.")
    if not app_id or Path(app_id).name != app_id or app_id in (".", ".."):
        raise ValueError("Ungültige App.")
    root = Path(UPDATE_LOG_ROOT) / app_id
    if root.is_symlink():
        raise ValueError("Verknüpfte Protokollordner werden nicht gelöscht.")
    runs = list_update_runs(app_id)
    eligible = [r for r in runs
                if r.get("state") in ("completed", "failed", "blocked")
                and r.get("run_type") in (("simulation",) if scope == "simulation"
                                          else ("simulation", "execute"))]
    candidates = eligible[max_runs:]
    if run_ids is not None:
        candidates = [r for r in candidates if r["run_id"] in run_ids]

    total_size = sum(
        r.get("size_bytes", 0)
        for r in runs
    )

    candidate_size = sum(
        r.get("size_bytes", 0)
        for r in candidates
    )

    result = {
        "app_id": app_id,
        "total_runs": len(runs),
        "max_runs": max_runs,
        "delete": delete,

        "total_size_bytes": total_size,
        "total_size_mb": round(
            total_size / 1024 / 1024,
            2
        ),

        "candidate_size_bytes": candidate_size,
        "candidate_size_mb": round(
            candidate_size / 1024 / 1024,
            2
        ),

        "candidates": candidates,
        "deleted": [],
        "errors": [],
    }

    if delete:
        for run in candidates:
            try:
                path = Path(run["path"])
                if path.is_symlink() or path.parent.resolve() != root.resolve():
                    raise ValueError("Unsicherer Protokollpfad")
                current = json.loads((path / "session.json").read_text(encoding="utf-8"))
                if (current.get("state") not in ("completed", "failed", "blocked")
                        or current.get("run_type") not in ("simulation", "execute")):
                    raise ValueError("Lauf ist nicht mehr abgeschlossen")
                shutil.rmtree(path)

                result["deleted"].append(
                    run["run_id"]
                )

            except Exception as e:
                result["errors"].append(
                    "{}: {}".format(
                        run["run_id"],
                        e
                    )
                )

    return result
