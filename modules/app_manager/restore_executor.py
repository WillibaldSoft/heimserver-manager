# -*- coding: utf-8 -*-
import json
import socket
from datetime import datetime
from pathlib import Path

from .restore_plan import run_restore_plan
from .backup_engine import run_backup
from .runner import sh
from .settings import get_setting, bool_setting


RESTORE_LOG_ROOT = get_setting("restore_log_root", "/srv/backups/apps/restore_runs")
# Execution permission is read at each check, so saved settings apply immediately.


def _now():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


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


def _stub_result(step, handler):
    return {
        "order": step.get("order"),
        "title": step.get("title"),
        "action": step.get("action"),
        "risk": step.get("risk"),
        "command": step.get("command") or "",
        "status": "blocked",
        "changed": False,
        "handler": handler,
        "message": "Handler vorbereitet, echte Ausführung noch deaktiviert",
    }


def _rollback_plan(manager, run_dir):
    app_id = getattr(manager, "app_id", "app")
    label = getattr(manager, "label", app_id)
    return {
        "enabled": True,
        "mode": "planned",
        "app_id": app_id,
        "label": label,
        "target_dir": str(Path(run_dir) / "rollback"),
        "description": "Vor einem echten Restore wird hier ein aktueller Sicherungspunkt erzeugt.",
        "planned_actions": [
            "aktuellen App-Status sichern",
            "aktuelle Konfiguration sichern",
            "aktuelle Datenbank sichern, falls definiert",
            "aktuellen Health-Status sichern",
            "Rollback-Metadaten schreiben",
        ],
    }


def _create_rollback_backup(manager, run_dir):
    rollback_dir = Path(run_dir) / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "ok": False,
        "mode": "executed",
        "target_dir": str(rollback_dir),
        "message": "",
        "backup": None,
    }

    try:
        backup_profile = str(
            getattr(
                manager,
                "restore_rollback_backup_profile",
                None,
            )
            or getattr(
                manager,
                "update_backup_profile",
                None,
            )
            or "system"
        ).strip()

        backup = run_backup(
            manager,
            profile=backup_profile,
        )

        result["backup_profile"] = backup_profile
        result["backup"] = backup
        result["ok"] = bool(backup.get("ok"))
        result["message"] = (
            "Rollback-Backup erzeugt"
            if result["ok"]
            else "Rollback-Backup fehlgeschlagen"
        )
    except Exception as e:
        result["ok"] = False
        result["message"] = "Rollback-Backup Ausnahme"
        result["error"] = str(e)

    _write_json(rollback_dir / "rollback-backup.json", result)
    return result


def _run_command(step, handler, timeout=300):
    cmd = step.get("command") or ""

    if not cmd:
        r = _stub_result(step, handler)
        r["status"] = "skipped"
        r["message"] = "Kein Befehl definiert"
        return r

    if not bool_setting("restore_execution_enabled", False):
        r = _stub_result(step, handler)
        r["command"] = cmd
        r["status"] = "blocked"
        r["message"] = "Feature-Flag blockiert echte Ausführung"
        return r

    r = sh(cmd, timeout=timeout)
    ok = bool(r.get("ok"))
    return {
        "order": step.get("order"),
        "title": step.get("title"),
        "action": step.get("action"),
        "risk": step.get("risk"),
        "command": cmd,
        "status": "executed" if ok else "failed",
        "changed": ok,
        "handler": handler,
        "message": "Befehl ausgeführt" if ok else "Befehl fehlgeschlagen",
        "returncode": r.get("returncode"),
        "stdout": r.get("stdout"),
        "stderr": r.get("stderr"),
    }


def _run_multi_commands(step, handler, commands, timeout=600):
    base = _stub_result(step, handler)
    base["commands"] = commands or []

    if not commands:
        base["status"] = "skipped"
        base["message"] = "Keine Befehle definiert"
        return base

    if not bool_setting("restore_execution_enabled", False):
        base["status"] = "blocked"
        base["message"] = "Feature-Flag blockiert echte Ausführung"
        return base

    results = []
    ok_all = True

    for cmd in commands:
        r = sh(cmd, timeout=timeout)
        results.append({
            "command": cmd,
            "ok": r.get("ok"),
            "returncode": r.get("returncode"),
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
        })
        if not r.get("ok"):
            ok_all = False
            break

    base["status"] = "executed" if ok_all else "failed"
    base["changed"] = ok_all
    base["message"] = "Befehle ausgeführt" if ok_all else "Befehl fehlgeschlagen"
    base["results"] = results
    return base


