from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import html
from datetime import datetime
import json
import subprocess
from flask import Response, request, session
import secrets

from .config import CONF, ensure_config, read_config
from . import api
from . import models
from . import blockers

def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS tvheadend_status (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS tvheadend_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            event_type TEXT,
            title TEXT,
            channel TEXT,
            start_time TEXT,
            stop_time TEXT,
            status TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()

def set_status(con, key, value):
    con.execute("""
        INSERT INTO tvheadend_status(key,value,updated_at)
        VALUES(?,?,datetime('now','localtime'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, str(value)))
    con.commit()

def service_state():
    try:
        p = subprocess.run(["systemctl", "is-active", "tvheadend.service"], text=True, capture_output=True, timeout=5)
        return (p.stdout or "").strip()
    except Exception:
        return "unknown"

def badge(value):
    v = str(value or "").lower()
    value = html.escape(str(value or ""))
    if v in ("active", "ok", "completed ok", "running"):
        return _ui_html("<span class='ok'>{}</span>").format(value)
    if "error" in v or "fail" in v or "miss" in v:
        return _ui_html("<span class='err'>{}</span>").format(value)
    if "unknown" in v:
        return _ui_html("<span class='warn'>{}</span>").format(value)
    return str(value or "")

def safe_call(fn, fallback=None):
    try:
        return fn()
    except Exception as exc:
        return fallback if fallback is not None else [{"error": str(exc)}]

def refresh_status(con):
    init_db(con)
    ensure_config()
    cfg = read_config()

    set_status(con, "tvheadend_service", service_state())
    set_status(con, "tvheadend_url", cfg.get("url", ""))

    try:
        info = api.serverinfo()
        set_status(con, "api_login", "ok")
        for key in ("sw_version", "api_version"):
            if key in info:
                set_status(con, key, info[key])
    except Exception as exc:
        set_status(con, "api_login", "error: " + str(exc))

    subs = safe_call(lambda: api.subscriptions(), "unknown")
    conns = safe_call(lambda: api.connections(), "unknown")
    upcoming = safe_call(lambda: api.recordings("grid_upcoming", 1), [])

    set_status(con, "streams_active", sum(not models.is_epg_grabber(row) for row in subs) if isinstance(subs, list) else "unknown")
    set_status(con, "connections_active", len(conns) if isinstance(conns, list) else "unknown")

    if upcoming:
        set_status(con, "next_recording", models.normalize_recording(upcoming[0]).get("title", ""))
    else:
        set_status(con, "next_recording", "")

def status_payload(ctx):
    con = ctx.db()
    try:
        refresh_status(con)
        rows = con.execute("SELECT key,value,updated_at FROM tvheadend_status ORDER BY key").fetchall()
        status = {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}
    finally:
        con.close()

    return {
        "ok": True,
        "status": status,
        "connections": safe_call(lambda: [models.normalize_stream(x) for x in api.connections()]),
        "subscriptions": safe_call(lambda: [models.normalize_stream(x) for x in api.subscriptions()]),
        "upcoming": safe_call(lambda: [models.normalize_recording(x) for x in api.recordings("grid_upcoming", 100)]),
        "finished": safe_call(lambda: [models.normalize_recording(x) for x in api.recordings("grid_finished", 100)]),
        "failed": safe_call(lambda: [models.normalize_recording(x) for x in api.recordings("grid_failed", 100)]),
        "active_recordings": safe_call(lambda: [models.normalize_recording(x) for x in api.recordings("grid", 100)]),
    }

def table(ctx, rows, columns):
    if not rows:
        return _ui_html("<p>Keine Einträge.</p>")
    errors = [row for row in rows if row.get("error") and not any(row.get(k) for k in ("title", "channel", "user", "peer", "status", "state"))]
    if errors and len(errors) == len(rows):
        return _ui_html("<p class='warn'>Daten konnten nicht geladen werden. Bitte die <a href='/tv/status'>Verbindung prüfen</a>.</p>")
    body = _ui_html("<div style='overflow-x:auto'><table><tr>")
    for title, key in columns:
        body += _ui_html("<th>{}</th>").format(ctx.esc(title))
    body += _ui_html("</tr>")
    for row in rows:
        body += _ui_html("<tr>")
        for title, key in columns:
            val = row.get(key, "")
            if key in ("start", "stop", "started"):
                try: val = datetime.fromtimestamp(float(val)).strftime("%d.%m.%Y %H:%M") if val else "–"
                except (ValueError, TypeError, OverflowError, OSError): pass
            if key in ("status", "state"):
                val = badge(val)
                body += _ui_html("<td>{}</td>").format(val)
            else:
                body += _ui_html("<td>{}</td>").format(ctx.esc(val))
        body += _ui_html("</tr>")
    body += _ui_html("</table></div>")
    return body

def section(ctx, title, rows, columns):
    return _ui_html("<div class='card'><h2>{}</h2>{}</div>").format(ctx.esc(title), table(ctx, rows, columns))

def register(app, ctx):
    from .recording_ui import register as register_recording
    register_recording(app, ctx)
    from .recordings_ui import register as register_deletion
    register_deletion(app, ctx)
    ensure_config()
    _register_tv_rtc_routes(app, ctx)

    @app.route("/api/tv/status")
    def api_tv_status():
        return Response(json.dumps(status_payload(ctx), ensure_ascii=False, indent=2), mimetype="application/json")

    @app.route("/tv")
    def tv_index():
        data = status_payload(ctx)
        st = data["status"]
        streams = st.get("streams_active", {}).get("value", "0")
        next_rec = st.get("next_recording", {}).get("value", "")
        api_login = st.get("api_login", {}).get("value", "unknown")

        body = _ui_html("<div class='card'><h2>Fernsehen und Aufnahmen</h2><p>Aufnahmen ansehen, geplante Sendungen prüfen und im Fernsehprogramm suchen.</p><a class='btn' href='/tv/epg'>Sendung suchen</a> <a class='btn' href='/tv/upcoming'>Geplante Aufnahmen</a> <a class='btn' href='/tv'>Status aktualisieren</a></div>")
        if api_login != "ok":
            body += _ui_html("<div class='card'><p class='warn'>Tvheadend ist nicht erreichbar oder die Anmeldung ist fehlgeschlagen. Aufnahme- und Streamdaten sind derzeit nicht zuverlässig verfügbar.</p><a class='btn' href='/tv/status'>Verbindung prüfen</a></div>")
        body += _ui_html("<div class='grid'>")
        body += ctx.card(_ui_text("Aufnahmen"), _ui_html("Fertige Aufnahmen und mögliche Aufnahmefehler prüfen."), [("Aufnahmen anzeigen", "/tv/recordings")])
        body += ctx.card(_ui_text("Als Nächstes"), _ui_html("Nächste Aufnahme: <b>{}</b>").format(ctx.esc(next_rec or (_ui_text("Keine geplant") if api_login == "ok" else _ui_text("Nicht verfügbar")))), [("Zeitplan anzeigen", "/tv/upcoming")])
        body += ctx.card(_ui_text("Live-TV"), _ui_html("Aktive Streams: <b>{}</b>").format(ctx.esc(streams)), [("Streams anzeigen", "/tv/streams")])
        body += ctx.card(_ui_text("Aufwachen für Aufnahmen"), _ui_html("Aufwachzeit und Vorlauf vor der nächsten Aufnahme prüfen."), [("Aufwachplanung öffnen", "/tv/rtc")])
        body += _ui_html("</div>")
        body += _ui_html("<div class='card'><p>Zum Anlegen, Bearbeiten und Abspielen von Aufnahmen die Tvheadend-Oberfläche verwenden.</p><a class='btn' href='/apps/tvheadend'>Tvheadend-App öffnen</a> <a class='btn' href='/tv/status'>Verbindungsdetails</a></div>")
        return ctx.page(_ui_text("TV & Aufnahmen"), body, "TV")

    @app.route("/tv/status")
    def tv_status_page():
        data = status_payload(ctx)
        body = _ui_html("<div class='card'><h2>Tvheadend Status</h2><table><tr><th>Wert</th><th>Status</th><th>Aktualisiert</th></tr>")
        for key, val in data["status"].items():
            v = val.get("value")
            body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td></tr>").format(ctx.esc(key), badge(v), ctx.esc(val.get("updated_at")))
        body += _ui_html("</table></div>")
        body += _ui_html("<div class='card'><h3>Konfiguration</h3><pre>{}</pre></div>").format(ctx.esc(str(CONF)))
        body += _ui_html("<div class='card'><h3>RTC</h3><p><a class='btn' href='/tv/rtc'>RTC-Aufnahmen öffnen</a> <a class='btn' href='/api/tv/rtc'>JSON RTC</a></p></div>")
        return ctx.page(_ui_text("Tvheadend Status"), body, "TV")

    @app.route("/tv/streams")
    def tv_streams_page():
        data = status_payload(ctx)
        body = section(ctx, "Aktive Verbindungen", data.get("connections", []), [
            ("Benutzer", "user"),
            ("IP", "peer"),
            ("Server", "server"),
            ("Start", "started"),
            ("Fehler", "error"),
        ])
        body += section(ctx, "Subscriptions / Live-TV", data.get("subscriptions", []), [
            ("Sender", "channel"),
            ("Titel", "title"),
            ("Status", "state"),
            ("Fehler", "error"),
        ])
        body += _ui_html("<div class='card'><p>Den aktuellen Schutz vor dem Einschlafen unter Schlafblocker prüfen: <a href='/server-control'>Schlafblocker öffnen</a>.</p></div>")
        return ctx.page(_ui_text("TV Streams"), body, "TV")

    @app.route("/tv/recordings")
    def tv_recordings_page():
        from .recordings_ui import render
        return render(ctx)

    @app.route("/tv/upcoming")
    def tv_upcoming_page():
        data = status_payload(ctx)
        rows = data.get("upcoming", [])
        body = section(ctx, "Geplante Aufnahmen", rows, [
            ("Titel", "title"),
            ("Sender", "channel"),
            ("Start", "start"),
            ("Ende", "stop"),
            ("Status", "status"),
            ("Fehler", "error"),
        ])
        body += _ui_html("<div class='card'><p>Hier stehen die kommenden Aufnahmen. Unter Aufwachplanung kannst du den Vorlauf und den nächsten Aufwachtermin prüfen.</p><p><a class='btn' href='/tv/rtc'>Aufwachplanung öffnen</a></p></div>")
        return ctx.page(_ui_text("Kommende TV-Aufnahmen"), body, "TV")

    @app.route("/tv/epg")
    def tv_epg_page():
        from .epg_ui import render
        return render(ctx, request.args)

    @app.route("/tv/dvb")
    def tv_dvb_page():
        body = _ui_html("<div class='card'><h2>DVB Diagnose</h2><p>Digital-Devices-/DVB-Diagnose wird in der nächsten TV-Phase ergänzt.</p></div>")
        return ctx.page(_ui_text("DVB Diagnose"), body, "TV")



# --- TV RTC routes ---
def _register_tv_rtc_routes(app, ctx):
    from flask import request, Response
    import json
    from . import rtc

    @app.route("/api/tv/rtc", methods=["GET", "POST"])
    def api_tv_rtc():
        if request.method == "POST" and not secrets.compare_digest(request.form.get("auth_csrf", ""), session.get("auth_csrf", "!")):
            return "csrf_required", 403
        try:
            prewake = int(request.values.get("prewake", "0") or "0")
            if not 0 <= prewake <= 1440:raise ValueError()
        except ValueError:return "Vorlauf muss zwischen 0 und 1440 Minuten liegen.", 400
        con_tmp = ctx.db()
        try:
            if request.method == "POST" and request.form.get("save") == "1":
                blockers.set_setting(con_tmp, blockers.SETTING_KEY, prewake)
            if prewake <= 0:
                prewake = blockers.get_prewake_minutes(con_tmp)
        finally:
            con_tmp.close()
        con = ctx.db()
        try:
            plan = rtc.plan_next_recording(con, prewake)
            events = rtc.current_rtc_events(con)
            wakealarm = rtc.read_kernel_wakealarm()
        finally:
            con.close()
        return Response(json.dumps({
            "ok": True,
            "plan": plan,
            "events": events,
            "kernel_wakealarm": wakealarm
        }, ensure_ascii=False, indent=2), mimetype="application/json")

    @app.route("/tv/rtc", methods=["GET", "POST"])
    def tv_rtc_page():
        if request.method == "POST" and not secrets.compare_digest(request.form.get("auth_csrf", ""), session.get("auth_csrf", "!")):
            return "csrf_required", 403
        try:
            prewake = int(request.values.get("prewake", "0") or "0")
            if not 0 <= prewake <= 1440:raise ValueError()
        except ValueError:return "Vorlauf muss zwischen 0 und 1440 Minuten liegen.", 400
        con_tmp = ctx.db()
        try:
            if request.method == "POST" and request.form.get("save") == "1":
                blockers.set_setting(con_tmp, blockers.SETTING_KEY, prewake)
            if prewake <= 0:
                prewake = blockers.get_prewake_minutes(con_tmp)
        finally:
            con_tmp.close()
        con = ctx.db()
        try:
            plan = rtc.plan_next_recording(con, prewake)
            events = rtc.current_rtc_events(con)
            wakealarm = rtc.read_kernel_wakealarm()
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>RTC-Aufnahmen</h2>")
        body += _ui_html("<p>Plant den nächsten Wakeup aus kommenden Tvheadend-Aufnahmen. Noch kein automatisches Ausschalten.</p>")
        body += _ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='")+html.escape(session.setdefault("auth_csrf", secrets.token_urlsafe(32)),quote=True)+_ui_html("'><label>Vorlauf Minuten <input name='prewake' value='{}'></label> <button class='btn'>Neu berechnen</button> <button class='btn' name='save' value='1'>Speichern</button></form>").format(prewake)
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Nächste Aufnahme</h3>")
        if plan.get("planned"):
            r = plan.get("recording", {})
            body += _ui_html("<table><tr><th>Titel</th><th>Sender</th><th>Start</th><th>Wake</th><th>Vorlauf</th></tr>")
            body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{} min</td></tr>").format(
                ctx.esc(r.get("title")), ctx.esc(r.get("channel")), ctx.esc(r.get("start")), ctx.esc(r.get("wake")), ctx.esc(r.get("prewake_minutes"))
            )
            body += _ui_html("</table>")
        else:
            body += _ui_html("<p>Keine kommende Aufnahme gefunden.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>RTC-Events</h3>")
        if events:
            body += _ui_html("<table><tr><th>Status</th><th>Titel</th><th>Wake</th><th>Ziel</th><th>Erstellt</th></tr>")
            for e in events:
                body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                    ctx.esc(_ui_text(e.get("status"))), ctx.esc(e.get("title")), ctx.esc(e.get("wake_time")), ctx.esc(e.get("target_time")), ctx.esc(e.get("created_at"))
                )
            body += _ui_html("</table>")
        else:
            body += _ui_html("<p>Keine RTC-Events.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Kernel Wakealarm</h3><pre>{}</pre></div>").format(ctx.esc(str(wakealarm)))
        body += _ui_html("<div class='card'><p><a class='btn' href='/api/tv/rtc'>JSON RTC</a></p></div>")
        return ctx.page(_ui_text("TV RTC"), body, "TV")

