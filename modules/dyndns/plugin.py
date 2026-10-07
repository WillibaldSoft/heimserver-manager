"""DynDNS setup, legacy preview, scheduled operation and per-provider status."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,html,io,json,secrets,threading,time,zipfile
from pathlib import Path
from flask import request,session,redirect,Response
from . import engine as e

STYLE="""<style>.dd-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.dd-form{max-width:850px}.dd-form label{display:block;margin:16px 0 6px;font-weight:600}.dd-form input:not([type=checkbox]):not([type=hidden]),.dd-form select{display:block;width:100%;box-sizing:border-box;background:#111c2c;color:#edf2fa;border:1px solid #526075;border-radius:8px;padding:10px;margin-top:6px}.dd-help{color:#b8c6da}.dd-error{border-left:4px solid #ff9c9c;padding:14px}.dd-table{overflow:auto}.dd-table td{vertical-align:top}.dd-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.dd-actions form{margin:0}.dd-form button{margin-top:18px}code{overflow-wrap:anywhere}</style>"""
def esc(value):return html.escape(str(value if value is not None else ''),quote=True)
def token():
    if 'dyndns_csrf' not in session:session['dyndns_csrf']=secrets.token_urlsafe(32)
    return "<input type='hidden' name='csrf' value='"+esc(session['dyndns_csrf'])+"'>"
def hidden(key,value):return "<input type='hidden' name='"+esc(key)+"' value='"+esc(value)+"'>"
def field(key,label,value='',kind='text',hint=''):
    return _ui_html('<label>')+esc(_ui_text(label))+_ui_html("<input type='")+kind+"' name='"+key+"' value='"+esc(value)+_ui_html("' autocomplete='off'></label><p class='dd-help'>")+esc(_ui_text(hint))+_ui_html('</p>')
def select(key,label,options,value):
    return _ui_html('<label>')+esc(_ui_text(label))+_ui_html("<select name='")+key+"'>"+''.join(_ui_html("<option value='")+esc(k)+"'"+(' selected' if str(k)==str(value) else '')+'>'+esc(v)+_ui_html('</option>') for k,v in options)+_ui_html('</select></label>')
def action(value,label,extra=''):
    return _ui_html("<form method='post' action='/dyndns/action'>")+token()+hidden('action',value)+extra+_ui_html("<button class='btn'>")+esc(_ui_text(label))+_ui_html('</button></form>')
def stamp(value):return time.strftime('%d.%m.%Y %H:%M:%S',time.localtime(value)) if value else 'Noch nicht gelaufen'
def legacy_revision():
    digest=hashlib.sha256()
    for path in sorted(e.LEGACY.rglob('*.conf')):
        if path.is_file():digest.update(str(path).encode());digest.update(path.read_bytes())
    return digest.hexdigest()

def register(app,ctx):
    def page(title,body):return ctx.page(title,STYLE+_ui_html("<div class='card dd-actions'><a class='btn' href='/dyndns'>Übersicht</a><a class='btn' href='/dyndns/targets'>Ziele & Dienste</a><a class='btn' href='/dyndns/edit'>Anbieter hinzufügen</a><a class='btn' href='/dyndns/settings'>Zeitplan & IP-Ermittlung</a><a class='btn' href='/dyndns/import'>Bestehendes Skript übernehmen</a><a class='btn' href='/dyndns/download'>Angepasstes Skript herunterladen</a></div>")+body,'DynDNS')
    def fail(exc):return page(_ui_text('DynDNS'),_ui_html("<div class='card dd-error'>")+esc(_ui_text(exc))+_ui_html("</div><a class='btn' href='/dyndns'>Zur Übersicht</a>")),400
    @app.before_request
    def dyndns_guard():
        if request.path.startswith('/dyndns') and request.method not in ('GET','HEAD','OPTIONS'):
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('dyndns_csrf','!')):return page(_ui_text('DynDNS'), _ui_html('<div class=card>Formular abgelaufen. Bitte Seite neu laden.</div>')),403
    @app.after_request
    def dyndns_headers(response):
        if request.path.startswith('/dyndns'):response.headers['Cache-Control']='no-store'
        return response
    from . import targets
    targets.register(app,page,token,hidden,field,select,esc)
    @app.route('/dyndns',endpoint='dyndns_overview')
    def overview():
        try:
            revision=e.revision();cfg=e.load();status=e.unit_status();managed=e.managed();msg=session.pop('dyndns_notice','')
            body=_ui_html("<div class='card'><h2>DynDNS · Erreichbar trotz wechselnder IP</h2><p>Hostnamen, Anbieter und Aktualisierungen an einem Ort verwalten.</p>")+(_ui_html('<p>')+esc(_ui_text(msg))+_ui_html('</p>') if msg else '')
            body+=_ui_html('<p><b>Betrieb:</b> ')+(_ui_text('Integrierter Update-Kern') if managed else _ui_text('Bisheriges Skript / noch nicht übernommen'))+' · Timer: '+esc(status['timer'].get('ActiveState',_ui_text('unbekannt')))+_ui_html(' · Nächster Lauf: ')+esc(status['timer'].get('NextElapseUSecRealtime') or _ui_text('nicht geplant'))+_ui_html('</p>')
            if not managed:body+=_ui_html("<p>Der bisherige Timer bleibt unverändert. Über „Bestehendes Skript übernehmen“ werden Anbieter und Intervall geprüft und anschließend auf den neuen Update-Kern umgestellt.</p>")
            body+=_ui_html('</div>')
            if managed:
                body+=_ui_html("<div class='card dd-actions'>")+action('check','IP & DNS prüfen (ohne Update)')+action('run','Jetzt aktualisieren')+action('pause','Zeitplan pausieren')+action('resume','Zeitplan aktivieren')+_ui_html('</div>')
            rows=cfg['providers']
            if not e.CONFIG.exists():
                old,errors=e.legacy_inventory();rows=old['providers']
                body+=_ui_html("<div class='card'><b>Erkannter Skriptbestand · noch nicht im neuen Modul gespeichert</b><p>")+str(len(rows))+_ui_html(' importierbare Anbieter. Zugangsdaten werden nicht angezeigt.</p>')
                for message in errors:body+=_ui_html('<p class="dd-error">')+esc(_ui_text(message))+_ui_html('</p>')
                body+=_ui_html('</div>')
            body+=_ui_html("<div class='card dd-table'><table><tr><th>Anbieter / Host</th><th>IP-Modus</th><th>Letzter Zustand</th><th>Ändern</th></tr>")
            for p in rows:
                state=e.provider_state(p['id']) if e.CONFIG.exists() else {}
                body+=_ui_html('<tr><td><b>')+esc(p['name'])+_ui_html('</b><br>')+esc(p['host'])+_ui_html('<br>')+(_ui_text('Aktiv') if p['enabled'] else _ui_text('Pausiert'))+_ui_html('</td><td>')+esc(_ui_text(e.MODES[p['mode']]))+_ui_html('</td><td>')+esc(_ui_text({'ok':'Bestätigt','error':'Fehler','limited':'Anbietersperre','checked':'Geprüft','unchanged':'Unverändert'}.get(state.get('status'),_ui_text('Noch keine Prüfung'))))+_ui_html('<br>')+esc(_ui_text(state.get('message','')))+_ui_html('<br><small>Prüfung: ')+stamp(state.get('checked'))+_ui_html('<br>Update: ')+stamp(state.get('updated'))+_ui_html('</small>')
                if state.get('detected'):body+=_ui_html('<br>')+esc('IPv4: '+(state['detected'].get('ipv4') or '—')+' · IPv6: '+(state['detected'].get('ipv6') or '—'))
                if state.get('retry_after',0)>time.time():body+=_ui_html('<br>Nächster Anbieter-Versuch frühestens: ')+stamp(state['retry_after'])
                if state.get('blocked_until',0)>time.time():body+=_ui_html('<br>Sperre bis ')+stamp(state['blocked_until'])
                controls='Übernahme erforderlich'
                if e.CONFIG.exists():
                    controls=_ui_html("<div class='dd-actions'><a class='btn' href='/dyndns/edit?id=")+esc(p['id'])+_ui_html("'>Bearbeiten</a><a class='btn' href='/dyndns/diagnosis?id=")+esc(p['id'])+_ui_html("'>Analyse & Reparatur</a>")
                    controls+=action('disable' if p['enabled'] else 'enable','Deaktivieren' if p['enabled'] else 'Aktivieren',hidden('id',p['id'])+hidden('revision',revision))
                    controls+=_ui_html("<a class='btn' href='/dyndns/delete?id=")+esc(p['id'])+_ui_html("'>Löschen …</a></div>")
                body+=_ui_html('</td><td>')+controls+_ui_html('</td></tr>')

            if not rows:body+=_ui_html('<tr><td colspan="4">Noch kein Anbieter eingerichtet. Mit „Anbieter hinzufügen“ beginnen.</td></tr>')
            body+=_ui_html('</table></div><div class="card"><h3>So arbeitet DynDNS</h3><p>IPv4 wird über api.ipify.org ermittelt. IPv6 verwendet eine stabile öffentliche Adresse der gewählten Serverschnittstelle. Anbieterbegrenzungen und Wartezeiten gelten auch bei „Jetzt aktualisieren“. Die IP-/DNS-Prüfung sendet keine Update-Anfrage an den Anbieter.</p><p>DynDNS verändert DNS-Einträge, öffnet aber keine Routerfreigaben und löst kein CGNAT-Problem.</p></div>')
            return page(_ui_text('DynDNS'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/delete',methods=['GET'])
    def delete_confirmation():
        try:
            revision=e.revision();cfg=e.load();key=request.args.get('id','')
            provider=next((p for p in cfg['providers'] if p['id']==key),None)
            if not provider:raise e.Problem('Anbieter nicht gefunden.')
            body=_ui_html("<div class='card'><h2>DynDNS-Adresse entfernen</h2><p><b>")+esc(provider['host'])+_ui_html("</b> · ")+esc(provider['name'])+_ui_html("</p><p>Entfernt diesen Eintrag samt gespeicherten Zugangsdaten aus der aktiven Manager-Konfiguration. Diese Adresse wird danach nicht mehr aktualisiert. Die Domain und der letzte DNS-Eintrag beim Anbieter bleiben bestehen; vorhandene Konfigurationssicherungen bleiben erhalten. Andere Adressen, Weiterleitungen und Dienste werden nicht verändert.</p>")
            body+=action('delete','Eintrag endgültig löschen',hidden('id',key)+hidden('revision',revision)+_ui_html("<label><input type='checkbox' name='confirm' value='1' required> Diesen Eintrag entfernen</label>"))
            body+=_ui_html("<a class='btn' href='/dyndns'>Abbrechen</a></div>")
            return page(_ui_text('DynDNS löschen'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/diagnosis',methods=['GET','POST'])
    def diagnosis():
        try:
            key=request.values.get('id','');cfg=e.load()
            provider=next((p for p in cfg['providers'] if p['id']==key),None)
            if not provider:raise e.Problem('Anbieter nicht gefunden.')
            if request.method=='POST':
                if e.busy():raise e.Problem('Eine DynDNS-Aktion läuft bereits.')
                def worker():
                    try:e.diagnose(key)
                    except (e.Problem,OSError):pass
                threading.Thread(target=worker,daemon=True).start()
                return redirect('/dyndns/diagnosis?id='+key,303)
            state=e.provider_state(key);report=state.get('diagnosis',{})
            body=_ui_html("<div class='card'><h2>Analyse & Reparatur · ")+esc(provider['host'])+_ui_html("</h2><p>Prüft öffentliche Serveradressen, DNS-Zone und autoritative A-/AAAA-Antworten. Bei UDP-Problemen wird TCP versucht. Eine wieder funktionierende DNS-Abfrage entfernt die alte DNS-Fehleranzeige. Zugangsdaten, DNS-Einträge und Anbietersperren werden nicht verändert.</p>")
            body+=_ui_html("<form method='post'>")+token()+hidden('id',key)+_ui_html("<button class='btn'>DNS erneut prüfen & Anzeige reparieren</button></form>")
            body+=_ui_html("<p><a class='btn' href='/dyndns/diagnosis?id=")+esc(key)+_ui_html("'>Ergebnis aktualisieren</a></p>")
            if e.busy():body+=_ui_html('<p>DynDNS-Aktion läuft. Ergebnis nach Abschluss aktualisieren.</p>')
            body+=_ui_html('<p>Letzte Diagnose: ')+stamp(report.get('checked'))+_ui_html('</p><p>')+esc(_ui_text(report.get('message','Noch keine Diagnose gestartet.')))+_ui_html('</p>')
            body+=_ui_html('<p>Anbieterwartezeit bis: ')+stamp(state.get('retry_after'))+' · Anbietersperre bis: '+stamp(state.get('blocked_until'))+_ui_html('</p></div>')
            for item in report.get('queries',[]):
                body+=_ui_html("<div class='card'><h3>")+esc(item['kind'])+_ui_html('</h3><p>Soll: ')+esc(item.get('wanted'))+_ui_html('<br>DNS: ')+esc(', '.join(item['records']) or _ui_text('Keine Adresse'))+_ui_html('<br>Zone: ')+esc(item['zone'])+_ui_html('</p><p>')+esc(_ui_text(item['message']))+_ui_html('</p><ul>')
                body+=''.join(_ui_html('<li>')+esc(step)+_ui_html('</li>') for step in item['steps'])+_ui_html('</ul></div>')
            return page(_ui_text('DynDNS · Analyse & Reparatur'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/edit',endpoint='dyndns_editor',methods=['GET','POST'])
    def editor():
        try:
            cfg=e.load();key=request.values.get('id','');old=next((p for p in cfg['providers'] if p['id']==key),None)
            if key and not old:raise e.Problem('Anbieter nicht gefunden.')
            if not e.CONFIG.exists() and list((e.LEGACY/'providers.d').glob('*.conf')):return redirect('/dyndns/import')
            kind=request.values.get('type',old['type'] if old else 'ddnss');preset=e.PRESETS.get(kind,e.PRESETS['custom'])
            message=''
            if request.method=='POST':
                try:
                    with e.lock():
                        if request.form.get('revision')!=e.revision():raise e.Problem('Konfiguration wurde inzwischen geändert. Seite neu laden.')
                        data=request.form.to_dict()
                        if old and not data.get('url'):data['url']=old['url']
                        item=e.validate_provider(data,old)
                        if any(p['id']!=item['id'] and p['host']==item['host'] for p in cfg['providers']):raise e.Problem('Für diesen Host ist bereits ein Anbieter eingerichtet.')
                        cfg['providers']=[item if p['id']==key else p for p in cfg['providers']] if old else cfg['providers']+[item]
                        e.save(cfg)
                        # Changed credentials/URL invalidate the success cache, but never rate limits.
                        state=e.provider_state(item['id']);state.pop('successful_ips',None);e.put_state(item['id'],state)
                    session['dyndns_notice']='Anbieter gespeichert. Der nächste geplante Lauf verwendet die Änderung.'
                    return redirect('/dyndns',303)
                except e.Problem as exc:message=str(exc)
            values=dict(old or dict(name=preset[0],type=kind,host='',username='',mode='ipv4',auth=preset[1],success='',enabled=True))
            if request.method=='POST':values.update({k:v for k,v in request.form.items() if k not in ('secret','url')})
            body=_ui_html("<div class='card'><h2>")+(_ui_text('Anbieter bearbeiten') if old else _ui_text('Anbieter einrichten'))+_ui_html('</h2>')
            if not old:body+=_ui_html("<form method='get' class='dd-form'>")+select('type','Vorlage',[(k,v[0]) for k,v in e.PRESETS.items()],kind)+_ui_html("<button class='btn'>Vorlage wählen</button></form>")
            body+=_ui_html("<p class='dd-error'>")+esc(_ui_text(message))+_ui_html("</p><form method='post' class='dd-form'>")+token()+hidden('id',key)+hidden('type',kind)+hidden('revision',e.revision())
            body+=field('name','Name',values['name'])+field('host','Vollständiger Hostname',values['host'],hint='Zum Beispiel meinserver.ddnss.de oder meinserver.duckdns.org')
            body+=select('mode','Zu aktualisierende Adressen',e.MODES.items(),values['mode'])+field('username','Benutzername (falls benötigt)',values['username'])
            body+=field('secret','Passwort / API-Schlüssel','','password','Bereits gespeichert – leer lassen zum Beibehalten.' if old else 'Wird geschützt auf dem Server gespeichert; erscheint nicht im Status oder Skript-Download.')
            body+=select('auth','Anmeldeart',[('none',_ui_text('Schlüssel in der Update-URL')),('basic',_ui_text('HTTP Basic Auth')),('bearer',_ui_text('Bearer Token'))],values['auth'])
            body+=field('url','Update-URL (optional bei Vorlage)','','password','Gespeicherte URL bleibt bei leerem Feld erhalten.' if old else 'Platzhalter: {host}, {user}, {secret}, {ipv4}, {ipv6}. Nur HTTPS. Die Vorlage wird bei leerem Feld verwendet.')
            if kind=='custom':body+=field('success','Exakte Erfolgsantwort',values.get('success',''),hint='Wird ohne Groß-/Kleinschreibung geprüft. Andere Antworten gelten als Fehler.')
            body+=_ui_html("<label><input type='checkbox' name='enabled' value='1'")+(' checked' if values.get('enabled') in (True,'1','yes') else '')+_ui_html("> Anbieter aktiv</label><button class='btn'>Speichern</button></form></div>")
            if old:body+=_ui_html("<div class='card'>")+action('delete','Anbieter endgültig entfernen',hidden('id',key)+hidden('revision',e.revision())+_ui_html("<label><input required type='checkbox' name='confirm' value='1'> Entfernen bestätigen (DNS-Eintrag bleibt beim Anbieter bestehen)</label>"))+_ui_html('</div>')
            return page(_ui_text('DynDNS-Anbieter'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/settings',endpoint='dyndns_settings',methods=['GET','POST'])
    def settings():
        try:
            cfg=e.load()
            if request.method=='POST':
                with e.lock():
                    if request.form.get('revision')!=e.revision():raise e.Problem('Konfiguration wurde inzwischen geändert.')
                    cfg.update(e.validate_settings(request.form));e.activate(cfg)
                session['dyndns_notice']='Einstellungen gespeichert; Zeitplan aktiviert. Kein sofortiges Update ausgelöst.';return redirect('/dyndns',303)
            body=_ui_html("<div class='card'><h2>Zeitplan & IP-Ermittlung</h2><form method='post' class='dd-form'>")+token()+hidden('revision',e.revision())
            body+=select('interval','Prüfintervall',[(v,str(v)+' Minuten') for v in (5,10,15,30,60,120,180,360,720)],cfg['interval'])
            body+=select('strategy','Wann aktualisieren?',e.STRATEGIES.items(),cfg['strategy'])+field('interface','IPv6-Netzwerkschnittstelle',cfg['interface'],hint='Leer: Schnittstelle der IPv6-Standardroute. Temporäre und nicht öffentliche IPv6-Adressen werden ignoriert.')
            body+=field('lock_hours','Sperrdauer bei Anbieterbegrenzung (Stunden)',cfg['lock_hours'],'number')
            body+=_ui_html("<p>Aktivierung ersetzt den bisherigen DynDNS-Timer nach Sicherung. Der erste Lauf erfolgt zum nächsten Kalendertermin; versäumte Läufe werden nicht sofort nachgeholt.</p><button class='btn'>Speichern & Zeitplan aktivieren</button></form></div>")
            return page(_ui_text('DynDNS-Zeitplan'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/import',endpoint='dyndns_importer',methods=['GET','POST'])
    def importer():
        try:
            cfg,errors=e.legacy_inventory()
            if request.method=='POST':
                with e.lock():
                    if request.form.get('legacy_revision')!=legacy_revision() or request.form.get('revision')!=e.revision():raise e.Problem('Bestand wurde inzwischen geändert. Übernahme neu prüfen.')
                    if e.CONFIG.exists():raise e.Problem('Modulbestand existiert bereits; erneuter Import würde Änderungen überschreiben.')
                    if errors:raise e.Problem('Nicht alle Anbieter können übernommen werden. Altkonfiguration zuerst korrigieren.')
                    if request.form.get('confirm')!='1':raise e.Problem('Bitte die Übernahme bestätigen.')
                    e.activate(cfg)
                session['dyndns_notice']='Bestand übernommen und Zeitplan umgestellt. Originaldateien und Sicherung bleiben erhalten.';return redirect('/dyndns',303)
            body=_ui_html("<div class='card'><h2>Skriptbestand übernehmen</h2><p>Quelle: /etc/multi-dyndns-v3. Import als Daten ohne Ausführung der Konfigurationsdateien. Die Übernahme sichert Konfiguration und systemd-Dateien, erhält die aktiven Anbieter und ersetzt den Update-Kern.</p><ul>")
            for p in cfg['providers']:body+=_ui_html('<li>')+esc(p['name'])+' · '+esc(p['host'])+' · '+esc(_ui_text(e.MODES[p['mode']]))+' · '+(_ui_text('aktiv') if p['enabled'] else _ui_text('pausiert'))+_ui_html('</li>')
            body+=_ui_html('</ul><p>Intervall: ')+str(cfg['interval'])+' Minuten · '+esc(e.STRATEGIES.get(cfg['strategy'],cfg['strategy']))+_ui_html('</p>')
            for message in errors:body+=_ui_html('<p class="dd-error">')+esc(_ui_text(message))+_ui_html('</p>')
            if not errors and cfg['providers'] and not e.CONFIG.exists():body+=_ui_html("<form method='post' class='dd-form'>")+token()+hidden('revision',e.revision())+hidden('legacy_revision',legacy_revision())+_ui_html("<label><input type='checkbox' name='confirm' value='1' required> Anbieter und Zeitplan übernehmen</label><button class='btn'>Geprüften Bestand übernehmen</button></form>")
            elif e.CONFIG.exists():body+=_ui_html('<p>Der Modulbestand ist bereits eingerichtet. Änderungen unter Anbieter und Zeitplan vornehmen.</p>')
            body+=_ui_html('</div>');return page(_ui_text('DynDNS-Übernahme'),body)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/action',endpoint='dyndns_operation',methods=['POST'])
    def operation():
        try:
            action_name=request.form.get('action','')
            if action_name=='check':
                if e.busy():raise e.Problem('Eine Aktion läuft bereits.')
                def check():
                    try:e.run_updates(True)
                    except e.Problem:pass
                threading.Thread(target=check,daemon=True).start();session['dyndns_notice']='Prüfung gestartet. Übersicht nach einigen Sekunden neu laden.'
            else:
                with e.lock():
                    if action_name in ('delete','enable','disable'):
                        if request.form.get('revision')!=e.revision():raise e.Problem('Konfiguration wurde inzwischen geändert. Seite neu laden.')
                        cfg=e.load();key=request.form.get('id','')
                        provider=next((p for p in cfg['providers'] if p['id']==key),None)
                        if not provider:raise e.Problem('Anbieter nicht gefunden.')
                        if action_name=='delete':
                            if request.form.get('confirm')!='1':raise e.Problem('Bitte das Entfernen bestätigen.')
                            cfg['providers']=[p for p in cfg['providers'] if p['id']!=key]
                            notice='DynDNS-Eintrag entfernt. Die Domain beim Anbieter bleibt bestehen.'
                        else:
                            provider['enabled']=action_name=='enable'
                            notice=('Adresse aktiviert. Nächster geplanter Lauf berücksichtigt sie; Anbieterwartezeiten bleiben bestehen.' if provider['enabled'] else 'Adresse deaktiviert. Keine weiteren Updates für diese Adresse; der letzte DNS-Eintrag bleibt bestehen.')
                        e.save(cfg)
                    else:
                        if not e.managed():raise e.Problem('Bitte zuerst den Bestand übernehmen.')
                        args={'run':['start','--no-block',e.UNIT+'.service'],'pause':['disable','--now',e.UNIT+'.timer'],'resume':['enable','--now',e.UNIT+'.timer']}.get(action_name)
                        if args is None:raise e.Problem('Unbekannte Aktion.')
                        if e.command(['systemctl',*args]).returncode:raise e.Problem('DynDNS-Aktion konnte nicht gestartet werden.')
                    session['dyndns_notice']=notice if action_name in ('delete','enable','disable') else 'Aktion ausgeführt.'
            return redirect('/dyndns',303)
        except (e.Problem,OSError) as exc:return fail(exc)
    @app.route('/dyndns/download',endpoint='dyndns_download')
    def download():
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('multi-dyndns-v4.py',Path(e.__file__).read_text())
            archive.writestr('multi-dyndns-manager.sh','#!/bin/sh\nset -eu\nexec /usr/bin/python3 "$(dirname -- "$0")/multi-dyndns-v4.py" "$@"\n')
            archive.writestr('README.txt','Multi DynDNS v4\nAngepasst aus Multi DynDNS Manager v3.9.\nPython 3, iproute2 und dnsutils erforderlich.\nDie Einrichtung und Anbieterpflege erfolgt im Server Manager unter /dyndns.\nDie CLI liest /etc/server-manager/dyndns.json (root, Modus 0600).\nKeine Zugangsdaten sind in diesem Download enthalten.\nAuf dem eingerichteten Server: sudo python3 multi-dyndns-v4.py --status\nNur IP/DNS prüfen: --check\nReales Anbieter-Update: --run-update\nKeine automatische Installation, Paketinstallation oder DNS-Änderung beim Download.\n')
        return Response(stream.getvalue(),mimetype='application/zip',headers={'Content-Disposition':'attachment; filename=multi-dyndns-v4.zip'})