def _handle_stop_application(manager, step):
    result = _stub_result(
        step,
        "_handle_stop_application",
    )

    if not bool_setting("restore_execution_enabled", False):
        result["status"] = "blocked"
        result["message"] = (
            "Feature-Flag blockiert echte Ausführung"
        )
        return result

    try:
        hook_result = manager.stop_for_restore()
    except Exception as e:
        result["status"] = "failed"
        result["message"] = (
            "Stop-Hook Ausnahme"
        )
        result["error"] = str(e)
        return result

    if not isinstance(hook_result, dict):
        result["status"] = "failed"
        result["message"] = (
            "Stop-Hook lieferte kein gültiges Ergebnis"
        )
        return result

    ok = hook_result.get("ok") is True

    result["status"] = (
        "executed"
        if ok
        else "failed"
    )
    result["changed"] = bool(
        hook_result.get("changed")
    )
    result["message"] = (
        hook_result.get("message")
        or (
            "Anwendung gestoppt"
            if ok
            else "Anwendung konnte nicht gestoppt werden"
        )
    )
    result["hook_result"] = hook_result

    return result


def _handle_create_rollback_backup(manager, step):
    return _stub_result(step, "_handle_create_rollback_backup")


def _handle_restore_config(manager, step):
    files = ((step.get("details") or {}).get("files") or [])
    commands = [x.get("command") for x in files if x.get("command")]
    return _run_multi_commands(step, "_handle_restore_config", commands, timeout=300)


def _handle_restore_data(manager, step):
    paths = ((step.get("details") or {}).get("paths") or [])
    commands = [x.get("command") for x in paths if x.get("command")]
    return _run_multi_commands(step, "_handle_restore_data", commands, timeout=3600)


def _handle_restore_database(manager, step):
    return _run_command(step, "_handle_restore_database", timeout=3600)


def _handle_start_application(manager, step):
    result = _stub_result(
        step,
        "_handle_start_application",
    )

    if not bool_setting("restore_execution_enabled", False):
        result["status"] = "blocked"
        result["message"] = (
            "Feature-Flag blockiert echte Ausführung"
        )
        return result

    try:
        hook_result = manager.start_after_restore()
    except Exception as e:
        result["status"] = "failed"
        result["message"] = (
            "Start-Hook Ausnahme"
        )
        result["error"] = str(e)
        return result

    if not isinstance(hook_result, dict):
        result["status"] = "failed"
        result["message"] = (
            "Start-Hook lieferte kein gültiges Ergebnis"
        )
        return result

    ok = hook_result.get("ok") is True

    result["status"] = (
        "executed"
        if ok
        else "failed"
    )
    result["changed"] = bool(
        hook_result.get("changed")
    )
    result["message"] = (
        hook_result.get("message")
        or (
            "Anwendung gestartet"
            if ok
            else "Anwendung konnte nicht gestartet werden"
        )
    )
    result["hook_result"] = hook_result

    return result


def _handle_health_check(manager, step):
    result = _stub_result(
        step,
        "_handle_health_check",
    )

    try:
        health = manager.restore_healthcheck()

        result["health"] = health
        result["status"] = "executed"
        result["changed"] = False
        result["message"] = (
            "Restore-Health-Check ausgeführt"
        )

        if (
            not isinstance(health, dict)
            or health.get("ok") is not True
        ):
            result["status"] = "failed"
            result["message"] = (
                "Restore-Health-Check meldet Fehler"
            )

    except Exception as e:
        result["status"] = "failed"
        result["message"] = (
            "Restore-Health-Check Ausnahme"
        )
        result["error"] = str(e)

    return result


def _handle_unknown(manager, step):
    return _stub_result(step, "_handle_unknown")


