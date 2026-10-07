from ui_translation import html_literal as _ui_html, text as _ui_text
import os
# -*- coding: utf-8 -*-
import html
import json
from pathlib import Path
from flask import Response, redirect, request

UPDATE_CACHE_FILE = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app_update_status.json'))
UPDATE_JOB_FILE = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app_update_job.json'))


def esc(x):
    return html.escape(str(x or ""))


def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _update_badge(state):
    if state == "current":
        return "🟢 aktuell"
    if state == "available":
        return "🔴 Update verfügbar"
    if state == "missing":
        return "⚫ nicht prüfbar"
    if state == "not_checked":
        return "⚪ nicht geprüft"
    return "🟡 unbekannt"


def register(app, ctx):
    @app.route("/updates", methods=["GET", "POST"])
    def updates_index():
        if request.method == "POST":
            return redirect("/apps/update-check/run-all", code=307)

        cache = _read_json(UPDATE_CACHE_FILE, {})
        job = _read_json(UPDATE_JOB_FILE, {"running": False, "state": "idle"})

        body = _ui_html("<div class='card'><h2>Update Manager</h2>")
        body += _ui_html("<p>Zeigt den zwischengespeicherten Update-Status der App-Manager-Anwendungen. Prüfungen laufen im Hintergrund.</p>")
        body += _ui_html("<p><form method='post' action='/apps/update-check/run-all' style='display:inline'><button class='btn active' type='submit'>Jetzt alle Updates prüfen</button></form> ")
        body += _ui_html("<a class='btn' href='/apps/update-check/settings'>Zeitplan</a> ")
        body += _ui_html("<a class='btn' href='/api/updates/status'>JSON Status</a></p></div>")

        if job.get("running"):
            done = int(job.get("done") or 0)
            total = int(job.get("total") or 1)
            percent = int(done * 100 / max(total, 1))
            body += _ui_html("<div class='card' style='border-left:5px solid orange'>")
            body += _ui_html("<h3>🔄 Updateprüfung läuft</h3>")
            body += _ui_html("<p>Aktuell: <code>{}</code><br>Fortschritt: <b>{}%</b> ({}/{})</p>").format(
                esc(job.get("current_label") or "—"),
                esc(percent),
                esc(done),
                esc(total),
            )
            body += "<progress value='{}' max='100' style='width:100%'></progress>".format(esc(percent))
            body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>App-Update-Status</h3>")
        body += _ui_html("<table><tr><th>App</th><th>Status</th><th>Geprüft</th><th>Methode</th><th>Hinweis</th></tr>")

        if not cache:
            body += _ui_html("<tr><td colspan='5'><span class='warn'>Noch keine Updateprüfung im Cache.</span></td></tr>")

        for app_id, item in sorted(cache.items()):
            state = item.get("state") or "unknown"
            body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td></tr>").format(
                esc(app_id),
                esc(_update_badge(state)),
                esc(item.get("checked_at") or ""),
                esc(item.get("method") or ""),
                esc(_ui_text(item.get("message")) or ""),
            )

        body += _ui_html("</table></div>")
        body += _ui_html("<div class='card'><p><a class='btn' href='/apps'>Apps</a></p></div>")

        return ctx.page(_ui_text("Update Manager"), body, "Updates")

    @app.route("/api/updates/status")
    def api_updates_status():
        data = {
            "ok": True,
            "cache": _read_json(UPDATE_CACHE_FILE, {}),
            "job": _read_json(UPDATE_JOB_FILE, {"running": False, "state": "idle"}),
        }
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")
