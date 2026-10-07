from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import json
from flask import Response
from modules.server_control.systembedarf import render_systembedarf

def register(app, ctx):
    @app.route("/api/server-control/status")
    def api_server_control_status():
        from modules.server_control.api import status
        ctx.init_db()
        con = ctx.db()
        try:
            data = status(con, ctx)
        finally:
            con.close()
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")

    @app.route("/server-control")
    def server_control_page():
        from modules.server_control.api import status
        ctx.init_db()
        con = ctx.db()
        try:
            data = status(con, ctx)
        finally:
            con.close()

        policy = data["policy"]
        body = _ui_html("<div class='card'><h2>Server Control</h2>")
        if policy["may_sleep"]:
            body += _ui_html("<p class='ok'><b>Schlaf/Ausschalten erlaubt</b></p>")
        else:
            body += _ui_html("<p class='warn'><b>Server muss wach bleiben</b></p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Systembedarf</h3>")
        body += render_systembedarf(ctx, data.get("blockers", []))
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>RTC / nächste Aufnahme</h3>")
        if data.get("next_recording"):
            n = data["next_recording"]
            body += _ui_html("<p>{} – Wake: <code>{}</code>, Ziel: <code>{}</code></p>").format(
                ctx.esc(n.get("title") or "-"),
                ctx.esc(n.get("wake_time") or n.get("wake") or ""),
                ctx.esc(n.get("target_time") or n.get("start") or ""),
            )
        else:
            body += _ui_html("<p>Keine geplante Aufnahme vorhanden.</p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><p><a class='btn' href='/api/server-control/status'>JSON Status</a> <a class='btn' href='/sleep/check'>Sleep-Check</a> <a class='btn' href='/sleep/actions'>Sleep-Aktionen</a></p></div>")
        return ctx.page(_ui_text("Server Control"), body, "Server Control")
