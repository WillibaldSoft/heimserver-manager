from ui_translation import html_literal as _ui_html, text as _ui_text
from i18n import tr
import os
# -*- coding: utf-8 -*-
import json
import os
import tarfile
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from flask import send_file, Response, request, redirect, jsonify

from .registry import all_managers, get_manager
from .backup import backup_check, DEFAULT_BACKUP_ROOT
from .backup_engine import get_backup_profiles
from .database import database_check
from .restore import restore_info
from .repair import repair_check
from .restore_engine import run_restore_check
from .restore_plan import run_restore_plan
from .restore_executor import execute_restore, RESTORE_LOG_ROOT
from .update_engine import run_update_plan, run_update_prepare, run_update_execute, start_background_update, UPDATE_LOG_ROOT, UPDATE_CONFIRM_TOKEN

# ==========================================================
# Globaler Jobstatus (Phase 5.10.1)
# ==========================================================

_ACTIVE_JOB = None
_ACTIVE_JOB_LOCK = threading.Lock()


def set_active_job(app_id=None, action=None, run_id=None):
    global _ACTIVE_JOB

    with _ACTIVE_JOB_LOCK:
        if app_id is None:
            _ACTIVE_JOB = None
            return

        _ACTIVE_JOB = {
            "app_id": app_id,
            "action": action,
            "run_id": run_id,
            "pid": os.getpid(),
            "started": int(time.time()),
        }


def get_active_job(app_id=None):
    """Ermittelt laufende App-Jobs robust aus session.json.

    RAM-Status ist nur Fallback. Dateibasierter Status überlebt Seitenwechsel
    und ist später für Schlaf-Blocker nutzbar.
    """
    terminal = {"completed", "failed", "blocked", "simulated", "prepared", "finished"}

    def read_json(path):
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    jobs = []

    root = Path(DEFAULT_BACKUP_ROOT)
    if root.exists():
        app_dirs = []
        if app_id:
            app_dirs = [root / app_id]
        else:
            app_dirs = [x for x in root.iterdir() if x.is_dir()]

        for app_dir in app_dirs:
            aid = app_dir.name

            # Backup-Runs: /backup_root/app/20xx/session.json
            for run_dir in app_dir.iterdir() if app_dir.exists() else []:
                sf = run_dir / "session.json"
                if not run_dir.is_dir() or not sf.exists():
                    continue

                session = read_json(sf)
                state = session.get("state")
                if not state or state in terminal:
                    continue

                stats = session.get("statistics") or {}
                total = int(stats.get("total", 6) or 6)
                done = int(stats.get("ok", 0) or 0)
                progress = int(done * 100 / total) if total else 0

                cs = int(session.get("current_step") or 0)
                if cs > 0:
                    progress = int((cs - 1) * 100 / 6)
                    progress = max(0, min(progress, 99))

                jobs.append({
                    "app_id": aid,
                    "type": "backup",
                    "action": "backup",
                    "run_id": run_dir.name,
                    "state": state,
                    "current_step": session.get("current_step"),
                    "current_action": session.get("current_action"),
                    "current_detail": session.get("current_detail"),
                    "current_path_key": session.get("current_path_key"),
                    "progress_percent": progress,
                    "updated_at": session.get("updated_at"),
                    "started_at": session.get("started_at"),
                    "url": "/apps/{}/backup/runs/{}".format(aid, run_dir.name),
                    "source": "session.json",
                    "session_file": str(sf),
                })

    if jobs:
        jobs.sort(key=lambda x: x.get("updated_at") or x.get("started_at") or "", reverse=True)
        return jobs[0]

    with _ACTIVE_JOB_LOCK:
        if _ACTIVE_JOB is None:
            return None

        job = dict(_ACTIVE_JOB)
        if app_id and job.get("app_id") != app_id:
            return None

        return job




def _status_class(ok, warnings=None):
    if ok and not warnings:
        return "ok"
    if ok:
        return "warn"
    return "err"


def _pre(ctx, data):
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    return _ui_html("<pre>{}</pre>").format(ctx.esc(text or ""))


def _card(ctx, title, body):
    return _ui_html("<div class='card'><h3>{}</h3>{}</div>").format(ctx.esc(_ui_text(title)), body)


def _details_card(ctx, title, data):
    return _card(
        ctx,
        title,
        _ui_html("<details><summary>Anzeigen</summary>{}</details>").format(_pre(ctx, data)),
    )


def _yes_no(v):
    return _ui_text("Ja" if bool(v) else "Nein")


def _risk_text(v):
    return _ui_text({
        "low": "Niedrig",
        "medium": "Mittel",
        "high": "Hoch",
    }.get(v, str(v or "—")))


def _status_text(v):
    return _ui_text({
        "executed": "Erfolgreich",
        "blocked": "Blockiert",
        "failed": "Fehler",
        "simulated": "Simulation",
        "skipped": "Übersprungen",
    }.get(v, str(v or "—")))


def _display(v):
    if v is None or v == "":
        return "—"
    return str(v)


def _profile_label(data):
    if not isinstance(data, dict):
        return _ui_text("—")
    return _ui_text(data.get("profile_label") or {
        "system": "Systembackup",
        "data": "Datenbackup (inkrementell)",
        "full": "Komplettbackup",
    }.get(data.get("profile"), "—"))


def _backup_mode_label(mode):
    return _ui_text({
        "incremental-prepared": "Hardlink-Snapshot (rsync)",
        "incremental": "Inkrementelles Datenbackup",
        "full": "Komplettbackup",
        "system": "Systembackup",
    }.get(str(mode), str(mode or "—")))


def _restore_backup_dashboard(ctx, backup_dir, readiness):
    """Render backup information for the restore page.

    Must always return a string. Some apps do not have restore/backups yet;
    returning None here breaks routes like /apps/<app>/restore.
    """
    if not isinstance(readiness, dict):
        readiness = {}

    backup = readiness.get("backup") if isinstance(readiness.get("backup"), dict) else {}
    result = backup.get("result") if isinstance(backup.get("result"), dict) else {}
    manifest = backup.get("manifest") if isinstance(backup.get("manifest"), dict) else {}

    backup_dir = Path(backup_dir) if backup_dir else None

    # Fallback: direkt aus Backup-Ordner lesen
    if backup_dir:
        try:
            rf = backup_dir / "result.json"
            if not result and rf.exists():
                result = json.loads(rf.read_text(encoding="utf-8"))
        except Exception:
            result = {}

        try:
            mf = backup_dir / "manifest.json"
            if not manifest and mf.exists():
                manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    if not isinstance(result, dict):
        result = {}
    if not isinstance(manifest, dict):
        manifest = {}

    if not backup_dir or (not result and not manifest):
        return (
            _ui_html("<div class='card'>"
            "<h3>Restore-Backups</h3>"
            "<p class='warn'>Für diese App sind noch keine verwertbaren Restore-Backup-Metadaten vorhanden.</p>"
            "</div>")
        )

    steps = result.get("steps") or manifest.get("steps") or {}
    if not isinstance(steps, dict):
        steps = {}

    archive = result.get("archive") or manifest.get("archive") or ""
    archive_name = Path(archive).name if archive else "—"

    body = _ui_html("<div class='grid'>")

    body += _ui_html("<div class='card'><h3>Backup</h3>")
    body += _ui_html("<p>Run: <code>{}</code><br>App: <b>{}</b><br>Host: <code>{}</code><br>Profil: <code>{}</code><br>Modus: <code>{}</code><br>Archiv: <code>{}</code><br>Größe: <code>{}</code></p>").format(
        ctx.esc(backup_dir.name),
        ctx.esc(_ui_text(result.get("label")) or _ui_text(manifest.get("label")) or "—"),
        ctx.esc(result.get("hostname") or manifest.get("hostname") or "—"),
        ctx.esc(_profile_label(result or manifest)),
        ctx.esc(_backup_mode_label((result.get("data_backup") or {}).get("mode") or manifest.get("mode") or result.get("profile"))),
        ctx.esc(archive_name),
        ctx.esc(_display(result.get("archive_size") or manifest.get("archive_size"))),
    )
    body += _ui_html("</div>")

    def yes_item(label, ok):
        return _ui_html("<li><b class='{}'>{}</b> {}</li>").format(
            "ok" if ok else "warn",
            "✓" if ok else "⚠",
            ctx.esc(_ui_text(label)),
        )

    body += _ui_html("<div class='card'><h3>Enthalten</h3><ul>")
    body += yes_item("Konfiguration", "config_files" in steps)
    body += yes_item("Daten", "paths" in steps)
    body += yes_item("Datenbank", "database" in steps)
    body += yes_item("Zusatzinformationen", "extra" in steps)
    body += _ui_html("</ul></div>")

    db = steps.get("database") or {}
    body += _ui_html("<div class='card'><h3>Datenbank</h3>")
    if isinstance(db, dict) and db.get("supported"):
        body += _ui_html("<p><b class='{}'>{}</b><br>Typ: <code>{}</code><br>Datei: <code>{}</code><br>Größe: <code>{}</code></p>").format(
            "ok" if db.get("ok") else "err",
            _ui_text("Dump vorhanden") if db.get("ok") else _ui_text("Dump fehlerhaft"),
            ctx.esc(_display(db.get("type"))),
            ctx.esc(Path(db.get("file", "")).name if db.get("file") else _display(db.get("target"))),
            ctx.esc(_display(db.get("size"))),
        )
    else:
        body += _ui_html("<p>Keine Datenbank im Backup.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Restore-Hinweise</h3><ul>")
    body += _ui_html("<li class='warn'>Restore kann produktive Daten überschreiben.</li>")
    body += _ui_html("<li class='warn'>App/Container müssen für einen echten Restore gestoppt werden.</li>")
    if isinstance(db, dict) and db.get("supported"):
        body += _ui_html("<li class='warn'>Datenbank würde zurückgespielt/überschrieben.</li>")
    body += _ui_html("<li>Diese Seite führt noch keinen Restore aus.</li>")
    body += _ui_html("</ul></div>")

    body += _ui_html("</div>")
    return body

def _find_restore_checks(data):
    if not isinstance(data, dict):
        return [], {}

    checks = (
        data.get("detail_checks")
        or data.get("checks_list")
        or []
    )
    summary = data.get("check_summary") or {}

    if checks:
        return checks, summary

    for v in data.values():
        if isinstance(v, dict):
            c, s = _find_restore_checks(v)
            if c:
                return c, s

    return [], {}


def _normalize_restore_readiness(data):
    if not isinstance(data, dict):
        return data

    checks, summary = _find_restore_checks(data)
    errors = data.get("errors") or []
    warnings = data.get("warnings") or []

    failed_checks = []
    warning_checks = []

    for c in checks:
        ok = bool(c.get("ok"))
        cw = c.get("warnings") or []
        ce = c.get("errors") or []

        if not ok or ce:
            failed_checks.append(c)
        elif cw:
            warning_checks.append(c)

    if checks:
        restore_possible = len(errors) == 0 and len(failed_checks) == 0
    else:
        restore_possible = bool(data.get("restore_possible")) and len(errors) == 0

    old = data.get("readiness") or {}

    if not restore_possible:
        level = "critical"
        score = min(int(old.get("score", 0) or 0), 50)
    elif warnings or warning_checks:
        level = "warning"
        score = max(int(old.get("score", 0) or 0), 75)
    else:
        level = "ready"
        score = max(int(old.get("score", 0) or 0), 95)

    data["restore_possible"] = restore_possible
    data["readiness"] = {
        **old,
        "score": score,
        "level": level,
        "logic": "checks-first",
        "failed_checks": len(failed_checks),
        "warning_checks": len(warning_checks),
        "errors": len(errors),
        "warnings": len(warnings),
    }

    return data


def _restore_readiness_dashboard(ctx, readiness):
    score_data = readiness.get("readiness") or {}
    score = score_data.get("score", "?")
    level = score_data.get("level", "unknown")
    possible = bool(readiness.get("restore_possible"))

    warnings = readiness.get("warnings") or []
    errors = readiness.get("errors") or []

    if errors or not possible:
        cls = "err"
        status = "Nicht bereit"
    elif warnings or level == "warning":
        cls = "warn"
        status = "Mit Warnungen"
    else:
        cls = "ok"
        status = "Bereit"

    body = _ui_html("<div class='card'><h3>Restore-Prüfung</h3>")
    body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Score: <b>{}</b> / 100<br>Level: <code>{}</code><br>Restore möglich: <b class='{}'>{}</b></p>").format(
        cls,
        ctx.esc(_ui_text(status)),
        ctx.esc(score),
        ctx.esc(level),
        cls,
        ctx.esc(_ui_text("ja") if possible else _ui_text("nein")),
    )
    body += _ui_html("</div>")

    body += _ui_html("<div class='grid'>")

    body += _ui_html("<div class='card'><h3>Fehler</h3>")
    if errors:
        body += _ui_html("<ul>")
        for e in errors:
            body += _ui_html("<li class='err'>✖ {}</li>").format(ctx.esc(e))
        body += _ui_html("</ul>")
    else:
        body += _ui_html("<p class='ok'>✓ Keine Fehler</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Warnungen</h3>")
    if warnings:
        body += _ui_html("<ul>")
        for w in warnings:
            body += _ui_html("<li class='warn'>⚠ {}</li>").format(ctx.esc(w))
        body += _ui_html("</ul>")
    else:
        body += _ui_html("<p class='ok'>✓ Keine Warnungen</p>")
    body += _ui_html("</div>")

    checks, check_summary = _find_restore_checks(readiness)
    body += _ui_html("<div class='card'><h3>Detailchecks</h3>")
    if check_summary:
        body += _ui_html("<p>Gesamt: <b>{}</b> · OK: <b class='ok'>{}</b> · Fehler: <b class='err'>{}</b> · Warnungen: <b class='warn'>{}</b></p>").format(
            ctx.esc(str(check_summary.get("total", ""))),
            ctx.esc(str(check_summary.get("ok", ""))),
            ctx.esc(str(check_summary.get("failed", ""))),
            ctx.esc(str(check_summary.get("warnings", ""))),
        )
    if checks:
        body += _ui_html("<table><tr><th>Check</th><th>Status</th><th>Meldung</th></tr>")
        for c in checks:
            ok = bool(c.get("ok"))
            cw = c.get("warnings") or []
            ce = c.get("errors") or []
            ccls = "ok" if ok and not cw else ("warn" if ok else "err")
            cstatus = "✓ OK" if ccls == "ok" else ("⚠ Warnung" if ccls == "warn" else "✖ Fehler")
            msg = c.get("message") or "; ".join(ce or cw) or "—"
            body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td><td>{}</td></tr>").format(
                ctx.esc(c.get("name", "")),
                ccls,
                ctx.esc(cstatus),
                ctx.esc(_ui_text(msg)),
            )
        body += _ui_html("</table>")
    else:
        body += _ui_html("<p class='warn'>Noch keine Detailchecks vorhanden.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Risiko</h3>")
    body += _ui_html("<ul>")
    if possible:
        body += _ui_html("<li class='warn'>⚠ Restore würde produktive Daten überschreiben.</li>")
    else:
        body += _ui_html("<li class='err'>✖ Restore aktuell nicht freigabefähig.</li>")
    body += _ui_html("<li>Diese Seite führt weiterhin keinen Restore aus.</li>")
    body += _ui_html("</ul>")
    body += _ui_html("</div>")

    body += _ui_html("</div>")
    return body



def _backup_archive_card(ctx, m, run_id, result):
    archive = result.get("archive", "")
    archive_path = Path(archive) if archive else None
    archive_exists = bool(archive_path and archive_path.exists())
    archive_name = archive_path.name if archive_path else "—"

    size = result.get("archive_size", "—")
    host = result.get("hostname", "—")
    timestamp = result.get("timestamp", "—")

    sha_file = Path(str(archive) + ".sha256") if archive else None
    sha_exists = bool(sha_file and sha_file.exists())
    sha_text = ""
    if sha_exists:
        try:
            sha_text = sha_file.read_text(encoding="utf-8").strip()
        except Exception:
            sha_text = ""

    cls = "ok" if archive_exists else "err"
    status = "✓ Archiv vorhanden" if archive_exists else "⚠ Archiv fehlt"

    body = _ui_html("<div class='card'><h3>Archiv</h3>")
    body += _ui_html("<p><b class='{}'>{}</b></p>").format(cls, ctx.esc(_ui_text(status)))
    body += _ui_html("<table>")
    body += _ui_html("<tr><th>Datei</th><td><code>{}</code></td></tr>").format(ctx.esc(archive_name))
    body += _ui_html("<tr><th>Größe</th><td><code>{}</code></td></tr>").format(ctx.esc(_display(size)))
    body += _ui_html("<tr><th>Host</th><td><code>{}</code></td></tr>").format(ctx.esc(_display(host)))
    body += _ui_html("<tr><th>Erstellt</th><td><code>{}</code></td></tr>").format(ctx.esc(_display(timestamp)))
    body += _ui_html("<tr><th>SHA256</th><td>{}</td></tr>").format(ctx.esc(_ui_text("vorhanden") if sha_exists else _ui_text("nicht vorhanden")))
    body += _ui_html("</table>")

    if archive_exists:
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs/{}/download'>Download</a></p>").format(
            ctx.esc(m.app_id),
            ctx.esc(run_id),
        )

    if sha_text:
        body += _ui_html("<details><summary>SHA256 anzeigen</summary><pre>{}</pre></details>").format(
            ctx.esc(sha_text)
        )

    body += _ui_html("</div>")
    return body


def _backup_content_dashboard(ctx, result):
    steps = result.get("steps") or {}
    body = _ui_html("<div class='grid'>")

    cfg = steps.get("config_files") or {}
    cfg_ok = all(v.get("ok") for v in cfg.values()) if isinstance(cfg, dict) and cfg else False
    body += _ui_html("<div class='card'><h3>Konfiguration</h3>")
    body += _ui_html("<p><b class='{}'>{}</b><br>{} Datei(en)</p>").format(
        "ok" if cfg_ok else "warn",
        _ui_text("✓ Gesichert") if cfg_ok else _ui_text("Nicht vorhanden"),
        ctx.esc(str(len(cfg) if isinstance(cfg, dict) else 0)),
    )
    body += _ui_html("</div>")

    paths = steps.get("paths") or {}
    paths_ok = all(v.get("ok") for v in paths.values()) if isinstance(paths, dict) and paths else False
    body += _ui_html("<div class='card'><h3>Daten</h3>")
    body += _ui_html("<p><b class='{}'>{}</b><br>{} Pfad(e)</p>").format(
        "ok" if paths_ok else "warn",
        _ui_text("✓ Gesichert") if paths_ok else _ui_text("Nicht vorhanden"),
        ctx.esc(str(len(paths) if isinstance(paths, dict) else 0)),
    )
    body += _ui_html("</div>")

    db = steps.get("database") or {}
    db_supported = bool(db.get("supported"))
    db_ok = bool(db.get("ok"))
    body += _ui_html("<div class='card'><h3>Datenbank</h3>")
    if db_supported:
        body += _ui_html("<p><b class='{}'>{}</b><br>Typ: <code>{}</code><br>Datei: <code>{}</code><br>Größe: <code>{}</code></p>").format(
            "ok" if db_ok else "err",
            _ui_text("✓ Gesichert") if db_ok else _ui_text("Fehler"),
            ctx.esc(_display(db.get("type"))),
            ctx.esc(Path(db.get("file", "")).name if db.get("file") else _display(db.get("target"))),
            ctx.esc(_display(db.get("size"))),
        )
    else:
        body += _ui_html("<p><b class='warn'>Nicht verwendet</b><br>{}</p>").format(
            ctx.esc(_ui_text(db.get("message", "Keine Datenbankdefinition")))
        )
    body += _ui_html("</div>")

    extra = steps.get("extra") or {}
    files = extra.get("files") or []
    body += _ui_html("<div class='card'><h3>Zusatzinformationen</h3>")
    body += _ui_html("<p><b class='{}'>{}</b><br>{} Datei(en)</p>").format(
        "ok" if extra.get("ok") else "warn",
        _ui_text("✓ Gesichert") if extra.get("ok") else _ui_text("Nicht vorhanden"),
        ctx.esc(str(len(files))),
    )
    if extra.get("message"):
        body += _ui_html("<p>{}</p>").format(ctx.esc(_ui_text(extra.get("message"))))
    body += _ui_html("</div>")

    body += _ui_html("</div>")
    return body


def _render_database_dashboard(ctx, data):
    configured = data.get("configured", True)
    supported = bool(data.get("supported", True))
    ok_value = data.get("ok", None)

    if configured is False:
        cls = "warn"
        status_text = "Nicht konfiguriert"
    elif ok_value is True:
        cls = "ok"
        status_text = "OK"
    elif ok_value is False:
        cls = "err"
        status_text = "Fehler"
    elif supported:
        cls = "warn"
        status_text = "Vorbereitet"
    else:
        cls = "err"
        status_text = "Nicht unterstützt"

    body = _ui_html("<div class='grid'>")

    body += _ui_html("<div class='card'><h3>Datenbankstatus</h3>")
    if configured is False:
        body += _ui_html("<p>Keine Datenbank konfiguriert.</p>")
    else:
        body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Typ: <code>{}</code><br>Container: <code>{}</code><br>Datenbank: <code>{}</code><br>Benutzer: <code>{}</code></p>").format(
            cls,
            ctx.esc(_ui_text(status_text)),
            ctx.esc(_display(data.get("type"))),
            ctx.esc(_display(data.get("container"))),
            ctx.esc(_display(data.get("database"))),
            ctx.esc(_display(data.get("user"))),
        )
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Dump / Backup</h3>")
    dump = data.get("dump") or data.get("dump_command") or ""
    if dump:
        body += _ui_html("<p>Dump-Befehl:</p><pre>{}</pre>").format(ctx.esc(dump))
    else:
        body += _ui_html("<p>Kein Dump-Befehl definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Container</h3>")
    container = data.get("container", "")
    if container:
        running = data.get("running")
        reachable = data.get("reachable")
        body += _ui_html("<p>Name: <code>{}</code>").format(ctx.esc(container))
        if running is not None:
            body += _ui_html("<br>Läuft: <b>{}</b>").format(_yes_no(running))
        if reachable is not None:
            body += _ui_html("<br>Erreichbar: <b>{}</b>").format(_yes_no(reachable))
        body += _ui_html("</p>")
    else:
        body += _ui_html("<p>Kein Datenbank-Container definiert.</p>")
    body += _ui_html("</div>")

    errors = data.get("errors") or []
    warnings = data.get("warnings") or []
    if errors or warnings:
        body += _ui_html("<div class='card'><h3>Hinweise</h3>")
        if errors:
            body += _ui_html("<h4>Fehler</h4><ul>")
            for e in errors:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul>")
        if warnings:
            body += _ui_html("<h4>Warnungen</h4><ul>")
            for w in warnings:
                body += _ui_html("<li class='warn'>{}</li>").format(ctx.esc(w))
            body += _ui_html("</ul>")
        body += _ui_html("</div>")

    body += _ui_html("</div>")
    return body


