from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import json
from flask import Response, request, redirect

from . import helper


def _badge(state):
    s = str(state or "unknown")
    if s == "active":
        return _ui_html("<span class='ok'>active</span>")
    if s in ("failed", "masked"):
        return _ui_html("<span class='warn'>%s</span>") % s
    return _ui_html("<span>%s</span>") % s


def _html_pre(ctx, value):
    return _ui_html("<pre style='white-space:pre-wrap;max-height:520px;overflow:auto'>%s</pre>") % ctx.esc(value or "")


def _service_table(ctx, rows):
    if not rows:
        return _ui_html("<p>Keine Dienste erkannt.</p>")
    body = _ui_html("""<style>
.server-service-scroll{overflow-x:auto}
.server-service-table{width:100%;min-width:900px;table-layout:fixed}
.server-service-table th,.server-service-table td{vertical-align:top;overflow-wrap:break-word;padding:12px 10px}
.server-service-table th:nth-child(1){width:23%}
.server-service-table th:nth-child(2),.server-service-table th:nth-child(3){width:9%}
.server-service-table th:nth-child(4){width:27%}
.server-service-table th:nth-child(5){width:32%}
.server-service-table code{white-space:normal;overflow-wrap:anywhere}
.service-actions{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.service-actions form{display:contents}
.service-actions .btn{margin:0;padding:6px 10px;min-height:34px;font-size:.9rem}
.service-note{margin-top:8px;font-size:.9rem}
.service-note summary{cursor:pointer;color:var(--link,#93c5fd)}
.service-note p{margin:8px 0;max-width:none}
</style><div class='server-service-scroll'><table class='server-service-table'><tr><th>Dienst</th><th>Status</th><th>Autostart</th><th>Beschreibung</th><th>Aktionen</th></tr>""")
    for r in rows:
        unit = r.get("unit") or ""
        body += _ui_html("<tr>")
        body += _ui_html("<td><code>%s</code></td>") % ctx.esc(unit)
        body += _ui_html("<td>%s</td>") % _badge(r.get("active"))
        body += _ui_html("<td>%s</td>") % ctx.esc(r.get("enabled") or "")
        description = ctx.esc(r.get("description") or "")
        if unit == "multi-dyndns-update.service":
            description += _ui_html("<details class='service-note'><summary>Timerbetrieb erklären</summary><p>DynDNS wird regelmäßig vom Timer gestartet. <code>inactive</code> zwischen den Läufen ist normal; <code>static</code> bedeutet, dass der Autostart über den Timer erfolgt.</p><a href='/dyndns'>DynDNS: Timer, nächster Lauf und Anbieterstatus</a></details>")
        if unit == "openipmi.service":
            description += _ui_html("<details class='service-note'><summary>Optional: IPMI-Hardwareverwaltung</summary><p><b>Optional: lokale IPMI/BMC-Hardwareverwaltung.</b> Nur bei passender Serverhardware benötigt, z. B. für Hardware-Sensoren. Ohne IPMI deaktiviert lassen. Start/Stop steuern den laufenden Dienst; Enable/Disable den Autostart. Deaktiviert ist hier kein Fehler.</p></details>")
        body += _ui_html("<td>%s</td>") % _ui_text(description)
        body += _ui_html("<td><div class='service-actions'>")
        for action, label in [("restart", "Restart"), ("reload", "Reload"), ("start", "Start"), ("stop", "Stop"), ("enable", "Enable"), ("disable", "Disable")]:
            body += _ui_html("<form method='post'><input type='hidden' name='unit' value='%s'><button class='btn' name='action' value='%s'>%s</button></form> ") % (ctx.esc(unit), ctx.esc(action), _ui_text(label))
        body += _ui_html("<a class='btn' href='/server?unit=%s#journal'>Logs</a> ") % ctx.esc(unit)
        body += _ui_html("<a class='btn' href='/server?unit=%s#unitfile'>Unit</a>") % ctx.esc(unit)
        body += _ui_html("</div></td></tr>")
    body += _ui_html("</table></div>")
    return body


def _failed_table(ctx, rows):
    if not rows:
        return _ui_html("<p class='ok'>Keine failed units.</p>")
    body = _ui_html("<table><tr><th>Unit</th><th>Status</th><th>Beschreibung</th></tr>")
    for r in rows:
        body += _ui_html("<tr><td><code>%s</code></td><td class='warn'>%s</td><td>%s</td></tr>") % (
            ctx.esc(r.get("unit") or ""), ctx.esc(_ui_text(r.get("state")) or ""), ctx.esc(r.get("description") or "")
        )
    body += _ui_html("</table>")
    return body


def _checks_table(ctx, rows):
    if not rows:
        return _ui_html("<p>Keine Checks.</p>")
    body = _ui_html("<table><tr><th>Check</th><th>Status</th><th>Details</th></tr>")
    for r in rows:
        cls = "ok" if r.get("ok") else "warn"
        body += _ui_html("<tr><td>%s</td><td class='%s'>%s</td><td>%s</td></tr>") % (
            ctx.esc(r.get("name") or ""), cls, _ui_text("OK") if r.get("ok") else _ui_text("WARN"), ctx.esc(r.get("details") or "")
        )
    body += _ui_html("</table>")
    return body


