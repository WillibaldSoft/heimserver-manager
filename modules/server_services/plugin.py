from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import json
from flask import Response, request, redirect

from . import service


def badge(state):
    s = str(state or "unknown")
    if s == "active":
        return _ui_html("<span class='ok'>aktiv</span>")
    if s in ("failed", "deactivating"):
        return _ui_html("<span class='bad'>%s</span>") % s
    if s in ("inactive", "unknown"):
        return _ui_html("<span class='warn'>%s</span>") % s
    return _ui_html("<span class='warn'>%s</span>") % s


def esc(ctx, value):
    return ctx.esc(value if value is not None else "")


def action_buttons(unit):
    u = unit
    return _ui_html("""
<form method='post' style='display:inline'>
<input type='hidden' name='unit' value='{u}'>
<button class='btn' name='action' value='restart'>Restart</button>
<button class='btn' name='action' value='reload'>Reload</button>
<button class='pill' name='action' value='start'>Start</button>
<button class='pill' name='action' value='stop' onclick="return confirm('Dienst wirklich stoppen?')">Stop</button>
<button class='pill' name='action' value='enable'>Enable</button>
<button class='pill' name='action' value='disable'>Disable</button>
</form>
<a class='pill' href='/server/services/{u}'>Details</a>
<a class='pill' href='/server/services/{u}/log'>Log</a>
""").format(u=u)


