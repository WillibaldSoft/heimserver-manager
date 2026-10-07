from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import html
import json
import os
import secrets
from flask import request, Response, redirect, session

from .status import backup_status
from .helper import script_status, run_script
from .restore import restore_test

def esc(x):
    return html.escape(str(x or ""))

def state_cls(state):
    return "ok" if state == "OK" else ("warn" if state in ("WARN", "LEER") else "err")

def register(app, ctx):
    from .client_api import register as client_register
    client_register(app,ctx)
    from .external_ui import register as external_register
    external_register(app, ctx)
    from .central_ui import register as central_register
    central_register(app, ctx)
    from .daily_ui import register as daily_register
    daily_register(app,ctx)
    @app.route("/backup", methods=["GET", "POST"])
    @app.route("/recovery", methods=["GET", "POST"])
    def backup_index():
        msg = ""
        output = ""

        if request.method == "POST":
            if not secrets.compare_digest(request.form.get("auth_csrf", ""),session.get("auth_csrf", "!")):return "Formular abgelaufen. Bitte neu laden.",403
            action = request.form.get("action", "")
            if action == "run":
                name = request.form.get("script", "")
                result = run_script(name)
                msg = "Backup gestartet/ausgeführt." if result.get("ok") else "Backup fehlgeschlagen."
                output = json.dumps(result, ensure_ascii=False, indent=2)
            elif action == "restore-test":
                path = request.form.get("path", "")
                if path not in {row.get("latest") for row in backup_status()["items"]} or not os.path.isfile(path):return "Nur vorhandene Backup-Dateien können gelesen werden.",400
                result = restore_test(path)
                msg = "Lesetest OK (kein vollständiger Wiederherstellungstest)." if result.get("ok") else "Lesetest fehlgeschlagen."
                output = json.dumps(result, ensure_ascii=False, indent=2)

        data = backup_status()
        token="<input type='hidden' name='auth_csrf' value='"+esc(session.setdefault("auth_csrf",secrets.token_urlsafe(32)))+"'>"

        body = _ui_html("<div class='card'><h2>Backup & Recovery</h2><p><a class='btn' href='/backup/desktop'>Desktop-Clients · Sicherungen und Einrichtung</a></p><p><a class='btn' href='/backup/external'>Externe Gesamtsicherung · inkrementell</a></p><p><a class='btn' href='/backup/daily'>Tägliche Sicherungskette</a></p><p><a class='btn' href='/backup/central'>Server-/Client-Backup und USB-Werkzeug</a></p>")
        body += _ui_html("<p>Status vorhandener Backups und Lesetest für Backup-Dateien.</p>")
        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(esc(_ui_text(msg)))
        body += _ui_html("<p><a class='btn' href='/backup'>Aktualisieren</a> <a class='btn' href='/api/backup/status'>JSON Status</a></p></div>")

        body += _ui_html("<div class='card'><h3>Backup-Status</h3>")
        body += _ui_html("<table><tr><th>Name</th><th>Status</th><th>Alter</th><th>Größe / Sicherungsart</th><th>Letztes Backup</th><th>Lesetest</th></tr>")
        for r in data["items"]:
            latest = r.get("latest") or ""
            body += _ui_html("<tr>")
            body += _ui_html("<td>{}</td>").format(esc(r["name"]))
            body += _ui_html("<td class='{}'>{}</td>").format(state_cls(r["state"]), esc(_ui_text(r["state"])))
            body += _ui_html("<td>{}</td>").format("" if r.get("age_h") is None else str(r["age_h"]) + " h")
            body += _ui_html("<td>{}</td>").format(esc(r.get("size", "")))
            body += _ui_html("<td><small>{}</small></td>").format(esc(latest))
            body += _ui_html("<td>")
            if latest and os.path.isfile(latest):
                body += _ui_html("<form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='restore-test'>")
                body += _ui_html("<input type='hidden' name='path' value='{}'>").format(esc(latest))
                body += _ui_html("<button class='pill' type='submit'>Test</button></form>")
            if latest and os.path.isdir(latest):
                body += _ui_html("Ordnerstand · Rücksicherung im zuständigen Modul")
            if r['state']=='LEER':body += _ui_html("Kein Treffer für das konfigurierte Dateimuster")
            body += _ui_html("</td></tr>")
        body += _ui_html("</table><p>LEER: Der überwachte Ordner existiert, enthält aber keinen Treffer für das konfigurierte Dateimuster. Ein vorhandenes Backup-Skript bestätigt keine erfolgreiche Sicherung. Der Lesetest prüft Dateien, ersetzt jedoch keinen vollständigen Wiederherstellungstest.</p></div>")


        if output:
            body += _ui_html("<div class='card'><h3>Ausgabe</h3><pre>{}</pre></div>").format(esc(output))

        body += _ui_html("<div class='card'><p><a class='btn' href='/'>Übersicht</a> <a class='btn' href='/updates'>Updates</a></p></div>")
        return ctx.page(_ui_text("Backup & Recovery"), body, "Backup")

    @app.route("/api/backup/status")
    @app.route("/api/recovery/status")
    def api_backup_status():
        data = backup_status()
        data["scripts"] = script_status()
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")