def _simple_table(ctx, rows, cols):
    if not rows:
        return _ui_html("<p>Keine Einträge.</p>")
    body = _ui_html("<table><tr>") + "".join(_ui_html("<th>%s</th>") % ctx.esc(_ui_text(c[1])) for c in cols) + _ui_html("</tr>")
    for r in rows:
        body += _ui_html("<tr>") + "".join(_ui_html("<td>%s</td>") % ctx.esc(r.get(c[0]) or "") for c in cols) + _ui_html("</tr>")
    body += _ui_html("</table>")
    return body


def register(app, ctx):
    @app.route('/api/server')
    def api_server_phase1():
        data = {
            "ok": True,
            "boot": helper.boot_info(),
            "services": helper.service_rows(),
            "failed": helper.failed_units(),
            "checks": helper.checks(),
            "docker": helper.docker_info(),
            "kvm": helper.kvm_info(),
            "processes": helper.top_processes(),
        }
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")

    @app.route('/server', methods=['GET', 'POST'])
    def server_phase1_page():
        msg = ""
        if request.method == 'POST':
            action = request.form.get('action') or ''
            unit = request.form.get('unit') or ''
            tool = request.form.get('tool') or ''
            if tool:
                res = helper.system_tool(tool)
                msg = "Werkzeug %s: %s" % (tool, "OK" if res.get("ok") else (res.get("stderr") or "Fehler"))
            elif action and unit:
                res = helper.service_action(action, unit)
                msg = "%s %s: %s" % (action, unit, "OK" if res.get("ok") else (res.get("stderr") or "Fehler"))

        selected_unit = request.args.get('unit') or 'server-manager.service'
        services = helper.service_rows()
        failed = helper.failed_units()
        boot = helper.boot_info()
        checks = helper.checks()
        docker = helper.docker_info()
        kvm = helper.kvm_info()
        procs = helper.top_processes()
        timers = helper.timers()
        sockets = helper.sockets()
        journal = helper.journal(selected_unit, 80)
        unit_file = helper.unit_file(selected_unit)
        deps = helper.dependencies(selected_unit)

        body = _ui_html("<div class='card'><h2>Server</h2>")
        body += _ui_html("<p>Systemzentrale: Dienste, Logs, Boot, Docker, KVM, Prozesse und Diagnose.</p>")
        if msg:
            body += _ui_html("<p><b>%s</b></p>") % ctx.esc(_ui_text(msg))
        body += _ui_html("<p><a class='btn' href='/api/server'>JSON Status</a></p>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='grid'>")
        body += ctx.card(_ui_text("Boot"), _ui_html("Uptime: <b>%s</b><br>Kernel: <code>%s</code><br>Reboot nötig: <b>%s</b>") % (
            ctx.esc(boot.get('uptime') or '-'), ctx.esc(boot.get('kernel') or '-'), ctx.esc(boot.get('reboot_required') or _ui_text('nein'))
        ), [])
        body += ctx.card(_ui_text("Fehler"), _ui_html("Failed units: <b>%s</b>") % len(failed), [])
        body += ctx.card(_ui_text("Docker"), _ui_html("Status: <b>%s</b><br>Container: <b>%s</b>") % (
            ctx.esc(docker.get('active') or '-'), ctx.esc(docker.get('containers') or '-')
        ), [])
        body += ctx.card(_ui_text("KVM"), _ui_html("Status: <b>%s</b><br>VMs: <b>%s</b>") % (
            ctx.esc(kvm.get('active') or '-'), ctx.esc(kvm.get('vms') or '-')
        ), [])
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h2>Dienste</h2>%s</div>") % _service_table(ctx, services)
        body += _ui_html("<div class='card'><h2>Checks</h2>%s</div>") % _checks_table(ctx, checks)
        body += _ui_html("<div class='card'><h2>Failed Units</h2>%s</div>") % _failed_table(ctx, failed)

        body += _ui_html("<div class='card'><h2>Werkzeuge</h2>")
        for tool, label in [("daemon-reload", "daemon-reload"), ("reset-failed", "reset-failed"), ("apt-clean", "apt clean"), ("journal-vacuum", "Journal 14 Tage behalten")]:
            body += _ui_html("<form method='post' style='display:inline'><button class='btn' name='tool' value='%s'>%s</button></form> ") % (tool, _ui_text(label))
        body += _ui_html("</div>")

        body += _ui_html("<div class='card' id='journal'><h2>Journal: <code>%s</code></h2>") % ctx.esc(selected_unit)
        body += _html_pre(ctx, "\n".join(journal.get('lines') or []))
        body += _ui_html("</div>")

        body += _ui_html("<div class='card' id='unitfile'><h2>Unit-Datei: <code>%s</code></h2>") % ctx.esc(selected_unit)
        body += _html_pre(ctx, unit_file.get('content') or unit_file.get('error') or '')
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h2>Abhängigkeiten</h2>")
        body += _html_pre(ctx, "\n".join(deps if isinstance(deps, list) else []))
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h2>Prozesse Top CPU/RAM</h2>%s</div>") % _simple_table(ctx, procs, [("pid", "PID"), ("cpu", "CPU"), ("mem", "RAM"), ("cmd", "Prozess")])
        body += _ui_html("<div class='card'><h2>Timer</h2>%s</div>") % _simple_table(ctx, timers, [("unit", "Timer"), ("next", "Nächster Lauf"), ("left", "In"), ("active", "Status")])
        body += _ui_html("<div class='card'><h2>Sockets</h2>%s</div>") % _simple_table(ctx, sockets, [("unit", "Socket"), ("listen", "Listen"), ("active", "Status")])

        return ctx.page(_ui_text("Server"), body, "Server")