def register(app, ctx):
    @app.route('/api/server/services')
    def api_server_services():
        data = {
            "ok": True,
            "units": service.all_status(),
            "failed": service.failed_units(),
        }
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json')

    @app.route('/server/services', methods=['GET', 'POST'])
    def server_services_page():
        msg = ""
        if request.method == 'POST':
            unit = request.form.get('unit', '')
            action = request.form.get('action', '')
            force = request.form.get('force') == '1'
            res = service.service_action(unit, action, force=force)
            if res.get('ok'):
                msg = "Aktion ausgeführt: %s %s" % (action, unit)
            else:
                msg = "Fehler: " + esc(ctx, res.get('error') or res.get('stderr') or res.get('stdout'))

        rows = service.all_status()
        failed = service.failed_units()
        body = _ui_html("<div class='card'><h2>Server-Dienste</h2>")
        body += _ui_html("<p>Status, Neustart, Reload, Aktivierung, Logs und Basisdiagnose wichtiger Serverdienste.</p>")
        if msg:
            body += _ui_html("<p><b>%s</b></p>") % esc(ctx, _ui_text(msg))
        body += _ui_html("<p><a class='btn' href='/server-control'>Server Control</a> <a class='btn' href='/server/services/failed'>Fehlerhafte Units</a> <a class='btn' href='/server/services/timers'>Timer</a> <a class='btn' href='/server/services/sockets'>Sockets</a> <a class='btn' href='/api/server/services'>JSON</a></p>")
        body += _ui_html("</div>")

        if failed:
            body += _ui_html("<div class='card'><h3>Fehlerhafte Units</h3><p class='bad'>%d fehlerhafte Unit(s)</p></div>") % len(failed)

        body += _ui_html("<div class='card'><h3>Wichtige Dienste</h3><table>")
        body += _ui_html("<tr><th>Dienst</th><th>Status</th><th>Enabled</th><th>Beschreibung</th><th>PID</th><th>Aktion</th></tr>")
        for r in rows:
            unit = esc(ctx, r.get('unit'))
            body += _ui_html("<tr>")
            body += _ui_html("<td><code>%s</code></td>") % unit
            body += _ui_html("<td>%s<br><small>%s/%s</small></td>") % (badge(r.get('active')), esc(ctx, r.get('load_state')), esc(ctx, r.get('sub_state')))
            body += _ui_html("<td>%s</td>") % esc(ctx, r.get('enabled'))
            body += _ui_html("<td>%s<br><small>%s</small></td>") % (esc(ctx, r.get('description')), esc(ctx, r.get('fragment_path')))
            body += _ui_html("<td>%s</td>") % esc(ctx, r.get('main_pid'))
            body += _ui_html("<td>%s</td>") % action_buttons(unit)
            body += _ui_html("</tr>")
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Weitere Funktionen</h3>")
        body += _ui_html("<ul>")
        body += _ui_html("<li>Reload statt Restart, wo möglich: weniger Ausfallzeit.</li>")
        body += _ui_html("<li>Enable/Disable für Autostart-Kontrolle.</li>")
        body += _ui_html("<li>Journal-Auszug direkt pro Dienst.</li>")
        body += _ui_html("<li>systemctl cat und Abhängigkeiten zur Ursachenanalyse.</li>")
        body += _ui_html("<li>Fehlerhafte Units, Timer und Sockets als Diagnoseflächen.</li>")
        body += _ui_html("<li>Dienstspezifische Checks: apache configtest, testparm, docker ps, mysqladmin ping.</li>")
        body += _ui_html("</ul></div>")
        return ctx.page(_ui_text("Server-Dienste"), body, "Server")

    @app.route('/server/services/failed')
    def server_services_failed():
        rows = service.failed_units()
        body = _ui_html("<div class='card'><h2>Fehlerhafte systemd Units</h2>")
        if not rows:
            body += _ui_html("<p class='ok'>Keine fehlerhaften Units.</p>")
        else:
            body += _ui_html("<table><tr><th>Unit</th><th>Zeile</th></tr>")
            for r in rows:
                u = esc(ctx, r.get('unit'))
                body += _ui_html("<tr><td><a href='/server/services/%s'>%s</a></td><td><code>%s</code></td></tr>") % (u, u, esc(ctx, r.get('line')))
            body += _ui_html("</table>")
        body += _ui_html("<p><a class='btn' href='/server/services'>Zurück</a></p></div>")
        return ctx.page(_ui_text("Fehlerhafte Units"), body, "Server")

    @app.route('/server/services/timers')
    def server_services_timers():
        out = service.timers()
        body = _ui_html("<div class='card'><h2>systemd Timer</h2><pre>%s</pre><p><a class='btn' href='/server/services'>Zurück</a></p></div>") % esc(ctx, out)
        return ctx.page(_ui_text("systemd Timer"), body, "Server")

    @app.route('/server/services/sockets')
    def server_services_sockets():
        out = service.sockets()
        body = _ui_html("<div class='card'><h2>systemd Sockets</h2><pre>%s</pre><p><a class='btn' href='/server/services'>Zurück</a></p></div>") % esc(ctx, out)
        return ctx.page(_ui_text("systemd Sockets"), body, "Server")

    @app.route('/server/services/<path:unit>')
    def server_service_detail(unit):
        unit = service.normalize_unit(unit)
        st = service.unit_status(unit)
        cat = service.unit_cat(unit)
        deps = service.unit_deps(unit)
        chk = service.health_check(unit)
        body = _ui_html("<div class='card'><h2>%s</h2>") % esc(ctx, unit)
        body += _ui_html("<p>Status: %s / Enabled: <code>%s</code></p>") % (badge(st.get('active')), esc(ctx, st.get('enabled')))
        body += _ui_html("<p>%s</p>") % action_buttons(esc(ctx, unit))
        body += _ui_html("</div>")
        body += _ui_html("<div class='card'><h3>Gesundheitscheck</h3><p><code>%s</code></p><pre>%s\n%s</pre></div>") % (esc(ctx, ' '.join(chk.get('cmd') or [])), esc(ctx, chk.get('stdout')), esc(ctx, chk.get('stderr')))
        body += _ui_html("<div class='card'><h3>Unit-Datei</h3><pre>%s\n%s</pre></div>") % (esc(ctx, cat.get('stdout')), esc(ctx, cat.get('stderr')))
        body += _ui_html("<div class='card'><h3>Abhängigkeiten</h3><pre>%s\n%s</pre></div>") % (esc(ctx, deps.get('stdout')), esc(ctx, deps.get('stderr')))
        body += _ui_html("<div class='card'><p><a class='btn' href='/server/services'>Zurück</a> <a class='btn' href='/server/services/%s/log'>Log</a></p></div>") % esc(ctx, unit)
        return ctx.page(unit, body, "Server")

    @app.route('/server/services/<path:unit>/log')
    def server_service_log(unit):
        unit = service.normalize_unit(unit)
        lines = request.args.get('lines', '120')
        res = service.journal(unit, lines)
        body = _ui_html("<div class='card'><h2>Log: %s</h2>") % esc(ctx, unit)
        body += _ui_html("<p><a class='btn' href='/server/services/%s'>Details</a> <a class='btn' href='/server/services'>Zurück</a></p>") % esc(ctx, unit)
        body += _ui_html("<pre>%s\n%s</pre></div>") % (esc(ctx, res.get('stdout')), esc(ctx, res.get('stderr')))
        return ctx.page(_ui_text("Dienst-Log"), body, "Server")