def _dispatch_step(manager, step, mode):
    handlers = {
        "stop_application": _handle_stop_application,
        "create_rollback_backup": _handle_create_rollback_backup,
        "restore_config": _handle_restore_config,
        "restore_data": _handle_restore_data,
        "restore_database": _handle_restore_database,
        "start_application": _handle_start_application,
        "health_check": _handle_health_check,
    }

    handler = handlers.get(step.get("action"), _handle_unknown)

    if mode == "execute":
        return handler(manager, step)

    result = _stub_result(step, getattr(handler, "__name__", "_handle_unknown"))
    result["status"] = "simulated"
    result["message"] = "No-Op: Schritt wurde nicht ausgeführt"
    return result


def _validate_execute_request(mode, confirm_token):
    errors = []
    expected = get_setting("restore_confirm_token", "RESTORE")
    require_token = bool_setting("restore_require_token", True)

    if mode == "execute" and require_token and confirm_token != expected:
        errors.append("Sicherheitsbestätigung fehlt oder ist ungültig. Erwartet: {}".format(expected))

    return {"ok": len(errors) == 0, "errors": errors, "warnings": []}


def _validate_execute_preconditions(plan):
    errors = []
    warnings = []

    if not plan.get("restore_possible"):
        errors.append("Restore laut Plan nicht möglich")

    readiness = plan.get("readiness") or {}
    score = readiness.get("score")
    if isinstance(score, int) and score < 80:
        errors.append(f"Readiness-Score zu niedrig: {score}")

    if readiness.get("level") in ("critical", "blocked"):
        errors.append(f"Readiness-Level blockiert Restore: {readiness.get('level')}")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def _new_session(manager, backup_dir, mode, run_id):
    return {
        "id": run_id,
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "mode": mode,
        "state": "created",
        "current_step": None,
        "current_action": None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "backup": str(backup_dir),
        "steps": [],
        "rollback": {
            "available": False,
            "executed": False,
        },
        "statistics": {
            "total": 0,
            "ok": 0,
            "failed": 0,
            "blocked": 0,
            "skipped": 0,
            "simulated": 0,
        },
    }


def _state_for_action(action):
    return {
        "stop_application": "stopping",
        "create_rollback_backup": "rollback",
        "restore_config": "restoring_config",
        "restore_data": "restoring_data",
        "restore_database": "restoring_database",
        "start_application": "starting",
        "health_check": "healthcheck",
    }.get(action, "restoring")


def _session_write(session):
    run_dir = session.get("run_dir")
    if run_dir:
        _write_json(Path(run_dir) / "session.json", session)


def _session_update(session, state=None, current_step=None, current_action=None):
    if state:
        session["state"] = state
    session["current_step"] = current_step
    session["current_action"] = current_action
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _session_write(session)


def _session_state(session, state):
    session["state"] = state
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _session_write(session)


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

    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _session_write(session)


