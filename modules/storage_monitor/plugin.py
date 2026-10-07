from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import html, json, secrets, subprocess
from flask import request, redirect, Response, session
from .disks import df_rows, disks_summary, mounted_devices, mount_candidates, mount_description
from .smart import smart_rows
from .monitor import check_storage
from .helpers import run, setting, set_setting, HELPER


def esc(x): return html.escape(str(x or ''))

def cls_status(s):
    return 'ok' if s == 'OK' else ('bad' if s == 'FAIL' else 'warn')

def pct_bar(pct):
    try: pct=int(pct or 0)
    except Exception: pct=0
    return _ui_html("<div class=bar><span style='width:{}%'></span></div>").format(max(0,min(100,pct)))


def register(app, ctx):
    @app.route('/speicher', strict_slashes=False)
    @app.route('/storage', strict_slashes=False)
    def storage_index():
        temp_warn = int(setting(ctx, 'temp_warn_c', '55') or '55')
        df = df_rows(); disks = disks_summary(); mounted=mounted_devices(); cand=mount_candidates(); smart=smart_rows(temp_warn); chk=check_storage(ctx, send=False)
        body = _ui_html("<div class='card'><h2>Speicher & SMART</h2>")
        body += _ui_html("<p>Speicherbelegung, Datenträger, SMART-Überwachung, ungemountete Partitionen und ntfy-Warnungen.</p>")
        body += _ui_html("<p><a class='btn' href='/speicher/check'>Prüfung ausführen</a> <a class='btn' href='/speicher/settings'>Einstellungen</a> <a class='btn' href='/api/speicher/status'>JSON</a></p>")
        if chk['problem_count']:
            body += _ui_html("<p class='warn'><b>{} Warnungen gefunden.</b></p>").format(chk['problem_count'])
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Speicherbelegung</h3><table><tr><th>Mount</th><th>Dateisystem</th><th>Größe</th><th>Benutzt</th><th>Frei</th><th>%</th><th>Balken</th></tr>")
        warn_pct = int(setting(ctx, 'disk_warn_percent', '90') or '90')
        for r in df:
            c = 'warn' if int(r['pct']) >= warn_pct else 'ok'
            body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td></tr>").format(esc(r['mount']), esc(r['fs']), esc(r['size']), esc(r['used']), esc(r['avail']), c, esc(r['use']), pct_bar(r['pct']))
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Alle Festplatten</h3><table><tr><th>Gerät</th><th>Mount-Name / Mountpunkt</th><th>Modell</th><th>Größe</th><th>Typ</th><th>Seriennummer</th></tr>")
        for d in disks:
            body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><small>{}</small></td></tr>").format(esc(d['path']), esc(mount_description(d)), esc((d.get('vendor','')+' '+d.get('model','')).strip()), esc(d['size']), esc(d.get('tran','')), esc(d.get('serial','')))
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Gemountete Partitionen</h3><table><tr><th>Gerät</th><th>Mount</th><th>Dateisystem</th><th>Label</th><th>UUID</th><th>Aktion</th></tr>")
        for m in mounted:
            body += _ui_html("<tr><td><code>{}</code></td><td><code>{}</code></td><td>{}</td><td>{}</td><td><small>{}</small></td></tr>").format(esc(m['path']), esc(m['mount']), esc(m['fstype']), esc(_ui_text(m['label'])), esc(m['uuid']))
            token=session.setdefault('auth_csrf',secrets.token_urlsafe(32))
            action=_ui_html("<form method='post' action='/speicher/unmount'><input type='hidden' name='auth_csrf' value='{}'><input type='hidden' name='device' value='{}'><input type='hidden' name='mountpoint' value='{}'><button class='btn'>Aushängen…</button></form>").format(esc(token),esc(m['path']),esc(m['mount']))
            body=body[:-5]+_ui_html('<td>')+action+_ui_html('</td></tr>')
        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Nicht gemountete Partitionen</h3>")
        body += _ui_html("<p>Diese Geräte haben ein Dateisystem, aber aktuell keinen Mountpunkt. Beim Mounten wird ein Administrator-/sudo-Passwort abgefragt.</p>")
        if not cand:
            body += _ui_html("<p>Keine mountbaren ungemounteten Partitionen gefunden.</p>")
        else:
            body += _ui_html("<table><tr><th>Gerät</th><th>Größe</th><th>FS</th><th>Label</th><th>UUID</th><th>Mounten</th></tr>")
            for c in cand:
                default_mp = '/mnt/' + (c.get('label') or c.get('name') or 'disk')
                body += _ui_html("<tr><form method='post' action='/speicher/mount'>")
                body += _ui_html("<td><code>{}</code><input type='hidden' name='device' value='{}'></td>").format(esc(c['path']), esc(c['path']))
                body += _ui_html("<td>{}</td><td>{}</td><td>{}</td><td><small>{}</small></td>").format(esc(c['size']), esc(c['fstype']), esc(_ui_text(c['label'])), esc(c['uuid']))
                body += _ui_html("<td><input name='mountpoint' value='{}' style='width:220px'> <button class='btn' type='submit'>Mounten…</button></td>").format(esc(default_mp))
                body += _ui_html("</form></tr>")
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>SMART</h3><table><tr><th>Gerät</th><th>Mount-Name / Mountpunkt</th><th>Status</th><th>Temp</th><th>Power-On</th><th>Reallocated</th><th>Pending</th><th>Uncorr</th><th>NVMe used</th><th>Media Errors</th><th>Aktion</th></tr>")
        for r in smart:
            c=cls_status(r['status'])
            body += _ui_html("<tr><td><code>{}</code></td><td>{}</td><td class='{}'>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><a class='pill' href='/speicher/smart?dev={}'>Details</a></td></tr>").format(esc(r['dev']), esc(mount_description(r)), c, esc(_ui_text(r['status'])), esc(r['temp']), esc(r['poh']), esc(r['realloc']), esc(r['pending']), esc(r['uncorr']), esc(r['used']), esc(r['media']), esc(r['dev']))
        body += _ui_html("</table></div>")
        return ctx.page(_ui_text('Speicher'), body, 'Speicher')

    @app.route('/speicher/unmount', methods=['POST'])
    def storage_unmount():
        if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):
            return 'Formular abgelaufen.',403
        dev=request.form.get('device','');mp=request.form.get('mountpoint','')
        if not any(m['path']==dev and m['mount']==mp for m in mounted_devices()):
            return ctx.page(_ui_text('Aushängen'), _ui_html('<p>Mount-Zuordnung geändert. Speicherübersicht neu laden.</p>'), 'Speicher'),400
        if request.form.get('confirm')=='1':
            try:
                result=subprocess.run(['sudo','-S','-p','',str(HELPER),'unmount',dev,mp],input=request.form.get('password','')+'\n',text=True,capture_output=True,timeout=75)
                message='Erfolgreich ausgehängt.' if result.returncode==0 else 'Aushängen fehlgeschlagen. Belegte Datenträger werden nicht erzwungen ausgehängt. '+result.stderr
            except subprocess.TimeoutExpired:
                message='Zeitüberschreitung. Mount-Zustand bitte erneut prüfen.'
            return ctx.page(_ui_text('Aushängen'),_ui_html("<div class='card'><h2>Aushängen</h2><p>")+esc(_ui_text(message))+_ui_html("</p><a class='btn' href='/speicher'>Zur Speicherübersicht</a></div>"),'Speicher')
        body=_ui_html("<div class='card'><h2>Partition aushängen</h2><p>Gerät: <code>{}</code><br>Mountpunkt: <code>{}</code></p>").format(esc(dev),esc(mp))
        body+=_ui_html("<p>Zugriffe auf diese Partition vorher beenden. Systemverzeichnisse sind geschützt; belegte Mounts werden ohne Zwang abgewiesen. Daten und fstab-Eintrag bleiben erhalten. Beim Neustart kann die Partition wieder automatisch eingehängt werden.</p>")
        body+=_ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='{}'><input type='hidden' name='device' value='{}'><input type='hidden' name='mountpoint' value='{}'><input type='hidden' name='confirm' value='1'><label>sudo-Passwort <input type='password' name='password' autocomplete='current-password'></label><button class='btn'>Jetzt aushängen</button></form><a href='/speicher'>Abbrechen</a></div>").format(esc(session['auth_csrf']),esc(dev),esc(mp))
        return ctx.page(_ui_text('Aushängen'),body,'Speicher')

    @app.route('/speicher/mount', methods=['POST'])
    def storage_mount_confirm():
        dev=request.form.get('device',''); mp=request.form.get('mountpoint','')
        body=_ui_html("<div class='card'><h2>Partition mounten</h2>")
        body+=_ui_html("<p>Es wird ein dauerhaftes Mountziel angelegt. Das Helper-Skript nutzt sudo-Rechte und fragt hier das sudo-Passwort ab.</p>")
        body+=_ui_html("<form method='post' action='/speicher/mount/apply'>")
        body+=_ui_html("<table>")
        body+=_ui_html("<tr><td>Gerät</td><td><code>{}</code><input type='hidden' name='device' value='{}'></td></tr>").format(esc(dev), esc(dev))
        body+=_ui_html("<tr><td>Mountpunkt</td><td><input name='mountpoint' value='{}' style='width:95%'></td></tr>").format(esc(mp))
        body+=_ui_html("<tr><td>Dauerhaft in fstab</td><td><select name='persist'><option value='1'>Ja, per UUID eintragen</option><option value='0'>Nein, nur jetzt mounten</option></select></td></tr>")
        body+=_ui_html("<tr><td>sudo Passwort</td><td><input name='password' type='password' autocomplete='current-password'></td></tr>")
        body+=_ui_html("</table><p><button class='btn' type='submit'>Jetzt mounten</button> <a class='btn' href='/speicher'>Abbrechen</a></p></form></div>")
        return ctx.page(_ui_text('Mount bestätigen'), body, 'Speicher')

    @app.route('/speicher/mount/apply', methods=['POST'])
    def storage_mount_apply():
        dev=request.form.get('device',''); mp=request.form.get('mountpoint',''); pw=request.form.get('password',''); persist=request.form.get('persist','1')
        cmd=['sudo','-S',str(HELPER),'mount',dev,mp,persist]
        p = run(['bash','-lc', "printf %s " + repr(pw+'\n') + " | " + ' '.join(__import__('shlex').quote(x) for x in cmd)], timeout=60)
        body=_ui_html("<div class='card'><h2>Mount-Ergebnis</h2>")
        body+=_ui_html("<p>Status: <b>{}</b></p><h3>Ausgabe</h3><pre>{}</pre><h3>Fehler</h3><pre>{}</pre>").format(_ui_text('OK') if p['ok'] else _ui_text('Fehler'), esc(p['out']), esc(_ui_text(p['err'])))
        body+=_ui_html("<p><a class='btn' href='/speicher'>Zurück</a></p></div>")
        return ctx.page(_ui_text('Mount Ergebnis'), body, 'Speicher')

    @app.route('/speicher/smart')
    def storage_smart_detail():
        dev=request.args.get('dev','')
        if dev not in {d['path'] for d in disks_summary()}:return ctx.page(_ui_text('SMART'),_ui_html('<p>Datenträger nicht gefunden.</p>'),'Speicher'),400
        short=run(['sudo','/usr/sbin/smartctl','-H',dev], timeout=15)
        attr=run(['sudo','/usr/sbin/smartctl','-A',dev], timeout=20)
        info=run(['sudo','/usr/sbin/smartctl','-i',dev], timeout=15)
        identity = next((d for d in disks_summary() if d['path'] == dev), {})
        body=_ui_html("<div class='card'><h2>SMART {}</h2><p>Mount-Name / Mountpunkt: {}</p>").format(esc(dev), esc(mount_description(identity)))
        body+=_ui_html("<p><a class='btn' href='/speicher'>Zurück</a> <a class='btn' href='/speicher/smart-test?type=short&dev={}'>Kurztest starten</a> <a class='btn' href='/speicher/smart-test?type=long&dev={}'>Langtest starten</a></p>").format(esc(dev), esc(dev))
        body+=_ui_html("<h3>Info</h3><pre>{}</pre><h3>Health</h3><pre>{}</pre><h3>Attribute</h3><pre>{}</pre></div>").format(esc(info['out'] or info['err']), esc(short['out'] or short['err']), esc(attr['out'] or attr['err']))
        return ctx.page(_ui_text('SMART Details'), body, 'Speicher')

    @app.route('/speicher/smart-test')
    def storage_smart_test():
        dev=request.args.get('dev',''); typ=request.args.get('type','short')
        if typ not in ('short','long'):
            typ='short'
        r=run(['sudo','/usr/sbin/smartctl','-t',typ,dev], timeout=20)
        body=_ui_html("<div class='card'><h2>SMART-Test</h2><pre>{}</pre><pre>{}</pre><p><a class='btn' href='/speicher/smart?dev={}'>Zurück</a></p></div>").format(esc(r['out']), esc(r['err']), esc(dev))
        return ctx.page(_ui_text('SMART-Test'), body, 'Speicher')

    @app.route('/speicher/check')
    def storage_check():
        send=False
        res=check_storage(ctx, send=send)
        body=_ui_html("<div class='card'><h2>Speicherprüfung</h2><p>Probleme: <b>{}</b></p>").format(res['problem_count'])
        body+=_ui_html("<p><a class='btn' href='/alarme'>Alarme & ntfy</a> <a class='btn' href='/speicher'>Zurück</a></p>")
        if res['problems']:
            body+=_ui_html("<table><tr><th>Typ</th><th>Level</th><th>Meldung</th></tr>")
            for p in res['problems']:
                body+=_ui_html("<tr><td>{}</td><td>{}</td><td>{}</td></tr>").format(esc(p['type']), esc(p['level']), esc(p['text']))
            body+=_ui_html("</table>")
        body+=_ui_html("</div>")
        return ctx.page(_ui_text('Speicherprüfung'), body, 'Speicher')

    def smart_config_call(action):
        if action not in ('smart-preview', 'smart-apply'):
            return {
                'ok': False,
                'error': 'Ungültige SMART-Aktion.',
            }

        result = run(
            [
                'sudo',
                '-n',
                str(HELPER),
                action,
            ],
            timeout=180,
        )

        raw = result.get('out', '').strip()

        try:
            data = json.loads(raw or '{}')
        except Exception:
            data = {
                'ok': False,
                'error': (
                    result.get('err')
                    or raw
                    or 'Ungültige Antwort des SMART-Helpers.'
                ),
            }

        if not result.get('ok') and data.get('ok', True):
            data['ok'] = False
            data['error'] = (
                result.get('err')
                or 'SMART-Helper fehlgeschlagen.'
            )

        return data


    def smart_size_human(value):
        try:
            value = float(value or 0)
        except Exception:
            value = 0

        units = ['B', 'KB', 'GB', 'TB', 'PB']
        index = 0

        while value >= 1024 and index < len(units) - 1:
            value /= 1024.0
            index += 1

        if index == 0:
            return '{} {}'.format(int(value), units[index])

        if value >= 10:
            return '{:.0f} {}'.format(value, units[index])

        return '{:.1f} {}'.format(value, units[index])


    def smart_device_table(items, status_label='Vorhanden'):
        if not items:
            return _ui_html("<p>Keine Einträge.</p>")

        body = (
            _ui_html("<table>"
            "<tr>"
            "<th>Status</th>"
            "<th>Name</th>"
            "<th>Gerät</th>"
            "<th>Modell</th>"
            "<th>Größe</th>"
            "<th>Mountpunkte</th>"
            "<th>Seriennummer</th>"
            "<th>SMART-Typ</th>"
            "</tr>")
        )

        for item in items:
            capable = item.get('smart_capable', True)

            if status_label == 'Entfernt':
                css = 'bad'
                status = 'Entfernt'
            elif not capable:
                css = 'warn'
                status = 'Nicht unterstützt'
            elif item.get('managed') is False:
                css = 'warn'
                status = 'Temporär'
            else:
                css = 'ok'
                status = status_label

            mountpoints = item.get('mountpoints') or []

            if isinstance(mountpoints, list):
                mount_text = ', '.join(mountpoints)
            else:
                mount_text = str(mountpoints)

            body += (
                _ui_html("<tr>"
                "<td class='{css}'>{status}</td>"
                "<td><b>{name}</b></td>"
                "<td><code>{device}</code><br>"
                "<small><code>{by_id}</code></small></td>"
                "<td>{model}</td>"
                "<td>{size}</td>"
                "<td>{mounts}</td>"
                "<td><small>{serial}</small></td>"
                "<td><code>{dtype}</code><br><small>{reason}</small></td>"
                "</tr>")
            ).format(
                css=css,
                status=esc(_ui_text(status)),
                name=esc(item.get('name') or item.get('id') or ''),
                device=esc(item.get('device') or item.get('path') or ''),
                by_id=esc(item.get('by_id') or item.get('path') or ''),
                model=esc(item.get('model') or ''),
                size=esc(
                    smart_size_human(item.get('size'))
                    if item.get('size') is not None
                    else ''
                ),
                mounts=esc(mount_text or '–'),
                serial=esc(item.get('serial') or ''),
                dtype=esc(item.get('type') or ''),
                reason=esc(item.get('managed_reason') or ''),
            )

        body += _ui_html("</table>")
        return body


    @app.route('/speicher/settings', methods=['GET', 'POST'])
    def storage_settings():
        msg = ''
        smart_data = None

        if request.method == 'POST':
            action = request.form.get('action', 'save-settings')

            if action == 'save-settings':
                return redirect('/alarme',303)

            elif action == 'smart-preview':
                smart_data = smart_config_call('smart-preview')

            elif action == 'smart-apply':
                smart_data = smart_config_call('smart-apply')

            else:
                msg = 'Unbekannte Aktion.'

        if smart_data is None:
            smart_data = smart_config_call('smart-preview')

        body = _ui_html("<div class='card'><h2>Speicher-Einstellungen</h2><p>ntfy und Warnschwellen werden jetzt zentral unter <a class='btn' href='/alarme'>Alarme</a> verwaltet.</p></div>")
        body += _ui_html("<div class='card'><h2>SMART-Konfiguration</h2>")
        body += (
            _ui_html("<p>"
            "Die Konfiguration wird aus den aktuell vorhandenen HDDs, SSDs "
            "und NVMe-Laufwerken neu aufgebaut. Nicht mehr vorhandene "
            "Laufwerke werden entfernt."
            "</p>")
        )

        service = smart_data.get('service') or {}
        active = service.get('active', 'unbekannt')
        enabled = service.get('enabled', 'unbekannt')

        active_class = 'ok' if active == 'active' else 'bad'

        body += (
            _ui_html("<table>"
            "<tr><td>Dienst</td><td class='{active_class}'><b>{active}</b></td></tr>"
            "<tr><td>Autostart</td><td>{enabled}</td></tr>"
            "<tr><td>Erkannte Datenträger</td><td><b>{detected_count}</b></td></tr>"
            "<tr><td>Dauerhaft überwacht</td><td><b>{smart_count}</b> SMART-Laufwerke</td></tr>"
            "<tr><td>Bisher konfiguriert</td><td>{existing_count} Laufwerke</td></tr>"
            "</table>")
        ).format(
            active_class=active_class,
            active=esc(active),
            enabled=esc(enabled),
            detected_count=esc(
                smart_data.get(
                    'detected_count',
                    len(smart_data.get('devices') or []),
                )
            ),
            smart_count=esc(smart_data.get('smart_count', 0)),
            existing_count=esc(smart_data.get('existing_count', 0)),
        )

        if smart_data.get('ok'):
            message = smart_data.get('message')

            if message:
                body += _ui_html("<p class='ok'><b>{}</b></p>").format(
                    esc(_ui_text(message))
                )

            if smart_data.get('mode') == 'smart-apply':
                body += (
                    _ui_html("<p>"
                    "Neu: <b>{}</b> · "
                    "Entfernt: <b>{}</b> · "
                    "Unverändert: <b>{}</b>"
                    "</p>")
                ).format(
                    len(smart_data.get('added') or []),
                    len(smart_data.get('removed') or []),
                    len(smart_data.get('unchanged') or []),
                )

                backup = smart_data.get('backup')

                if backup:
                    body += (
                        _ui_html("<p>Sicherung: <code>{}</code></p>")
                    ).format(
                        esc(backup)
                    )

        else:
            body += (
                _ui_html("<p class='bad'><b>SMART-Konfigurationsfehler:</b> {}</p>")
            ).format(
                esc(
                    _ui_text(smart_data.get('error'))
                    or _ui_text('Unbekannter Fehler')
                )
            )

            if smart_data.get('rollback_done'):
                body += (
                    _ui_html("<p class='warn'>"
                    "Die vorherige Konfiguration wurde automatisch "
                    "wiederhergestellt."
                    "</p>")
                )

        body += (
            _ui_html("<form method='post' style='display:inline-block;margin-right:8px'>"
            "<input type='hidden' name='action' value='smart-preview'>"
            "<button class='btn' type='submit'>Vorschau aktualisieren</button>"
            "</form>")
        )

        body += (
            _ui_html("<form method='post' style='display:inline-block' "
            "onsubmit=\"return confirm('SMART-Konfiguration aus den aktuell vorhandenen Laufwerken neu erzeugen?');\">"
            "<input type='hidden' name='action' value='smart-apply'>"
            "<button class='btn' type='submit'>"
            "Vorhandene Laufwerke neu einlesen und übernehmen"
            "</button>"
            "</form>")
        )

        body += _ui_html("</div>")

        devices = smart_data.get('devices') or []

        body += _ui_html("<div class='card'><h3>Aktuell vorhandene Laufwerke</h3>")
        body += smart_device_table(devices, 'Vorhanden')
        body += _ui_html("</div>")

        removed = smart_data.get('removed') or []

        if removed:
            body += _ui_html("<div class='card'><h3>Nicht mehr vorhandene Laufwerke</h3>")
            body += (
                _ui_html("<p>Diese Einträge werden beim Übernehmen aus "
                "<code>/etc/smartd.conf</code> entfernt.</p>")
            )
            body += smart_device_table(removed, 'Entfernt')
            body += _ui_html("</div>")

        added = smart_data.get('added') or []

        if added:
            body += _ui_html("<div class='card'><h3>Neue Laufwerke</h3>")
            body += smart_device_table(added, 'Neu')
            body += _ui_html("</div>")

        history = smart_data.get('history') or []

        body += _ui_html("<div class='card'><h3>SMART-Konfigurationsverlauf</h3>")

        if not history:
            body += _ui_html("<p>Noch keine Aktualisierungen protokolliert.</p>")
        else:
            body += (
                _ui_html("<table>"
                "<tr>"
                "<th>Zeitpunkt</th>"
                "<th>Status</th>"
                "<th>Laufwerke</th>"
                "<th>Neu</th>"
                "<th>Entfernt</th>"
                "<th>Hinweis</th>"
                "</tr>")
            )

            for entry in history:
                status = entry.get('status', '')
                css = 'ok' if status == 'success' else 'bad'

                hint = (
                    entry.get('backup')
                    or entry.get('error')
                    or ''
                )

                body += (
                    _ui_html("<tr>"
                    "<td>{timestamp}</td>"
                    "<td class='{css}'>{status}</td>"
                    "<td>{devices}</td>"
                    "<td>{added}</td>"
                    "<td>{removed}</td>"
                    "<td><small>{hint}</small></td>"
                    "</tr>")
                ).format(
                    timestamp=esc(entry.get('timestamp', '')),
                    css=css,
                    status=esc(_ui_text(status)),
                    devices=esc(entry.get('devices', '')),
                    added=esc(entry.get('added', '')),
                    removed=esc(entry.get('removed', '')),
                    hint=esc(_ui_text(hint)),
                )

            body += _ui_html("</table>")

        body += _ui_html("</div>")

        return ctx.page(
            _ui_text('Speicher Einstellungen'),
            body,
            'Speicher',
        )


    @app.route('/api/speicher/status')
    def api_storage_status():
        temp_warn=int(setting(ctx,'temp_warn_c','55') or '55')
        data={'ok':True,'df':df_rows(),'disks':disks_summary(),'mounted':mounted_devices(),'unmounted':mount_candidates(),'smart':smart_rows(temp_warn),'check':check_storage(ctx,send=False)}
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json')
