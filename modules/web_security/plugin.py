"""Authenticated status and review-first server actions."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html
import json
import secrets
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from flask import request,session,redirect,Response,jsonify
from . import engine as e,jobs,installer,apache_editor

LABELS={'manager_https_private':'Privaten Manager-HTTPS-Zugang einrichten','manager_https_disable':'Privaten Manager-HTTPS-Zugang deaktivieren','manager_https_public':'Öffentlichen Manager-HTTPS-Zugang einrichten','setup_reverse_proxy':'Reverse Proxy einrichten','add_nextcloud_redirect':'Weiterleitung hinzufügen','nextcloud_https':'Nextcloud: Domain & HTTPS ergänzen','edit_apache_site':'Apache-Website ändern','delete_cert':'Zertifikat löschen','install_apache':'Apache installieren / aktivieren','install_certbot':'Certbot installieren / aktivieren','install_fail2ban':'Fail2ban installieren / aktivieren','apache_check':'Apache-Konfiguration prüfen','apache_reload':'Apache neu laden','renew_test':'Erneuerung testen','renew':'Fällige Erneuerung ausführen','issue_cert':'Zertifikat anfordern und installieren','create_site':'HTTP-Website einrichten','enable_login_jail':'Login-Schutz einrichten','unban':'IP entsperren','tls_check':'HTTPS-Ziele prüfen'}
STATES={'active':'Aktiv','inactive':'Inaktiv','failed':'Fehlgeschlagen','unknown':'Unbekannt','ok':'Gültig','warning':'Läuft bald ab','critical':'Läuft in höchstens 7 Tagen ab','expired':'Abgelaufen','not_yet_valid':'Noch nicht gültig'}
esc=lambda value:html.escape(str(value),quote=True)
STYLE="""<style>.ws-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.ws-form label{display:block;margin:12px 0}.ws-form input,.ws-form textarea{box-sizing:border-box;max-width:100%;padding:8px;border:1px solid #526075;border-radius:6px;background:#111827;color:#f3f4f6}.ws-form input:not([type=checkbox]){width:420px}.ws-form textarea{width:100%}.ws-form input[type=checkbox]{width:auto}.ws-table{overflow-x:auto}.ws-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"""


def register(app,ctx):
    cache={};lock=threading.Lock()
    def status(fresh=False):
        with lock:
            if not fresh and cache.get('time',0)>time.monotonic()-20:return cache['value']
            out={}
            for key,fn in [('apache',e.apache_status),('certificates',e.certificates),('renewal',e.renewal_status),('fail2ban',e.f2b_status)]:
                try:out[key]=fn()
                except (OSError,ValueError,subprocess.SubprocessError) as exc:out[key]={'error':str(exc)}
            cache.update(time=time.monotonic(),value=out);return out
    def page(body,code=200):return ctx.page(_ui_text('Web & Sicherheit'),STYLE+_ui_html("<div class='card'><div class='ws-actions'><a class='btn' href='/web-security'>Status</a><a class='btn' href='/web-security/setup'>Installer & Einrichtung</a><a class='btn' href='/web-security/targets'>HTTPS-Ziele</a></div></div>")+body,'Server'),code
    def token():
        session.setdefault('web_security_csrf',secrets.token_urlsafe(32))
        return "<input type='hidden' name='csrf' value='"+esc(session['web_security_csrf'])+"'>"
    def button(action,label=None,values=None):
        body=_ui_html("<form method='post' action='/web-security/preview' style='display:inline'>")+token()+_ui_html("<input type='hidden' name='action' value='")+action+"'>"
        for key,value in (values or {}).items():body+="<input type='hidden' name='"+esc(key)+"' value='"+esc(value)+"'>"
        return body+_ui_html("<button class='btn'>")+esc(_ui_text(label) or _ui_text(LABELS[action]))+_ui_html("</button></form>")
    def field(name,label,value='',type='text'):
        return _ui_html('<label>')+esc(_ui_text(label))+_ui_html("<br><input type='")+type+"' name='"+name+"' value='"+esc(value)+_ui_html("'></label>")
    from . import manager_https_ui
    manager_https_ui.register(app, ctx, token, field, STYLE)

    @app.before_request
    def csrf_guard():
        if request.path.startswith('/web-security') and request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('web_security_csrf','!')):return page(_ui_html('<p>Formular abgelaufen. Bitte neu laden.</p>'),403)

    @app.route('/web-security',endpoint='web_security_overview')
    def overview():
        data=status();a=data['apache'];renew=data['renewal'];f=data['fail2ban']
        body=_ui_html("<div class='ws-grid'>")
        for label,row in [('Apache',a),('Certbot',renew),('Fail2ban',f)]:
            body+=_ui_html("<div class='card'><h2>")+_ui_text(label)+_ui_html('</h2><p>Installation: <b>')+(_ui_text('Vorhanden') if row.get('installed') else _ui_text('Nicht erkannt'))+_ui_html('</b></p>')
            if row.get('error'):body+=_ui_html("<p class='warn'>")+esc(_ui_text(row['error']))+_ui_html('</p>')
            if 'state' in row:body+=_ui_html('<p>Dienst: <b>')+esc(_ui_text(STATES.get(row['state'],_ui_text(row['state']))))+_ui_html('</b></p>')
            body+=_ui_html('</div>')
        body+=_ui_html('</div>')
        body+=_ui_html("<div class='card'><h2>Apache-Websites</h2>")
        if a.get('installed'):
            body+=_ui_html('<p>Konfiguration: <b>')+(_ui_text('In Ordnung') if a.get('config_ok') else _ui_text('Fehler / nicht prüfbar'))+_ui_html('</b></p>')
            body+=button('apache_check')+button('apache_reload')
            body+=_ui_html("<div class='ws-table'><table><tr><th>Domainnamen</th><th>Ports</th><th>Webordner</th><th>Zertifikatsdateien</th><th>Konfiguration</th><th>Ändern</th></tr>")
            for row in a.get('sites',[]):body+=_ui_html('<tr>')+''.join(_ui_html('<td>')+esc(value)+_ui_html('</td>') for value in (', '.join(row['names']) or _ui_text('Standard-Website'),', '.join(row['listeners']),', '.join(row['roots']),', '.join(row['certificates']) or _ui_text('Kein TLS in dieser Datei'),row['file']))+_ui_html("<td><a class='btn' href='/web-security/apache/edit?")+esc(urlencode({'site':row['file']}))+_ui_html("'>Bearbeiten</a></td></tr>")
            body+=_ui_html('</table></div><details><summary>Konfigurationstest / Zuordnung</summary><pre>')+esc(a.get('config_message',''))+'\n'+esc(a.get('vhosts',''))+_ui_html('</pre></details>')
        else:body+=_ui_html("<p>Über „Installer & Einrichtung“ installieren.</p>")
        body+=_ui_html('</div><div class="card"><h2>Zertifikate</h2><p>Lokale Dateien und tatsächlich ausgelieferte Zertifikate werden getrennt geprüft.</p>')
        body+=_ui_html("<p><a class='btn' href='/web-security/setup#certificate-install'>Zertifikat für Domain installieren</a></p>")
        timer=renew.get('timer',{});last=renew.get('last',{})
        body+=_ui_html('<p>Erneuerungstimer: <b>')+esc(_ui_text(STATES.get(timer.get('ActiveState'),timer.get('ActiveState',_ui_text('Unbekannt')))))+_ui_html('</b><br>Nächster Lauf: ')+esc(timer.get('NextElapseUSecRealtime') or _ui_text('Nicht geplant'))+_ui_html('<br>Letzter Dienstlauf: ')+esc(last.get('ExecMainExitTimestamp') or _ui_text('Nicht bekannt'))+' · Ergebnis: '+esc(last.get('Result') if last.get('ExecMainExitTimestamp') else _ui_text('Noch nicht bestätigt'))+_ui_html('</p>')
        body+=_ui_html("<p class='muted'><b>Hinweis:</b> Der aktive Timer prüft automatisch zum oben angezeigten nächsten Lauf. Certbot erneuert normalerweise erst im letzten Drittel der Laufzeit (bei 90 Tagen: unter 30 Tagen Restlaufzeit). „Fällige Erneuerung ausführen“ prüft sofort, erzwingt aber keine Verlängerung; noch nicht fällige Zertifikate bleiben unverändert. „Erneuerung testen“ verlängert das Zertifikat nicht.</p>")
        certs=data['certificates']
        if isinstance(certs,dict):body+=_ui_html("<p class='warn'>")+esc(_ui_text(certs.get('error')))+_ui_html('</p>');certs=[]
        body+=_ui_html("<div class='ws-table'><table><tr><th>Name / Domains</th><th>Zustand</th><th>Ablauf</th><th>Aussteller / Erneuerung</th><th>Aktionen</th></tr>")
        for cert in certs:
            cls='ok' if cert.get('state')=='ok' else 'warn'
            body+=_ui_html('<tr><td><b>')+esc(cert['name'])+_ui_html('</b><br>')+esc(', '.join(cert.get('domains',[])))+_ui_html("</td><td class='")+cls+"'>"+esc(_ui_text(STATES.get(cert.get('state'),_ui_text(cert.get('state')))))+_ui_html('<br>')+esc(_ui_text(cert.get('error','')))+_ui_html('</td><td>')+esc(cert.get('expires',_ui_text('Unbekannt')))+_ui_html('<br>')+esc(cert.get('days','?'))+_ui_html(' Tage</td><td>')+esc(cert.get('issuer',''))+_ui_html('<br>')+esc(cert.get('authenticator',''))+_ui_html('</td><td>')+button('renew_test',values={'cert_name':cert['name']})+button('renew',values={'cert_name':cert['name']})+_ui_html("<a class='btn' href='/web-security/certificates/delete?")+esc(urlencode({'name':cert['name']}))+_ui_html("'>Löschen …</a></td></tr>")
        body+=_ui_html('</table></div>')
        if not certs:body+=_ui_html('<p>Keine lokalen Let’s-Encrypt-Zertifikate erkannt. Andere Zertifikate lassen sich über die HTTPS-Ziele prüfen.</p>')
        body+=_ui_html("<p><a class='btn' href='/web-security/targets'>HTTPS-Ziele konfigurieren</a>")+button('tls_check')+_ui_html('</p>')
        try:probes=json.loads((e.ROOT/'tls-status.json').read_text())
        except (OSError,ValueError):probes=[]
        for row in probes:
            good=row.get('verified') and row.get('matches_local') is not False
            body+=_ui_html("<p class='")+('ok' if good else 'warn')+_ui_html("'><b>")+esc(row['host'])+':'+str(row['port'])+_ui_html('</b> · ')+(_ui_text('TLS-Vertrauen und Hostname gültig') if row.get('verified') else _ui_text('HTTPS-Prüfung fehlgeschlagen'))
            if row.get('cert_name'):body+=' · '+(_ui_text('Zertifikat stimmt mit lokalem Stand überein') if row.get('matches_local') else _ui_text('Lokaler und ausgelieferter Stand abweichend / nicht vergleichbar'))
            body+=_ui_html('<br>')+esc(_ui_text(row.get('error')) or row.get('local_error') or '')+_ui_html('<br>Geprüft: ')+esc(row.get('checked_at',''))+_ui_html('</p>')
        body+=_ui_html('</div><div class="card"><h2>Fail2ban</h2><p>Aktive Regeln und Zähler des laufenden Dienstes. Eine aktive Regel allein bestätigt noch nicht die Wirksamkeit ihrer Firewall-Aktion.</p>')
        body+=_ui_html("<div class='ws-table'><table><tr><th>Regel</th><th>Fehlversuche aktuell / gesamt</th><th>Sperren aktuell / gesamt</th><th>Gesperrte IP-Adressen</th></tr>")
        for row in f.get('jails',[]):
            body+=_ui_html('<tr><td>')+esc(row['name'])+_ui_html('</td><td>')+esc(row.get('failed','?'))+' / '+esc(row.get('total_failed','?'))+_ui_html('</td><td>')+esc(row.get('banned','?'))+' / '+esc(row.get('total_banned','?'))+_ui_html('</td><td>')
            for ip in row.get('ips',[]):body+=esc(ip)+' '+button('unban','Entsperren',{'jail':row['name'],'ip':ip})+_ui_html('<br>')
            body+=esc(_ui_text(row.get('error','')))+_ui_html('</td></tr>')
        body+=_ui_html('</table></div></div>')
        if (e.ROOT/'active.json').exists():
            try:
                key=json.loads((e.ROOT/'active.json').read_text())['id'];job=jobs.load(key)
                body+=_ui_html("<div class='card'><a href='/web-security/jobs/")+esc(key)+_ui_html("'>Letzter Auftrag</a>: ")+esc(_ui_text(job['state']))+_ui_html('</div>')
            except (OSError,ValueError):pass
        return page(body)

    @app.route('/api/web-security/status',endpoint='web_security_api_status')
    def api_status():return jsonify(status())

    @app.route('/web-security/setup',endpoint='web_security_setup')
    def setup():
        body=_ui_html("<div class='card'><h2>Installer für neue Server</h2><p>Debian/Ubuntu mit systemd. Nur fehlende Pakete werden ergänzt; vorhandene Konfigurationen bleiben erhalten. Die nächste Seite zeigt die geplanten Änderungen.</p><div class='ws-grid'>")
        for key,c in installer.COMPONENTS.items():
            body+=_ui_html('<div><h3>')+esc(_ui_text(c['label']))+_ui_html('</h3><p>')+esc(', '.join(c['packages']))+_ui_html('</p>')+button('install_'+key)+_ui_html("<p><a href='/web-security/installer/")+key+_ui_html("'>Eigenständigen Installer herunterladen</a></p></div>")
        body+=_ui_html('</div><p>Heruntergeladenen Installer zuerst mit <code>python3 installer.py --check</code> prüfen; Installation mit <code>sudo python3 installer.py --install</code>.</p></div>')
        body+=_ui_html("<div class='card ws-form'><h2>Neue Apache-Website</h2><p>Für einen neuen, leeren Webordner. Vorhandene Apps behalten ihre bisherigen Websites.</p><form method='post' action='/web-security/preview'>")+token()+_ui_html("<input type='hidden' name='action' value='create_site'>")+field('domain','Domainname')+field('root','Neuer oder leerer Webordner','/var/www/')+_ui_html("<button class='btn'>Website prüfen</button></form></div>")
        body+=_ui_html("<div class='card ws-form' id='certificate-install'><h2>Zertifikat für Domain installieren</h2><p>Für bereits eingerichtete Apache-Domains. DNS und Port 80 müssen auf diesen Server zeigen. Certbot richtet HTTPS für die passenden Websites ein. Für bestehende Zertifikate die Erneuerungsfunktion verwenden.</p><form method='post' action='/web-security/preview'>")+token()+_ui_html("<input type='hidden' name='action' value='issue_cert'>")+field('domains','Domainname (optional weitere Namen mit Leerzeichen trennen)')+field('email','E-Mail-Adresse','',type='email')+_ui_html("<label><input type='checkbox' name='terms' value='1' required> Den <a href='https://letsencrypt.org/repository/' target='_blank' rel='noopener noreferrer'>Bedingungen von Let’s Encrypt</a> zustimmen</label><button class='btn'>Zertifikatsinstallation prüfen</button></form></div>")
        body+=_ui_html("<div class='card ws-form'><h2>Fail2ban für den Server-Manager-Login</h2><p>Eigene Regel für fehlgeschlagene Anmeldungen am direkten Server-Manager-Port. Vorhandene SSH-/Apache-Regeln bleiben erhalten.</p><form method='post' action='/web-security/preview'>")+token()+_ui_html("<input type='hidden' name='action' value='enable_login_jail'>")+field('ignore','Zusätzliche vertrauenswürdige IPs / Netze (optional)')+_ui_html("<button class='btn'>Login-Schutz prüfen</button></form></div>")
        return page(body)

    @app.route('/web-security/installer/<component>',endpoint='web_security_download')
    def download(component):
        if component not in installer.COMPONENTS:return page(_ui_html('Installer nicht gefunden.'),404)
        source=Path(installer.__file__).read_text().replace('raise SystemExit(main())','raise SystemExit(main('+repr(component)+'))')
        return Response(source,mimetype='text/x-python',headers={'Content-Disposition':'attachment; filename=install-'+component+'.py'})

    @app.route('/web-security/targets',methods=['GET','POST'],endpoint='web_security_target_settings')
    def target_settings():
        message=''
        try:
            if request.method=='POST':
                rows=[]
                for i in range(31):
                    host=request.form.get('host_'+str(i),'').strip()
                    if host:rows.append(dict(host=host,port=request.form.get('port_'+str(i),'443'),connect=request.form.get('connect_'+str(i),''),cert_name=request.form.get('cert_'+str(i),'')))
                e.save_targets(rows);message='HTTPS-Ziele gespeichert. Die Prüfung wird separat gestartet.'
            rows=e.load().get('targets',[])
        except (ValueError,OSError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),400)
        body=_ui_html("<div class='card ws-form'><h2>HTTPS-Ziele</h2><p>Domain und tatsächlich verwendeten HTTPS-Port angeben, z. B. 8123 für Home Assistant. Eine optionale Verbindungs-IP prüft gezielt einen internen Server; der Domainname bleibt für TLS maßgeblich. Ohne Verbindungs-IP wird DNS verwendet.</p><p>Die Prüfung läuft von diesem Server aus und ersetzt keinen Test aus einem fremden Netz.</p><p>")+esc(_ui_text(message))+_ui_html("</p><form method='post'>")+token()+_ui_html("<div class='ws-table'><table><tr><th>Domain</th><th>Port</th><th>Verbindungs-IP (optional)</th><th>Lokaler Zertifikatsname (optional)</th></tr>")
        for i,row in enumerate(rows+[dict(host='',port=443,connect='',cert_name='')]):
            body+=_ui_html('<tr>')+''.join(_ui_html("<td><input name='")+key+'_'+str(i)+"' value='"+esc(row[source])+_ui_html("'></td>") for key,source in [('host','host'),('port','port'),('connect','connect'),('cert','cert_name')])+_ui_html('</tr>')
        body+=_ui_html("</table></div><p>Zum Entfernen einer Zeile den Domainnamen leeren.</p><button class='btn'>Ziele speichern</button></form></div>")
        return page(body)

    def config_link(ref):
        path=Path(ref)
        if path.parent==e.APACHE/'sites-available' and path.suffix=='.conf':
            return esc(ref)+_ui_html(" <a class='btn' href='/web-security/apache/edit?")+esc(urlencode({'site':path.name}))+_ui_html("'>Bearbeiten / deaktivieren</a>")
        return esc(ref)

    @app.route('/web-security/apache/edit',endpoint='web_security_apache_edit')
    def apache_edit():
        try:
            row=apache_editor.read(request.args.get('site',''))
            body=_ui_html("<div class='card ws-form'><h2>Apache-Website: ")+esc(row['name'])+_ui_html("</h2><p>Website-Konfiguration bearbeiten oder deaktivieren. Deaktivieren entfernt die Website aus Apache; die Konfigurationsdatei bleibt erhalten. Andere Domains in dieser Datei sind ebenfalls betroffen.</p><form method='post' action='/web-security/preview'>")+token()+_ui_html("<input type='hidden' name='action' value='edit_apache_site'><input type='hidden' name='site' value='")+esc(row['name'])+_ui_html("'><input type='hidden' name='base_hash' value='")+esc(row['base_hash'])+_ui_html("'><label>Status <select name='enabled'><option value='yes'")+(' selected' if row['enabled'] else '')+_ui_html(">Aktiv</option><option value='no'")+('' if row['enabled'] else ' selected')+_ui_html(">Deaktiviert</option></select></label><label>Konfiguration<textarea name='content' rows='28' spellcheck='false' style='font-family:monospace'>")+esc(row['content'])+_ui_html("</textarea></label><p>Vor dem Übernehmen werden Änderungen angezeigt. Beim Speichern erfolgen Sicherung und Apache-Konfigurationstest. Bei Fehlern wird der bisherige Stand wiederhergestellt.</p><button class='btn'>Änderungen prüfen</button></form><p><a href='/web-security'>Zurück</a></p></div>")
            response=app.make_response(page(body));response.headers['Cache-Control']='no-store';return response
        except (ValueError,OSError,subprocess.SubprocessError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),400)

    @app.route('/web-security/certificates/delete',endpoint='web_security_delete_certificate')
    def delete_certificate():
        try:
            detail=e.deletion_details(request.args.get('name',''))
            body=_ui_html("<div class='card ws-form'><h2>Zertifikat löschen: ")+esc(detail['name'])+_ui_html("</h2><p>Enthaltene Domains: ")+esc(', '.join(detail['domains']))+_ui_html("</p><p>Gelöscht wird das gesamte lokale Zertifikat mit Schlüssel, allen Versionen und automatischer Erneuerung. Bei mehreren Domainnamen sind alle betroffen. DNS und Website-Dateien bleiben bestehen; externe Kopien werden nicht gelöscht und das Zertifikat wird nicht widerrufen.</p>")
            if detail['references']:
                body+=_ui_html("<p class='warn'>Löschen gesperrt: Zuerst diese Verwendungen umstellen oder entfernen.</p><ul>")+''.join(_ui_html('<li>')+config_link(ref)+_ui_html('</li>') for ref in detail['references'])+_ui_html('</ul>')
            else:
                body+=_ui_html("<p>Keine Verweise in den geprüften lokalen Dienstkonfigurationen, Erneuerungs-Hooks oder HTTPS-Zielen gefunden. Weitere Verwendungen auf anderen Servern müssen zuvor umgestellt sein.</p><form method='post' action='/web-security/preview'>")+token()+_ui_html("<input type='hidden' name='action' value='delete_cert'><input type='hidden' name='cert_name' value='")+esc(detail['name'])+"'>"+field('confirm_name','Zur Bestätigung den vollständigen Zertifikatsnamen eingeben')+_ui_html("<button class='btn'>Löschung prüfen</button></form>")
            if detail.get('inactive'):
                body+=_ui_html("<details><summary>Nicht eingebundene Konfigurationen / Sicherungen (sperren nicht)</summary><p>Nach einer Zertifikatslöschung diese Dateien vor erneuter Aktivierung oder Wiederherstellung anpassen.</p><ul>")+''.join(_ui_html('<li>')+config_link(ref)+_ui_html('</li>') for ref in detail['inactive'])+_ui_html('</ul></details>')
            return page(body+_ui_html("<p><a href='/web-security'>Abbrechen</a></p></div>"))
        except (ValueError,OSError,subprocess.SubprocessError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),400)

    @app.route('/web-security/preview',methods=['POST'],endpoint='web_security_preview')
    def preview():
        try:
            p=e.plan(request.form.get('action',''),request.form)
            pending=e.ROOT/'pending';pending.mkdir(parents=True,exist_ok=True,mode=0o700)
            for old in pending.glob('*.json'):
                if time.time()-old.stat().st_mtime>600:old.unlink(missing_ok=True)
            key=secrets.token_hex(16)
            e.atomic(pending/(key+'.json'),p)
            session['web_security_plan']={'id':key,'digest':e.digest(p),'time':time.time()}
            body=_ui_html("<div class='card'><h2>")+esc(_ui_text(LABELS[p['action']]))+_ui_html(" · Vorschau</h2><ul>")+''.join(_ui_html('<li>')+esc(step)+_ui_html('</li>') for step in p['steps'])+_ui_html("</ul><p>Es wurde noch nichts geändert.</p><form method='post' action='/web-security/execute'>")+token()+_ui_html("<input type='hidden' name='digest' value='")+e.digest(p)+_ui_html("'><button class='btn'>Bestätigen und ausführen</button></form><p><a href='/web-security'>Abbrechen</a></p></div>")
            if p.get('diff'):body+=_ui_html("<div class='card'><h3>Dateiänderungen</h3><pre>")+esc(p['diff'])+_ui_html('</pre></div>')
            response=app.make_response(page(body));response.headers['Cache-Control']='no-store';return response
        except (ValueError,OSError,subprocess.SubprocessError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),400)

    @app.route('/web-security/execute',methods=['POST'],endpoint='web_security_execute')
    def execute():
        try:
            saved=session.pop('web_security_plan',None)
            if not saved or time.time()-saved['time']>600 or not secrets.compare_digest(request.form.get('digest',''),saved['digest']):raise e.Problem('Vorschau abgelaufen oder verändert. Bitte erneut prüfen.')
            path=e.ROOT/'pending'/(saved['id']+'.json')
            p=json.loads(path.read_text());path.unlink()
            if e.digest(p)!=saved['digest']:raise e.Problem('Vorschau verändert.')
            key=jobs.start(p);cache.clear()
            return redirect('/web-security/jobs/'+key,303)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),400)

    @app.route('/web-security/jobs/<key>',endpoint='web_security_job_page')
    def job_page(key):
        try:
            row=jobs.load(key);folder=jobs.folder(key)
            body=_ui_html("<div class='card'><h2>")+esc(_ui_text(LABELS.get(row['action'],row['action'])))+_ui_html('</h2><p>Status: <b>')+esc(_ui_text(row['state']))+_ui_html('</b></p><pre>')+esc(row['message'])+_ui_html('</pre>')
            if (folder/'result.json').is_file():body+=_ui_html('<h3>Ergebnis</h3><pre>')+esc(json.dumps(json.loads((folder/'result.json').read_text()),ensure_ascii=False,indent=2))+_ui_html('</pre>')
            if (folder/'run.log').is_file():body+=_ui_html('<details><summary>Protokoll</summary><pre>')+esc((folder/'run.log').read_text(errors='replace')[-16000:])+_ui_html('</pre></details>')
            if row['state'] not in e.TERMINAL:body+=_ui_html('<script>setTimeout(()=>location.reload(),3000)</script>')
            else:cache.clear()
            return page(body+_ui_html("<p><a class='btn' href='/web-security'>Status erneut ansehen</a></p></div>"))
        except (ValueError,OSError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'),404)