def execute_restore(manager, backup_dir, mode="noop", confirm_token=""):
    rid = _run_id(manager)
    run_dir = Path(RESTORE_LOG_ROOT) / getattr(manager, "app_id", "app") / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    session = _new_session(manager, backup_dir, mode, rid)
    session["run_dir"] = str(run_dir)

    if mode == "execute":
        request_check = _validate_execute_request(mode, confirm_token)
        errors = list(request_check.get("errors") or [])

        if not bool_setting("restore_execution_enabled", False):
            errors.append("Feature-Flag verhindert Restore.")

        if errors:
            result = {
                "ok": False,
                "mode": "execute",
                "blocked": True,
                "run_id": rid,
                "run_dir": str(run_dir),
                "app_id": getattr(manager, "app_id", ""),
                "label": getattr(manager, "label", ""),
                "backup_dir": str(backup_dir),
                "started_at": session["started_at"],
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "message": "Restore-Ausführung blockiert.",
                "request_check": request_check,
                "errors": errors,
                "steps": [],
                "session": session,
            }
            _session_state(session, "blocked")
            session["finished_at"] = result["finished_at"]
            _write_json(run_dir / "session.json", session)
            _write_json(run_dir / "result.json", result)
            return result

    _session_state(session, "validating")
    plan = run_restore_plan(manager, backup_dir)

    result = {
        "ok": False,
        "mode": mode,
        "run_id": rid,
        "run_dir": str(run_dir),
        "app_id": getattr(manager, "app_id", ""),
        "label": getattr(manager, "label", ""),
        "backup_dir": str(backup_dir),
        "started_at": session["started_at"],
        "finished_at": None,
        "restore_possible": plan.get("restore_possible", False),
        "readiness": plan.get("readiness", {}),
        "summary": plan.get("summary", {}),
        "warnings": list(plan.get("warnings") or []),
        "errors": list(plan.get("errors") or []),
        "steps": [],
        "plan": plan,
        "rollback": _rollback_plan(manager, run_dir),
        "session": session,
    }

    _write_json(run_dir / "plan.json", plan)
    _write_json(run_dir / "rollback-plan.json", result["rollback"])

    if mode not in ("noop", "prepare", "execute"):
        result["errors"].append("Unterstützte Modi: noop, prepare, execute")
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _session_state(session, "failed")
        session["finished_at"] = result["finished_at"]
        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)
        return result

    preconditions = _validate_execute_preconditions(plan)
    result["preconditions"] = preconditions

    if not preconditions.get("ok"):
        result["errors"].extend(preconditions.get("errors") or [])
        result["warnings"].extend(preconditions.get("warnings") or [])
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _session_state(session, "failed")
        session["finished_at"] = result["finished_at"]
        _write_json(run_dir / "session.json", session)
        _write_json(run_dir / "result.json", result)
        return result

    rollback_result = None

    if mode in ("prepare", "execute"):
        _session_state(session, "rollback")

        rollback_result = _create_rollback_backup(
            manager,
            run_dir,
        )

        result["rollback"]["mode"] = "executed"
        result["rollback"]["result"] = rollback_result

        session["rollback"]["available"] = bool(
            rollback_result.get("ok")
        )
        session["rollback"]["executed"] = True

        if not rollback_result.get("ok"):
            result["errors"].append(
                "Rollback-Backup konnte nicht erzeugt werden"
            )

            # Bei echter Ausführung darf ohne gültigen
            # Sicherungspunkt kein destruktiver Restore beginnen.
            if mode == "execute":
                result["finished_at"] = (
                    datetime.now().isoformat(
                        timespec="seconds"
                    )
                )

                _session_update(
                    session,
                    state="failed",
                    current_step=None,
                    current_action=None,
                )

                session["finished_at"] = (
                    result["finished_at"]
                )

                result["session"] = session

                _write_json(
                    run_dir / "session.json",
                    session,
                )

                _write_json(
                    run_dir / "result.json",
                    result,
                )

                return result

    _session_state(session, "restoring")

    for step in plan.get("steps") or []:
        action = step.get("action")
        order = step.get("order")

        _session_update(
            session,
            state=_state_for_action(action),
            current_step=order,
            current_action=action,
        )
        _write_json(run_dir / "session.json", session)

        dispatched = _dispatch_step(manager, step, mode)

        if (
            mode in ("prepare", "execute")
            and action == "create_rollback_backup"
        ):
            changed = bool(
                rollback_result
                and rollback_result.get("ok")
            )

            dispatched["status"] = (
                "executed"
                if changed
                else "failed"
            )

            dispatched["changed"] = changed

            dispatched["message"] = (
                "Rollback-Backup erzeugt"
                if changed
                else "Rollback-Backup fehlgeschlagen"
            )

            dispatched["rollback_result"] = (
                rollback_result
            )

        result["steps"].append(dispatched)
        _session_add_step(session, dispatched)
        _write_json(run_dir / "session.json", session)

        if dispatched.get("status") == "failed":
            result["errors"].append("Restore-Schritt fehlgeschlagen: {}".format(action))
            _session_update(session, state="failed", current_step=order, current_action=action)
            break

    result["ok"] = len(result["errors"]) == 0
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")

    if result["ok"]:
        if mode == "noop":
            final_state = "simulated"
        elif mode == "prepare":
            final_state = "prepared"
        else:
            final_state = "completed"

        _session_update(
            session,
            state=final_state,
            current_step=None,
            current_action=None,
        )
    else:
        _session_update(
            session,
            state="failed",
            current_step=None,
            current_action=None,
        )

    session["finished_at"] = result["finished_at"]

    _write_json(run_dir / "session.json", session)
    _write_json(run_dir / "result.json", result)
    return result
