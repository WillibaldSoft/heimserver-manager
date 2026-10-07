from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import json
from flask import Response, request, redirect
from modules.server_control import api as server_control_api

from . import runtime, manual
from . import policy
from . import actions
from . import schedules
from modules.server_control.systembedarf import render_systembedarf
from modules.app_manager.plugin import get_active_job

def badge(value):
    if value:
        return _ui_html("<span class='ok'>erlaubt</span>")
    return _ui_html("<span class='warn'>blockiert</span>")

def table_blockers(ctx, blockers):
    if not blockers:
        return _ui_html("<p class='ok'>Keine Blocker.</p>")

    body = _ui_html("<table><tr><th>Quelle</th><th>Name</th><th>Grund</th><th>Aktion</th></tr>")
    for b in blockers:
        url = b.get("url") or ""
        action = "—"
        if url:
            action = _ui_html("<a class='btn' href='{}'>Öffnen</a>").format(ctx.esc(url))

        body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
            ctx.esc(b.get("source")),
            ctx.esc(b.get("name") or b.get("title")),
            ctx.esc(_ui_text(b.get("reason"))),
            action,
        )
    body += _ui_html("</table>")
    return body

def table_actions(ctx, rows):
    if not rows:
        return _ui_html("<p>Keine Aktionen.</p>")
    body = _ui_html("<table><tr><th>Zeit</th><th>Aktion</th><th>Modus</th><th>Erlaubt</th><th>Ergebnis</th><th>Details</th></tr>")
    for r in rows:
        body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
            ctx.esc(r.get("created_at")),
            ctx.esc(r.get("action")),
            ctx.esc(_ui_text(r.get("mode"))),
            ctx.esc(r.get("allowed")),
            ctx.esc(r.get("result")),
            ctx.esc(r.get("details")),
        )
    body += _ui_html("</table>")
    return body

def evaluate_sleep_with_server_control(con, ctx):
    data = policy.evaluate(con, ctx)

    try:
        from modules.app_manager.plugin import get_active_job
        job = get_active_job()
    except Exception as e:
        job = None
        data.setdefault("warnings", []).append(
            "App-Manager Jobstatus nicht prüfbar: {}".format(str(e))
        )

    if job:
        blockers = list(data.get("blockers") or [])

        app_id = job.get("app_id") or "unknown"
        action = job.get("action") or job.get("type") or "job"
        detail = job.get("current_detail") or action
        path_key = job.get("current_path_key") or ""
        progress = job.get("progress_percent")

        reason = "{}".format(detail)
        if path_key:
            reason += " ({})".format(path_key)
        if progress is not None:
            reason += " {}%".format(progress)

        blockers.append({
            "source": "App Manager",
            "name": app_id,
            "reason": reason,
            "url": job.get("url"),
            "type": "app-manager-job",
        })

        data["may_sleep"] = False
        data["blockers"] = blockers
        data["blocker_count"] = len(blockers)
        data["active_app_job"] = job

    return data