def _render_backup_dashboard(ctx, data):
    cls = "ok" if data.get("ok") else "err"
    body = _ui_html("<div class='grid'>")

    body += _ui_html("<div class='card'><h3>Backup-Status</h3>")
    body += _ui_html("<p><b class='{}'>{}</b></p>").format(
        cls,
        ctx.esc(_ui_text("OK") if data.get("ok") else _ui_text("Fehler")),
    )
    if data.get("message"):
        body += _ui_html("<p>{}</p>").format(ctx.esc(_ui_text(data.get("message"))))
    body += _ui_html("</div>")

    cfg = data.get("config_files") or data.get("configs") or {}
    body += _ui_html("<div class='card'><h3>Konfiguration</h3>")
    if isinstance(cfg, dict) and cfg:
        body += _ui_html("<table><tr><th>Name</th><th>Pfad</th><th>Vorhanden</th><th>Lesbar</th><th>Schreibbar</th><th>Größe</th></tr>")
        for k, v in cfg.items():
            if isinstance(v, dict):
                path = v.get("path", "")
                exists = _yes_no(v.get("exists"))
                readable = _yes_no(v.get("readable"))
                writable = _yes_no(v.get("writable"))
                size = v.get("size", "—")
            else:
                path = str(v)
                exists = "—"
                readable = "—"
                writable = "—"
                size = "—"

            body += _ui_html("<tr><td><code>{}</code></td><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(k),
                ctx.esc(path),
                ctx.esc(exists),
                ctx.esc(readable),
                ctx.esc(writable),
                ctx.esc(_display(size)),
            )
        body += _ui_html("</table>")
    else:
        body += _ui_html("<p>Keine Konfigurationsdateien definiert.</p>")
    body += _ui_html("</div>")

    paths = data.get("paths") or data.get("data_paths") or {}
    body += _ui_html("<div class='card'><h3>Datenpfade</h3>")
    if isinstance(paths, dict) and paths:
        body += _ui_html("<table><tr><th>Name</th><th>Pfad</th><th>Vorhanden</th><th>Lesbar</th><th>Schreibbar</th><th>Größe</th></tr>")
        for k, v in paths.items():
            if isinstance(v, dict):
                path = v.get("path", "")
                exists = _yes_no(v.get("exists"))
                readable = _yes_no(v.get("readable"))
                writable = _yes_no(v.get("writable"))
                size = v.get("size", "—")
            else:
                path = str(v)
                exists = "—"
                readable = "—"
                writable = "—"
                size = "—"

            body += _ui_html("<tr><td><code>{}</code></td><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(k),
                ctx.esc(path),
                ctx.esc(exists),
                ctx.esc(readable),
                ctx.esc(writable),
                ctx.esc(_display(size)),
            )
        body += _ui_html("</table>")
    else:
        body += _ui_html("<p>Keine Datenpfade definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Datenbank</h3>")
    db = data.get("database") or {}
    if isinstance(db, dict) and db:
        if db.get("configured") is False:
            body += _ui_html("<p>Keine Datenbank definiert.</p>")
        else:
            body += _ui_html("<p>Typ: <code>{}</code><br>Container: <code>{}</code><br>Datenbank: <code>{}</code><br>Benutzer: <code>{}</code></p>").format(
                ctx.esc(_display(db.get("type"))),
                ctx.esc(_display(db.get("container"))),
                ctx.esc(_display(db.get("database"))),
                ctx.esc(_display(db.get("user"))),
            )
    else:
        body += _ui_html("<p>Keine Datenbank definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("</div>")
    return body



def _render_status_dashboard(ctx, data):
    warnings = data.get("warnings") or []
    cls = _status_class(bool(data.get("ok")), warnings)
    status = "Läuft" if cls == "ok" else ("Warnung" if cls == "warn" else "Fehler")

    service = data.get("service") or {}
    web = data.get("web") or {}
    compose = data.get("compose") or {}
    version = data.get("version") or {}

    body = _ui_html("<div class='grid'>")

    body += _ui_html("<div class='card'><h3>Status</h3>")
    body += _ui_html("<p><b class='{}'>{}</b></p>").format(cls, ctx.esc(_ui_text(status)))
    if warnings:
        body += _ui_html("<p class='warn'>{}</p>").format(ctx.esc(", ".join(warnings)))
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>App</h3>")
    body += _ui_html("<p>ID: <code>{}</code><br>Name: <b>{}</b><br>Typ: <code>{}</code>").format(
        ctx.esc(data.get("id", "")),
        ctx.esc(_ui_text(data.get("label", ""))),
        ctx.esc(data.get("kind", "")),
    )

    if version.get("value"):
        body += _ui_html("<br>Version: <b>{}</b>").format(
            ctx.esc(version.get("value", ""))
        )

    body += _ui_html("</p></div>")

    body += _ui_html("<div class='card'><h3>Compose</h3>")
    if compose.get("configured"):
        body += _ui_html("<p>Pfad: <code>{}</code><br>Vorhanden: <b>{}</b></p>").format(
            ctx.esc(compose.get("path", "")),
            _yes_no(compose.get("exists")),
        )
    else:
        body += _ui_html("<p>Kein Compose-Projekt definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Web/API</h3>")
    if web.get("configured"):
        wcls = "ok" if web.get("ok") else "err"
        body += _ui_html("<p>Status: <b class='{}'>{}</b><br>HTTP: <code>{}</code><br>URL: <code>{}</code></p>").format(
            wcls,
            _ui_text("Erreichbar") if web.get("ok") else _ui_text("Nicht erreichbar"),
            ctx.esc(web.get("http_code", "")),
            ctx.esc(web.get("url", "")),
        )
    else:
        body += _ui_html("<p>Keine Web/API-Prüfung definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h3>Dienst</h3>")
    if service.get("service"):
        active = service.get("active", "")
        enabled = service.get("enabled", "")
        scls = "ok" if active == "active" else "warn"
        body += _ui_html("<p>Name: <code>{}</code><br>Status: <b class='{}'>{}</b><br>Autostart: <code>{}</code></p>").format(
            ctx.esc(service.get("service", "")),
            scls,
            ctx.esc(active),
            ctx.esc(enabled),
        )
    else:
        body += _ui_html("<p>Kein systemd-Dienst definiert.</p>")
    body += _ui_html("</div>")

    body += _ui_html("</div>")
    return body


def _session_progress_values(session, kind):
    stats=session.get('statistics') or {}
    def number(value):
        try:return max(0,int(value or 0))
        except (TypeError,ValueError):return 0
    steps=session.get('steps') or []
    done=sum(number(stats.get(key)) for key in ('ok','failed','blocked','skipped','simulated'))
    total=max(6 if kind=='backup' else 1,number(stats.get('total')),len(steps))
    state=session.get('state','unknown')
    terminal=state in ('completed','failed','blocked','simulated','prepared','finished','interrupted')
    percent=min(99,int(done*100/total))
    if state in ('completed','finished') and not number(stats.get('failed')):percent=100
    return done,total,percent,terminal


def _session_api_response(run_dir,kind):
    import re
    run_dir=Path(run_dir)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}',run_dir.name) or run_dir.resolve().parent!=run_dir.parent.resolve():
        return jsonify(ok=False,error='Ungültiger Run.'),400
    path=run_dir/'session.json'
    if not path.is_file():return jsonify(ok=False,error='Session nicht gefunden.'),404
    try:
        session=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(session,dict):raise ValueError('Ungültige Session')
    except (OSError,ValueError):
        return jsonify(ok=False,error='Session wird aktualisiert. Erneut versuchen.'),503
    try:result=json.loads((run_dir/'result.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):result={}
    if not isinstance(result,dict):result={}
    done,total,percent,terminal=_session_progress_values(session,kind)
    effective_state='failed' if session.get('state')=='completed' and (session.get('statistics') or {}).get('failed') else session.get('state','unknown')
    response=jsonify(ok=True,state=effective_state,progress_percent=percent,total_steps=total,completed_steps=done,terminal=terminal,
        current_step=session.get('current_step'),current_action=session.get('current_action'),current_detail=session.get('current_detail'),current_path_key=session.get('current_path_key'),
        updated_at=session.get('updated_at'),statistics=session.get('statistics') or {},steps=session.get('steps') or [],
        archive=session.get('archive') or result.get('archive'),archive_size=result.get('archive_size'),run_dir=str(run_dir))
    response.headers['Cache-Control']='no-store'
    return response


def _live_session_widget(ctx, kind, app_id, run_id):
    api = "/api/apps/{}/{}/runs/{}/session".format(
        ctx.esc(app_id),
        ctx.esc(kind),
        ctx.esc(run_id),
    )

    return _ui_html("""
<div class='card' id='live-session-card' data-api='__API__'>
  <h3>Live-Status</h3>
  <p>Status: <b id='live-state'>lade...</b><br>
     Fortschritt: <b id='live-progress-text'>0%</b><br>
     Schritt: <code id='live-current-step'>—</code><br>
     Aktion: <code id='live-current-action'>—</code><br>
     Letztes Update: <code id='live-updated-at'>—</code></p>
  <progress id='live-progress' value='0' max='100' style='width:100%'></progress>
  <div id='live-stats'></div>
  <div id='live-steps'></div>
</div>

<script>
(function(){
  const card = document.getElementById("live-session-card");
  if (!card) return;

  const api = card.dataset.api;

  function esc(v) {
    if (v === null || v === undefined || v === "") return "—";
    return String(v).replace(/[&<>"']/g, function(c) {
      if (c === "&") return "&amp;";
      if (c === "<") return "&lt;";
      if (c === ">") return "&gt;";
      if (c === '"') return "&quot;";
      if (c === "'") return "&#39;";
      return c;
    });
  }

  function clsFor(v) {
    if (["executed","completed","simulated","prepared"].includes(v)) return "ok";
    if (["failed","blocked"].includes(v)) return "err";
    return "warn";
  }

  function textFor(v) {
    const m = {
      executed:"Erfolgreich", blocked:"Blockiert", failed:"Fehler",
      simulated:"Simulation", skipped:"Übersprungen",
      completed:"Abgeschlossen", prepared:"Vorbereitet",
      created:"Erstellt", collecting:"Metadaten",
      config:"Konfiguration", data:"Daten", database:"Datenbank",
      extra:"Zusatzinfos", archive:"Archiv"
    };
    return m[v] || esc(v);
  }

  function setText(id, value) {
    const e = document.getElementById(id);
    if (e) e.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  }

  function setClass(id, cls) {
    const e = document.getElementById(id);
    if (e) e.className = cls;
  }

  function filename(path) {
    if (!path) return "—";
    return String(path).split("/").pop() || String(path);
  }

  function renderSteps(steps) {
    if (!steps || !steps.length) {
      document.getElementById("live-steps").innerHTML = "";
      return;
    }

    let html = "<h4>Live-Schritte</h4>";
    html += "<table><tr><th>#</th><th>Schritt</th><th>Aktion</th><th>Status</th><th>Meldung</th></tr>";
    for (const st of steps) {
      const status = st.status || "";
      html += "<tr>";
      html += "<td>" + esc(st.order) + "</td>";
      html += "<td>" + esc(st.title) + "</td>";
      html += "<td><code>" + esc(st.action) + "</code></td>";
      html += "<td class='" + clsFor(status) + "'>" + textFor(status) + "</td>";
      html += "<td>" + esc(st.message) + "</td>";
      html += "</tr>";
    }
    html += "</table>";
    document.getElementById("live-steps").innerHTML = html;
  }

  async function poll() {
    try {
      const r = await fetch(api, {cache: "no-store"});
      if (r.redirected && new URL(r.url).pathname === "/login") {
        setText("live-state", "Sitzung abgelaufen – bitte erneut anmelden");
        return;
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();

      if (!d.ok) {
        setText("live-state", "Status derzeit nicht verfügbar; erneuter Versuch folgt");
        setTimeout(poll, 5000);
        setClass("live-state", "err");
        return;
      }

      const state = d.state || "unknown";
      const percent = d.progress_percent || 0;
      const cls = clsFor(state);

      setText("live-state", textFor(state));
      setClass("live-state", cls);
      setText("live-progress-text", percent + "%");
      document.getElementById("live-progress").value = percent;
      setText("live-current-step", d.current_step);
      setText("live-current-action", [d.current_action, d.current_detail, d.current_path_key].filter(Boolean).join(" · "));
      setText("live-updated-at", d.updated_at);

      setText("run-summary-state", textFor(state));
      setClass("run-summary-state", cls);
      setText("run-summary-archive", filename(d.archive));
      setText("run-summary-size", d.archive_size);
      setText("run-summary-workdir", d.run_dir);

      const s = d.statistics || {};
      document.getElementById("live-stats").innerHTML =
        "<table><tr><th>Gesamt</th><th>OK</th><th>Fehler</th><th>Blockiert</th><th>Übersprungen</th><th>Simuliert</th></tr>" +
        "<tr><td>" + esc(s.total || d.total_steps || 0) + "</td>" +
        "<td>" + esc(s.ok || 0) + "</td>" +
        "<td>" + esc(s.failed || 0) + "</td>" +
        "<td>" + esc(s.blocked || 0) + "</td>" +
        "<td>" + esc(s.skipped || 0) + "</td>" +
        "<td>" + esc(s.simulated || 0) + "</td></tr></table>";

      renderSteps(d.steps || []);

      if (!d.terminal) {
        setTimeout(poll, 2000);
      }
    } catch(e) {
      setText("live-state", "Statusabfrage fehlgeschlagen; erneuter Versuch folgt");
      setTimeout(poll, 5000);
      setClass("live-state", "err");
      console.error(e);
    }
  }

  poll();
})();
</script>
""").replace("__API__", api)



def _safe_call(fn, fallback_title="Fehler"):
    try:
        return fn()
    except Exception as e:
        return {"ok": False, "error": str(e), "title": fallback_title}


def _section_data(m, section):
    if section == "info":
        return m.info()
    if section == "health":
        return m.health()
    if section == "backup":
        return backup_check(m)
    if section == "database":
        return database_check(m)
    if section == "restore":
        return restore_info(m)
    if section == "repair":
        return repair_check(m)
    if section == "update":
        return m.update_check()
    if section == "logs":
        return m.logs(120)
    return m.status()


def _full_app_data(m):
    return {
        "status": _safe_call(lambda: m.status(), "status"),
        "info": _safe_call(lambda: m.info(), "info"),
        "health": _safe_call(lambda: m.health(), "health"),
        "backup_check": _safe_call(lambda: backup_check(m), "backup_check"),
        "database_check": _safe_call(lambda: database_check(m), "database_check"),
        "restore_info": _safe_call(lambda: restore_info(m), "restore_info"),
        "repair_check": _safe_call(lambda: repair_check(m), "repair_check"),
        "update_check": _safe_call(lambda: m.update_check(), "update_check"),
    }



UPDATE_CACHE_FILE = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app_update_status.json'))
UPDATE_JOB_FILE = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app_update_job.json'))
_UPDATE_JOB_LOCK = threading.Lock()


def _read_update_job():
    try:
        if UPDATE_JOB_FILE.exists():
            return json.loads(UPDATE_JOB_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "running": False,
        "state": "idle",
    }


def _write_update_job(data):
    UPDATE_JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_JOB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_update_job(**kwargs):
    with _UPDATE_JOB_LOCK:
        data = _read_update_job()
        data.update(kwargs)
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_update_job(data)
        return data




def _read_update_cache():
    try:
        if UPDATE_CACHE_FILE.exists():
            return json.loads(UPDATE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_update_cache(data):
    UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cached_update_check(app_id):
    data = _read_update_cache()
    return data.get(app_id) or {
        "state": "not_checked",
        "label": "Nicht geprüft",
        "update_available": None,
        "message": "Update-Prüfung noch nicht gestartet",
        "method": "cache",
    }


def _store_update_check(app_id, result):
    data = _read_update_cache()
    result["checked_at"] = datetime.now().isoformat(timespec="seconds")
    data[app_id] = result
    _write_update_cache(data)
    return result


def register(app, ctx):
    from .apt_ui import register as register_apt, card as apt_card
    register_apt(app, ctx)
    from .dddvb_ui import register as register_dddvb, card as dddvb_card
    register_dddvb(app, ctx)
    from .nvidia_ui import register as register_nvidia, card as nvidia_card
    register_nvidia(app, ctx)
    from .install_ui import register as register_installers, buttons as installer_buttons
    register_installers(app, ctx)
    from .manage_ui import register as register_manage
    register_manage(app, ctx)
    from .power_api_ui import register as register_power_api
    register_power_api(app,ctx)
    from .qwen_ui import register as register_qwen
    register_qwen(app, ctx)
    @app.route("/api/apps/jobs/active")
    def api_apps_active_job():
        payload = {
            "ok": True,
            "active_job": get_active_job(),
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            mimetype="application/json",
        )

    @app.route("/apps/discovery", methods=["GET", "POST"])
    def apps_discovery():
        body = _ui_html("<div class='card'><h2>App Discovery</h2>")
        body += _ui_html("<p><a class='btn' href='/apps'>Zurück zu Apps</a> ")
        body += _ui_html("<a class='btn' href='/apps/manage'>Apps verwalten</a></p>")
        body += _ui_html("<p>Erkennt Docker-Compose-Projekte und relevante systemd-Dienste. Der Scan wird nur manuell gestartet.</p>")
        body += _ui_html("<form method='post'><button class='btn active' type='submit'>Discovery starten</button></form>")
        body += _ui_html("</div>")

        if request.method != "POST":
            body += _ui_html("<div class='card'><p class='warn'>Noch kein Scan gestartet.</p></div>")
            return ctx.page(_ui_text("App Discovery"), body, "Apps")

        from .discovery import discover_apps

        data = discover_apps()

        body += _ui_html("<div class='card'><h3>Docker Compose</h3>")
        body += _ui_html("<table><tr><th>Name</th><th>Pfad</th><th>Status</th></tr>")
        for item in data.get("compose") or []:
            status = _ui_html("<span class='ok'>verwaltet</span>") if item.get("managed") else _ui_html("<span class='warn'>nicht verwaltet</span>")
            body += _ui_html("<tr><td>{}</td><td><code>{}</code></td><td>{}</td></tr>").format(
                ctx.esc(item.get("name")),
                ctx.esc(item.get("path")),
                _ui_text(status),
            )
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>systemd-Dienste</h3>")
        body += _ui_html("<table><tr><th>Dienst</th><th>Aktiv</th><th>Status</th></tr>")
        for item in data.get("services") or []:
            status = _ui_html("<span class='ok'>verwaltet</span>") if item.get("managed") else _ui_html("<span class='warn'>nicht verwaltet</span>")
            body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(item.get("service")),
                ctx.esc(item.get("active")),
                _ui_text(status),
            )
        body += _ui_html("</table></div>")

        return ctx.page(_ui_text("App Discovery"), body, "Apps")


    @app.route("/apps/update-check/settings", methods=["GET", "POST"])
    def apps_update_check_settings():
        import subprocess
        import re

        timer_file = Path("/etc/systemd/system/server-manager-app-update-check.timer")

        def current_time():
            try:
                txt = timer_file.read_text(encoding="utf-8")
                m = re.search(r"OnCalendar=\*-\*-\*\s+(\d{2}:\d{2}):\d{2}", txt)
                if m:
                    return m.group(1)
            except Exception:
                pass
            return "03:30"

        def timer_enabled():
            r = subprocess.run(
                ["systemctl", "is-enabled", "server-manager-app-update-check.timer"],
                text=True,
                capture_output=True,
            )
            return r.stdout.strip() == "enabled"

        msg = ""
        if request.method == "POST":
            time_value = request.form.get("time", "03:30").strip()
            enabled = "1" if request.form.get("enabled") == "1" else "0"

            r = subprocess.run(
                ["sudo", "/usr/local/sbin/server-manager-set-app-update-timer", time_value, enabled],
                text=True,
                capture_output=True,
            )
            if r.returncode == 0:
                msg = _ui_html("<p class='ok'>Timer gespeichert.</p>")
            else:
                msg = _ui_html("<p class='err'>Fehler: <code>{}</code></p>").format(ctx.esc(r.stderr or r.stdout))

        t = current_time()
        checked = "checked" if timer_enabled() else ""

        body = _ui_html("<div class='card'><h2>") + tr(_ui_text("Automatische Updateprüfung")) + _ui_html("</h2>")
        body += _ui_html("<p>") + tr(_ui_text("Vor der App-Updateprüfung werden die APT-Paketlisten einmal aktualisiert. Das gilt auch für „Alle Updates prüfen“. Es werden keine Pakete installiert. Bei einem APT-Fehler wird die App-Prüfung abgebrochen und das Protokoll verlinkt.")) + _ui_html("</p>")
        body += _ui_html("<p><a class='btn' href='/apps'>Zurück zu Apps</a></p>")
        body += msg
        body += _ui_html("<form method='post'>")
        body += _ui_html("<p><label><input type='checkbox' name='enabled' value='1' {}> automatische Updateprüfung aktiv</label></p>").format(checked)
        body += _ui_html("<p>Zeit täglich: <input name='time' type='time' value='{}'></p>").format(ctx.esc(t))
        body += _ui_html("<p><button class='btn active' type='submit'>Speichern</button></p>")
        body += _ui_html("</form></div>")

        return ctx.page(tr("Automatische Updateprüfung"), body, "Apps")


    @app.route("/apps/update-check/run-all", methods=["POST"])
    def apps_update_check_run_all():
        managers = list(all_managers())
        with _UPDATE_JOB_LOCK:
            if _read_update_job().get("running"):
                return redirect("/apps")
            _write_update_job(dict(running=True,state="queued",current_label="APT-Paketlisten aktualisieren",done=0,total=len(managers),apt_job_id=None,error=None))

        def _worker():
            total = len(managers)
            _set_update_job(
                running=True,
                state="running",
                current_app=None,
                current_label="APT-Paketlisten aktualisieren",
                done=0,
                total=total,
                started_at=datetime.now().isoformat(timespec="seconds"),
                finished_at=None,
                error=None,
            )

            done = 0
            try:
                from .apt_jobs import refresh_for_update_checks
                refresh_for_update_checks(lambda key: _set_update_job(apt_job_id=key))
                for m in managers:
                    done += 1
                    _set_update_job(
                        current_app=m.app_id,
                        current_label=m.label,
                        done=done - 1,
                        total=total,
                    )

                    st = _safe_call(lambda m=m: m.status(), "status")
                    inst = st.get("installation") or {}
                    if inst.get("state") == "missing":
                        continue

                    result = _safe_call(lambda m=m: m.update_check(), "update_check")
                    _store_update_check(m.app_id, result)

                    _set_update_job(
                        current_app=m.app_id,
                        current_label=m.label,
                        done=done,
                        total=total,
                    )

                _set_update_job(
                    running=False,
                    state="completed",
                    current_app=None,
                    current_label=None,
                    done=total,
                    total=total,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                )
            except Exception as e:
                _set_update_job(
                    running=False,
                    state="failed",
                    error=str(e),
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                )

        threading.Thread(target=_worker, daemon=True).start()
        return redirect("/apps")


    @app.route("/api/apps/update-check/job")
    def api_apps_update_check_job():
        return Response(
            json.dumps(_read_update_job(), ensure_ascii=False, indent=2) + "\n",
            mimetype="application/json",
        )


    @app.route("/apps/<app_id>/update-check/run", methods=["POST"])
    def apps_update_check_run(app_id):
        m = get_manager(app_id)
        if not m:
            return redirect("/apps")

        result = _safe_call(lambda: m.update_check(), "update_check")
        _store_update_check(app_id, result)

        return redirect("/apps")

    @app.route("/apps")
    def apps_index():
        rows = []
        for m in all_managers():
            st = _safe_call(lambda m=m: m.status(), "status")
            from .lifecycle import installation
            st['installation'] = installation(m)
            up = _cached_update_check(m.app_id)
            rows.append((m, st, up))

        body = (
            _ui_html("<div class='card'><h2>Application Manager</h2>"
            "<p>Einheitliche Verwaltung für Anwendungen, Health Checks, Backup, Restore, Repair, Logs und Updates. "
            "Verfügbare Aktionen hängen von der jeweiligen App und den Ausführungsfreigaben ab.</p>"
            "<p><a class='btn' href='/apps/manage'>Apps verwalten</a> <a class='btn' href='/apps/discovery'>Discovery</a> <a class='btn' href='/apps/update-check/settings'>") + tr(_ui_text("Automatische Updateprüfung")) + _ui_html("</a> <form method='post' action='/apps/update-check/run-all' style='display:inline'><button class='btn active' type='submit'>Alle Updates prüfen</button></form></p></div>")
        )

        from .settings import load_settings
        execution_settings = load_settings()
        body += _ui_html("<div class='card'><h3>App-Manager · Ausführungsfreigaben</h3><p>Diese Anzeigen beschreiben, welche Änderungen erlaubt sind. <b>Freigegeben bedeutet nicht, dass gerade ein Auftrag läuft.</b></p>")
        for label, enabled, explanation in [
            ("Wiederherstellung (Restore)", bool(execution_settings.get("restore_execution_enabled")), "Erlaubt die Wiederherstellung unterstützter Apps aus einer Sicherung. Dabei können vorhandene Daten und Konfigurationen ersetzt werden. Prüfungen, erforderliche Rücksicherungen und Bestätigungen der jeweiligen App gelten weiterhin."),
            ("App-Updates", bool(execution_settings.get("update_execution_enabled")), "Erlaubt echte Updates unterstützter Apps nach den jeweiligen Prüfungen und Bestätigungen. Erforderliche Pre-Update-Backups bleiben Voraussetzung. Diese Freigabe startet keine Updates automatisch."),
        ]:
            body += _ui_html("<p><b>") + _ui_text(label) + _ui_html(": <span class='") + ("ok" if enabled else "warn") + "'>" + (_ui_text("Freigegeben") if enabled else _ui_text("Gesperrt")) + _ui_html("</span></b><br>") + ctx.esc(_ui_text(explanation)) + _ui_html("</p>")
        body += _ui_html("<p>Live-Refresh: <b>") + ctx.esc(str(execution_settings.get("live_refresh_seconds", 2))) + _ui_html(" Sekunden</b> · Aktualisierungsintervall der Auftragsanzeige.</p><p><a class='btn' href='/settings'>Ausführungsfreigaben und Live-Refresh einstellen</a></p>")
        body += _ui_html("<p>Bei gesperrter Ausführung bleiben Statusabfragen und unterstützte Prüfungen bzw. Simulationen verfügbar. Die Schalter beziehen sich auf App-Restore und App-Updates; APT-Systempakete und das Manager-DEB-Update haben eigene Abläufe. Laufende Aufträge und deren Fortschritt werden separat in den jeweiligen Auftragsansichten angezeigt.</p></div>")

        update_job = _read_update_job()
        if update_job.get("running"):
            done = int(update_job.get("done") or 0)
            total = int(update_job.get("total") or 1)
            percent = int(done * 100 / max(total, 1))
            body += _ui_html("<div class='card' style='border-left:5px solid orange'>")
            body += _ui_html("<h3>🔄 Updateprüfung läuft</h3>")
            body += _ui_html("<p>Aktuell: <code>{}</code><br>Fortschritt: <b>{}%</b> ({}/{})</p>").format(
                ctx.esc(update_job.get("current_label") or "—"),
                ctx.esc(str(percent)),
                ctx.esc(str(done)),
                ctx.esc(str(total)),
            )
            body += "<progress value='{}' max='100' style='width:100%'></progress>".format(ctx.esc(str(percent)))
            body += _ui_html("<p><a class='pill' href='/api/apps/update-check/job'>Job JSON</a></p>")
            body += _ui_html("</div>")

        if update_job.get("state") == "failed":
            body += _ui_html("<div class='card'><h3>Updateprüfung fehlgeschlagen</h3><p class='err'>") + ctx.esc(_ui_text(update_job.get("error")) or _ui_text("Prüfung nicht abgeschlossen.")) + _ui_html("</p></div>")
        apt_job_id=str(update_job.get("apt_job_id") or "")
        if len(apt_job_id)==32 and all(c in "0123456789abcdef" for c in apt_job_id):
            body += _ui_html("<div class='card'><a class='btn' href='/apps/apt/jobs/") + apt_job_id + _ui_html("'>APT-Protokoll der Updateprüfung</a></div>")
        body += _ui_html("<div class='grid'>")
        body += apt_card()
        for m, st, up in rows:
            cls = _status_class(bool(st.get("ok")), st.get("warnings"))
            status = "OK" if cls == "ok" else ("Warnung" if cls == "warn" else "Fehler")
            warn = ", ".join(st.get("warnings") or [])

            inst = st.get("installation") or {}
            inst_state = inst.get("state") or "unknown"
            inst_reason = inst.get("reason") or "Unbekannt"

            if inst_state == "installed":
                inst_badge = _ui_html("<span class='ok'>installiert</span>")
            elif inst_state == "missing":
                inst_badge = _ui_html("<span class='err'>nicht installiert</span>")
            elif inst_state == "partial":
                inst_badge = _ui_html("<span class='warn'>teilweise installiert</span>")
            else:
                inst_badge = _ui_html("<span class='warn'>unbekannt</span>")

            body += _ui_html("<div class='card'>")
            body += _ui_html("<h3>{}</h3>").format(ctx.esc(_ui_text(m.label)))
            install_extra = ""
            if inst_state in ("missing", "partial"):
                install_extra = _ui_html("<br><small>{}</small>").format(ctx.esc(inst_reason))

            up_state = up.get("state") or "unknown"
            up_label = up.get("label") or "Unbekannt"
            checked_at = up.get("checked_at") or ""

            up_message = up.get("message") or ""
            up_detail_html = ""

            up_details = up.get("details") or {}
            app_updates = up_details.get("app_updates") or []
            valid_app_updates = []

            if isinstance(app_updates, list):
                for item in app_updates:
                    if not isinstance(item, dict):
                        continue

                    app_name = str(item.get("app") or "").strip()
                    app_version = str(item.get("version") or "").strip()

                    if not app_name:
                        continue

                    valid_app_updates.append({
                        "app": app_name,
                        "version": app_version,
                    })

            if up_state == "current":
                up_badge = "🟢 aktuell"

            elif up_state == "available":
                up_badge = "🔴 Update verfügbar"

            elif up_state == "missing":
                up_badge = "⚪ Nicht prüfbar"

                if up_message:
                    up_detail_html = (
                        _ui_html("<br><small>{}</small>").format(
                            ctx.esc(_ui_text(up_message))
                        )
                    )

            elif up_state == "not_checked":
                up_badge = "⚪ nicht geprüft"

            else:
                up_badge = "🟡 unbekannt"

            if m.app_id == "comfyui":
                stable_update = bool(
                    up.get("stable_update_available")
                )
                development_available = bool(
                    up.get("development_available")
                )

                development_commits = int(
                    up.get("development_commits") or 0
                )

                stable_version = str(
                    up.get("stable_version") or ""
                ).strip()

                stable_revision = str(
                    up.get("stable_revision_short") or ""
                ).strip()

                development_version = str(
                    up.get("development_version") or ""
                ).strip()

                development_installed = bool(
                    up.get("development_installed")
                )

                if development_installed:
                    up_badge = (
                        "🔵 Entwicklungsversion installiert"
                    )

                    if stable_update and stable_version:
                        up_detail_html += (
                            _ui_html("<br><small>"
                            "🟠 Stable <code>{}</code> verfügbar"
                            "</small>")
                        ).format(
                            ctx.esc(stable_version)
                        )

                elif stable_update:
                    up_badge = "🟠 Stable-Update verfügbar"

                else:
                    up_badge = "🟢 aktuell (Stable)"

                if (
                    development_available
                    and development_commits
                ):
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🔵 {} neuere Entwicklung-Commits verfügbar"
                        "</small>")
                    ).format(
                        ctx.esc(str(development_commits))
                    )

            if m.app_id == "nextcloud" and not getattr(m, "container", None):
                current_core = str(
                    up.get("current_version") or "unbekannt"
                )
                latest_core = str(
                    up.get("latest_version") or current_core
                )

                if up_state == "available":
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🔴 <b>Core:</b> "
                        "<code>{}</code> → <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(current_core),
                        ctx.esc(latest_core),
                    )

                elif up_state == "current":
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🟢 <b>Core:</b> aktuell "
                        "(<code>{}</code>)"
                        "</small>")
                    ).format(ctx.esc(current_core))

                elif up_state == "missing":
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "⚪ <b>Core:</b> nicht prüfbar"
                        "</small>")
                    )

                elif up_state == "not_checked":
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "⚪ <b>Core:</b> noch nicht geprüft"
                        "</small>")
                    )

                else:
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🟡 <b>Core:</b> Status unbekannt"
                        "</small>")
                    )

                if valid_app_updates:
                    app_count = len(valid_app_updates)
                    app_count_label = (
                        "1 Update"
                        if app_count == 1
                        else "{} Updates".format(app_count)
                    )

                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🟡 <b>Apps:</b> {} verfügbar"
                        "</small>")
                    ).format(ctx.esc(_ui_text(app_count_label)))

                    up_detail_html += (
                        _ui_html("<ul style='margin-top:4px;margin-bottom:0'>")
                    )

                    for item in valid_app_updates:
                        app_name = ctx.esc(item["app"])
                        app_version = ctx.esc(item["version"])

                        if app_version:
                            up_detail_html += (
                                _ui_html("<li><small><code>{}</code> → "
                                "<code>{}</code></small></li>")
                            ).format(app_name, app_version)
                        else:
                            up_detail_html += (
                                _ui_html("<li><small><code>{}</code></small></li>")
                            ).format(app_name)

                    up_detail_html += _ui_html("</ul>")

                else:
                    up_detail_html += (
                        _ui_html("<br><small>"
                        "🟢 <b>Apps:</b> keine Updates"
                        "</small>")
                    )

            checked_html = ""

            if checked_at:
                checked_html = _ui_html("<br><small>geprüft: {}</small>").format(
                    ctx.esc(checked_at)
                )

            elif up_state == "not_checked":
                checked_html = _ui_html("<br><small>noch nie geprüft</small>")

            version_html = ""

            # Bevorzugt die Version des tatsächlich laufenden
            # Containers aus manager.status().
            runtime_version = st.get("version") or {}

            if isinstance(runtime_version, dict):
                runtime_version_value = str(
                    runtime_version.get("value") or ""
                ).strip()
            else:
                runtime_version_value = str(
                    runtime_version or ""
                ).strip()

            current_version = (
                runtime_version_value
                or str(
                    up.get("current_version") or ""
                ).strip()
            )

            latest_version = str(
                up.get("latest_version") or ""
            ).strip()

            if m.app_id == "comfyui":
                stable_version = str(
                    up.get("stable_version") or ""
                ).strip()

                stable_revision = str(
                    up.get("stable_revision_short") or ""
                ).strip()

                development_version = str(
                    up.get("development_version") or ""
                ).strip()

                development_commits = int(
                    up.get("development_commits") or 0
                )

                if current_version:
                    version_html += (
                        _ui_html("<br><small>"
                        "Installiert: <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(current_version)
                    )

                if stable_version:
                    stable_display = stable_version

                    if stable_revision:
                        stable_display += " / " + stable_revision

                    version_html += (
                        _ui_html("<br><small>"
                        "Stable verfügbar: <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(stable_display)
                    )

                if development_version:
                    version_html += (
                        _ui_html("<br><small>"
                        "Entwicklung: <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(development_version)
                    )

                version_html += (
                    _ui_html("<br><small>"
                    "Commits voraus: <code>{}</code>"
                    "</small>")
                ).format(
                    ctx.esc(str(development_commits))
                )

            else:
                if current_version:
                    version_html += (
                        _ui_html("<br><small>"
                        "Installiert: <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(current_version)
                    )

                if latest_version:
                    version_html += (
                        _ui_html("<br><small>"
                        "Verfügbar: <code>{}</code>"
                        "</small>")
                    ).format(
                        ctx.esc(latest_version)
                    )

            body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Typ: <code>{}</code><br>Installation: {}{}<br>Update: {}{}{}{}{}</p>").format(
                cls,
                ctx.esc(_ui_text(status)),
                ctx.esc(getattr(m, "installation_mode", m.kind)),
                inst_badge,
                install_extra,
                ctx.esc(_ui_text(up_badge)),
                up_detail_html,
                version_html,
                checked_html,
                "",
            )

            if warn:
                body += _ui_html("<p class='warn'>{}</p>").format(ctx.esc(warn))

            active_job = get_active_job(m.app_id)
            if active_job:
                job_type = active_job.get("type") or active_job.get("action") or "job"
                detail = active_job.get("current_detail") or active_job.get("current_action") or "läuft"
                path_key = active_job.get("current_path_key") or ""
                progress = active_job.get("progress_percent")
                url = active_job.get("url") or "/apps/{}".format(m.app_id)

                body += _ui_html("<div class='card' style='border-left:5px solid orange;background:#2b2111'>")
                body += _ui_html("<h4 style='margin-top:0'>🟢 Backup läuft</h4>")
                body += _ui_html("<p>")
                body += _ui_html("Status: <code>{}</code><br>").format(ctx.esc(active_job.get("state") or "läuft"))
                body += _ui_html("Schritt: <code>{}/6</code><br>").format(ctx.esc(_display(active_job.get("current_step"))))
                body += _ui_html("Aktion: <b>{}</b><br>").format(ctx.esc(_ui_text(detail)))
                if path_key:
                    body += _ui_html("Pfad: <code>{}</code><br>").format(ctx.esc(path_key))
                if progress is not None:
                    body += _ui_html("Fortschritt: <b>{}%</b><br>").format(ctx.esc(str(progress)))
                    body += "<progress value='{}' max='100' style='width:100%'></progress>".format(ctx.esc(str(progress)))
                body += _ui_html("</p><p><a class='btn active' href='{}'>Zum laufenden Backup</a></p>").format(ctx.esc(url))
                body += _ui_html("</div>")

            body += _ui_html("<p>")
            body += installer_buttons(m, include_manage=True)
            body += _ui_html("<form method='post' action='/apps/{}/update-check/run' style='display:inline'>").format(ctx.esc(m.app_id))
            body += _ui_html("<button class='btn' type='submit'>Update prüfen</button></form> ")

            body += _ui_html("</p></div>")
        body += _ui_html("</div>")

        return ctx.page(_ui_text("Application Manager"), body, "Apps")

    @app.route("/apps/<app_id>")
    def apps_detail(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        section = request.args.get("section", "status")
        valid = {
            "status": "Status",
            "health": "Health",
            "backup": "Backup",
            "database": "Datenbank",
            "restore": "Restore",
            "repair": "Repair",
        }
        if section not in valid:
            section = "status"

        st_head = _safe_call(lambda: m.status(), "status")
        head_cls = _status_class(bool(st_head.get("ok")), st_head.get("warnings"))
        compose = st_head.get("compose") or {}
        service = st_head.get("service") or {}
        version = st_head.get("version") or {}

        if head_cls == "ok":
            if compose.get("configured"):
                head_status = "Läuft"
            elif service.get("active") == "active":
                head_status = "Läuft"
            else:
                head_status = "OK"
        elif head_cls == "warn":
            head_status = "Warnung"
        else:
            head_status = "Fehler"

        kind_label = {
            "docker-compose": "Docker Compose",
            "systemd": "Systemdienst",
            "generic": "Generisch",
        }.get(getattr(m, "kind", ""), getattr(m, "kind", ""))

        body = _ui_html("<div class='card'><h2>{}</h2>").format(ctx.esc(_ui_text(m.label)))

        body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Typ: <code>{}</code>").format(
            head_cls,
            ctx.esc(head_status),
            ctx.esc(_ui_text(kind_label)),
        )

        if version.get("value"):
            body += _ui_html("<br>Version: <b>{}</b>").format(
                ctx.esc(version.get("value", ""))
            )

        if compose.get("configured"):
            body += _ui_html("<br>Projekt: <code>{}</code>").format(ctx.esc(compose.get("path", "")))

        if service.get("service"):
            body += _ui_html("<br>Dienst: <code>{}</code> / <code>{}</code>").format(
                ctx.esc(service.get("service", "")),
                ctx.esc(service.get("active", "")),
            )

        warnings = st_head.get("warnings") or []
        if warnings:
            body += _ui_html("<br><span class='warn'>{}</span>").format(ctx.esc(", ".join(warnings)))

        body += _ui_html("</p>")

        body += _ui_html("<p>")
        body += _ui_html("<a class='btn' href='/apps'>← Zurück</a> ")

        body += _ui_html("</p>")

        body += _ui_html("<p><b>Aktionen:</b><br>")
        body += installer_buttons(m)
        if m.app_id in ("nextcloud", "nextcloud_docker"):
            body += _ui_html("<a class='btn' href='/apps/nextcloud/https'>Domain & HTTPS</a> ")
        body += _ui_html("<a class='btn' href='/apps/{}/backup/select'>Backup</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/schedule'>Backup-Zeitplan</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/restore'>Restore</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/update'>{}</a> ").format(ctx.esc(m.app_id), _ui_text("Update & Stable") if m.app_id == "comfyui" else _ui_text("Update"))

        body += _ui_html("<a class='btn' href='/apps/{}?section=logs'>Logs</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("</p>")

        body += _ui_html("<p><b>Ansicht:</b><br>")

        for s, label in valid.items():
            active = " active" if s == section else ""
            body += _ui_html("<a class='btn{}' href='/apps/{}?section={}'>{}</a> ").format(
                active, ctx.esc(m.app_id), ctx.esc(s), ctx.esc(_ui_text(label))
            )
        body += _ui_html("</div>")

        data = _safe_call(lambda: _section_data(m, section), section)

        if section == "status":
            body += _render_status_dashboard(ctx, data)
            body += _details_card(ctx, "Status JSON", data)
        elif section == "backup":
            body += _render_backup_dashboard(ctx, data)
            body += _details_card(ctx, "Backup JSON", data)
        elif section == "database":
            body += _render_database_dashboard(ctx, data)
            body += _details_card(ctx, "Datenbank JSON", data)
        else:
            body += _card(ctx, valid[section], _pre(ctx, data))

        return ctx.page(m.label, body, "Apps")

    @app.route("/apps/<app_id>/backup/select")
    def apps_backup_select(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        profiles = get_backup_profiles(m)

        body = _ui_html("<div class='card'><h2>Backup starten: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}'>Zurück</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/runs'>Backup-Runs</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots'>Daten-Snapshots</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/schedule'>Zeitplan</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Wähle, was gesichert werden soll.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")
        order = ["system", "data", "full"]
        icons = {"system": "🖥️", "data": "📂", "full": "💾"}

        for pid in order:
            prof = profiles.get(pid)
            if not prof:
                continue

            label = prof.get("label", pid)

            body += _ui_html("<div class='card'>")
            body += _ui_html("<h3>{} {}</h3>").format(ctx.esc(icons.get(pid, "")), ctx.esc(_ui_text(label)))
            body += _ui_html("<p>{}</p>").format(ctx.esc(_ui_text(prof.get("description", ""))))
            body += _ui_html("<ul>")
            body += _ui_html("<li>Konfiguration: <b>{}</b></li>").format(_ui_text("ja") if prof.get("config") else _ui_text("nein"))
            body += _ui_html("<li>Datenpfade: <b>{}</b></li>").format(_ui_text("ja") if prof.get("data") else _ui_text("nein"))
            body += _ui_html("<li>Datenbank: <b>{}</b></li>").format(_ui_text("ja") if prof.get("database") else _ui_text("nein"))
            body += _ui_html("<li>Zusatzinfos: <b>{}</b></li>").format(_ui_text("ja") if prof.get("extra") else _ui_text("nein"))
            body += _ui_html("<li>Inkrementell: <b>{}</b></li>").format(_ui_text("ja") if prof.get("incremental") else _ui_text("nein"))
            body += _ui_html("</ul>")
            body += _ui_html('<form method="post" action="/apps/{}/backup" onsubmit="return confirm(\'Backup starten: {}?\')">').format(
                ctx.esc(m.app_id),
                ctx.esc(_ui_text(label)),
            )
            body += _ui_html("<input type='hidden' name='profile' value='{}'>").format(ctx.esc(pid))
            body += _ui_html("<button class='btn' type='submit'>{} starten</button>").format(ctx.esc(_ui_text(label)))
            body += _ui_html("</form>")
            body += _ui_html("</div>")

        body += _ui_html("</div>")
        return ctx.page("Backup starten " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup", methods=["POST"])
    def apps_backup(app_id):
        from modules.backup.daily import RUNNING as daily_running
        if daily_running:return 'Tägliche Sicherungskette läuft. Bitte Abschluss abwarten.',409
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        profile = request.form.get("profile", "system").strip() or "system"
        profiles = get_backup_profiles(m)
        if profile not in profiles:
            profile = "system"

        started_at = time.time()

        def _run_backup_background():
            with app.app_context():
                set_active_job(m.app_id, "backup", None)
                try:
                    m.backup(profile=profile)
                except TypeError:
                    # Fallback für alte Manager-Signaturen
                    m.backup()
                except Exception:
                    pass
                finally:
                    set_active_job()

        t = threading.Thread(target=_run_backup_background, daemon=True)
        t.start()

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        run_id = ""

        for _ in range(40):
            if root.exists():
                runs = sorted(
                    [x for x in root.iterdir() if x.is_dir()],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                for r in runs:
                    try:
                        if r.stat().st_mtime >= started_at - 2:
                            run_id = r.name
                            break
                    except Exception:
                        pass
            if run_id:
                break
            time.sleep(0.1)

        if run_id:
            return redirect("/apps/{}/backup/runs/{}".format(m.app_id, run_id))

        body = _ui_html("<div class='card'><h2>Backup gestartet: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p>Backup läuft im Hintergrund.</p>")
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs'>Backup-Runs öffnen</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("</div>")
        return ctx.page("Backup gestartet " + m.label, body, "Apps")

    @app.route("/apps/<app_id>/backup/import", methods=["GET", "POST"])
    def apps_backup_import(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        body = _ui_html("<div class='card'><h2>Backup importieren: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs'>Zurück zu Backup-Runs</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}'>App</a></p>").format(ctx.esc(m.app_id))

        if request.method != "POST":
            body += _ui_html("<p>Extern gesichertes <code>.tar.gz</code>-Backup hochladen und als Backup-Run importieren.</p>")
            body += _ui_html("<form method='post' enctype='multipart/form-data'>")
            body += _ui_html("<p><input type='file' name='backup_file' accept='.tar.gz,.tgz' required></p>")
            body += _ui_html("<button class='btn' type='submit'>Backup importieren</button>")
            body += _ui_html("</form></div>")
            return ctx.page("Backup importieren " + m.label, body, "Apps")

        upload = request.files.get("backup_file")
        if not upload or not upload.filename:
            body += _ui_html("<p class='err'>Keine Datei hochgeladen.</p></div>")
            return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

        filename = Path(upload.filename).name
        if not (filename.endswith(".tar.gz") or filename.endswith(".tgz")):
            body += _ui_html("<p class='err'>Nur .tar.gz oder .tgz erlaubt.</p></div>")
            return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

        app_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        app_root.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(prefix="server-manager-backup-import-") as tmp:
                tmp_path = Path(tmp)
                uploaded_archive = tmp_path / filename
                upload.save(str(uploaded_archive))

                if not tarfile.is_tarfile(uploaded_archive):
                    body += _ui_html("<p class='err'>Archiv ist kein gültiges TAR/GZIP-Backup.</p></div>")
                    return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

                extract_dir = tmp_path / "extract"
                extract_dir.mkdir(parents=True, exist_ok=True)

                with tarfile.open(uploaded_archive, "r:gz") as tar:
                    members = tar.getmembers()

                    for member in members:
                        name = member.name or ""
                        parts = Path(name).parts

                        if name.startswith("/") or ".." in parts:
                            body += _ui_html("<p class='err'>Unsicherer Archivpfad erkannt: <code>{}</code></p></div>").format(ctx.esc(name))
                            return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

                    tar.extractall(extract_dir)

                candidates = []
                for d in extract_dir.rglob("*"):
                    if d.is_dir() and (d / "manifest.json").exists() and (d / "result.json").exists():
                        candidates.append(d)

                if not candidates:
                    body += _ui_html("<p class='err'>Kein gültiger Backup-Run gefunden: manifest.json/result.json fehlen.</p></div>")
                    return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

                src_run = sorted(candidates, key=lambda x: len(str(x)))[0]

                manifest = json.loads((src_run / "manifest.json").read_text(encoding="utf-8"))
                result = json.loads((src_run / "result.json").read_text(encoding="utf-8"))

                backup_app_id = manifest.get("app_id") or result.get("app_id")
                if backup_app_id != m.app_id:
                    body += _ui_html("<p class='err'>Backup gehört zu <code>{}</code>, nicht zu <code>{}</code>.</p></div>").format(
                        ctx.esc(backup_app_id),
                        ctx.esc(m.app_id),
                    )
                    return ctx.page("Backup importieren " + m.label, body, "Apps"), 400

                import_id = "imported_{}_{}".format(
                    datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                    src_run.name,
                )

                dest_run = app_root / import_id
                dest_archive = app_root / (import_id + ".tar.gz")

                if dest_run.exists() or dest_archive.exists():
                    body += _ui_html("<p class='err'>Import-Ziel existiert bereits.</p></div>")
                    return ctx.page("Backup importieren " + m.label, body, "Apps"), 409

                shutil.copytree(src_run, dest_run)
                shutil.copy2(uploaded_archive, dest_archive)

                result["archive"] = str(dest_archive)
                result["imported"] = True
                result["imported_at"] = datetime.now().isoformat(timespec="seconds")
                result["import_source_filename"] = filename
                result["archive_size"] = result.get("archive_size") or "{} Bytes".format(dest_archive.stat().st_size)
                (dest_run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

                session_file = dest_run / "session.json"
                if session_file.exists():
                    session = json.loads(session_file.read_text(encoding="utf-8"))
                else:
                    session = {
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

                session.update({
                    "id": import_id,
                    "app_id": m.app_id,
                    "label": getattr(m, "label", m.app_id),
                    "mode": "backup",
                    "state": "completed",
                    "origin": "external_import",
                    "imported": True,
                    "imported_at": datetime.now().isoformat(timespec="seconds"),
                    "archive": str(dest_archive),
                    "work_dir": str(dest_run),
                })
                session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

                body += _ui_html("<p class='ok'><b>Backup importiert.</b></p>")
                body += _ui_html("<p>Run: <code>{}</code><br>Archiv: <code>{}</code></p>").format(
                    ctx.esc(import_id),
                    ctx.esc(dest_archive.name),
                )
                body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs/{}'>Backup öffnen</a> ").format(
                    ctx.esc(m.app_id),
                    ctx.esc(import_id),
                )
                body += _ui_html("<a class='btn' href='/apps/{}/restore?backup={}'>Restore prüfen</a></p>").format(
                    ctx.esc(m.app_id),
                    ctx.esc(import_id),
                )
                body += _ui_html("</div>")
                return ctx.page("Backup importiert " + m.label, body, "Apps")

        except Exception as e:
            body += _ui_html("<p class='err'>Import fehlgeschlagen.</p><pre>{}</pre></div>").format(ctx.esc(str(e)))
            return ctx.page("Backup importieren " + m.label, body, "Apps"), 500


    @app.route("/apps/<app_id>/backup/snapshots")
    def apps_backup_snapshots(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        import os
        from datetime import datetime

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"

        body = _ui_html("<div class='card'><h2>Daten-Snapshots: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}'>App</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/select'>Backup starten</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/runs'>Backup-Runs</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Snapshots aus dem inkrementellen Datenbackup via rsync/Hardlinks.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Snapshots</h3>")

        if not snap_root.exists():
            body += _ui_html("<p class='warn'>Keine Daten-Snapshots vorhanden.</p></div>")
            return ctx.page("Daten-Snapshots " + m.label, body, "Apps")

        latest = None
        latest_link = snap_root / "latest"
        if latest_link.exists() or latest_link.is_symlink():
            try:
                latest = latest_link.resolve().name
            except Exception:
                latest = None

        entries = []
        for d in snap_root.iterdir():
            if not d.is_dir() or d.name == "latest":
                continue
            try:
                size = os.popen("du -sh '{}' 2>/dev/null | cut -f1".format(str(d).replace("'", "'\\''"))).read().strip()
                created = datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                entries.append((d.name, created, size or "—"))
            except Exception:
                continue

        if not entries:
            body += _ui_html("<p class='warn'>Keine Snapshot-Verzeichnisse gefunden.</p></div>")
            return ctx.page("Daten-Snapshots " + m.label, body, "Apps")

        entries.sort(reverse=True)

        body += _ui_html("<table><tr><th>Snapshot</th><th>Erstellt</th><th>Größe</th><th>Latest</th><th>Aktion</th></tr>")
        for name, created, size in entries:
            body += _ui_html("<tr>")
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(name))
            body += _ui_html("<td>{}</td>").format(ctx.esc(created))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(size))
            body += _ui_html("<td class='{}'>{}</td>").format("ok" if name == latest else "", "✔" if name == latest else "")
            body += _ui_html("<td><a class='btn' href='/apps/{}/backup/snapshots/{}'>Öffnen</a></td>").format(
                ctx.esc(m.app_id),
                ctx.esc(name),
            )
            body += _ui_html("</tr>")
        body += _ui_html("</table></div>")

        return ctx.page("Daten-Snapshots " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>")
    def apps_backup_snapshot_detail(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        import os
        from datetime import datetime

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        latest = None
        latest_link = snap_root / "latest"
        if latest_link.exists() or latest_link.is_symlink():
            try:
                latest = latest_link.resolve().name
            except Exception:
                latest = None

        # passenden Backup-Run suchen
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        result = {}
        session = {}
        manifest = {}
        data_manifest = {}
        data_snapshot = {}

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        result = read_json(run_dir / "result.json")
        session = read_json(run_dir / "session.json")
        manifest = read_json(run_dir / "manifest.json")
        data_manifest = read_json(run_dir / "data" / "manifest.json")
        data_snapshot = read_json(run_dir / "data" / ".snapshot.json")

        db = result.get("data_backup") or session.get("data_backup") or data_manifest or {}
        inc = db.get("incremental_snapshot") or {}

        size = os.popen("du -sh '{}' 2>/dev/null | cut -f1".format(str(snap_dir).replace("'", "'\\''"))).read().strip() or "—"
        created = datetime.fromtimestamp(snap_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        body = _ui_html("<div class='card'><h2>Snapshot: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots'>Zurück zu Snapshots</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/select'>Backup starten</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/runs/{}'>Backup-Run</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")

        body += _ui_html("<div class='card'><h3>Übersicht</h3>")
        body += _ui_html("<p>App: <b>{}</b><br>Snapshot: <code>{}</code><br>Erstellt: <code>{}</code><br>Größe: <code>{}</code><br>Latest: <b class='{}'>{}</b></p>").format(
            ctx.esc(_ui_text(m.label)),
            ctx.esc(snapshot_id),
            ctx.esc(created),
            ctx.esc(size),
            "ok" if snapshot_id == latest else "warn",
            ctx.esc(_ui_text("ja") if snapshot_id == latest else _ui_text("nein")),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Backup-Profil</h3>")
        body += _ui_html("<p>Profil: <code>{}</code><br>Modus: <code>{}</code><br>Inkrementell: <b>{}</b><br>Snapshot-Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(_profile_label(result or session or manifest)),
            ctx.esc(_display(db.get("mode"))),
            ctx.esc(_ui_text("ja") if db.get("incremental") else _ui_text("nein")),
            ctx.esc(str(snap_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Basis</h3>")
        body += _ui_html("<p>Vorheriger Snapshot:<br><code>{}</code><br>Snapshot-Root:<br><code>{}</code></p>").format(
            ctx.esc(_display(db.get("previous_snapshot") or inc.get("previous_snapshot"))),
            ctx.esc(_display(inc.get("snapshot_root") or str(snap_root))),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Statistik</h3>")
        body += _ui_html("<p>Dateien: <b>{}</b><br>Ordner: <b>{}</b><br>Bytes: <code>{}</code><br>Changed: <code>{}</code><br>Deleted: <code>{}</code></p>").format(
            ctx.esc(_display(db.get("total_files"))),
            ctx.esc(_display(db.get("total_dirs"))),
            ctx.esc(_display(db.get("total_bytes"))),
            ctx.esc(_display(db.get("changed_files"))),
            ctx.esc(_display(db.get("deleted_files"))),
        )
        body += _ui_html("</div>")

        body += _ui_html("</div>")

        paths = (inc.get("paths") or {})
        body += _ui_html("<div class='card'><h3>Datenpfade</h3>")
        if paths:
            body += _ui_html("<table><tr><th>Name</th><th>Status</th><th>Quelle</th><th>Snapshot-Ziel</th><th>Link-Dest</th></tr>")
            for name, info in paths.items():
                ok = bool(info.get("ok"))
                body += _ui_html("<tr>")
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(name))
                body += _ui_html("<td class='{}'>{}</td>").format("ok" if ok else "err", _ui_text("OK") if ok else _ui_text("Fehler"))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(info.get("source"))))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(info.get("target"))))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(info.get("link_dest"))))
                body += _ui_html("</tr>")
            body += _ui_html("</table>")
        else:
            body += _ui_html("<p class='warn'>Keine Pfad-Metadaten gefunden.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Snapshot-Dateien</h3>")
        body += _ui_html("<table><tr><th>Datei</th><th>Vorhanden</th><th>Größe</th></tr>")
        files = [
            ("Run result.json", run_dir / "result.json"),
            ("Run session.json", run_dir / "session.json"),
            ("Run manifest.json", run_dir / "manifest.json"),
            ("Daten manifest.json", run_dir / "data" / "manifest.json"),
            ("Daten .snapshot.json", run_dir / "data" / ".snapshot.json"),
        ]
        for label, fp in files:
            exists = fp.exists()
            fsize = "{} Bytes".format(fp.stat().st_size) if exists else "—"
            body += _ui_html("<tr><td>{}</td><td class='{}'>{}</td><td><code>{}</code></td></tr>").format(
                ctx.esc(_ui_text(label)),
                "ok" if exists else "warn",
                _ui_text("ja") if exists else _ui_text("nein"),
                ctx.esc(fsize),
            )
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Aktionen</h3>")
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots'>Zur Liste</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/files'>Dateien durchsuchen</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/compare'>Mit vorherigem vergleichen</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-plan'>Restore-Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Restore-Assistent</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<p class='warn'>Vergleich, Restore und Dateibrowser sind vorbereitet und werden in den nächsten Phasen umgesetzt.</p>")
        body += _ui_html("</div>")

        if data_manifest:
            body += _details_card(ctx, "Daten-Manifest JSON", data_manifest)
        if data_snapshot:
            body += _details_card(ctx, "Snapshot JSON", data_snapshot)

        return ctx.page("Snapshot " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/compare")
    def apps_backup_snapshot_compare(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        snap_file = run_dir / "data" / ".snapshot.json"
        data_manifest_file = run_dir / "data" / "manifest.json"

        if not snap_file.exists():
            return ctx.page(
                _ui_text("Snapshot-Metadaten fehlen"),
                _ui_html("<div class='card'><h2>Snapshot-Metadaten fehlen</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_file))),
                "Apps",
            ), 404

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        current = read_json(snap_file)
        data_manifest = read_json(data_manifest_file)

        previous_path = data_manifest.get("previous_snapshot")
        if not previous_path:
            db = data_manifest.get("incremental_snapshot") or {}
            previous_path = db.get("previous_snapshot")

        if not previous_path:
            previous_path = request.args.get("base", "")

        previous_id = Path(previous_path).name if previous_path else ""
        previous_run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / previous_id if previous_id else None
        previous_file = previous_run_dir / "data" / ".snapshot.json" if previous_run_dir else None

        if not previous_file or not previous_file.exists():
            body = _ui_html("<div class='card'><h2>Snapshot-Vergleich: {}</h2>").format(ctx.esc(snapshot_id))
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück zum Snapshot</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots'>Zur Liste</a></p>").format(ctx.esc(m.app_id))
            body += _ui_html("<p class='warn'>Kein vorheriger Snapshot mit Metadaten gefunden.</p>")
            body += _ui_html("<p>Gesuchter Basis-Snapshot: <code>{}</code></p>").format(ctx.esc(_display(previous_path)))
            body += _ui_html("</div>")
            return ctx.page("Snapshot-Vergleich " + m.label, body, "Apps")

        previous = read_json(previous_file)

        def flatten(snapshot):
            out = {}
            paths = snapshot.get("paths") or {}
            for group, pdata in paths.items():
                items = pdata.get("items") or {}
                for rel, meta in items.items():
                    key = "{}/{}".format(group, rel)
                    out[key] = {
                        "group": group,
                        "rel": rel,
                        "size": int(meta.get("size", 0) or 0),
                        "mtime": int(meta.get("mtime", 0) or 0),
                        "type": meta.get("type", ""),
                    }
            return out

        cur = flatten(current)
        old = flatten(previous)

        cur_keys = set(cur.keys())
        old_keys = set(old.keys())

        added_keys = sorted(cur_keys - old_keys)
        deleted_keys = sorted(old_keys - cur_keys)

        changed_keys = []
        unchanged = 0

        for k in sorted(cur_keys & old_keys):
            c = cur[k]
            o = old[k]
            if c.get("type") != o.get("type") or c.get("size") != o.get("size") or c.get("mtime") != o.get("mtime"):
                changed_keys.append(k)
            else:
                unchanged += 1

        added_bytes = sum(cur[k].get("size", 0) for k in added_keys if cur[k].get("type") == "file")
        changed_bytes = sum(cur[k].get("size", 0) for k in changed_keys if cur[k].get("type") == "file")
        deleted_bytes = sum(old[k].get("size", 0) for k in deleted_keys if old[k].get("type") == "file")

        body = _ui_html("<div class='card'><h2>Snapshot-Vergleich: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück zum Snapshot</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots'>Zur Liste</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Basis: <code>{}</code><br>Aktuell: <code>{}</code></p>").format(
            ctx.esc(previous_id),
            ctx.esc(snapshot_id),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")

        body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
        body += _ui_html("<p>Neu: <b class='ok'>{}</b><br>Geändert: <b class='warn'>{}</b><br>Gelöscht: <b class='err'>{}</b><br>Unverändert: <b>{}</b></p>").format(
            ctx.esc(str(len(added_keys))),
            ctx.esc(str(len(changed_keys))),
            ctx.esc(str(len(deleted_keys))),
            ctx.esc(str(unchanged)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Datenmenge</h3>")
        body += _ui_html("<p>Neue Daten: <code>{}</code> Bytes<br>Geänderte Daten: <code>{}</code> Bytes<br>Gelöschte Daten: <code>{}</code> Bytes</p>").format(
            ctx.esc(str(added_bytes)),
            ctx.esc(str(changed_bytes)),
            ctx.esc(str(deleted_bytes)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Snapshots</h3>")
        body += _ui_html("<p>Basis-Datei:<br><code>{}</code><br>Aktuelle Datei:<br><code>{}</code></p>").format(
            ctx.esc(str(previous_file)),
            ctx.esc(str(snap_file)),
        )
        body += _ui_html("</div>")

        body += _ui_html("</div>")

        def render_list(title, keys, source, cls):
            html = _ui_html("<div class='card'><h3>{}</h3>").format(ctx.esc(title))
            if not keys:
                html += _ui_html("<p class='ok'>Keine Einträge.</p></div>")
                return html

            html += _ui_html("<table><tr><th>Pfad</th><th>Typ</th><th>Größe</th><th>mtime</th></tr>")
            for k in keys[:300]:
                meta = source.get(k) or {}
                html += _ui_html("<tr>")
                html += _ui_html("<td><code>{}</code></td>").format(ctx.esc(k))
                html += _ui_html("<td>{}</td>").format(ctx.esc(_display(meta.get("type"))))
                html += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(meta.get("size"))))
                html += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(meta.get("mtime"))))
                html += _ui_html("</tr>")
            html += _ui_html("</table>")
            if len(keys) > 300:
                html += _ui_html("<p class='warn'>Anzeige auf 300 Einträge begrenzt. Gesamt: {}</p>").format(ctx.esc(str(len(keys))))
            html += _ui_html("</div>")
            return html

        body += render_list("Neue Dateien/Ordner", added_keys, cur, "ok")
        body += render_list("Geänderte Dateien/Ordner", changed_keys, cur, "warn")
        body += render_list("Gelöschte Dateien/Ordner", deleted_keys, old, "err")

        body += _details_card(ctx, "Vergleich JSON", {
            "base": previous_id,
            "current": snapshot_id,
            "summary": {
                "added": len(added_keys),
                "changed": len(changed_keys),
                "deleted": len(deleted_keys),
                "unchanged": unchanged,
                "added_bytes": added_bytes,
                "changed_bytes": changed_bytes,
                "deleted_bytes": deleted_bytes,
            },
            "added": added_keys[:1000],
            "changed": changed_keys[:1000],
            "deleted": deleted_keys[:1000],
        })

        return ctx.page("Snapshot-Vergleich " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/files")
    def apps_backup_snapshot_files(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        import os

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        rel = request.args.get("path", "").strip().lstrip("/")
        current = (snap_dir / rel).resolve()

        try:
            current.relative_to(snap_dir.resolve())
        except Exception:
            return ctx.page(
                _ui_text("Ungültiger Pfad"),
                _ui_html("<div class='card'><h2>Ungültiger Pfad</h2></div>"),
                "Apps",
            ), 400

        if not current.exists() or not current.is_dir():
            return ctx.page(
                _ui_text("Ordner nicht gefunden"),
                _ui_html("<div class='card'><h2>Ordner nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(current))),
                "Apps",
            ), 404

        body = _ui_html("<div class='card'><h2>Dateibrowser: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück zum Snapshot</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots'>Snapshot-Liste</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Aktueller Pfad: <code>/{}</code><br>Basis: <code>{}</code></p>").format(
            ctx.esc(rel),
            ctx.esc(str(snap_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Inhalt</h3>")

        if rel:
            parent = str(Path(rel).parent)
            if parent == ".":
                parent = ""
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/files?path={}'>Eine Ebene hoch</a></p>").format(
                ctx.esc(m.app_id),
                ctx.esc(snapshot_id),
                ctx.esc(parent),
            )

        entries = []
        try:
            for item in current.iterdir():
                try:
                    st = item.lstat()
                    item_rel = str(item.relative_to(snap_dir))
                    typ = "Ordner" if item.is_dir() else ("Symlink" if item.is_symlink() else "Datei")
                    size = "" if item.is_dir() else str(st.st_size)
                    mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    entries.append((0 if item.is_dir() else 1, item.name.lower(), item.name, item_rel, typ, size, mtime))
                except Exception:
                    continue
        except Exception as e:
            body += _ui_html("<p class='err'>{}</p>").format(ctx.esc(str(e)))

        if not entries:
            body += _ui_html("<p class='warn'>Ordner ist leer.</p>")
        else:
            entries.sort()
            body += _ui_html("<table><tr><th>Name</th><th>Typ</th><th>Größe</th><th>Geändert</th><th>Aktion</th></tr>")
            for _, _, name, item_rel, typ, size, mtime in entries[:500]:
                body += _ui_html("<tr>")
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(name))
                body += _ui_html("<td>{}</td>").format(ctx.esc(typ))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(size or "—"))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(mtime))
                if typ == "Ordner":
                    body += _ui_html("<td><a class='btn' href='/apps/{}/backup/snapshots/{}/files?path={}'>Öffnen</a></td>").format(
                        ctx.esc(m.app_id),
                        ctx.esc(snapshot_id),
                        ctx.esc(item_rel),
                    )
                else:
                    body += _ui_html("<td><code>read-only</code></td>")
                body += _ui_html("</tr>")
            body += _ui_html("</table>")

            if len(entries) > 500:
                body += _ui_html("<p class='warn'>Anzeige auf 500 Einträge begrenzt. Gesamt: {}</p>").format(ctx.esc(str(len(entries))))

        body += _ui_html("</div>")

        return ctx.page("Snapshot-Dateien " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-plan")
    def apps_backup_snapshot_restore_plan(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        manifest_file = run_dir / "data" / "manifest.json"

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        manifest = read_json(manifest_file)
        inc = manifest.get("incremental_snapshot") or {}
        paths = inc.get("paths") or {}

        body = _ui_html("<div class='card'><h2>Snapshot Restore-Plan: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück zum Snapshot</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots'>Snapshot-Liste</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p><b>Dry-Run:</b> Diese Seite plant nur den Restore. Es wird nichts verändert.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")

        body += _ui_html("<div class='card'><h3>Quelle</h3>")
        body += _ui_html("<p>Snapshot:<br><code>{}</code><br>Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(snapshot_id),
            ctx.esc(str(snap_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Typ</h3>")
        body += _ui_html("<p>Restore-Art: <b>Datenrestore</b><br>Profil: <code>Datenbackup (inkrementell)</code><br>Methode: <code>rsync</code></p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Sicherheit</h3>")
        body += _ui_html("<ul>")
        body += _ui_html("<li class='warn'>Restore würde produktive Datenpfade überschreiben.</li>")
        body += _ui_html("<li class='warn'>App/Container sollten vor Restore gestoppt werden.</li>")
        body += _ui_html("<li class='ok'>Dieser Plan führt noch keinen Restore aus.</li>")
        body += _ui_html("</ul>")
        body += _ui_html("</div>")

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Geplante Datenpfade</h3>")
        if not paths:
            body += _ui_html("<p class='warn'>Keine Pfad-Metadaten gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>#</th><th>Name</th><th>Snapshot-Quelle</th><th>Ziel</th><th>Befehl</th></tr>")
            order = 1
            for name, info in paths.items():
                source = info.get("target") or str(snap_dir / name)
                target = info.get("source") or ""
                cmd = "rsync -aHAX --numeric-ids --delete {}/ {}/".format(
                    str(source).rstrip("/"),
                    str(target).rstrip("/"),
                )
                body += _ui_html("<tr>")
                body += _ui_html("<td>{}</td>").format(ctx.esc(str(order)))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(name))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(source)))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(target)))
                body += _ui_html("<td><pre>{}</pre></td>").format(ctx.esc(cmd))
                body += _ui_html("</tr>")
                order += 1
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Vorbedingungen</h3>")
        body += _ui_html("<ul>")
        body += _ui_html("<li>Snapshot-Verzeichnis muss vorhanden und lesbar sein.</li>")
        body += _ui_html("<li>Zielpfade müssen existieren oder erstellbar sein.</li>")
        body += _ui_html("<li>Vor Restore sollte ein Systembackup oder Rollback-Punkt erstellt werden.</li>")
        body += _ui_html("<li>Bei laufenden Diensten besteht Inkonsistenzrisiko.</li>")
        body += _ui_html("</ul>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Aktionen</h3>")
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/files'>Dateien durchsuchen</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Restore simulieren</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<button class='btn err' disabled>Restore ausführen später</button></p>")
        body += _ui_html("<p class='warn'>Die echte Restore-Ausführung bleibt absichtlich blockiert und kommt in einer separaten Phase.</p>")
        body += _ui_html("</div>")

        body += _details_card(ctx, "Restore-Plan JSON", {
            "ok": True,
            "mode": "snapshot_restore_plan",
            "app_id": m.app_id,
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "paths": paths,
            "blocked": True,
            "message": "Snapshot-Restore ist geplant, Ausführung noch deaktiviert.",
        })

        return ctx.page("Snapshot Restore-Plan " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-dryrun")
    def apps_backup_snapshot_restore_dryrun(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from .runner import sh

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        manifest_file = run_dir / "data" / "manifest.json"

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        def parse_rsync(lines):
            added = []
            changed = []
            deleted = []
            other = []

            for line in lines:
                x = line.strip()
                if not x:
                    continue
                if x.startswith("sending incremental file list"):
                    continue
                if x.startswith("sent ") or x.startswith("total size is ") or x.startswith("Total "):
                    continue
                if x.startswith("*deleting "):
                    deleted.append(x.replace("*deleting ", "", 1))
                elif x.startswith(">f++++++++") or x.startswith("cd++++++++"):
                    added.append(x)
                elif x.startswith(">") or x.startswith("c") or x.startswith("."):
                    changed.append(x)
                else:
                    other.append(x)

            return added, changed, deleted, other

        def stat_value(stdout, label):
            for line in stdout.splitlines():
                if line.lower().startswith(label.lower()):
                    return line.split(":", 1)[1].strip() if ":" in line else ""
            return ""

        manifest = read_json(manifest_file)
        inc = manifest.get("incremental_snapshot") or {}
        paths = inc.get("paths") or {}

        body = _ui_html("<div class='card'><h2>Restore-Simulation: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Restore-Assistent</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-plan'>Restore-Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}'>Snapshot</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<p><b>Dry-Run:</b> Es wird <u>nichts</u> verändert. Ausgeführt wird <code>rsync --dry-run --itemize-changes --stats</code>.</p>")
        body += _ui_html("</div>")

        results = []
        totals = {
            "added": 0,
            "changed": 0,
            "deleted": 0,
            "other": 0,
            "errors": 0,
            "paths": 0,
        }

        for name, info in paths.items():
            source = info.get("target") or str(snap_dir / name)
            target = info.get("source") or ""

            src = Path(source)
            tgt = Path(target)

            pre_errors = []
            if not src.exists():
                pre_errors.append("Snapshot-Quelle fehlt")
            if not target:
                pre_errors.append("Zielpfad fehlt")
            elif not tgt.exists():
                pre_errors.append("Zielpfad existiert nicht")

            cmd = "rsync -aHAXn --itemize-changes --stats --numeric-ids --delete {}/ {}/".format(
                str(source).rstrip("/"),
                str(target).rstrip("/"),
            )

            if pre_errors:
                r = {"returncode": 99, "stdout": "", "stderr": "; ".join(pre_errors)}
            else:
                r = sh(cmd, timeout=3600)

            stdout = r.get("stdout") or ""
            stderr = r.get("stderr") or ""
            rc = int(r.get("returncode", 1) or 0)

            raw_lines = [x for x in stdout.splitlines() if x.strip()]
            added, changed, deleted, other = parse_rsync(raw_lines)

            if rc != 0:
                totals["errors"] += 1

            totals["paths"] += 1
            totals["added"] += len(added)
            totals["changed"] += len(changed)
            totals["deleted"] += len(deleted)
            totals["other"] += len(other)

            results.append({
                "name": name,
                "source": source,
                "target": target,
                "command": cmd,
                "returncode": rc,
                "ok": rc == 0,
                "added": added[:500],
                "changed": changed[:500],
                "deleted": deleted[:500],
                "other": other[:500],
                "counts": {
                    "added": len(added),
                    "changed": len(changed),
                    "deleted": len(deleted),
                    "other": len(other),
                },
                "stats": {
                    "number_of_files": stat_value(stdout, "Number of files"),
                    "number_of_created_files": stat_value(stdout, "Number of created files"),
                    "number_of_deleted_files": stat_value(stdout, "Number of deleted files"),
                    "total_file_size": stat_value(stdout, "Total file size"),
                    "total_transferred_file_size": stat_value(stdout, "Total transferred file size"),
                    "literal_data": stat_value(stdout, "Literal data"),
                    "matched_data": stat_value(stdout, "Matched data"),
                },
                "stderr": stderr,
            })

        cls = "ok" if totals["errors"] == 0 else "err"

        body += _ui_html("<div class='grid'>")
        body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
        body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Pfade geprüft: <b>{}</b><br>Fehlerhafte Pfade: <b>{}</b></p>").format(
            cls,
            ctx.esc(_ui_text("OK") if totals["errors"] == 0 else _ui_text("Fehler")),
            ctx.esc(str(totals["paths"])),
            ctx.esc(str(totals["errors"])),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Geplante Änderungen</h3>")
        body += _ui_html("<p>Neu: <b class='ok'>{}</b><br>Geändert: <b class='warn'>{}</b><br>Gelöscht: <b class='err'>{}</b><br>Sonstige: <b>{}</b></p>").format(
            ctx.esc(str(totals["added"])),
            ctx.esc(str(totals["changed"])),
            ctx.esc(str(totals["deleted"])),
            ctx.esc(str(totals["other"])),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Sicherheit</h3>")
        body += _ui_html("<ul>")
        body += _ui_html("<li class='ok'>Keine Schreiboperationen.</li>")
        body += _ui_html("<li class='ok'>Keine Löschoperationen.</li>")
        body += _ui_html("<li class='warn'>Ein echter Restore würde <code>--delete</code> verwenden.</li>")
        body += _ui_html("</ul></div>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Dry-Run Ergebnisse</h3>")
        body += _ui_html("<table><tr><th>Pfad</th><th>Status</th><th>Neu</th><th>Geändert</th><th>Gelöscht</th><th>Quelle</th><th>Ziel</th></tr>")
        for r in results:
            c = r.get("counts") or {}
            body += _ui_html("<tr>")
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("name")))
            body += _ui_html("<td class='{}'>{}</td>").format("ok" if r.get("ok") else "err", _ui_text("OK") if r.get("ok") else _ui_text("Fehler"))
            body += _ui_html("<td class='ok'>{}</td>").format(ctx.esc(str(c.get("added", 0))))
            body += _ui_html("<td class='warn'>{}</td>").format(ctx.esc(str(c.get("changed", 0))))
            body += _ui_html("<td class='err'>{}</td>").format(ctx.esc(str(c.get("deleted", 0))))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("source", "")))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("target", "")))
            body += _ui_html("</tr>")
        body += _ui_html("</table></div>")

        for r in results:
            c = r.get("counts") or {}
            body += _ui_html("<div class='card'><h3>Details: {}</h3>").format(ctx.esc(r.get("name", "")))
            body += _ui_html("<p>Befehl:</p><pre>{}</pre>").format(ctx.esc(r.get("command", "")))

            if r.get("stderr"):
                body += _ui_html("<p class='err'>stderr:</p><pre>{}</pre>").format(ctx.esc(r.get("stderr", "")))

            st = r.get("stats") or {}
            body += _ui_html("<p>rsync-Statistik:<br>Dateien: <code>{}</code><br>Neu angelegt: <code>{}</code><br>Gelöscht: <code>{}</code><br>Gesamtgröße: <code>{}</code><br>Transfergröße: <code>{}</code></p>").format(
                ctx.esc(_display(st.get("number_of_files"))),
                ctx.esc(_display(st.get("number_of_created_files"))),
                ctx.esc(_display(st.get("number_of_deleted_files"))),
                ctx.esc(_display(st.get("total_file_size"))),
                ctx.esc(_display(st.get("total_transferred_file_size"))),
            )

            def table(title, rows, css):
                html = _ui_html("<h4>{}</h4>").format(ctx.esc(title))
                if not rows:
                    return html + _ui_html("<p class='ok'>Keine Einträge.</p>")
                html += _ui_html("<table><tr><th>#</th><th>Eintrag</th></tr>")
                for i, line in enumerate(rows[:300], 1):
                    html += _ui_html("<tr><td>{}</td><td class='{}'><code>{}</code></td></tr>").format(
                        ctx.esc(str(i)),
                        css,
                        ctx.esc(line),
                    )
                html += _ui_html("</table>")
                if len(rows) > 300:
                    html += _ui_html("<p class='warn'>Anzeige auf 300 Einträge begrenzt.</p>")
                return html

            body += table("Neue Dateien/Ordner", r.get("added") or [], "ok")
            body += table("Geänderte Dateien/Ordner", r.get("changed") or [], "warn")
            body += table("Gelöschte Dateien/Ordner", r.get("deleted") or [], "err")

            if r.get("other"):
                body += table("Sonstige rsync-Ausgaben", r.get("other") or [], "")

            body += _ui_html("</div>")

        payload = {
            "ok": totals["errors"] == 0,
            "mode": "snapshot_restore_dryrun",
            "app_id": m.app_id,
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "summary": totals,
            "results": results,
        }

        body += _details_card(ctx, "Dry-Run JSON", payload)

        return ctx.page("Restore-Simulation " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-wizard")
    def apps_backup_snapshot_restore_wizard(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        import os
        from .runner import sh

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        manifest_file = run_dir / "data" / "manifest.json"
        snapshot_file = run_dir / "data" / ".snapshot.json"

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        manifest = read_json(manifest_file)
        snapshot = read_json(snapshot_file)
        inc = manifest.get("incremental_snapshot") or {}
        paths = inc.get("paths") or {}

        checks = []

        def add_check(name, ok, message, level=None):
            if level is None:
                level = "ok" if ok else "err"
            checks.append({
                "name": name,
                "ok": bool(ok),
                "level": level,
                "message": message,
            })

        add_check("snapshot_dir", snap_dir.exists() and snap_dir.is_dir(), "Snapshot-Verzeichnis vorhanden")
        add_check("manifest_json", manifest_file.exists(), "Daten-Manifest vorhanden")
        add_check("snapshot_json", snapshot_file.exists(), "Snapshot-Metadaten vorhanden")
        add_check("paths_present", bool(paths), "{} Datenpfad(e) im Manifest".format(len(paths)))

        readable = bool(snap_dir.exists() and os.access(str(snap_dir), os.R_OK))
        add_check("snapshot_readable", readable, "Snapshot lesbar" if readable else "Snapshot nicht lesbar")

        free_root = Path(DEFAULT_BACKUP_ROOT)
        try:
            usage = shutil.disk_usage(str(free_root))
            free_bytes = int(usage.free)
            total_bytes = int(usage.total)
        except Exception:
            free_bytes = 0
            total_bytes = 0

        snapshot_bytes = int(manifest.get("total_bytes", 0) or snapshot.get("total_bytes", 0) or 0)
        add_check(
            "free_space",
            free_bytes > max(snapshot_bytes, 1),
            "Freier Speicher: {} Bytes".format(free_bytes),
            "ok" if free_bytes > max(snapshot_bytes, 1) else "warn",
        )

        target_rows = []
        target_errors = 0
        for name, info in paths.items():
            source = Path(info.get("target") or (snap_dir / name))
            target = Path(info.get("source") or "")
            src_ok = source.exists()
            tgt_exists = target.exists()
            tgt_parent_ok = target.parent.exists() if str(target) else False
            writable = os.access(str(target), os.W_OK) if tgt_exists else os.access(str(target.parent), os.W_OK) if tgt_parent_ok else False

            if not src_ok or not writable:
                target_errors += 1

            target_rows.append({
                "name": name,
                "source": str(source),
                "target": str(target),
                "source_ok": src_ok,
                "target_exists": tgt_exists,
                "target_parent_ok": tgt_parent_ok,
                "writable": writable,
            })

        add_check(
            "target_paths",
            target_errors == 0,
            "{} Zielpfad(e), {} Problem(e)".format(len(target_rows), target_errors),
            "ok" if target_errors == 0 else "err",
        )

        status = _safe_call(lambda: m.status(), "status")
        status_ok = bool(status.get("ok"))
        warnings = status.get("warnings") or []
        app_level = "ok" if status_ok and not warnings else "warn" if status_ok else "err"
        add_check(
            "app_status",
            status_ok,
            "App-Status: {}".format("OK" if status_ok else "Fehler"),
            app_level,
        )

        hard_errors = [c for c in checks if c.get("level") == "err"]
        warnings_list = [c for c in checks if c.get("level") == "warn"]
        restore_possible = len(hard_errors) == 0

        safety_backup = request.args.get("safety_backup", "1") != "0"
        repair_permissions = request.args.get("repair_permissions", "1") != "0"
        healthcheck = request.args.get("healthcheck", "1") != "0"

        body = _ui_html("<div class='card'><h2>Snapshot Restore-Assistent: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}'>Zurück zum Snapshot</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-plan'>Restore-Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Restore simulieren</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<p><b>Read-only:</b> Der Assistent prüft nur. Es wird nichts verändert.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")

        body += _ui_html("<div class='card'><h3>Snapshot</h3>")
        body += _ui_html("<p>App: <b>{}</b><br>Snapshot: <code>{}</code><br>Verzeichnis:<br><code>{}</code><br>Dateien: <b>{}</b><br>Bytes: <code>{}</code></p>").format(
            ctx.esc(_ui_text(m.label)),
            ctx.esc(snapshot_id),
            ctx.esc(str(snap_dir)),
            ctx.esc(_display(manifest.get("total_files") or snapshot.get("total_files"))),
            ctx.esc(_display(snapshot_bytes)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Restore-Freigabe</h3>")
        if restore_possible:
            body += _ui_html("<p class='ok'><b>Restore vorbereitbar</b></p>")
        else:
            body += _ui_html("<p class='err'><b>Restore gesperrt</b></p>")
        body += _ui_html("<p>Fehler: <b class='err'>{}</b><br>Warnungen: <b class='warn'>{}</b></p>").format(
            ctx.esc(str(len(hard_errors))),
            ctx.esc(str(len(warnings_list))),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Speicher</h3>")
        body += _ui_html("<p>Snapshot-Daten: <code>{}</code> Bytes<br>Frei: <code>{}</code> Bytes<br>Gesamt: <code>{}</code> Bytes</p>").format(
            ctx.esc(str(snapshot_bytes)),
            ctx.esc(str(free_bytes)),
            ctx.esc(str(total_bytes)),
        )
        body += _ui_html("</div>")

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Vorprüfung</h3>")
        body += _ui_html("<table><tr><th>Check</th><th>Status</th><th>Meldung</th></tr>")
        for c in checks:
            cls = c.get("level", "ok")
            icon = "✓" if cls == "ok" else "⚠" if cls == "warn" else "✖"
            body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td><td>{}</td></tr>").format(
                ctx.esc(c.get("name")),
                cls,
                ctx.esc(icon),
                ctx.esc(_ui_text(c.get("message"))),
            )
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Optionen</h3>")
        body += _ui_html("<form method='get'>")
        body += _ui_html("<p><label><input type='checkbox' name='safety_backup' value='1' {}> Sicherheitsbackup vor Restore erstellen</label></p>").format("checked" if safety_backup else "")
        body += _ui_html("<p><label><input type='checkbox' name='repair_permissions' value='1' {}> Rechte/Eigentümer nach Restore prüfen</label></p>").format("checked" if repair_permissions else "")
        body += _ui_html("<p><label><input type='checkbox' name='healthcheck' value='1' {}> Healthcheck nach Restore ausführen</label></p>").format("checked" if healthcheck else "")
        body += _ui_html("<p><button class='btn' type='submit'>Optionen aktualisieren</button></p>")
        body += _ui_html("</form>")
        if not safety_backup:
            body += _ui_html("<p class='warn'><b>Sicherheitsbackup deaktiviert.</b> Rollback ist dadurch später nicht möglich.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Zielpfade</h3>")
        if target_rows:
            body += _ui_html("<table><tr><th>Name</th><th>Quelle</th><th>Ziel</th><th>Quelle OK</th><th>Ziel vorhanden</th><th>Schreibbar</th></tr>")
            for r in target_rows:
                body += _ui_html("<tr>")
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r["name"]))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r["source"]))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r["target"]))
                body += _ui_html("<td class='{}'>{}</td>").format("ok" if r["source_ok"] else "err", _ui_text("ja") if r["source_ok"] else _ui_text("nein"))
                body += _ui_html("<td class='{}'>{}</td>").format("ok" if r["target_exists"] else "warn", _ui_text("ja") if r["target_exists"] else _ui_text("nein"))
                body += _ui_html("<td class='{}'>{}</td>").format("ok" if r["writable"] else "err", _ui_text("ja") if r["writable"] else _ui_text("nein"))
                body += _ui_html("</tr>")
            body += _ui_html("</table>")
        else:
            body += _ui_html("<p class='warn'>Keine Zielpfade gefunden.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>App-Status</h3>")
        body += _pre(ctx, status)
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Nächster Schritt</h3>")
        if restore_possible:
            body += _ui_html("<p class='ok'><b>Vorprüfung bestanden.</b></p>")
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Restore simulieren</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-create-backup'>Sicherheitsbackup erstellen</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-session'>Restore-Session testen</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn err' href='/apps/{}/backup/snapshots/{}/restore-execute'>Restore ausführen</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        else:
            body += _ui_html("<p class='err'><b>Restore-Ausführung bleibt gesperrt, bis die Fehler behoben sind.</b></p>")
        body += _ui_html("</div>")

        body += _details_card(ctx, "Restore-Assistent JSON", {
            "ok": True,
            "restore_possible": restore_possible,
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "checks": checks,
            "target_paths": target_rows,
            "options": {
                "safety_backup": safety_backup,
                "repair_permissions": repair_permissions,
                "healthcheck": healthcheck,
            },
            "status": status,
        })

        return ctx.page("Snapshot Restore-Assistent " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-create-backup", methods=["GET", "POST"])
    def apps_backup_snapshot_restore_create_backup(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from .runner import sh
        from datetime import datetime

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        manifest_file = run_dir / "data" / "manifest.json"

        restore_backup_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "restore_backups"

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        manifest = read_json(manifest_file)
        inc = manifest.get("incremental_snapshot") or {}
        paths = inc.get("paths") or {}

        if request.method != "POST":
            body = _ui_html("<div class='card'><h2>Sicherheitsbackup erstellen: {}</h2>").format(ctx.esc(snapshot_id))
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Zurück zum Assistenten</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Restore simulieren</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<p class='warn'><b>Schreibender Vorgang:</b> Es werden die aktuellen Zielpfade in ein Rollback-Verzeichnis kopiert. Produktive Daten werden dabei nicht verändert.</p>")
            body += _ui_html("<p>Ziel: <code>{}</code></p>").format(ctx.esc(str(restore_backup_root)))
            body += _ui_html("<form method='post' onsubmit=\"return confirm('Sicherheitsbackup der Zielpfade jetzt erstellen?')\">")
            body += _ui_html("<button class='btn err' type='submit'>Sicherheitsbackup jetzt erstellen</button>")
            body += _ui_html("</form></div>")

            body += _ui_html("<div class='card'><h3>Zu sichernde Zielpfade</h3>")
            if not paths:
                body += _ui_html("<p class='warn'>Keine Pfade gefunden.</p>")
            else:
                body += _ui_html("<table><tr><th>Name</th><th>Zielpfad</th><th>Vorhanden</th></tr>")
                for name, info in paths.items():
                    target = Path(info.get("source") or "")
                    body += _ui_html("<tr><td><code>{}</code></td><td><code>{}</code></td><td class='{}'>{}</td></tr>").format(
                        ctx.esc(name),
                        ctx.esc(str(target)),
                        "ok" if target.exists() else "err",
                        _ui_text("ja") if target.exists() else _ui_text("nein"),
                    )
                body += _ui_html("</table>")
            body += _ui_html("</div>")

            return ctx.page("Sicherheitsbackup " + m.label, body, "Apps")

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_id = "restore_{}".format(ts)
        backup_dir = restore_backup_root / backup_id
        backup_dir.mkdir(parents=True, exist_ok=False)

        results = []
        errors = []

        for name, info in paths.items():
            target = Path(info.get("source") or "")
            dest = backup_dir / name

            if not target.exists():
                r = {
                    "name": name,
                    "source": str(target),
                    "target": str(dest),
                    "ok": False,
                    "returncode": 99,
                    "stderr": "Zielpfad existiert nicht",
                    "stdout": "",
                    "command": "",
                }
                errors.append("{}: Zielpfad fehlt".format(name))
                results.append(r)
                continue

            dest.mkdir(parents=True, exist_ok=True)

            cmd = "rsync -aHAX --numeric-ids {}/ {}/".format(
                str(target).rstrip("/"),
                str(dest).rstrip("/"),
            )

            rr = sh(cmd, timeout=86400)
            ok = rr.get("returncode") == 0

            r = {
                "name": name,
                "source": str(target),
                "target": str(dest),
                "ok": ok,
                "returncode": rr.get("returncode"),
                "stdout": rr.get("stdout"),
                "stderr": rr.get("stderr"),
                "command": cmd,
            }

            if not ok:
                errors.append("{}: rsync fehlgeschlagen".format(name))

            results.append(r)

        meta = {
            "ok": len(errors) == 0,
            "type": "restore_safety_backup",
            "app_id": m.app_id,
            "label": getattr(m, "label", m.app_id),
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "backup_id": backup_id,
            "backup_dir": str(backup_dir),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rollback_available": len(errors) == 0,
            "paths": results,
            "errors": errors,
        }

        (backup_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        body = _ui_html("<div class='card'><h2>Sicherheitsbackup Ergebnis: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Zurück zum Assistenten</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Restore simulieren</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))

        if meta["ok"]:
            body += _ui_html("<p class='ok'><b>Sicherheitsbackup erstellt.</b></p>")
        else:
            body += _ui_html("<p class='err'><b>Sicherheitsbackup mit Fehlern.</b></p>")

        body += _ui_html("<p>Backup-ID: <code>{}</code><br>Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(backup_id),
            ctx.esc(str(backup_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Pfade</h3>")
        body += _ui_html("<table><tr><th>Name</th><th>Status</th><th>Quelle</th><th>Sicherung</th><th>Returncode</th></tr>")
        for r in results:
            body += _ui_html("<tr>")
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("name", "")))
            body += _ui_html("<td class='{}'>{}</td>").format("ok" if r.get("ok") else "err", _ui_text("OK") if r.get("ok") else _ui_text("Fehler"))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("source", "")))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(r.get("target", "")))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(r.get("returncode"))))
            body += _ui_html("</tr>")
        body += _ui_html("</table></div>")

        if errors:
            body += _ui_html("<div class='card'><h3>Fehler</h3><ul>")
            for e in errors:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul></div>")

        body += _details_card(ctx, "Sicherheitsbackup JSON", meta)

        return ctx.page("Sicherheitsbackup " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-session", methods=["GET", "POST"])
    def apps_backup_snapshot_restore_session(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from datetime import datetime
        import time

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        session_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "restore_sessions"
        lock_file = session_root / "restore.lock"

        def now_s():
            return datetime.now().isoformat(timespec="seconds")

        def write_json(path, data):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def log_line(session_dir, msg):
            with (session_dir / "session.log").open("a", encoding="utf-8") as f:
                f.write("{} {}\n".format(now_s(), msg))

        def wait_for_health(max_seconds=120, interval=2):
            attempts = []
            deadline = time.time() + max_seconds
            last = {}

            while time.time() < deadline:
                try:
                    h = m.restore_healthcheck()
                except Exception as e:
                    h = {"ok": False, "error": str(e)}

                last = h
                attempts.append({
                    "time": now_s(),
                    "ok": bool(h.get("ok")),
                    "warnings": h.get("warnings") or [],
                    "web": h.get("web") or {},
                    "containers": h.get("containers") or {},
                })

                if h.get("ok") and not h.get("warnings"):
                    return {
                        "ok": True,
                        "method": "wait_for_health",
                        "timeout": max_seconds,
                        "attempts": attempts,
                        "last": h,
                    }

                time.sleep(interval)

            return {
                "ok": bool(last.get("ok")),
                "method": "wait_for_health",
                "timeout": max_seconds,
                "attempts": attempts,
                "last": last,
                "error": "Healthcheck Timeout oder Warnungen nach Start",
            }

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(
                _ui_text("Snapshot nicht gefunden"),
                _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2><p><code>{}</code></p></div>").format(ctx.esc(str(snap_dir))),
                "Apps",
            ), 404

        if request.method != "POST":
            body = _ui_html("<div class='card'><h2>Restore Session: {}</h2>").format(ctx.esc(snapshot_id))
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Restore-Assistent</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Dry-Run</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<p class='warn'><b>Vorbereitung:</b> Diese Session testet Stop/Start/Healthcheck. Es wird noch kein Restore ausgeführt.</p>")
            if lock_file.exists():
                body += _ui_html("<p class='err'><b>Restore-Lock vorhanden:</b><br><code>{}</code></p>").format(ctx.esc(str(lock_file)))
            body += _ui_html("<form method='post' onsubmit=\"return confirm('Restore-Session starten? App wird kurz gestoppt und wieder gestartet.')\">")
            body += _ui_html("<button class='btn err' type='submit'>Restore-Session testen</button>")
            body += _ui_html("</form></div>")
            return ctx.page("Restore Session " + m.label, body, "Apps")

        session_root.mkdir(parents=True, exist_ok=True)

        if lock_file.exists():
            return ctx.page(
                _ui_text("Restore gesperrt"),
                _ui_html("<div class='card'><h2>Restore gesperrt</h2><p class='err'>Es existiert bereits ein Restore-Lock:<br><code>{}</code></p></div>").format(ctx.esc(str(lock_file))),
                "Apps",
            ), 409

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_id = "restore_session_{}".format(ts)
        session_dir = session_root / session_id
        session_dir.mkdir(parents=True, exist_ok=False)

        result = {
            "ok": False,
            "status": "created",
            "mode": "restore_session_prepare",
            "app_id": m.app_id,
            "label": getattr(m, "label", m.app_id),
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "session_id": session_id,
            "session_dir": str(session_dir),
            "lock_file": str(lock_file),
            "started_at": now_s(),
            "updated_at": now_s(),
            "finished_at": None,
            "steps": {},
            "errors": [],
        }

        try:
            lock_file.write_text(json.dumps({
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "created_at": now_s(),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            log_line(session_dir, "Session erstellt")
            write_json(session_dir / "session.json", result)

            result["status"] = "stopping"
            result["updated_at"] = now_s()
            write_json(session_dir / "session.json", result)
            log_line(session_dir, "Stoppe App")

            try:
                stop_result = m.stop_for_restore()
            except Exception as e:
                stop_result = {"ok": False, "error": str(e)}

            result["steps"]["stop"] = stop_result
            result["updated_at"] = now_s()

            if not stop_result.get("ok"):
                result["status"] = "failed"
                result["errors"].append("App konnte nicht gestoppt werden.")
                log_line(session_dir, "Stop fehlgeschlagen")
            else:
                result["status"] = "stopped"
                log_line(session_dir, "App gestoppt")

                result["status"] = "starting"
                result["updated_at"] = now_s()
                write_json(session_dir / "session.json", result)
                log_line(session_dir, "Starte App")

                try:
                    start_result = m.start_after_restore()
                except Exception as e:
                    start_result = {"ok": False, "error": str(e)}

                result["steps"]["start"] = start_result
                result["updated_at"] = now_s()

                if not start_result.get("ok"):
                    result["status"] = "failed"
                    result["errors"].append("App konnte nicht gestartet werden.")
                    log_line(session_dir, "Start fehlgeschlagen")
                else:
                    result["status"] = "started"
                    log_line(session_dir, "App gestartet")

                    result["status"] = "healthcheck_wait"
                    result["updated_at"] = now_s()
                    write_json(session_dir / "session.json", result)
                    log_line(session_dir, "Warte auf Healthcheck")

                    health_wait = wait_for_health(max_seconds=120, interval=2)
                    result["steps"]["healthcheck"] = health_wait
                    result["updated_at"] = now_s()

                    if not health_wait.get("ok"):
                        result["status"] = "failed"
                        result["errors"].append("Healthcheck fehlgeschlagen oder Timeout.")
                        log_line(session_dir, "Healthcheck fehlgeschlagen")
                    else:
                        result["status"] = "finished"
                        log_line(session_dir, "Healthcheck OK")

            result["finished_at"] = now_s()
            result["ok"] = len(result["errors"]) == 0
            if not result["ok"]:
                result["status"] = "failed"

            write_json(session_dir / "session.json", result)

        finally:
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except Exception:
                pass

        body = _ui_html("<div class='card'><h2>Restore Session Ergebnis: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Restore-Assistent</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Dry-Run</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))

        if result["ok"]:
            body += _ui_html("<p class='ok'><b>Restore-Session erfolgreich.</b></p>")
        else:
            body += _ui_html("<p class='err'><b>Restore-Session mit Fehlern.</b></p>")

        body += _ui_html("<p>Status: <code>{}</code><br>Session-ID: <code>{}</code><br>Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(result.get("status")),
            ctx.esc(session_id),
            ctx.esc(str(session_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Schritte</h3>")
        body += _ui_html("<table><tr><th>Schritt</th><th>Status</th><th>Methode</th><th>Returncode</th></tr>")
        for key in ["stop", "start", "healthcheck"]:
            step = result["steps"].get(key) or {}
            body += _ui_html("<tr>")
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(key))
            body += _ui_html("<td class='{}'>{}</td>").format("ok" if step.get("ok") else "err", _ui_text("OK") if step.get("ok") else _ui_text("Fehler"))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(step.get("method"))))
            body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(_display(step.get("returncode"))))
            body += _ui_html("</tr>")
        body += _ui_html("</table></div>")

        hw = (result["steps"].get("healthcheck") or {})
        attempts = hw.get("attempts") or []
        if attempts:
            body += _ui_html("<div class='card'><h3>Healthcheck-Wartephase</h3>")
            body += _ui_html("<p>Versuche: <b>{}</b><br>Timeout: <code>{}</code> Sekunden</p>").format(
                ctx.esc(str(len(attempts))),
                ctx.esc(_display(hw.get("timeout"))),
            )
            body += _ui_html("<table><tr><th>Zeit</th><th>Status</th><th>Warnungen</th></tr>")
            for a in attempts[-20:]:
                warn = ", ".join(a.get("warnings") or [])
                body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td><td>{}</td></tr>").format(
                    ctx.esc(a.get("time")),
                    "ok" if a.get("ok") and not warn else "warn",
                    _ui_text("OK") if a.get("ok") else _ui_text("wartet"),
                    ctx.esc(warn),
                )
            body += _ui_html("</table></div>")

        if result["errors"]:
            body += _ui_html("<div class='card'><h3>Fehler</h3><ul>")
            for e in result["errors"]:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul></div>")

        log_file = session_dir / "session.log"
        if log_file.exists():
            body += _ui_html("<div class='card'><h3>Session Log</h3><pre>{}</pre></div>").format(
                ctx.esc(log_file.read_text(encoding="utf-8", errors="replace"))
            )

        body += _details_card(ctx, "Restore Session JSON", result)

        return ctx.page("Restore Session " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/snapshots/<snapshot_id>/restore-execute", methods=["GET", "POST"])
    def apps_backup_snapshot_restore_execute(app_id, snapshot_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from .runner import sh
        from datetime import datetime
        import time

        snap_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "data_snapshots"
        snap_dir = snap_root / snapshot_id
        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / snapshot_id
        manifest_file = run_dir / "data" / "manifest.json"
        session_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "restore_sessions"
        restore_backup_root = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "restore_backups"
        lock_file = session_root / "restore.lock"

        def now_s():
            return datetime.now().isoformat(timespec="seconds")

        def read_json(path):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {}

        def save(session):
            session["updated_at"] = now_s()
            (Path(session["session_dir"]) / "session.json").write_text(
                json.dumps(session, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def log_line(session, msg):
            with (Path(session["session_dir"]) / "session.log").open("a", encoding="utf-8") as f:
                f.write("{} {}\n".format(now_s(), msg))

        def extract_docker_states(h):
            states = {}
            for c in h.get("compose_ps") or []:
                name = c.get("Name") or c.get("Names") or c.get("Service") or "container"
                states[name] = {
                    "state": str(c.get("State", "")).lower(),
                    "health": str(c.get("Health", "")).lower(),
                    "status": c.get("Status", ""),
                }
            return states

        def docker_health_ready(states):
            if not states:
                return True
            for _, v in states.items():
                state = v.get("state", "")
                health = v.get("health", "")
                if health:
                    if health != "healthy":
                        return False
                elif state != "running":
                    return False
            return True

        def wait_for_health(max_seconds=120, interval=2):
            attempts = []
            deadline = time.time() + max_seconds
            last = {}

            while time.time() < deadline:
                try:
                    h = m.restore_healthcheck()
                except Exception as e:
                    h = {"ok": False, "error": str(e)}

                last = h
                states = extract_docker_states(h)
                web_ok = bool((h.get("web") or {}).get("ok"))
                no_warnings = not (h.get("warnings") or [])
                docker_ok = docker_health_ready(states)

                attempts.append({
                    "time": now_s(),
                    "ok": bool(h.get("ok")),
                    "warnings": h.get("warnings") or [],
                    "web_ok": web_ok,
                    "docker_ok": docker_ok,
                    "docker_states": states,
                })

                if h.get("ok") and web_ok and docker_ok and no_warnings:
                    return {
                        "ok": True,
                        "method": "wait_for_health",
                        "timeout": max_seconds,
                        "attempts": attempts,
                        "docker_states": states,
                        "last": h,
                    }

                time.sleep(interval)

            return {
                "ok": False,
                "method": "wait_for_health",
                "timeout": max_seconds,
                "attempts": attempts,
                "docker_states": extract_docker_states(last),
                "last": last,
                "error": "Healthcheck Timeout, Docker nicht healthy oder Web/API nicht erreichbar",
            }

        def latest_restore_backup():
            if not restore_backup_root.exists():
                return None
            items = []
            for d in restore_backup_root.iterdir():
                mf = d / "meta.json"
                if d.is_dir() and mf.exists():
                    try:
                        data = json.loads(mf.read_text(encoding="utf-8"))
                        if data.get("ok") and data.get("snapshot_id") == snapshot_id:
                            items.append((d.stat().st_mtime, d.name, data))
                    except Exception:
                        pass
            if not items:
                return None
            items.sort(reverse=True)
            return items[0][2]

        if not snap_dir.exists() or not snap_dir.is_dir():
            return ctx.page(_ui_text("Snapshot nicht gefunden"), _ui_html("<div class='card'><h2>Snapshot nicht gefunden</h2></div>"), "Apps"), 404

        manifest = read_json(manifest_file)
        inc = manifest.get("incremental_snapshot") or {}
        paths = inc.get("paths") or {}
        safety_backup = latest_restore_backup()
        no_safety = request.args.get("no_safety_backup") == "1" or request.form.get("no_safety_backup") == "1"

        if request.method != "POST":
            body = _ui_html("<div class='card'><h2>Restore ausführen: {}</h2>").format(ctx.esc(snapshot_id))
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/snapshots/{}/restore-wizard'>Restore-Assistent</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-dryrun'>Dry-Run</a> ").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/snapshots/{}/restore-create-backup'>Sicherheitsbackup</a></p>").format(ctx.esc(m.app_id), ctx.esc(snapshot_id))
            body += _ui_html("<p class='err'><b>Produktiver Schreibvorgang.</b> Dieser Restore überschreibt Zielpfade per rsync und verwendet <code>--delete</code>.</p>")
            body += _ui_html("<p class='{}'>{}</p>").format(
                "ok" if safety_backup else "warn",
                _ui_html("Sicherheitsbackup gefunden: <code>{}</code>").format(ctx.esc(safety_backup.get("backup_id"))) if safety_backup else _ui_text("Kein Sicherheitsbackup für diesen Snapshot gefunden."),
            )
            body += _ui_html("<form method='post' onsubmit=\"return confirm('ECHTEN Restore jetzt ausführen?')\">")
            body += _ui_html("<p>Bestätigungstoken<br><input name='confirm_token' placeholder='RESTORE' required></p>")
            if not safety_backup:
                body += _ui_html("<p><label><input type='checkbox' name='no_safety_backup' value='1'> Ohne Sicherheitsbackup fortfahren</label></p>")
            body += _ui_html("<button class='btn err' type='submit'>Echten Restore ausführen</button></form></div>")

            # Aktuelle Restore-Ausführung anzeigen
            latest_session = None
            try:
                sr = Path(DEFAULT_BACKUP_ROOT) / m.app_id / "restore_sessions"
                items = []
                if sr.exists():
                    for d in sr.iterdir():
                        jf = d / "session.json"
                        if d.is_dir() and d.name.startswith("restore_execute_") and jf.exists():
                            try:
                                data = json.loads(jf.read_text(encoding="utf-8"))
                                if data.get("snapshot_id") == snapshot_id:
                                    items.append((d.stat().st_mtime, data))
                            except Exception:
                                pass
                if items:
                    items.sort(reverse=True)
                    latest_session = items[0][1]
            except Exception:
                latest_session = None

            if latest_session:
                steps = latest_session.get("steps") or {}
                body += _ui_html("<div class='card'><h3>Letzte Restore-Ausführung</h3>")
                body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Session: <code>{}</code><br>Zeit: <code>{}</code></p>").format(
                    "ok" if latest_session.get("ok") else "err",
                    ctx.esc(_ui_text(latest_session.get("status", "unbekannt"))),
                    ctx.esc(latest_session.get("session_id", "")),
                    ctx.esc(latest_session.get("finished_at") or latest_session.get("updated_at") or ""),
                )
                body += _ui_html("<table><tr><th>Schritt</th><th>Status</th></tr>")
                for k in ["stop", "restore", "start", "healthcheck"]:
                    st = steps.get(k) or {}
                    body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td></tr>").format(
                        ctx.esc(k),
                        "ok" if st.get("ok") else "err",
                        _ui_text("OK") if st.get("ok") else _ui_text("Fehler"),
                    )
                body += _ui_html("</table>")

                docker_states = ((steps.get("healthcheck") or {}).get("docker_states") or {})
                if docker_states:
                    body += _ui_html("<h4>Docker-Status</h4>")
                    body += _ui_html("<table><tr><th>Container</th><th>State</th><th>Health</th><th>Status</th></tr>")
                    for cname, cinfo in docker_states.items():
                        health = cinfo.get("health") or "no-health"
                        cls = "ok" if cinfo.get("state") == "running" and health in ["healthy", "no-health", ""] else "warn"
                        body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td><td><code>{}</code></td><td><code>{}</code></td></tr>").format(
                            ctx.esc(cname),
                            cls,
                            ctx.esc(_ui_text(cinfo.get("state", ""))),
                            ctx.esc(health),
                            ctx.esc(cinfo.get("status", "")),
                        )
                    body += _ui_html("</table>")

                body += _ui_html("</div>")

            return ctx.page("Restore ausführen " + m.label, body, "Apps")

        if request.form.get("confirm_token") != "RESTORE":
            return ctx.page(_ui_text("Restore blockiert"), _ui_html("<div class='card'><h2>Restore blockiert</h2><p class='err'>Bestätigungstoken falsch.</p></div>"), "Apps"), 403

        if not safety_backup and not no_safety:
            return ctx.page(_ui_text("Restore blockiert"), _ui_html("<div class='card'><h2>Restore blockiert</h2><p class='err'>Kein Sicherheitsbackup vorhanden.</p></div>"), "Apps"), 403

        session_root.mkdir(parents=True, exist_ok=True)

        if lock_file.exists():
            return ctx.page(_ui_text("Restore gesperrt"), _ui_html("<div class='card'><h2>Restore gesperrt</h2><p class='err'>Restore-Lock vorhanden.</p></div>"), "Apps"), 409

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_id = "restore_execute_{}".format(ts)
        session_dir = session_root / session_id
        session_dir.mkdir(parents=True, exist_ok=False)

        session = {
            "ok": False,
            "status": "created",
            "mode": "snapshot_restore_execute",
            "app_id": m.app_id,
            "label": getattr(m, "label", m.app_id),
            "snapshot_id": snapshot_id,
            "snapshot_dir": str(snap_dir),
            "session_id": session_id,
            "session_dir": str(session_dir),
            "lock_file": str(lock_file),
            "safety_backup": safety_backup,
            "no_safety_backup": no_safety,
            "started_at": now_s(),
            "updated_at": now_s(),
            "finished_at": None,
            "steps": {
                "stop": {"ok": False, "pending": True},
                "restore": {"ok": False, "pending": True, "method": "rsync", "paths": []},
                "start": {"ok": False, "pending": True},
                "healthcheck": {"ok": False, "pending": True},
            },
            "errors": [],
        }

        try:
            lock_file.write_text(json.dumps({
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "created_at": now_s(),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            save(session)
            log_line(session, "Restore-Session erstellt")

            session["status"] = "stopping"
            save(session)
            log_line(session, "Stoppe App")

            try:
                session["steps"]["stop"] = m.stop_for_restore()
            except Exception as e:
                session["steps"]["stop"] = {"ok": False, "error": str(e)}
            save(session)

            if not session["steps"]["stop"].get("ok"):
                session["errors"].append("App konnte nicht gestoppt werden.")
                session["status"] = "failed"
                save(session)
            else:
                session["status"] = "restoring"
                save(session)
                log_line(session, "Starte rsync Restore")

                restore_results = []
                for name, info in paths.items():
                    source = info.get("target") or str(snap_dir / name)
                    target = info.get("source") or ""
                    cmd = "rsync -aHAX --numeric-ids --delete {}/ {}/".format(
                        str(source).rstrip("/"),
                        str(target).rstrip("/"),
                    )
                    rr = sh(cmd, timeout=86400)
                    ok = rr.get("returncode") == 0

                    item = {
                        "name": name,
                        "source": source,
                        "target": target,
                        "command": cmd,
                        "ok": ok,
                        "returncode": rr.get("returncode"),
                        "stdout": rr.get("stdout"),
                        "stderr": rr.get("stderr"),
                    }
                    restore_results.append(item)
                    log_line(session, "Restore {}: {}".format(name, "OK" if ok else "FEHLER"))

                    session["steps"]["restore"] = {
                        "ok": all(x.get("ok") for x in restore_results),
                        "pending": False,
                        "method": "rsync",
                        "paths": restore_results,
                    }
                    save(session)

                    if not ok:
                        session["errors"].append("Restore fehlgeschlagen: {}".format(name))
                        save(session)

                if session["errors"]:
                    session["status"] = "failed"
                    save(session)
                else:
                    session["steps"]["restore"] = {
                        "ok": True,
                        "pending": False,
                        "method": "rsync",
                        "paths": restore_results,
                    }
                    session["status"] = "starting"
                    save(session)

                    log_line(session, "Starte App")
                    try:
                        session["steps"]["start"] = m.start_after_restore()
                    except Exception as e:
                        session["steps"]["start"] = {"ok": False, "error": str(e)}
                    save(session)

                    if not session["steps"]["start"].get("ok"):
                        session["errors"].append("App konnte nicht gestartet werden.")
                        session["status"] = "failed"
                        save(session)
                    else:
                        session["status"] = "healthcheck_wait"
                        save(session)
                        log_line(session, "Warte auf Healthcheck")

                        session["steps"]["healthcheck"] = wait_for_health(max_seconds=120, interval=2)
                        save(session)

                        if not session["steps"]["healthcheck"].get("ok"):
                            session["errors"].append("Healthcheck fehlgeschlagen.")
                            session["status"] = "failed"
                        else:
                            session["status"] = "finished"
                        save(session)

            session["finished_at"] = now_s()
            session["ok"] = len(session["errors"]) == 0
            if not session["ok"]:
                session["status"] = "failed"
            save(session)

        finally:
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except Exception:
                pass

        body = _ui_html("<div class='card'><h2>Restore Ergebnis: {}</h2>").format(ctx.esc(snapshot_id))
        body += _ui_html("<p class='{}'><b>{}</b></p>").format(
            "ok" if session["ok"] else "err",
            _ui_text("Restore erfolgreich abgeschlossen.") if session["ok"] else _ui_text("Restore mit Fehlern."),
        )
        body += _ui_html("<p>Status: <code>{}</code><br>Session: <code>{}</code><br>Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(session.get("status")),
            ctx.esc(session_id),
            ctx.esc(str(session_dir)),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Schritte</h3><table><tr><th>Schritt</th><th>Status</th></tr>")
        for key in ["stop", "restore", "start", "healthcheck"]:
            step = session["steps"].get(key) or {}
            body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td></tr>").format(
                ctx.esc(key),
                "ok" if step.get("ok") else "err",
                _ui_text("OK") if step.get("ok") else _ui_text("Fehler"),
            )
        body += _ui_html("</table></div>")

        if session["errors"]:
            body += _ui_html("<div class='card'><h3>Fehler</h3><ul>")
            for e in session["errors"]:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul></div>")

        log_file = session_dir / "session.log"
        if log_file.exists():
            body += _ui_html("<div class='card'><h3>Session Log</h3><pre>{}</pre></div>").format(
                ctx.esc(log_file.read_text(encoding="utf-8", errors="replace"))
            )

        body += _details_card(ctx, "Restore Execute JSON", session)

        return ctx.page("Restore Ergebnis " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/schedule", methods=["GET", "POST"])
    def apps_backup_schedule(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from .schedule_engine import write_schedule, delete_schedule, list_schedules
        from .runner import sh

        if request.method == "POST":
            action = request.form.get("action", "save")
            profile = request.form.get("profile", "system").strip()

            if action == "delete":
                res = delete_schedule(m.app_id, profile)
            else:
                res = write_schedule(
                    m.app_id,
                    profile,
                    request.form.get("frequency", "daily"),
                    request.form.get("time", "03:00"),
                    request.form.get("weekday", "Mon"),
                )

            body = _ui_html("<div class='card'><h2>Zeitplan geändert: {}</h2>").format(ctx.esc(_ui_text(m.label)))
            body += _ui_html("<p><a class='btn' href='/apps/{}/backup/schedule'>Zurück zum Zeitplan</a> ").format(ctx.esc(m.app_id))
            body += _ui_html("<a class='btn' href='/apps/{}/backup/select'>Backup starten</a></p>").format(ctx.esc(m.app_id))
            body += _ui_html("<pre>{}</pre></div>").format(ctx.esc(json.dumps(res, ensure_ascii=False, indent=2)))
            return ctx.page("Backup-Zeitplan " + m.label, body, "Apps")

        profiles = get_backup_profiles(m)
        schedules = list_schedules(m.app_id)

        body = _ui_html("<div class='card'><h2>Backup-Zeitplan: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}'>App</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/select'>Backup starten</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/runs'>Backup-Runs</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Geplante Backups werden als systemd Timer eingerichtet.</p></div>")

        body += _ui_html("<div class='card'><h3>Neuen Zeitplan anlegen/ändern</h3>")
        body += _ui_html("<form method='post'>")
        body += _ui_html("<input type='hidden' name='action' value='save'>")

        body += _ui_html("<p>Profil<br><select name='profile'>")
        for pid, prof in profiles.items():
            body += _ui_html("<option value='{}'>{}</option>").format(ctx.esc(pid), ctx.esc(_ui_text(prof.get("label", pid))))
        body += _ui_html("</select></p>")

        body += _ui_html("<p>Intervall<br><select name='frequency'>")
        body += _ui_html("<option value='daily'>Täglich</option>")
        body += _ui_html("<option value='weekly'>Wöchentlich</option>")
        body += _ui_html("<option value='monthly'>Monatlich</option>")
        body += _ui_html("</select></p>")

        body += _ui_html("<p>Uhrzeit<br><input name='time' value='03:00' pattern='[0-2][0-9]:[0-5][0-9]'></p>")

        body += _ui_html("<p>Wochentag bei wöchentlich<br><select name='weekday'>")
        for wd in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            body += _ui_html("<option value='{}'>{}</option>").format(wd, wd)
        body += _ui_html("</select></p>")

        body += _ui_html("<button class='btn' type='submit'>Zeitplan speichern</button>")
        body += _ui_html("</form></div>")

        body += _ui_html("<div class='card'><h3>Aktive Zeitpläne</h3>")
        if not schedules:
            body += _ui_html("<p class='warn'>Keine Backup-Zeitpläne eingerichtet.</p>")
        else:
            body += _ui_html("<table><tr><th>Profil</th><th>Timer</th><th>Aktiv</th><th>Enabled</th><th>Plan</th><th>Aktion</th></tr>")
            for item in schedules:
                body += _ui_html("<tr>")
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(item.get("profile")))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(item.get("timer")))
                body += _ui_html("<td class='{}'>{}</td>").format("ok" if item.get("active") == "active" else "warn", ctx.esc(item.get("active")))
                body += _ui_html("<td>{}</td>").format(ctx.esc(item.get("enabled")))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(item.get("on_calendar")))
                body += _ui_html("<td><form method='post' style='display:inline' onsubmit=\"return confirm('Zeitplan löschen?')\">")
                body += _ui_html("<input type='hidden' name='action' value='delete'>")
                body += _ui_html("<input type='hidden' name='profile' value='{}'>").format(ctx.esc(item.get("profile")))
                body += _ui_html("<button class='btn err' type='submit'>Löschen</button></form></td>")
                body += _ui_html("</tr>")
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Systemd</h3><pre>{}</pre></div>").format(
            ctx.esc(sh("systemctl list-timers --all --no-pager 'server-manager-appbackup-*' 2>&1 || true", timeout=15).get("stdout", ""))
        )

        return ctx.page("Backup-Zeitplan " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/runs")
    def apps_backup_runs(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        runs = []
        if root.exists():
            runs = sorted([x for x in root.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)

        body = _ui_html("<div class='card'><h2>Backup-Runs: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}'>App</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/backup/import'>Backup importieren</a></p></div>").format(ctx.esc(m.app_id))

        body += _ui_html("<div class='card'><h3>Läufe</h3>")
        if not runs:
            body += _ui_html("<p class='warn'>Keine Backup-Runs gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>Run</th><th>Profil</th><th>Status</th><th>Archiv</th><th>Aktion</th></tr>")
            for rdir in runs[:30]:
                session_file = rdir / "session.json"
                result_file = rdir / "result.json"
                state = "unbekannt"
                archive = ""
                profile = "—"
                if session_file.exists():
                    try:
                        data = json.loads(session_file.read_text(encoding="utf-8"))
                        state = data.get("state", "unbekannt")
                        archive = data.get("archive", "")
                        profile = _profile_label(data)
                    except Exception:
                        state = "nicht lesbar"
                elif result_file.exists():
                    try:
                        data = json.loads(result_file.read_text(encoding="utf-8"))
                        state = "completed" if data.get("ok") else "failed"
                        archive = data.get("archive", "")
                        profile = _profile_label(data)
                    except Exception:
                        state = "nicht lesbar"

                cls = {
                    "completed": "ok",
                    "failed": "err",
                    "created": "warn",
                    "collecting": "warn",
                    "config": "warn",
                    "data": "warn",
                    "database": "warn",
                    "extra": "warn",
                    "archive": "warn",
                }.get(state, "")

                body += (
                    _ui_html("<tr><td><code>{}</code></td><td>{}</td><td class='{}'>{}</td><td><code>{}</code></td><td>"
                    "<a class='btn' href='/apps/{}/backup/runs/{}'>Öffnen</a> "
                    "<form method='post' action='/apps/{}/backup/runs/{}/delete' style='display:inline' "
                    "onsubmit=\"return confirm('Backup-Run wirklich löschen?')\">"
                    "<button class='btn err' type='submit'>Löschen</button></form>"
                    "</td></tr>")
                ).format(
                    ctx.esc(rdir.name),
                    ctx.esc(profile),
                    cls,
                    ctx.esc(_ui_text(state)),
                    ctx.esc(archive),
                    ctx.esc(m.app_id),
                    ctx.esc(rdir.name),
                    ctx.esc(m.app_id),
                    ctx.esc(rdir.name),
                )
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        return ctx.page("Backup-Runs " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/runs/<run_id>/delete", methods=["POST"])
    def apps_backup_run_delete(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        import re

        if not (
            re.match(r"^\\d{4}-\\d{2}-\\d{2}_\\d{2}-\\d{2}-\\d{2}$", run_id)
            or run_id.startswith("imported_")
        ):
            return ctx.page(
                _ui_text("Ungültiger Backup-Run"),
                _ui_html("<div class='card'><h2>Ungültiger Backup-Run</h2><p class='err'>Sonderverzeichnisse dürfen nicht gelöscht werden.</p></div>"),
                "Apps",
            ), 400

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        run_dir = root / run_id

        try:
            run_dir.resolve().relative_to(root.resolve())
        except Exception:
            return ctx.page(_ui_text("Ungültiger Backup-Run"), _ui_html("<div class='card'><h2>Ungültiger Backup-Run</h2></div>"), "Apps"), 400

        if not run_dir.exists() or not run_dir.is_dir():
            return ctx.page(_ui_text("Backup-Run nicht gefunden"), _ui_html("<div class='card'><h2>Backup-Run nicht gefunden</h2></div>"), "Apps"), 404

        deleted = []
        errors = []
        archive_paths = []

        for jf in [run_dir / "result.json", run_dir / "session.json"]:
            try:
                if jf.exists():
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    archive = data.get("archive")
                    if archive:
                        ap = Path(archive)
                        try:
                            ap.resolve().relative_to(root.resolve())
                            archive_paths.append(ap)
                        except Exception:
                            pass
            except Exception:
                pass

        archive_paths.append(root / (run_id + ".tar.gz"))

        for ap in sorted(set(archive_paths)):
            for fp in [ap, Path(str(ap) + ".sha256")]:
                try:
                    if fp.exists() and fp.is_file():
                        fp.unlink()
                        deleted.append(str(fp))
                except Exception as e:
                    errors.append("{}: {}".format(str(fp), str(e)))

        try:
            shutil.rmtree(run_dir)
            deleted.append(str(run_dir))
        except Exception as e:
            errors.append("{}: {}".format(str(run_dir), str(e)))

        body = _ui_html("<div class='card'><h2>Backup löschen: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs'>Zurück zu Backup-Runs</a></p>").format(ctx.esc(m.app_id))

        if errors:
            body += _ui_html("<p class='err'><b>Backup wurde nicht vollständig gelöscht.</b></p><ul>")
            for e in errors:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul>")
        else:
            body += _ui_html("<p class='ok'><b>Backup gelöscht.</b></p>")

        if deleted:
            body += _ui_html("<h3>Gelöscht</h3><ul>")
            for d in deleted:
                body += _ui_html("<li><code>{}</code></li>").format(ctx.esc(d))
            body += _ui_html("</ul>")

        body += _ui_html("</div>")
        return ctx.page("Backup gelöscht " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/backup/runs/<run_id>/download")
    def apps_backup_run_download(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / run_id
        result_file = run_dir / "result.json"

        if not result_file.exists():
            return ctx.page(_ui_text("Backup-Ergebnis fehlt"), _ui_html("<div class='card'><h2>Backup-Ergebnis fehlt</h2></div>"), "Apps"), 404

        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception as e:
            return ctx.page(_ui_text("Backup-Ergebnis fehlerhaft"), _ui_html("<div class='card'><h2>Backup-Ergebnis fehlerhaft</h2><pre>{}</pre></div>").format(ctx.esc(str(e))), "Apps"), 500

        archive = Path(result.get("archive", ""))
        if not archive.exists() or not archive.is_file():
            return ctx.page(_ui_text("Archiv nicht gefunden"), _ui_html("<div class='card'><h2>Archiv nicht gefunden</h2></div>"), "Apps"), 404

        return send_file(
            archive,
            as_attachment=True,
            download_name=archive.name,
        )


    @app.route("/apps/<app_id>/backup/runs/<run_id>")
    def apps_backup_run_detail(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / run_id
        if not run_dir.exists() or not run_dir.is_dir():
            return ctx.page(_ui_text("Backup-Run nicht gefunden"), _ui_html("<div class='card'><h2>Backup-Run nicht gefunden</h2></div>"), "Apps"), 404

        session_file = run_dir / "session.json"
        result_file = run_dir / "result.json"
        manifest_file = run_dir / "manifest.json"

        session = {}
        result = {}
        manifest = {}

        if session_file.exists():
            try:
                session = json.loads(session_file.read_text(encoding="utf-8"))
            except Exception as e:
                session = {"ok": False, "error": str(e)}

        if result_file.exists():
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception as e:
                result = {"ok": False, "error": str(e)}

        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception as e:
                manifest = {"ok": False, "error": str(e)}

        state = session.get("state") or ("completed" if result.get("ok") else "unknown")
        if state=="completed" and (session.get("statistics") or {}).get("failed"):state="failed"
        state_text = {
            "created": "Vorbereitet",
            "collecting": "Metadaten werden gesichert",
            "config": "Konfiguration wird gesichert",
            "data": "Daten werden gesichert",
            "database": "Datenbank wird gesichert",
            "extra": "Zusatzinformationen werden gesichert",
            "archive": "Archiv wird erstellt",
            "completed": "Abgeschlossen",
            "failed": "Fehler",
            "blocked": "Blockiert",
            "unknown": "Unbekannt",
        }.get(state, state)

        cls = {
            "completed": "ok",
            "failed": "err",
            "blocked": "err",
            "created": "warn",
            "collecting": "warn",
            "config": "warn",
            "data": "warn",
            "database": "warn",
            "extra": "warn",
            "archive": "warn",
        }.get(state, "")

        body = ""
        body += _ui_html("<div class='card'><h2>Backup-Run: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/backup/runs'>Zurück zu Runs</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}'>App</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<form method='post' action='/apps/{}/backup/runs/{}/delete' style='display:inline' onsubmit=\"return confirm('Backup-Run wirklich löschen?')\">").format(ctx.esc(m.app_id), ctx.esc(run_id))
        body += _ui_html("<button class='btn err' type='submit'>Backup löschen</button></form></p>")
        body += _ui_html("<p>Run: <code>{}</code></p></div>").format(ctx.esc(run_id))

        archive = session.get("archive") or result.get("archive", "")
        archive_name = Path(archive).name if archive else "—"
        archive_size = result.get("archive_size", "—")

        body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
        body += _ui_html("<p>Status: <b id='run-summary-state' class='{}'>{}</b><br>Profil: <code>{}</code><br>Archiv: <code id='run-summary-archive'>{}</code><br>Größe: <code id='run-summary-size'>{}</code><br>Arbeitsverzeichnis: <code id='run-summary-workdir'>{}</code></p>").format(
            cls,
            ctx.esc(_ui_text(state_text)),
            ctx.esc(_profile_label(session or result)),
            ctx.esc(archive_name),
            ctx.esc(_display(archive_size)),
            ctx.esc(session.get("work_dir") or result.get("work_dir", "")),
        )
        body += _ui_html("</div>")

        if session:
            body += _live_session_widget(ctx, "backup", m.app_id, run_id)

            stats = session.get("statistics") or {}
            done,total,percent,_ = _session_progress_values(session, "backup")

            body += _ui_html("<div class='card'><h3>Fortschritt nach Arbeitsschritten</h3>")
            body += _ui_html("<p><b>{}%</b> — {} von {} Schritten</p>").format(
                ctx.esc(str(percent)),
                ctx.esc(str(done)),
                ctx.esc(str(total)),
            )
            body += "<progress value='{}' max='100' style='width:100%'></progress>".format(ctx.esc(str(percent)))
            body += _ui_html("</div>")

            body += _ui_html("<div class='card'><h3>Backup-Session</h3>")
            body += _ui_html("<p>Aktueller Schritt: <code>{}</code><br>Aktion: <code>{}</code><br>Start: <code>{}</code><br>Update: <code>{}</code><br>Ende: <code>{}</code></p>").format(
                ctx.esc(_display(session.get("current_step"))),
                ctx.esc(_display(session.get("current_action"))),
                ctx.esc(_display(session.get("started_at"))),
                ctx.esc(_display(session.get("updated_at"))),
                ctx.esc(_display(session.get("finished_at"))),
            )

            body += _ui_html("<table><tr><th>Gesamt</th><th>OK</th><th>Fehler</th><th>Blockiert</th><th>Übersprungen</th><th>Simuliert</th></tr>")
            body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr></table>").format(
                ctx.esc(str(stats.get("total", 0))),
                ctx.esc(str(stats.get("ok", 0))),
                ctx.esc(str(stats.get("failed", 0))),
                ctx.esc(str(stats.get("blocked", 0))),
                ctx.esc(str(stats.get("skipped", 0))),
                ctx.esc(str(stats.get("simulated", 0))),
            )

            steps = session.get("steps") or []
            if steps:
                body += _ui_html("<h4>Schritte</h4>")
                body += _ui_html("<table><tr><th>#</th><th>Schritt</th><th>Aktion</th><th>Status</th><th>Geändert</th><th>Meldung</th></tr>")
                for st in steps:
                    status = st.get("status", "")
                    scls = "ok" if status == "executed" else ("err" if status == "failed" else ("warn" if status == "blocked" else ""))
                    body += _ui_html("<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td class='{}'>{}</td><td>{}</td><td>{}</td></tr>").format(
                        ctx.esc(_display(st.get("order"))),
                        ctx.esc(_ui_text(_display(st.get("title")))),
                        ctx.esc(_display(st.get("action"))),
                        scls,
                        ctx.esc(_status_text(status)),
                        ctx.esc(_yes_no(st.get("changed"))),
                        ctx.esc(_ui_text(_display(st.get("message")))),
                    )
                body += _ui_html("</table>")

            body += _ui_html("</div>")

        if result:
            body += _backup_archive_card(ctx, m, run_id, result)
            body += _ui_html("<div class='card'><h3>Backup-Inhalt</h3>")
            body += _ui_html("</div>")
            body += _backup_content_dashboard(ctx, result)

        if session:
            body += _details_card(ctx, "Session JSON", session)
        if result:
            body += _details_card(ctx, "Result JSON", result)
        if manifest:
            body += _details_card(ctx, "Manifest JSON", manifest)

        return ctx.page("Backup-Run " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/restore")
    def apps_restore_readiness(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        backups = []
        if root.exists():
            backups = sorted([x for x in root.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)

        selected = request.args.get("backup", "")
        selected_path = None

        if selected:
            cand = root / selected
            if cand.exists() and cand.is_dir():
                selected_path = cand

        if not selected_path and backups:
            selected_path = backups[0]

        body = _ui_html("<div class='card'><h2>Restore-Prüfung: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}'>Zurück</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='pill' href='/api/apps/{}'>JSON</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p><b>Read-only:</b> Es wird nichts zurückgespielt.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Backups</h3>")
        if not backups:
            body += _ui_html("<p class='warn'>Keine Backups gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>Backup</th><th>Aktion</th></tr>")
            for b in backups[:20]:
                active = " active" if selected_path and b.name == selected_path.name else ""
                body += _ui_html("<tr><td><code>{}</code></td><td><a class='btn{}' href='/apps/{}/restore?backup={}'>Prüfen</a> <a class='btn' href='/apps/{}/restore/plan?backup={}'>Plan</a></td></tr>").format(
                    ctx.esc(b.name), active, ctx.esc(m.app_id), ctx.esc(b.name), ctx.esc(m.app_id), ctx.esc(b.name)
                )
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        if selected_path:
            data = _safe_call(lambda: run_restore_check(m, str(selected_path)), "restore_readiness")
            data = _normalize_restore_readiness(data)

            body += _restore_backup_dashboard(ctx, selected_path, data) or ""
            body += _restore_readiness_dashboard(ctx, data)

            dbcmd = (((data.get("backup") or {}).get("details") or {}).get("restore") or {}).get("database_command")
            if dbcmd:
                body += _ui_html("<div class='card'><h3>Datenbank-Restore</h3>")
                body += _ui_html("<pre>{}</pre>").format(ctx.esc(dbcmd))
                body += _ui_html("</div>")

            body += _details_card(ctx, "Restore JSON", data)

        return ctx.page("Restore " + m.label, body, "Apps")

    @app.route("/apps/<app_id>/restore/plan")
    def apps_restore_plan(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        selected = request.args.get("backup", "")
        selected_path = None

        if selected:
            cand = root / selected
            if cand.exists() and cand.is_dir():
                selected_path = cand

        if not selected_path:
            backups = []
            if root.exists():
                backups = sorted([x for x in root.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)
            if backups:
                selected_path = backups[0]

        body = _ui_html("<div class='card'><h2>Restore-Plan: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore'>Zurück zur Restore-Prüfung</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}'>App</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p><b>Dry-Run:</b> Es wird nichts verändert oder zurückgespielt.</p>")
        body += _ui_html("<form method='post' action='/apps/{}/restore/noop?backup={}' style='display:inline' onsubmit=\"return confirm('No-Op Restore simulieren? Es wird nichts geändert.')\">").format(ctx.esc(m.app_id), ctx.esc(selected_path.name if selected_path else ""))
        body += _ui_html("<button class='btn' type='submit'>No-Op ausführen</button></form> ")
        body += _ui_html("<form method='post' action='/apps/{}/restore/prepare?backup={}' style='display:inline' onsubmit=\"return confirm('Rollback-Punkt erzeugen? Es wird noch kein Restore ausgeführt.')\">").format(ctx.esc(m.app_id), ctx.esc(selected_path.name if selected_path else ""))
        body += _ui_html("<button class='btn' type='submit'>Rollback vorbereiten</button></form> ")
        body += _ui_html("<form method='post' action='/apps/{}/restore/execute?backup={}' style='display:inline' onsubmit=\"return confirm('ACHTUNG: Restore würde Daten überschreiben. Aktuell ist die Ausführung per Feature-Flag blockiert. Fortfahren?')\">").format(ctx.esc(m.app_id), ctx.esc(selected_path.name if selected_path else ""))
        body += _ui_html("<input name='confirm_token' placeholder='RESTORE eingeben' autocomplete='off' style='width:160px'> ")
        body += _ui_html("<button class='btn err' type='submit'>Restore ausführen</button></form> ")
        body += _ui_html("<a class='btn' href='/apps/{}/restore/runs'>Restore-Runs</a>").format(ctx.esc(m.app_id))
        body += _ui_html("</div>")

        if not selected_path:
            body += _ui_html("<div class='card'><p class='warn'>Kein Backup gefunden.</p></div>")
            return ctx.page("Restore-Plan " + m.label, body, "Apps")

        data = _safe_call(lambda: run_restore_plan(m, str(selected_path)), "restore_plan")
        summary = data.get("summary") or {}
        readiness = data.get("readiness") or {}

        possible = "ja" if data.get("restore_possible") else "nein"
        score = readiness.get("score", "?")
        level = readiness.get("level", "unknown")
        cls = "ok" if data.get("restore_possible") else "err"
        if level == "warning":
            cls = "warn"

        body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
        body += _ui_html("<p>Backup: <code>{}</code></p>").format(ctx.esc(str(selected_path)))
        body += _ui_html("<p>Score: <b class='{}'>{}</b> / 100<br>Level: <code>{}</code><br>Restore möglich: <b class='{}'>{}</b></p>").format(
            cls, ctx.esc(score), ctx.esc(level), cls, ctx.esc(possible)
        )
        body += _ui_html("<p>Config-Dateien: <b>{}</b><br>Datenpfade: <b>{}</b><br>Datenbank-Restore: <b>{}</b><br>Risiko: <code>{}</code><br>Dauer: <code>{}</code></p>").format(
            ctx.esc(summary.get("config_files", 0)),
            ctx.esc(summary.get("data_paths", 0)),
            ctx.esc(_ui_text("ja") if summary.get("database_restore") else _ui_text("nein")),
            ctx.esc(summary.get("risk", "")),
            ctx.esc(summary.get("estimated_duration", "")),
        )
        body += _ui_html("</div>")

        warnings = data.get("warnings") or []
        errors = data.get("errors") or []

        if errors:
            body += _ui_html("<div class='card'><h3>Fehler</h3><ul>")
            for e in errors:
                body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
            body += _ui_html("</ul></div>")

        if warnings:
            body += _ui_html("<div class='card'><h3>Warnungen</h3><ul>")
            for w in warnings:
                body += _ui_html("<li class='warn'>{}</li>").format(ctx.esc(w))
            body += _ui_html("</ul></div>")

        body += _ui_html("<div class='card'><h3>Restore-Schritte</h3>")
        body += _ui_html("<table><tr><th>#</th><th>Schritt</th><th>Risiko</th><th>Befehl / Details</th></tr>")
        for step in data.get("steps") or []:
            risk = step.get("risk", "")
            rcls = "err" if risk == "high" else ("warn" if risk == "medium" else "ok")
            detail = ""
            if step.get("command"):
                detail += _ui_html("<pre>{}</pre>").format(ctx.esc(step.get("command")))

            det = step.get("details") or {}
            files = det.get("files") or []
            paths = det.get("paths") or []
            if files:
                detail += _ui_html("<p><b>Dateien:</b></p><ul>")
                for f in files:
                    detail += _ui_html("<li><code>{}</code> → <code>{}</code></li>").format(
                        ctx.esc(f.get("backup_file", "")), ctx.esc(f.get("target_file", ""))
                    )
                detail += _ui_html("</ul>")
            if paths:
                detail += _ui_html("<p><b>Datenpfade:</b></p><ul>")
                for pth in paths:
                    detail += _ui_html("<li><code>{}</code> → <code>{}</code></li>").format(
                        ctx.esc(pth.get("backup_path", "")), ctx.esc(pth.get("target_path", ""))
                    )
                detail += _ui_html("</ul>")

            body += _ui_html("<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td></tr>").format(
                ctx.esc(step.get("order")),
                ctx.esc(step.get("title")),
                rcls,
                ctx.esc(risk),
                detail,
            )
        body += _ui_html("</table></div>")

        body += _card(ctx, "Restore Plan JSON", _pre(ctx, data))
        return ctx.page("Restore-Plan " + m.label, body, "Apps")

    @app.route("/apps/<app_id>/restore/noop", methods=["POST"])
    def apps_restore_noop(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        selected = request.form.get("backup", "") or request.args.get("backup", "")
        selected_path = None

        if selected:
            cand = root / selected
            if cand.exists() and cand.is_dir():
                selected_path = cand

        if not selected_path:
            return ctx.page(
                _ui_text("Kein Backup ausgewählt"),
                _ui_html("<div class='card'><h2>Kein gültiges Backup ausgewählt</h2></div>"),
                "Apps",
            ), 400

        data = _safe_call(lambda: execute_restore(m, str(selected_path), mode="noop"), "restore_noop")

        body = _ui_html("<div class='card'><h2>No-Op Restore: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore/plan?backup={}'>Zurück zum Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(selected_path.name))
        body += _ui_html("<a class='btn' href='/apps/{}/restore/runs'>Restore-Runs</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p><b>Es wurden keine Änderungen ausgeführt.</b></p>")
        steps = data.get("steps") or []
        if steps:
            body += _ui_html("<h3>Simulationsschritte</h3>")
            body += _ui_html("<table><tr><th>#</th><th>Schritt</th><th>Status</th></tr>")
            for step in steps:
                body += _ui_html("<tr>")
                body += _ui_html("<td>{}</td>").format(ctx.esc(step.get("order")))
                body += _ui_html("<td>{}</td>").format(ctx.esc(_ui_text(step.get("label"))))
                body += _ui_html("<td>{}</td>").format(ctx.esc(_ui_text(step.get("status"))))
                body += _ui_html("</tr>")
            body += _ui_html("</table>")


        if not data.get("started"):
            body += _ui_html("<p>Run-ID: <code>{}</code><br>Run-Verzeichnis: <code>{}</code></p>").format(
                ctx.esc(data.get("run_id", "")),
                ctx.esc(data.get("run_dir", "")),
            )
        body += _ui_html("</div>")

        body += _card(ctx, "No-Op Ergebnis", _pre(ctx, data))
        return ctx.page("No-Op Restore " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/restore/prepare", methods=["POST"])
    def apps_restore_prepare(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        selected = request.form.get("backup", "") or request.args.get("backup", "")
        selected_path = None

        if selected:
            cand = root / selected
            if cand.exists() and cand.is_dir():
                selected_path = cand

        if not selected_path:
            return ctx.page(
                _ui_text("Kein Backup ausgewählt"),
                _ui_html("<div class='card'><h2>Kein gültiges Backup ausgewählt</h2></div>"),
                "Apps",
            ), 400

        data = _safe_call(lambda: execute_restore(m, str(selected_path), mode="prepare"), "restore_prepare")
        rollback = (data.get("rollback") or {}).get("result") or {}

        body = _ui_html("<div class='card'><h2>Rollback-Punkt vorbereitet: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore/plan?backup={}'>Zurück zum Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(selected_path.name))
        body += _ui_html("<a class='btn' href='/apps/{}/restore/runs'>Restore-Runs</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p><b>Es wurde nur ein Rollback-Backup erzeugt. Restore wurde nicht ausgeführt.</b></p>")
        if not data.get("started"):
            body += _ui_html("<p>Run-ID: <code>{}</code><br>Run-Verzeichnis: <code>{}</code></p>").format(
                ctx.esc(data.get("run_id", "")),
                ctx.esc(data.get("run_dir", "")),
            )

        if rollback.get("ok"):
            body += _ui_html("<p class='ok'><b>Rollback-Backup erfolgreich erzeugt.</b></p>")
            backup = rollback.get("backup") or {}
            if backup.get("archive"):
                body += _ui_html("<p>Archiv: <code>{}</code><br>Größe: <code>{}</code></p>").format(
                    ctx.esc(backup.get("archive", "")),
                    ctx.esc(backup.get("archive_size", "")),
                )
        else:
            body += _ui_html("<p class='err'><b>Rollback-Backup fehlgeschlagen.</b></p>")

        body += _ui_html("</div>")

        body += _card(ctx, "Prepare Ergebnis", _pre(ctx, data))
        return ctx.page("Prepare Restore " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/restore/execute", methods=["POST"])
    def apps_restore_execute(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(DEFAULT_BACKUP_ROOT) / m.app_id
        selected = request.form.get("backup", "") or request.args.get("backup", "")
        selected_path = None

        if selected:
            cand = root / selected
            if cand.exists() and cand.is_dir():
                selected_path = cand

        if not selected_path:
            return ctx.page(
                _ui_text("Kein Backup ausgewählt"),
                _ui_html("<div class='card'><h2>Kein gültiges Backup ausgewählt</h2></div>"),
                "Apps",
            ), 400

        confirm_token = request.form.get("confirm_token", "")
        data = _safe_call(lambda: execute_restore(m, str(selected_path), mode="execute", confirm_token=confirm_token), "restore_execute")

        body = _ui_html("<div class='card'><h2>Restore-Ausführung: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore/plan?backup={}'>Zurück zum Plan</a> ").format(ctx.esc(m.app_id), ctx.esc(selected_path.name))
        body += _ui_html("<a class='btn' href='/apps/{}/restore/runs'>Restore-Runs</a></p>").format(ctx.esc(m.app_id))

        if data.get("blocked"):
            body += _ui_html("<p class='err'><b>BLOCKIERT</b></p>")
            body += _ui_html("<p>Restore-Ausführung ist per Feature-Flag deaktiviert.</p>")
            body += _ui_html("<p><b>Es wurden keinerlei Änderungen vorgenommen.</b></p>")
        elif data.get("ok"):
            body += _ui_html("<p class='ok'><b>Restore erfolgreich.</b></p>")
        else:
            body += _ui_html("<p class='err'><b>Restore fehlgeschlagen.</b></p>")

        if not data.get("started"):
            body += _ui_html("<p>Run-ID: <code>{}</code><br>Run-Verzeichnis: <code>{}</code></p>").format(
                ctx.esc(data.get("run_id", "")),
                ctx.esc(data.get("run_dir", "")),
            )
        body += _ui_html("</div>")

        body += _card(ctx, "Execute Ergebnis", _pre(ctx, data))
        return ctx.page("Restore Execute " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/restore/runs")
    def apps_restore_runs(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        root = Path(RESTORE_LOG_ROOT) / m.app_id
        runs = []
        if root.exists():
            runs = sorted([x for x in root.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)

        body = _ui_html("<div class='card'><h2>Restore-Runs: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore'>Zurück zur Restore-Prüfung</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}'>App</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Läufe</h3>")
        if not runs:
            body += _ui_html("<p class='warn'>Keine Restore-Runs gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>Run</th><th>Status</th><th>Modus</th><th>Aktion</th></tr>")
            for r in runs[:30]:
                result_file = r / "result.json"
                status = "unbekannt"
                mode = ""
                if result_file.exists():
                    try:
                        data = json.loads(result_file.read_text(encoding="utf-8"))
                        status = "OK" if data.get("ok") else "Fehler"
                        mode = data.get("mode", "")
                    except Exception:
                        status = "nicht lesbar"
                body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td><code>{}</code></td><td><a class='btn' href='/apps/{}/restore/runs/{}'>Öffnen</a></td></tr>").format(
                    ctx.esc(r.name), ctx.esc(_ui_text(status)), ctx.esc(mode), ctx.esc(m.app_id), ctx.esc(r.name)
                )
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        return ctx.page("Restore-Runs " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/restore/runs/<run_id>")
    def apps_restore_run_detail(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps",
            ), 404

        run_dir = Path(RESTORE_LOG_ROOT) / m.app_id / run_id
        result_file = run_dir / "result.json"
        plan_file = run_dir / "plan.json"

        body = _ui_html("<div class='card'><h2>Restore-Run: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/restore/runs'>Zurück zu Runs</a></p>").format(ctx.esc(m.app_id))
        body += _ui_html("<p>Run: <code>{}</code></p>").format(ctx.esc(run_id))
        body += _ui_html("</div>")

        if not run_dir.exists():
            body += _ui_html("<div class='card'><p class='err'>Run nicht gefunden.</p></div>")
            return ctx.page("Restore-Run " + m.label, body, "Apps"), 404

        session_file = run_dir / "session.json"

        if session_file.exists():
            try:
                session = json.loads(session_file.read_text(encoding="utf-8"))
            except Exception as e:
                session = {"ok": False, "error": str(e)}

            body += _live_session_widget(ctx, "restore", m.app_id, run_id)

            state = session.get("state", "")
            cls = {
                "completed": "ok",
                "blocked": "warn",
                "failed": "err",
            }.get(state, "")

            body += _ui_html("<div class='card'><h3>Restore-Session</h3>")
            body += _ui_html("<p>State: <b class='{}'>{}</b><br>Mode: <code>{}</code><br>Backup: <code>{}</code></p>").format(
                cls,
                ctx.esc(_ui_text(state)),
                ctx.esc(session.get("mode", "")),
                ctx.esc(session.get("backup", "")),
            )

            stats = session.get("statistics") or {}
            body += _ui_html("<table><tr><th>Gesamt</th><th>OK</th><th>Fehler</th><th>Blockiert</th><th>Übersprungen</th><th>Simuliert</th></tr>")
            body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr></table>").format(
                stats.get("total", 0),
                stats.get("ok", 0),
                stats.get("failed", 0),
                stats.get("blocked", 0),
                stats.get("skipped", 0),
                stats.get("simulated", 0),
            )

            body += _pre(ctx, session)
            body += _ui_html("</div>")

        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception as e:
                data = {"ok": False, "error": str(e)}

            cls = "ok" if data.get("ok") else "err"
            if data.get("blocked"):
                cls = "warn"

            body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
            body += _ui_html("<p>Status: <b class='{}'>{}</b><br>Modus: <code>{}</code><br>Blocked: <code>{}</code></p>").format(
                cls,
                ctx.esc(_ui_text("OK") if data.get("ok") else (_ui_text("BLOCKIERT") if data.get("blocked") else _ui_text("FEHLER"))),
                ctx.esc(data.get("mode", "")),
                ctx.esc(data.get("blocked", False)),
            )
            body += _ui_html("<p>Backup: <code>{}</code></p>").format(ctx.esc(data.get("backup_dir", "")))

            readiness = data.get("readiness") or {}
            if readiness:
                body += _ui_html("<p>Readiness: <b>{}</b>/100<br>Level: <code>{}</code></p>").format(
                    ctx.esc(readiness.get("score", "")),
                    ctx.esc(readiness.get("level", "")),
                )

            pre = data.get("preconditions") or {}
            if pre:
                body += _ui_html("<h4>Vorbedingungen</h4>")
                body += _ui_html("<p>OK: <code>{}</code></p>").format(ctx.esc(pre.get("ok")))
                if pre.get("errors"):
                    body += _ui_html("<ul>")
                    for e in pre.get("errors") or []:
                        body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
                    body += _ui_html("</ul>")

            rollback = data.get("rollback") or {}
            if rollback:
                body += _ui_html("<h4>Rollback</h4>")
                body += _ui_html("<p>Mode: <code>{}</code><br>Ziel: <code>{}</code></p>").format(
                    ctx.esc(rollback.get("mode", "")),
                    ctx.esc(rollback.get("target_dir", "")),
                )
                rbres = rollback.get("result") or {}
                if rbres:
                    rbcls = "ok" if rbres.get("ok") else "err"
                    body += _ui_html("<p>Rollback-Backup: <b class='{}'>{}</b></p>").format(
                        rbcls,
                        ctx.esc(_ui_text("OK") if rbres.get("ok") else _ui_text("Fehler")),
                    )
                    backup = rbres.get("backup") or {}
                    if backup.get("archive"):
                        body += _ui_html("<p>Archiv: <code>{}</code><br>Größe: <code>{}</code></p>").format(
                            ctx.esc(backup.get("archive", "")),
                            ctx.esc(backup.get("archive_size", "")),
                        )

            if data.get("errors"):
                body += _ui_html("<h4>Fehler</h4><ul>")
                for e in data.get("errors") or []:
                    body += _ui_html("<li class='err'>{}</li>").format(ctx.esc(e))
                body += _ui_html("</ul>")

            if data.get("warnings"):
                body += _ui_html("<h4>Warnungen</h4><ul>")
                for w in data.get("warnings") or []:
                    body += _ui_html("<li class='warn'>{}</li>").format(ctx.esc(w))
                body += _ui_html("</ul>")

            steps = data.get("steps") or []
            if steps:
                body += _ui_html("<h4>Schritte</h4><table><tr><th>#</th><th>Aktion</th><th>Status</th><th>Handler</th><th>Geändert</th></tr>")
                for st in steps:
                    scls = "ok" if st.get("status") in ("executed", "simulated") else "warn"
                    if st.get("status") in ("failed", "blocked"):
                        scls = "err"
                    body += _ui_html("<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td><code>{}</code></td><td>{}</td></tr>").format(
                        ctx.esc(st.get("order", "")),
                        ctx.esc(st.get("title", "")),
                        scls,
                        ctx.esc(_ui_text(st.get("status", ""))),
                        ctx.esc(st.get("handler", "")),
                        ctx.esc(st.get("changed", False)),
                    )
                body += _ui_html("</table>")

            body += _ui_html("</div>")
            body += _card(ctx, "Result JSON", _pre(ctx, data))

        if plan_file.exists():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception as e:
                plan = {"ok": False, "error": str(e)}
            body += _card(ctx, "Plan", _pre(ctx, plan))

        return ctx.page("Restore-Run " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/update")
    def apps_update_plan(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        data = _safe_call(lambda: run_update_plan(m), "update_plan")
        summary = data.get("summary") or {}

        body = _ui_html("<div class='card'><h2>Update-Plan: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        if m.app_id == "comfyui":
            body = _ui_html("<div class='card'><h2>ComfyUI · Update & Stable</h2><p><a class='btn active' href='/apps/comfyui/update' aria-current='page'>Update</a> <a class='btn' href='/apps/comfyui/stable-switch'>Stable-Version</a></p><p>Update prüfen und vorbereiten oder unter „Stable-Version“ gezielt auf den ermittelten Stable-Release wechseln. Beide Wege behalten ihre jeweiligen Sicherungen und Bestätigungen.</p><h3>Update-Plan</h3>")

        body += _ui_html("<p><a class='btn' href='/apps/{}'>Zurück</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/update/runs'>Update-Runs</a></p>").format(ctx.esc(m.app_id))
        execution_enabled_live = bool(summary.get("execution_enabled"))
        requires_backup_live = bool(summary.get("requires_backup", True))

        body += _ui_html("<p><b>Modus:</b> Vorbereitung, Simulation oder freigegebener Echtlauf</p>")

        body += _ui_html("<form method='post' action='/apps/{}/update/prepare' style='display:inline' onsubmit=\"return confirm('Pre-Update-Backup jetzt erstellen?')\">").format(ctx.esc(m.app_id))
        body += _ui_html("<button class='btn' type='submit'>Backup vorbereiten</button></form> ")

        body += _ui_html("<form method='post' action='/apps/{}/update/execute' style='display:inline' onsubmit=\"return confirm('Update-Simulation starten? Es werden keine Änderungen durchgeführt.')\">").format(ctx.esc(m.app_id))
        body += _ui_html("<input type='hidden' name='confirm_token' value='SIMULATE'>")
        body += _ui_html("<button class='btn active' type='submit'>Update simulieren</button></form> ")

        body += _ui_html("<hr><h3>Echtes Update</h3>")

        guard = data.get("update_guard") or {}

        if guard.get("blocked"):

            body += _ui_html("<div class='card' style='border-left:5px solid #dc2626'>")
            body += _ui_html("<p class='err'><b>⚠ Update-Ausführung deaktiviert</b></p>")

            if guard.get("message"):
                body += _ui_html("<p><b>Grund:</b><br>{}</p>").format(
                    ctx.esc(_ui_text(guard.get("message")))
                )

            details = guard.get("details") or []

            if details:
                body += _ui_html("<p><b>Details:</b></p><ul>")

                for item in details:
                    if isinstance(item, dict):
                        body += _ui_html("<li><code>{}={}</code></li>").format(
                            ctx.esc(item.get("key", "")),
                            ctx.esc(item.get("value", "")),
                        )
                    else:
                        body += _ui_html("<li>{}</li>").format(
                            ctx.esc(str(item))
                        )

                body += _ui_html("</ul>")

            if guard.get("recommendation"):
                body += _ui_html("<p><b>Empfehlung:</b><br>{}</p>").format(
                    ctx.esc(guard.get("recommendation"))
                )

            if requires_backup_live:
                body += (
                    _ui_html("<p class='warn'><b>Vor einem echten Update muss zuerst "
                    "ein Pre-Update-Backup erzeugt werden.</b></p>")
                )
                body += (
                    _ui_html("<p>Nach erfolgreichem „Backup vorbereiten“ wird der "
                    "Echtlauf auf der Prepare-Seite fest an diesen "
                    "Backup-Run gebunden.</p>")
                )
            else:
                body += _ui_html("<p>Manuelle Freigabe mit Update-Token:</p>")
                body += "<form method='post' action='/apps/{}/update/execute' style='display:inline' ".format(ctx.esc(m.app_id))
                body += _ui_html("onsubmit=\"return confirm('Gepinnte Version erkannt. Update trotzdem ausführen?')\">")
                body += _ui_html("<input type='password' name='confirm_token' placeholder='UPDATE-Token eingeben' autocomplete='off' style='width:220px'> ")
                body += _ui_html("<button class='btn err' type='submit'>Update freigeben</button></form>")

            body += _ui_html("</div>")

        elif execution_enabled_live:

            if requires_backup_live:
                body += (
                    _ui_html("<p class='warn'><b>Für diese App ist vor dem echten "
                    "Update ein gebundenes Pre-Update-Backup erforderlich.</b></p>")
                )
                body += (
                    _ui_html("<p>Bitte oben „Backup vorbereiten“ wählen. "
                    "Nach erfolgreichem Prepare erscheint dort der "
                    "freigegebene Echtlauf mit gebundener Prepare-Run-ID.</p>")
                )
            else:
                body += _ui_html("<p class='warn'>Führt ein echtes Update aus. Preflight und Execution Gate müssen erfolgreich sein.</p>")
                body += _ui_html("<form method='post' action='/apps/{}/update/execute' style='display:inline' onsubmit=\"return confirm('ECHTES Update wirklich starten?')\">").format(ctx.esc(m.app_id))
                body += _ui_html("<input type='password' name='confirm_token' placeholder='Update-Token eingeben' autocomplete='off' style='width:220px'> ")
                body += _ui_html("<button class='btn err' type='submit'>Update ausführen</button></form>")

        else:
            body += _ui_html("<span class='warn'>Echtlauf deaktiviert</span>")

        body += _ui_html("</div>")

        guard = data.get("update_guard") or {}

        if guard:

            body += _ui_html("<div class='card' style='border-left:5px solid #f59e0b'>")
            body += _ui_html("<h3>Update-Schutz</h3>")

            if guard.get("blocked"):
                body += _ui_html("<p class='err'><b>⚠ Update blockiert</b></p>")

            if guard.get("message"):
                body += _ui_html("<p><b>Grund:</b><br>{}</p>").format(
                    ctx.esc(_ui_text(guard.get("message")))
                )

            details = guard.get("details") or []

            if details:
                body += _ui_html("<p><b>Details:</b></p><ul>")

                for item in details:
                    if isinstance(item, dict):
                        body += _ui_html("<li><code>{}={}</code></li>").format(
                            ctx.esc(item.get("key", "")),
                            ctx.esc(item.get("value", "")),
                        )
                    else:
                        body += _ui_html("<li>{}</li>").format(
                            ctx.esc(str(item))
                        )

                body += _ui_html("</ul>")

            if guard.get("config_file"):

                body += _ui_html("<p><b>Konfigurationsdatei:</b><br>")
                body += _ui_html("<code>{}</code></p>").format(
                    ctx.esc(guard.get("config_file"))
                )

            if guard.get("edit_hint"):

                body += _ui_html("<p><b>Anleitung:</b><br>")
                body += _ui_html("{}<br>").format(
                    ctx.esc(guard.get("edit_hint"))
                )
                body += _ui_html("Beispiel:<br>")
                body += _ui_html("<code>IMMICH_VERSION=v3 → gewünschte Version setzen</code></p>")


            if guard.get("recommendation"):
                body += _ui_html("<p><b>Empfehlung:</b><br>{}</p>").format(
                    ctx.esc(guard.get("recommendation"))
                )

            body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Zusammenfassung</h3>")
        body += _ui_html("<p>Unterstützt: <b>{}</b><br>Schritte: <b>{}</b><br>Backup erforderlich: <b>{}</b><br>Execution enabled: <b>{}</b><br>Risiko: <code>{}</code></p>").format(
            _yes_no(data.get("supported")),
            ctx.esc(_display(summary.get("step_count"))),
            _yes_no(summary.get("requires_backup")),
            _yes_no(summary.get("execution_enabled")),
            ctx.esc(_risk_text(summary.get("risk", ""))),
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Update-Schritte</h3>")
        body += _ui_html("<table><tr><th>#</th><th>Schritt</th><th>Pflicht</th><th>Automatisch</th></tr>")

        for idx, st in enumerate(data.get("steps") or [], start=1):
            required = st.get("required", False)
            automatic = st.get("automatic", False)

            body += _ui_html("<tr>")
            body += _ui_html("<td>{}</td>").format(idx)
            body += _ui_html("<td>{}</td>").format(
                ctx.esc(_display(st.get("label") or st.get("title")))
            )
            body += _ui_html("<td>{}</td>").format(
                _yes_no(required)
            )
            body += _ui_html("<td>{}</td>").format(
                _yes_no(automatic)
            )
            body += _ui_html("</tr>")

        body += _ui_html("</table></div>")

        from . import prepare_ui
        body += prepare_ui.card(m.app_id)
        body += prepare_ui.script(m.app_id)
        body += _card(ctx, "Update Plan JSON", _pre(ctx, data))
        return ctx.page("Update-Plan " + m.label, body, "Apps")


    @app.route('/api/apps/<app_id>/update/prepare-status')
    def prepare_status(app_id):
        if not get_manager(app_id):return jsonify(error='unknown_app'),404
        from . import prepare_ui
        return jsonify(prepare=prepare_ui.latest(app_id),backup=get_active_job(app_id))

    @app.route("/apps/<app_id>/update/prepare", methods=["GET", "POST"])
    def apps_update_prepare(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        from . import prepare_ui
        if request.method == 'GET':
            try:data=prepare_ui.result(m.app_id,request.args.get('run_id',''))
            except (OSError,ValueError):return ctx.page(_ui_text('Backup-Vorbereitung'),_ui_html("<p>Ergebnis noch nicht verfügbar oder Run-ID ungültig.</p><a href='/apps/")+ctx.esc(m.app_id)+_ui_html("/update'>Zum Update-Plan</a>"),'Apps'),404
        else:
            data = _safe_call(lambda: run_update_prepare(m), "update_prepare")
            if request.headers.get('X-Prepare-Async')=='1':
                from urllib.parse import urlencode
                if data.get('run_id'):return jsonify(url='/apps/'+m.app_id+'/update/prepare?'+urlencode({'run_id':data['run_id']}))
                return jsonify(error='Vorbereitung fehlgeschlagen; Update-Runs prüfen.'),500

        body = _ui_html("<div class='card'><h2>Update vorbereitet: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/update'>Zurück zum Update-Plan</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/update/runs'>Update-Runs</a></p>").format(ctx.esc(m.app_id))

        if data.get("ok"):
            body += _ui_html("<p class='ok'><b>Pre-Update-Backup erfolgreich erzeugt.</b></p>")
            backup = data.get("backup") or {}
            if backup.get("archive"):
                body += _ui_html("<p>Archiv: <code>{}</code><br>Größe: <code>{}</code></p>").format(
                    ctx.esc(backup.get("archive", "")),
                    ctx.esc(backup.get("archive_size", "")),
                )
        else:
            body += _ui_html("<p class='err'><b>Prepare fehlgeschlagen. Kein echtes Update freigegeben.</b></p>")
            body += _card(ctx, "Prepare Ergebnis", _pre(ctx, data))
            return ctx.page("Update Prepare " + m.label, body, "Apps")

        if not data.get("started"):
            body += _ui_html("<p>Run-ID: <code>{}</code><br>Run-Verzeichnis: <code>{}</code></p>").format(
                ctx.esc(data.get("run_id", "")),
                ctx.esc(data.get("run_dir", "")),
            )

        if data.get("run_id"):
            body += _ui_html("<p><a class='btn' href='/apps/{}/update/runs/{}'>Run ansehen</a></p>").format(
                ctx.esc(m.app_id),
                ctx.esc(data.get("run_id", "")),
            )

        body += _ui_html("<hr><h3>Update ausführen</h3>")

        guard = data.get("update_guard") or {}

        if guard.get("blocked"):

            body += _ui_html("<div class='card' style='border-left:5px solid #dc2626'>")
            body += _ui_html("<p class='err'><b>⚠ Update geschützt</b></p>")

            if guard.get("message"):
                body += _ui_html("<p><b>Grund:</b><br>{}</p>").format(
                    ctx.esc(_ui_text(guard.get("message")))
                )

            details = guard.get("details") or []

            if details:
                body += _ui_html("<p><b>Details:</b></p><ul>")

                for item in details:
                    if isinstance(item, dict):
                        body += _ui_html("<li><code>{}={}</code></li>").format(
                            ctx.esc(item.get("key", "")),
                            ctx.esc(item.get("value", "")),
                        )
                    else:
                        body += _ui_html("<li>{}</li>").format(
                            ctx.esc(str(item))
                        )

                body += _ui_html("</ul>")

            if guard.get("recommendation"):
                body += _ui_html("<p><b>Empfehlung:</b><br>{}</p>").format(
                    ctx.esc(guard.get("recommendation"))
                )

            body += _ui_html("<p>Für eine manuelle Freigabe den Update-Token eingeben.</p>")

            body += "<form method='post' action='/apps/{}/update/execute' style='display:inline' ".format(ctx.esc(m.app_id))
            body += _ui_html("onsubmit=\"return confirm('Compose verwendet eine gepinnte Version. Update trotzdem ausführen?')\">")
            body += _ui_html("<input type='hidden' name='prepare_run_id' value='{}'>").format(
                ctx.esc(data.get("run_id", ""))
            )
            body += _ui_html("<input type='password' name='confirm_token' placeholder='UPDATE-Token eingeben' autocomplete='off' style='width:220px'> ")
            body += _ui_html("<button class='btn err' type='submit'>Update freigeben</button></form>")

            body += _ui_html("</div>")

        else:

            body += _ui_html("<p>Update kann jetzt ausgeführt werden. Backup, Preflight und Execution Gate werden geprüft.</p>")

            manager_kind = getattr(m, "kind", "") or ""
            compose_dir = getattr(m, "compose_dir", None)

            if m.app_id == "nextcloud" and not getattr(m, "container", None):
                current_version = data.get("current_version") or "unbekannt"
                latest_version = data.get("latest_version") or "unbekannt"

                confirm_message = (
                    "ACHTUNG: Das Nextcloud-Core-Update wird von {} auf {} "
                    "ausgeführt. Nextcloud kann während des Updates "
                    "vorübergehend nicht erreichbar sein. Fortfahren?"
                ).format(current_version, latest_version)

            elif compose_dir or manager_kind == "docker-compose":
                confirm_message = (
                    "ACHTUNG: Das Update aktualisiert Docker-Images und kann "
                    "Container neu starten. Fortfahren?"
                )

            elif manager_kind.startswith("native"):
                confirm_message = (
                    "ACHTUNG: Das native Update wird jetzt auf dem System "
                    "ausgeführt. Der Dienst kann vorübergehend nicht "
                    "erreichbar sein. Fortfahren?"
                )

            else:
                confirm_message = (
                    "ACHTUNG: Das echte Update wird jetzt ausgeführt. "
                    "Fortfahren?"
                )

            body += (
                _ui_html("<form method='post' action='/apps/{}/update/execute' "
                "style='display:inline' "
                "onsubmit=\"return confirm('{}')\">")
            ).format(
                ctx.esc(m.app_id),
                ctx.esc(_ui_text(confirm_message)),
            )
            body += _ui_html("<input type='hidden' name='prepare_run_id' value='{}'>").format(
                ctx.esc(data.get("run_id", ""))
            )
            body += _ui_html("<input name='confirm_token' placeholder='UPDATE eingeben' autocomplete='off' style='width:160px'> ")
            body += _ui_html("<button class='btn err' type='submit'>Update ausführen</button></form>")

        body += _card(ctx, "Prepare Ergebnis", _pre(ctx, data))
        return ctx.page("Update Prepare " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/update/execute", methods=["POST"])
    def apps_update_execute(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        confirm_token = request.form.get("confirm_token", "")

        prepare_run_id = (
            request.form.get("prepare_run_id", "")
            or ""
        ).strip()

        data = _safe_call(
            lambda: start_background_update(
                m,
                confirm_token=confirm_token,
                prepare_run_id=prepare_run_id,
            ),
            "update_execute",
        )

        body = _ui_html("<div class='card'><h2>Update-Ausführung: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/update'>Zurück zum Update-Plan</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}/update/runs'>Update-Runs</a></p>").format(ctx.esc(m.app_id))

        if data.get("started"):

            body += _ui_html("<div class='card' style='border-left:5px solid #16a34a'>")
            body += _ui_html("<h3>Update im Hintergrund gestartet</h3>")
            body += _ui_html("<p class='ok'><b>✓ Update läuft weiter.</b></p>")
            body += _ui_html("<p>Die WebUI bleibt während des Updates verfügbar.</p>")

            if data.get("run_id"):

                body += _ui_html("<p><b>Run-ID:</b><br>")
                body += _ui_html("<code>{}</code></p>").format(
                    ctx.esc(data.get("run_id"))
                )

                body += _ui_html("<p><a class='btn' href='/apps/{}/update/runs/{}'>Run ansehen</a></p>").format(
                    ctx.esc(m.app_id),
                    ctx.esc(data.get("run_id"))
                )

            body += _ui_html("</div>")

        elif data.get("simulate"):
            body += _ui_html("<p class='ok'><b>Simulation erfolgreich.</b></p>")
            body += _ui_html("<p><b>Es wurden keine Änderungen vorgenommen.</b></p>")

        elif data.get("blocked"):
            body += _ui_html("<p class='err'><b>BLOCKIERT</b></p>")
            body += _ui_html("<p>Keine Änderungen durchgeführt.</p>")

        elif data.get("ok"):
            body += _ui_html("<p class='ok'><b>Update erfolgreich.</b></p>")

        else:
            body += _ui_html("<p class='err'><b>Update fehlgeschlagen.</b></p>")

        if not data.get("started"):
            body += _ui_html("<p>Run-ID: <code>{}</code><br>Run-Verzeichnis: <code>{}</code></p>").format(
                ctx.esc(data.get("run_id", "")),
                ctx.esc(data.get("run_dir", "")),
            )
        body += _ui_html("</div>")

        body += _card(ctx, "Execute Ergebnis", _pre(ctx, data))
        return ctx.page("Update Execute " + m.label, body, "Apps")




    @app.route(
        "/apps/<app_id>/stable-switch",
        methods=["GET", "POST"]
    )
    def apps_comfyui_stable_switch(app_id):
        m = get_manager(app_id)

        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps"
            ), 404

        if m.app_id != "comfyui":
            return ctx.page(
                _ui_text("Stable-Wechsel nicht unterstützt"),
                (
                    _ui_html("<div class='card'>"
                    "<h2>Stable-Wechsel nicht unterstützt</h2>"
                    "<p>Diese Funktion ist nur für ComfyUI verfügbar.</p>"
                    "</div>")
                ),
                "Apps"
            ), 404

        if not hasattr(m, "stable_switch_plan"):
            return ctx.page(
                _ui_text("Stable-Wechsel nicht unterstützt"),
                (
                    _ui_html("<div class='card'>"
                    "<h2>Stable-Wechsel nicht unterstützt</h2>"
                    "<p>Der ComfyUI-Manager stellt keinen "
                    "Stable-Switch bereit.</p>"
                    "</div>")
                ),
                "Apps"
            ), 500

        plan = _safe_call(
            lambda: m.stable_switch_plan(),
            "comfyui_stable_switch_plan",
        )

        result = None
        prepare = None

        if request.method == "POST":
            action = (
                request.form.get("action", "")
                or ""
            ).strip()

            if action == "simulate":
                result = _safe_call(
                    lambda: m.stable_switch_execute({
                        "simulate": True,
                    }),
                    "comfyui_stable_switch_simulate",
                )

            elif action == "prepare":
                prepare = _safe_call(
                    lambda: run_update_prepare(m),
                    "comfyui_stable_switch_prepare",
                )

            elif action == "execute":
                confirm_token = (
                    request.form.get("confirm_token", "")
                    or ""
                ).strip()

                prepare_run_id = (
                    request.form.get("prepare_run_id", "")
                    or ""
                ).strip()

                if confirm_token != UPDATE_CONFIRM_TOKEN:
                    result = {
                        "ok": False,
                        "blocked": True,
                        "mode": "execute",
                        "message": (
                            "Stable-Wechsel blockiert: "
                            "Bestätigungstoken ist ungültig."
                        ),
                        "errors": [
                            "Zum echten Stable-Wechsel muss "
                            "UPDATE eingegeben werden."
                        ],
                    }

                elif not prepare_run_id:
                    result = {
                        "ok": False,
                        "blocked": True,
                        "mode": "execute",
                        "message": (
                            "Stable-Wechsel blockiert: "
                            "kein Prepare-Run gebunden."
                        ),
                        "errors": [
                            "Vor dem echten Stable-Wechsel muss "
                            "ein Pre-Update-Backup erzeugt werden."
                        ],
                    }

                else:
                    result = _safe_call(
                        lambda: m.stable_switch_execute({
                            "simulate": False,
                            "stable_switch_authorized": True,
                            "source_prepare_run_id": prepare_run_id,
                        }),
                        "comfyui_stable_switch_execute",
                    )

            else:
                result = {
                    "ok": False,
                    "blocked": True,
                    "message": "Unbekannte Stable-Switch-Aktion.",
                }

        body = _ui_html("<div class='card'>")
        body += _ui_html("<h2>ComfyUI · Update & Stable</h2><p><a class='btn' href='/apps/comfyui/update'>Update</a> <a class='btn active' href='/apps/comfyui/stable-switch' aria-current='page'>Stable-Version</a></p><p>Hier wird der Wechsel auf den ermittelten Stable-Release geprüft, simuliert und vorbereitet.</p><h3>Stable-Version verwalten</h3>")

        body += (
            _ui_html("<p><a class='btn' href='/apps/comfyui'>"
            "Zurück zu ComfyUI</a> "
            "<a class='btn' href='/apps/comfyui/update'>"
            "Update-Plan</a></p>")
        )

        current_revision = (
            plan.get("current_revision_short")
            or plan.get("current_revision")
            or "unbekannt"
        )

        stable_version = (
            plan.get("stable_version")
            or "unbekannt"
        )

        stable_revision = (
            plan.get("stable_revision_short")
            or plan.get("stable_revision")
            or "unbekannt"
        )

        current_branch = (
            plan.get("current_branch")
            or "unbekannt"
        )

        body += _ui_html("<p>")
        body += _ui_html("Aktueller Branch: <code>{}</code><br>").format(
            ctx.esc(current_branch)
        )
        body += _ui_html("Installierter Commit: <code>{}</code><br>").format(
            ctx.esc(current_revision)
        )
        body += _ui_html("Stable-Version: <b>{}</b><br>").format(
            ctx.esc(stable_version)
        )
        body += _ui_html("Stable-Commit: <code>{}</code></p>").format(
            ctx.esc(stable_revision)
        )

        if plan.get("already_stable"):
            body += (
                _ui_html("<p class='ok'><b>"
                "ComfyUI befindet sich bereits auf diesem Stable-Stand."
                "</b></p>")
            )

        elif plan.get("safe_to_switch"):
            body += (
                _ui_html("<p class='warn'><b>"
                "Kontrollierter Wechsel auf Stable ist möglich."
                "</b></p>")
            )

        else:
            body += (
                _ui_html("<p class='err'><b>"
                "Stable-Wechsel ist derzeit nicht sicher freigegeben."
                "</b></p>")
            )

        if plan.get("message"):
            body += _ui_html("<p>{}</p>").format(
                ctx.esc(_ui_text(plan.get("message")))
            )

        errors = plan.get("errors") or []

        if errors:
            body += _ui_html("<p><b>Fehler:</b></p><ul>")
            for item in errors:
                body += _ui_html("<li>{}</li>").format(
                    ctx.esc(item)
                )
            body += _ui_html("</ul>")

        body += _ui_html("</div>")

        if plan.get("already_stable"):
            body += _ui_html("<div class='card'>")
            body += _ui_html("<h3>Stable-Status</h3>")
            body += (
                _ui_html("<p class='ok'><b>"
                "Stable {} ist aktiv."
                "</b></p>").format(
                    ctx.esc(stable_version)
                )
            )
            body += (
                _ui_html("<p>Branch: <code>{}</code><br>"
                "Commit: <code>{}</code></p>").format(
                    ctx.esc(current_branch),
                    ctx.esc(current_revision),
                )
            )
            body += (
                _ui_html("<p>Kein Stable-Wechsel erforderlich.</p>")
            )
            body += _ui_html("</div>")

            body += _card(
                ctx,
                "Stable-Switch Plan JSON",
                _pre(ctx, plan),
            )

            return ctx.page(
                _ui_text("ComfyUI Stable-Wechsel"),
                body,
                "Apps",
            )

        body += _ui_html("<div class='card'>")
        body += _ui_html("<h3>1. Simulation</h3>")
        body += (
            _ui_html("<p>Prüft den vollständigen Stable-Wechsel, "
            "ohne Änderungen durchzuführen.</p>")
        )
        body += (
            _ui_html("<form method='post'>"
            "<input type='hidden' name='action' value='simulate'>"
            "<button class='btn' type='submit'>"
            "Stable-Wechsel simulieren"
            "</button>"
            "</form>")
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'>")
        body += _ui_html("<h3>2. Pre-Update-Backup</h3>")
        body += (
            _ui_html("<p>Erzeugt einen explizit bindbaren Prepare-Run "
            "mit Git-HEAD, Branch und Python-Paketstand.</p>")
        )
        body += (
            _ui_html("<form method='post'>"
            "<input type='hidden' name='action' value='prepare'>"
            "<button class='btn active' type='submit'>"
            "Backup vorbereiten"
            "</button>"
            "</form>")
        )
        body += _ui_html("</div>")

        if prepare:
            body += _ui_html("<div class='card'>")
            body += _ui_html("<h3>Prepare-Ergebnis</h3>")

            if prepare.get("ok"):
                body += (
                    _ui_html("<p class='ok'><b>"
                    "Pre-Update-Backup erfolgreich."
                    "</b></p>")
                )

                prepare_run_id = (
                    prepare.get("run_id")
                    or ""
                )

                body += _ui_html("<p>Prepare-Run:<br><code>{}</code></p>").format(
                    ctx.esc(prepare_run_id)
                )

                body += "<hr>"
                body += _ui_html("<h3>3. Echter Stable-Wechsel</h3>")
                body += (
                    _ui_html("<p class='warn'>"
                    "ComfyUI wird gestoppt, auf den Stable-Branch "
                    "umgestellt, geprüft und wieder gestartet. "
                    "Bei einem Fehler wird automatisch auf den "
                    "gesicherten Git- und Python-Stand zurückgerollt."
                    "</p>")
                )

                body += (
                    _ui_html("<form method='post' "
                    "onsubmit=\"return confirm("
                    "'ComfyUI wirklich auf Stable wechseln?')\">")
                )
                body += (
                    _ui_html("<input type='hidden' "
                    "name='action' value='execute'>")
                )
                body += (
                    _ui_html("<input type='hidden' "
                    "name='prepare_run_id' value='{}'>")
                ).format(
                    ctx.esc(prepare_run_id)
                )
                body += (
                    _ui_html("<input name='confirm_token' "
                    "placeholder='UPDATE eingeben' "
                    "autocomplete='off' "
                    "style='width:160px'> ")
                )
                body += (
                    _ui_html("<button class='btn err' type='submit'>"
                    "Auf Stable wechseln"
                    "</button>")
                )
                body += _ui_html("</form>")

            else:
                body += (
                    _ui_html("<p class='err'><b>"
                    "Pre-Update-Backup fehlgeschlagen."
                    "</b></p>")
                )

            body += _pre(ctx, prepare)
            body += _ui_html("</div>")

        if result:
            body += _ui_html("<div class='card'>")
            body += _ui_html("<h3>Stable-Switch Ergebnis</h3>")

            if result.get("simulate") and result.get("ok"):
                body += (
                    _ui_html("<p class='ok'><b>"
                    "Simulation erfolgreich."
                    "</b></p>")
                )
                body += (
                    _ui_html("<p>Es wurden keine Änderungen durchgeführt.</p>")
                )

            elif result.get("blocked"):
                body += _ui_html("<p class='err'><b>BLOCKIERT</b></p>")

            elif result.get("ok"):
                body += (
                    _ui_html("<p class='ok'><b>"
                    "Stable-Wechsel erfolgreich."
                    "</b></p>")
                )

            else:
                body += (
                    _ui_html("<p class='err'><b>"
                    "Stable-Wechsel fehlgeschlagen."
                    "</b></p>")
                )

            body += _pre(ctx, result)
            body += _ui_html("</div>")

        body += _card(
            ctx,
            "Stable-Switch Plan JSON",
            _pre(ctx, plan)
        )

        return ctx.page(
            _ui_text("ComfyUI Stable-Wechsel"),
            body,
            "Apps"
        )


    @app.route("/apps/<app_id>/update/cleanup", methods=["GET", "POST"])
    def apps_update_cleanup(app_id):
        m = get_manager(app_id)

        if not m:
            return ctx.page(
                _ui_text("App nicht gefunden"),
                _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                "Apps"
            ), 404

        from .update_engine import cleanup_update_runs
        from .install_ui import token
        from flask import session
        import secrets

        keep, scope, result = 20, "simulation", None
        import hashlib
        def fingerprint(runs):
            return hashlib.sha256(json.dumps(sorted(r["run_id"] for r in runs)).encode()).hexdigest()
        preview_key = "update_cleanup_preview_" + app_id
        if request.method == "POST":
            if not secrets.compare_digest(request.form.get("csrf", ""), session.get("app_install_csrf", "!")):
                return ctx.page(_ui_text("Läufe löschen"), _ui_html("<p>Formular abgelaufen. Bitte neu laden.</p>"), "Apps"), 403
            try:
                keep = int(request.form.get("max_runs", "20"))
                scope = request.form.get("scope", "simulation")
                if request.form.get("action") == "delete":
                    saved = session.pop(preview_key, None)
                    if not saved or saved["keep"] != keep or saved["scope"] != scope:
                        raise ValueError("Bitte zuerst eine aktuelle Vorschau erstellen.")
                    current = cleanup_update_runs(app_id, keep, False, scope)
                    if saved["digest"] != fingerprint(current["candidates"]):
                        raise ValueError("Die Laufübersicht hat sich geändert. Bitte erneut eine Vorschau erstellen.")
                    result = cleanup_update_runs(app_id, keep, True, scope, [r["run_id"] for r in current["candidates"]])
                preview = cleanup_update_runs(app_id, keep, False, scope)
            except ValueError as exc:
                return ctx.page(_ui_text("Läufe löschen"), _ui_html("<p>") + ctx.esc(str(exc)) + _ui_html("</p><p>Bitte zur Bereinigung zurückkehren.</p>"), "Apps"), 400
        else:
            preview = cleanup_update_runs(app_id, keep, False, scope)
        candidates = preview["candidates"]
        session[preview_key] = {"keep": keep, "scope": scope, "digest": fingerprint(candidates)}
        body = _ui_html("<div class='card'><h2>Gespeicherte Update-Läufe löschen: ") + ctx.esc(_ui_text(m.label)) + _ui_html("</h2>")
        body += _ui_html("<p>Gelöscht werden ausschließlich Protokolle abgeschlossener Läufe. Programme und Backups bleiben erhalten. Vorbereitungen, laufende und unklare Läufe bleiben geschützt.</p>")
        if result is not None:
            body += _ui_html("<p><b>{} Läufe gelöscht.</b></p>").format(len(result["deleted"]))
            for error in result["errors"]:
                body += _ui_html("<p class='err'>") + ctx.esc(_ui_text(error)) + _ui_html("</p>")
            if not result["deleted"] and not result["errors"]:
                body += _ui_html("<p>Keine passenden abgeschlossenen Läufe vorhanden.</p>")
        body += _ui_html("<form method='post'>") + token()
        body += _ui_html("<p><label>Auswahl <select name='scope'>")
        for value, label in (("simulation", "Nur Simulationen"), ("finished", "Simulationen und Echtläufe (auch fehlgeschlagene)")):
            body += _ui_html("<option value='{}' {}>{}</option>").format(value, "selected" if scope == value else "", _ui_text(label))
        body += _ui_html("</select></label></p><p><label>Neueste Läufe dieser Auswahl behalten: <input type='number' min='0' name='max_runs' value='{}' required></label> (0 = alle passenden Läufe löschen)</p>").format(keep)
        body += _ui_html("<button class='btn' name='action' value='preview'>Vorschau anzeigen</button></form>")
        body += _ui_html("<h3>Vorschau: {} Läufe · {} MB</h3>").format(len(candidates), preview["candidate_size_mb"])
        if candidates:
            body += _ui_html("<ul>")
            for run in candidates:
                body += _ui_html("<li><code>{}</code> · {} · {}</li>").format(ctx.esc(run["run_id"]), ctx.esc(run["run_type"]), ctx.esc(_ui_text(run["state"])))
            body += _ui_html("</ul><form method='post'>") + token()
            body += _ui_html("<input type='hidden' name='max_runs' value='{}'><input type='hidden' name='scope' value='{}'>").format(keep, scope)
            body += _ui_html("<button class='btn err' name='action' value='delete' onclick=\"return confirm('Die angezeigten Laufprotokolle endgültig löschen?')\">Angezeigte Läufe löschen</button></form>")
        else:
            body += _ui_html("<p>Keine löschbaren Läufe für diese Auswahl. Gegebenenfalls die Anzahl auf 0 setzen oder Echtläufe einschließen.</p>")
        body += _ui_html("<p><a class='btn' href='/apps/{}/update/runs'>Zurück zu den Läufen</a></p></div>").format(ctx.esc(app_id))
        return ctx.page(_ui_text("Gespeicherte Läufe löschen"), body, "Apps")


    @app.route("/apps/<app_id>/update/runs")
    def apps_update_runs(app_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"), _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"), "Apps"), 404

        root = Path(UPDATE_LOG_ROOT) / m.app_id
        runs = []
        if root.exists():
            runs = sorted([x for x in root.iterdir() if x.is_dir()], key=lambda x: x.name, reverse=True)

        body = _ui_html("<div class='card'><h2>Update-Runs: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/update'>Zurück zum Update-Plan</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn active' href='/apps/{}/update/cleanup'>Läufe löschen</a> ").format(ctx.esc(m.app_id))
        body += _ui_html("<a class='btn' href='/apps/{}'>App</a></p></div>").format(ctx.esc(m.app_id))

        body += _ui_html("<div class='card'><h3>Läufe</h3>")
        if not runs:
            body += _ui_html("<p class='warn'>Keine Update-Runs gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>Run</th><th>Status</th><th>Typ</th><th>Modus</th><th>Aktion</th></tr>")

            for rdir in runs[:30]:
                result_file = rdir / "result.json"
                session_file = rdir / "session.json"

                data = {}
                session = {}

                if result_file.exists():
                    try:
                        data = json.loads(result_file.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}

                if session_file.exists():
                    try:
                        session = json.loads(session_file.read_text(encoding="utf-8"))
                    except Exception:
                        session = {}

                status = "OK" if data.get("ok") else (
                    "BLOCKIERT" if data.get("blocked") else "FEHLER"
                )

                run_type = session.get("run_type", "unknown")

                if run_type == "simulation":
                    type_text = "🟡 Simulation"
                elif run_type == "prepare":
                    type_text = "🔵 Prepare"
                elif run_type == "execute":
                    type_text = "🔴 Execute"
                else:
                    type_text = "⚪ unbekannt"

                mode = data.get("mode", "")

                body += _ui_html("<tr>")
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(rdir.name))
                body += _ui_html("<td>{}</td>").format(ctx.esc(_ui_text(status)))
                body += _ui_html("<td>{}</td>").format(ctx.esc(type_text))
                body += _ui_html("<td><code>{}</code></td>").format(ctx.esc(mode))
                body += _ui_html("<td><a class='btn' href='/apps/{}/update/runs/{}'>Öffnen</a></td>").format(
                    ctx.esc(m.app_id),
                    ctx.esc(rdir.name),
                )
                body += _ui_html("</tr>")

            body += _ui_html("</table>")
        body += _ui_html("</div>")

        return ctx.page("Update-Runs " + m.label, body, "Apps")


    @app.route("/apps/<app_id>/update/runs/<run_id>")
    def apps_update_run_detail(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return ctx.page(_ui_text("App nicht gefunden"),
                            _ui_html("<div class='card'><h2>App nicht gefunden</h2></div>"),
                            "Apps"), 404

        run_dir = Path(UPDATE_LOG_ROOT) / app_id / run_id

        result = {}
        session = {}

        try:
            result_file = run_dir / "result.json"
            session_file = run_dir / "session.json"

            if result_file.exists():
                result = json.loads(result_file.read_text(encoding="utf-8"))

            if session_file.exists():
                session = json.loads(session_file.read_text(encoding="utf-8"))

        except Exception as e:
            result = {"error": str(e)}

        simulate = bool(result.get("simulate") or session.get("simulate"))

        if simulate:
            mode_badge = _ui_html("<span class='warn'>🟡 Simulation</span>")
        else:
            mode_badge = _ui_html("<span class='err'>🔴 Echtlauf</span>")

        state = session.get("state") or result.get("message") or "unbekannt"

        body = _ui_html("<div class='card'>")
        body += _ui_html("<h2>Update Run: {}</h2>").format(ctx.esc(_ui_text(m.label)))
        body += _ui_html("<p><a class='btn' href='/apps/{}/update/runs'>Zurück</a></p>").format(
            ctx.esc(app_id)
        )

        body += _ui_html("<p>Modus: {}<br>Status: <b>{}</b></p>").format(
            mode_badge,
            ctx.esc(_ui_text(state))
        )


        # Live Run Status
        current_step = session.get("current_step")
        current_action = session.get("current_action")

        started_at = (
            session.get("started_at")
            or result.get("started_at")
            or ""
        )

        finished_at = (
            session.get("finished_at")
            or result.get("finished_at")
            or ""
        )


        body += _ui_html("<div class='card' style='border-left:5px solid #2563eb'>")
        body += _ui_html("<h3>Live Status</h3>")

        body += _ui_html("<p>")

        if state in ("running", "backup", "preflight"):
            body += _ui_html("<span class='warn'>🟡 Läuft</span><br>")
        elif state in ("completed", "success"):
            body += _ui_html("<span class='ok'>🟢 Abgeschlossen</span><br>")
        elif state in ("failed", "error"):
            body += _ui_html("<span class='err'>🔴 Fehler</span><br>")
        else:
            body += _ui_html("<span class='warn'>⚪ {}</span><br>").format(
                ctx.esc(_ui_text(state))
            )


        if current_step:
            body += _ui_html("<b>Aktueller Schritt:</b> {}<br>").format(
                ctx.esc(current_step)
            )

        if current_action:
            body += _ui_html("<b>Aktion:</b> {}<br>").format(
                ctx.esc(current_action)
            )

        if started_at:
            body += _ui_html("<b>Start:</b> {}<br>").format(
                ctx.esc(started_at)
            )

        if finished_at:
            body += _ui_html("<b>Ende:</b> {}<br>").format(
                ctx.esc(finished_at)
            )

        body += _ui_html("</p>")
        body += _ui_html("</div>")


        if simulate:
            body += _ui_html("<p class='ok'><b>Keine Änderungen durchgeführt.</b></p>")

        analysis = result.get("execute_analysis") or session.get("execute_analysis") or {}

        if analysis:
            category = analysis.get("category") or "unbekannt"
            recommendation = analysis.get("recommendation") or "Keine Empfehlung vorhanden."
            rollback_required = bool(analysis.get("rollback_required"))
            rollback_reason = analysis.get("rollback_reason") or "Keine Rollback-Bewertung vorhanden."

            cls = "err" if analysis.get("status") == "failed" else "ok"

            body += _ui_html("<div class='card' style='border-left:5px solid #f59e0b'>")
            body += _ui_html("<h3>Update-Fehleranalyse</h3>")
            body += _ui_html("<p>Status: <b class='{}'>{}</b><br>").format(
                cls,
                ctx.esc(_ui_text(analysis.get("status", "unbekannt")))
            )
            body += _ui_html("Kategorie: <code>{}</code></p>").format(
                ctx.esc(category)
            )
            body += _ui_html("<p><b>Empfehlung:</b><br>{}</p>").format(
                ctx.esc(recommendation)
            )
            body += _ui_html("<p><b>Rollback nötig:</b> {}<br>{}</p>").format(
                _ui_text("Ja") if rollback_required else _ui_text("Nein"),
                ctx.esc(rollback_reason)
            )

            if category == "docker_registry_rate_limit":
                body += _ui_html("<p class='warn'><b>Retry-Hinweis:</b> Docker Hub Rate Limit. Später erneut versuchen oder Docker Login einrichten.</p>")

            body += _ui_html("</div>")

        body += _ui_html("<p>Run-ID:<br><code>{}</code><br><br>Verzeichnis:<br><code>{}</code></p>").format(
            ctx.esc(run_id),
            ctx.esc(str(run_dir))
        )

        body += _ui_html("</div>")


        steps = result.get("steps") or session.get("steps") or []

        body += _ui_html("<div class='card'><h3>Schritte</h3>")
        body += _ui_html("<table><tr><th>#</th><th>Schritt</th><th>Status</th><th>Änderung</th></tr>")

        for step in steps:
            body += _ui_html("<tr>")
            body += _ui_html("<td>{}</td>").format(
                ctx.esc(step.get("order"))
            )
            body += _ui_html("<td>{}</td>").format(
                ctx.esc(_ui_text(step.get("label")) or step.get("title"))
            )
            body += _ui_html("<td>{}</td>").format(
                ctx.esc(_ui_text(step.get("status")))
            )
            body += _ui_html("<td>{}</td>").format(
                _ui_text("Ja") if step.get("changed") else _ui_text("Nein")
            )
            body += _ui_html("</tr>")

        body += _ui_html("</table></div>")


        body += _card(
            ctx,
            "Diagnose JSON",
            _pre(ctx, result)
        )

        return ctx.page(
            "Update Run " + m.label,
            body,
            "Apps"
        )

    @app.route("/api/apps/<app_id>/backup/runs/<run_id>/session")
    def api_backup_run_session(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return Response(
                json.dumps({"ok": False, "error": "app not found"}, ensure_ascii=False, indent=2),
                status=404,
                mimetype="application/json",
            )

        run_dir = Path(DEFAULT_BACKUP_ROOT) / m.app_id / run_id
        return _session_api_response(run_dir, "backup")


    @app.route("/api/apps/<app_id>/restore/runs/<run_id>/session")
    def api_restore_run_session(app_id, run_id):
        m = get_manager(app_id)
        if not m:
            return Response(
                json.dumps({"ok": False, "error": "app not found"}, ensure_ascii=False, indent=2),
                status=404,
                mimetype="application/json",
            )

        run_dir = Path(RESTORE_LOG_ROOT) / m.app_id / run_id
        return _session_api_response(run_dir, "restore")


    @app.route("/api/apps")
    def api_apps():
        data = []
        for m in all_managers():
            st = _safe_call(lambda m=m: m.status(), "status")
            data.append(st)
        return Response(
            json.dumps({"ok": True, "apps": data}, ensure_ascii=False, indent=2),
            mimetype="application/json",
        )

    @app.route("/api/apps/<app_id>")
    def api_app_detail(app_id):
        m = get_manager(app_id)
        if not m:
            return Response(
                json.dumps({"ok": False, "error": "not found"}, ensure_ascii=False),
                status=404,
                mimetype="application/json",
            )

        data = _full_app_data(m)
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype="application/json",
        )