def register(app, ctx):
    manual.initialize(ctx)
    runtime.start(ctx)
    schedules.register(app, ctx)

    @app.route("/sleep/settings", methods=["GET", "POST"])
    def sleep_settings():
        from tools.platform_check import mint_desktop
        if mint_desktop():return ctx.page(_ui_text('Schlafsteuerung'), _ui_html('<div class="card">Mint-Testprofil: automatische Schlaf- und RTC-Steuerung ist deaktiviert. Energieverwaltung über Linux Mint konfigurieren.</div>'), 'Schlafsteuerung')
        from flask import request

        con = ctx.db()
        msg = ""
        try:
            policy.ensure_tables(con)

            if request.method == "POST":
                auto_enabled = "1" if request.form.get("auto_enabled") == "1" else "0"
                execute_enabled = "1" if request.form.get("execute_enabled") == "1" else "0"
                default_action = request.form.get("default_action") or "suspend"
                grace_minutes = request.form.get("grace_minutes") or "45"

                try:
                    grace_minutes = str(max(0, min(1440, int(grace_minutes))))
                except ValueError:
                    grace_minutes = "45"
                policy.set_setting(con, "auto_enabled", auto_enabled)
                policy.set_setting(con, "execute_enabled", execute_enabled)
                policy.set_setting(con, "default_action", default_action)
                policy.set_setting(con, "grace_minutes", grace_minutes)
                msg = "Einstellungen gespeichert."

            auto_enabled = policy.get_setting(con, "auto_enabled", "0")
            execute_enabled = policy.get_setting(con, "execute_enabled", "0")
            default_action = policy.get_setting(con, "default_action", "suspend")
            grace_minutes = policy.get_setting(con, "grace_minutes", "45")

            last = policy.recent_actions(con, 5)
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>Sleep-Automatik</h2>")
        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(ctx.esc(_ui_text(msg)))

        body += _ui_html("""
<form method="post">
<p><label><input type="checkbox" name="auto_enabled" value="1" {auto_checked}> Automatik aktiv</label></p>
<p><label><input type="checkbox" name="execute_enabled" value="1" {exec_checked}> Aktionen wirklich ausführen</label></p>
<p>
<label>
Nachlauftimer:
<input
    type="number"
    name="grace_minutes"
    value="{grace_minutes}"
    min="0"
    max="1440"
    style="width:80px">
 Minuten
</label>
</p>
<p><label>Standardaktion:
<select name="default_action">
<option value="suspend" {suspend_sel}>Suspend</option>
<option value="hibernate" {hibernate_sel}>Hibernate</option>
<option value="poweroff" {poweroff_sel}>Aus / Poweroff</option>
</select>
</label></p>
<p><button class="btn" type="submit">Speichern</button></p>
</form>
""").format(
            auto_checked="checked" if auto_enabled == "1" else "",
            exec_checked="checked" if execute_enabled == "1" else "",
            suspend_sel="selected" if default_action == "suspend" else "",
            hibernate_sel="selected" if default_action == "hibernate" else "",
            poweroff_sel="selected" if default_action == "poweroff" else "",
            grace_minutes=grace_minutes,
        )

        body += _ui_html("<p><b>Status:</b> Automatik {} / Ausführung {}</p>").format(
            _ui_text("aktiv") if auto_enabled == "1" else _ui_text("aus"),
            _ui_text("aktiv") if execute_enabled == "1" else _ui_text("Dry-Run")
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Letzte Runtime-Aktionen</h3>")
        if not last:
            body += _ui_html("<p>Keine Aktionen.</p>")
        else:
            body += _ui_html("<table><tr><th>Zeit</th><th>Aktion</th><th>Modus</th><th>Erlaubt</th><th>Ergebnis</th></tr>")
            for r in last:
                body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                    ctx.esc(r.get("created_at")),
                    ctx.esc(r.get("action")),
                    ctx.esc(_ui_text(r.get("mode"))),
                    ctx.esc(r.get("allowed")),
                    ctx.esc(r.get("result")),
                )
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><p><a class='btn' href='/sleep'>Zurück</a> <a class='btn' href='/sleep/schedules'>Zeitpläne</a></p></div>")
        return ctx.page(_ui_text("Sleep-Automatik"), body, "Schlaf & Wake")

    @app.route("/api/sleep/status")
    def api_sleep_status():
        con = ctx.db()
        try:
#            data = policy.evaluate(con)
            data = evaluate_sleep_with_server_control(con, ctx)
            data["recent_actions"] = policy.recent_actions(con, 10)
        finally:
            con.close()
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")

    @app.route("/sleep")
    def sleep_index():
        con = ctx.db()
        try:
#            data = policy.evaluate(con)
            data = evaluate_sleep_with_server_control(con, ctx)
            recent = policy.recent_actions(con, 10)
        finally:
            con.close()

        body = _ui_html("<div class='grid'>")
        body += ctx.card(_ui_text("Sleep-Check"), "Aktuelle Entscheidung: {}".format(badge(data["may_sleep"])), [("Öffnen", "/sleep/check")])
        body += ctx.card(_ui_text("Automatik"), _ui_html("Sleep-Engine aktivieren, Dry-Run oder echte Ausführung."), [("Öffnen", "/sleep/settings")])
        body += ctx.card(_ui_text("Aktionen"), _ui_html("Suspend, Hibernate, Poweroff kontrolliert ausführen."), [("Öffnen", "/sleep/actions")])
        body += ctx.card(_ui_text("Zeitpläne"), _ui_html("Täglich von/bis mit Aktion Wach, Suspend, Aus oder Hibernate."), [("Öffnen", "/sleep/schedules")])
        body += ctx.card(_ui_text("Server Control"), _ui_html("Blocker und RTC kommen aus Server-Control."), [("Öffnen", "/server-control")])
        body += ctx.card(_ui_text("JSON"), _ui_html("API-Status der Sleep-Engine."), [("Öffnen", "/api/sleep/status")])
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h2>Systembedarf</h2>{}</div>").format(render_systembedarf(ctx, data["blockers"]))
        body += _ui_html("<div class='card'><h2>Letzte Aktionen</h2>{}</div>").format(table_actions(ctx, recent))
        return ctx.page(_ui_text("Schlaf & Wake"), body, "Schlaf & Wake")

    @app.route("/sleep/check")
    def sleep_check():
        con = ctx.db()
        try:
#            data = policy.evaluate(con)
            data = evaluate_sleep_with_server_control(con, ctx)
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>Sleep-Check</h2>")
        body += _ui_html("<p>Schlaf/Ausschalten: <b>{}</b></p>").format(badge(data["may_sleep"]))
        body += _ui_html("<p>Standardaktion: <code>{}</code></p>").format(ctx.esc(data["default_action"]))
        body += _ui_html("<p>Automatik: <code>{}</code></p>").format("aktiv" if data["auto_enabled"] else "aus")
        body += _ui_html("</div>")
        body += _ui_html("<div class='card'><h2>Systembedarf</h2>{}</div>").format(render_systembedarf(ctx, data["blockers"]))
        body += _ui_html("<div class='card'><p><a class='btn' href='/api/sleep/status'>JSON Status</a></p></div>")
        return ctx.page(_ui_text("Sleep-Check"), body, "Schlaf & Wake")

    @app.route("/sleep/actions", methods=["GET", "POST"])
    def sleep_actions():
        msg = ""
        con = ctx.db()
        try:
            if request.method == "POST":
                action = request.form.get("action", "check")
                force = request.form.get("force") == "1"
#                data = policy.evaluate(con)
                data = evaluate_sleep_with_server_control(con, ctx)
                allowed = manual.can_start(data,force)

                if action == "check":
                    policy.record_action(con, "check", data["default_action"], data["may_sleep"], "ok", "check only")
                    msg = "Sleep-Check ausgeführt."
                elif action in ("suspend", "hibernate", "poweroff"):
                    if not allowed:
                        policy.record_action(con, action, action, False, "blocked", "active blockers")
                        msg = "Aktion blockiert: aktive Blocker vorhanden."
                    else:
                        # Sicherheitsstufe: echtes Ausführen nur mit execute=1.
                        execute = request.form.get("execute") == "1"
                        if execute:
                            try:result = manual.start(ctx,action,evaluate_sleep_with_server_control,force)
                            except ValueError as exc:result = {'ok':False,'result':str(exc)}
                        else:
                            result = actions.dry_run(action)
                        policy.record_action(con, action, action, allowed, result.get("result", result.get("ok")), json.dumps(result, ensure_ascii=False))
                        msg = "Aktion verarbeitet: {}".format(action)
                else:
                    msg = "Unbekannte Aktion."

#            data = policy.evaluate(con)
            data = evaluate_sleep_with_server_control(con, ctx)
            recent = policy.recent_actions(con, 30)
            manual_status = manual.state(con)
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>Sleep-Aktionen</h2>")
        if manual_status:
            body += _ui_html("<p><b>Manuelle Server-Aktion: {}</b><br>{}</p>").format(ctx.esc(_ui_text(manual_status.get('state',''))),ctx.esc(_ui_text(manual_status.get('message',''))))
        if manual.active():body += _ui_html("<script>setTimeout(function(){location.replace('/sleep/actions');},3000);</script>")
        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(ctx.esc(_ui_text(msg)))
        body += _ui_html("<p>Aktueller Status: {}</p>").format(badge(data["may_sleep"]))
        body += _ui_html("""
<form method='post'>
<button class='btn' name='action' value='check'>Sleep-Check</button>
<button class='btn' name='action' value='suspend'>Suspend Test</button>
<button class='btn' name='action' value='hibernate'>Hibernate Test</button>
<button class='btn' name='action' value='poweroff'>Poweroff Test</button>
<label><input type='checkbox' name='force' value='1'> Andere Blocker ignorieren (VM-Schutz bleibt)</label>
<label><input type='checkbox' name='execute' value='1'> wirklich ausführen</label>
</form>
<p><small>Ohne „wirklich ausführen“ wird nur ein Dry-Run protokolliert. Bei echter manueller Aktion werden die durch Schlaf & Wake verwalteten VMs sofort regulär heruntergefahren. Der Server wartet auf deren Ende, höchstens fünf Minuten; anschließend wird bei fehlender Freigabe abgebrochen.</small></p>
""")
        body += _ui_html("</div>")
        body += _ui_html("<div class='card'><h2>Systembedarf</h2>{}</div>").format(render_systembedarf(ctx, data["blockers"]))
        body += _ui_html("<div class='card'><h2>Letzte Aktionen</h2>{}</div>").format(table_actions(ctx, recent))
        return ctx.page(_ui_text("Sleep-Aktionen"), body, "Schlaf & Wake")
