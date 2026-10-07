"""Scanner administration with explicit installation/configuration actions."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html
import json
import secrets
import subprocess
from urllib.parse import urlsplit
from flask import request, session, redirect, Response
from . import engine as e

STYLE="""<style>.sc-form{max-width:850px}.sc-form label{display:block;margin:14px 0}.sc-form input,.sc-form select{display:block;width:100%;box-sizing:border-box;padding:10px;background:#111c2c;color:#edf2fa;border:1px solid #526075;border-radius:7px}.sc-actions{display:flex;gap:10px;flex-wrap:wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"""
def esc(v):return html.escape(str(v),quote=True)
def token():
    if 'scanner_csrf' not in session:session['scanner_csrf']=secrets.token_urlsafe(32)
    return "<input type='hidden' name='csrf' value='"+esc(session['scanner_csrf'])+"'>"
def field(key,label,value):return _ui_html('<label>')+esc(_ui_text(label))+_ui_html("<input name='")+key+"' value='"+esc(value)+_ui_html("' required></label>")
def select(key,label,options,value):return _ui_html('<label>')+_ui_text(label)+_ui_html("<select name='")+key+"'>"+''.join(_ui_html("<option value='")+k+"'"+(' selected' if k==value else '')+'>'+v+_ui_html('</option>') for k,v in options)+_ui_html('</select></label>')

def register(app,ctx):
    def page(body):return ctx.page(_ui_text('Scanner'),STYLE+_ui_html("<div class='card'><a class='btn' href='/scanner'>Scanner</a> <a class='btn' href='/scanner/settings'>Einstellungen & Installer</a> <a class='btn' href='/scanner/home-assistant'>Home-Assistant-Konfiguration</a></div>")+body,'Scanner')
    def fail(exc,code=400):return page(_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html("</p></div>")),code
    @app.before_request
    def scanner_csrf():
        if request.path.startswith('/scanner') and request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('scanner_csrf','!')):return fail('Formular abgelaufen. Seite neu laden.',403)
    @app.route('/scanner')
    def scanner_index():
        try:
            c=e.load();missing=e.missing_packages()
            body=_ui_html("<div class='card'><h2>Scanner-API</h2><p>Installation: <b>")+(_ui_text('vorhanden') if e.API.exists() else _ui_text('fehlt'))+_ui_html('</b> · Dienst: <b>')+esc(e.service_state())+_ui_html('</b></p>')
            body+=_ui_html('<p>Verwaltung: ')+(_ui_text('Einstellungen übernommen') if e.CONFIG.exists() else _ui_text('Bestand erkannt; Einstellungen noch nicht übernommen'))+_ui_html('</p><p>Scanner-IP: <b>')+esc(c['ip'] or _ui_text('Automatische Erkennung'))+_ui_html('</b> · ')+esc(c['protocol'])+' · API-Port: '+str(c['port'])+_ui_html('</p><p>Scan-Ausgabe: <code>')+esc(c['outdir'])+_ui_html('</code></p>')
            body+=_ui_html('<p>Pakete: ')+(_ui_text('vollständig installiert') if not missing else 'Fehlend: '+esc(', '.join(missing)))+_ui_html('</p>')
            try:
                status=e.read_api(c,'/status');body+=_ui_html('<p>Scan-Session: ')+(_ui_text('aktiv – Änderungen gesperrt') if status.get('active') else _ui_text('bereit'))+_ui_html('</p>')
            except (OSError,ValueError):body+=_ui_html('<p>API nicht erreichbar. Verbindung prüfen oder Installer verwenden.</p>')
            body+=_ui_html("<div class='sc-actions'><a class='btn' href='/scanner/settings'>IP / Einstellungen ändern</a><form method='post' action='/scanner/check'>")+token()+_ui_html("<button class='btn'>API & Scanner prüfen</button></form><form method='post' action='/scanner/discover'>")+token()+_ui_html("<button class='btn'>Scanner im Netzwerk suchen</button></form></div><p>Prüfungen starten keinen Scan. Bestehende Home-Assistant-Aufrufe bleiben nutzbar.</p></div>")
            if (e.ROOT/'active.json').exists():
                key=json.loads((e.ROOT/'active.json').read_text())['id'];j=e.job(key)
                body+=_ui_html("<div class='card'><a href='/scanner/jobs/")+esc(key)+_ui_html("'>Letzter Auftrag</a>: ")+esc(_ui_text(j['message']))+_ui_html('</div>')
            return page(body)
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return fail(exc)
    @app.route('/scanner/settings',methods=['GET','POST'])
    def scanner_settings():
        try:
            if request.method=='POST':
                key=e.start(request.form,request.form.get('action','apply'),request.form.get('revision',''))
                return redirect('/scanner/jobs/'+key,303)
            c=e.load()
            body=_ui_html("<div class='card sc-form'><h2>Einstellungen & Installer</h2><p>Änderungen werden gesichert und erst bei freiem Scanner übernommen. Die API wird kurz neu gestartet. Bei einem Startfehler wird der vorherige Dateistand wiederhergestellt.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='revision' value='")+e.revision()+"'>"
            body+=select('mode','Scanner-Verbindung',[('ip',_ui_text('Feste Scanner-IP verwenden')),('auto',_ui_text('Bisherige SANE-Gerätekennung / automatische Erkennung'))],c['mode'])
            body+=field('ip','Scanner-IP (IPv4, nur bei fester Verbindung erforderlich)',c['ip']).replace(' required>', '>')
            body+=select('protocol','Scanner-Protokoll',[('eSCL',_ui_text('eSCL / AirScan')),('WSD',_ui_text('WSD'))],c['protocol'])
            for key,label in [('scanner_port','Scanner-Port (meist 80)'),('path','Scanner-Pfad (eSCL: /eSCL/ · Canon WSD: /wsd/scanservice.cgi)'),('device','SANE-Gerätekennung (nur automatische Verbindung)'),('outdir','Ordner für fertige Scans'),('bind','API-Bind-Adresse (0.0.0.0 = alle Serverschnittstellen)'),('port','API-Port (Home Assistant bisher 8181)')]:body+=field(key,label,c[key])
            import pwd,grp,stat
            users=sorted({u.pw_name for u in pwd.getpwall() if u.pw_uid!=0}|{'scanner'})
            body+=select('user','Dienstbenutzer / Eigentümer neuer Scans',[(u,u) for u in users],c['user'])
            body+=select('access','Zugriff auf den Scan-Ordner',[('keep',_ui_text('Bestehende Rechte beibehalten')),('private',_ui_text('Nur Dienstbenutzer')),('read',_ui_text('Dienstbenutzer schreibt; Gruppe darf lesen')),('write',_ui_text('Dienstbenutzer und Gruppe dürfen lesen / schreiben'))],c.get('access','keep'))
            groups=sorted(g.gr_name for g in grp.getgrall())
            body+=select('access_group','Zugriffsgruppe',[('',_ui_text('Bitte wählen'))]+[(g,g) for g in groups],c.get('access_group',''))
            out=e.Path(c['outdir'])
            if out.exists():
                st=out.stat()
                try:owner=pwd.getpwuid(st.st_uid).pw_name
                except KeyError:owner=str(st.st_uid)
                try:group=grp.getgrgid(st.st_gid).gr_name
                except KeyError:group=str(st.st_gid)
                members=sorted({u.pw_name for u in pwd.getpwall() if u.pw_gid==st.st_gid}|set(grp.getgrgid(st.st_gid).gr_mem)) if group in groups else []
                body+=_ui_html('<p>Aktueller Ordner: Eigentümer <b>')+esc(owner)+_ui_html('</b> · Gruppe <b>')+esc(group)+_ui_html('</b> · Rechte <code>')+esc(stat.filemode(st.st_mode))+_ui_html('</code><br>Gruppenmitglieder: ')+esc(', '.join(members) or _ui_text('Keine lokalen Mitglieder erkannt'))+_ui_html('</p>')
            body+=_ui_html("<p>Der Ordner kann nachträglich geändert werden. Vorhandene Scans bleiben am bisherigen Ort. Eine neue Rechteauswahl betrifft den Zielordner und künftige Scans; bestehende Dateien werden nicht rekursiv geändert. Gruppenmitgliedschaften unter Freigaben & Benutzer verwalten. Root, übergeordnete Ordner, ACLs und SMB-/NFS-Regeln können den tatsächlichen Zugriff beeinflussen. Zusätzliche ACLs werden bei einer Rechteänderung nicht überschrieben.</p>")
            body+=_ui_html("<p>Scanner-IP und API-Bind-Adresse sind unterschiedliche Geräteadressen. Wenn API-Adresse oder Port geändert werden, die Home-Assistant-Aufrufe entsprechend anpassen. Der Sitzungsordner bleibt /var/lib/scansession.</p><div class='sc-actions'><button class='btn' name='action' value='apply'>Speichern & übernehmen</button><button class='btn' name='action' value='install'>Scanner-API installieren / reparieren</button></div></form><p>Der Installer legt das Standardkonto scanner bei Bedarf als Systemkonto ohne interaktive Anmeldung und ohne Home-Verzeichnis an. Vorhandene Konten bleiben unverändert. Andere Dienstbenutzer müssen bereits existieren. Ein neu angelegtes Konto bleibt bei späteren Installationsfehlern erhalten. Der Installer ergänzt nur fehlende Pakete: Python, Flask, sane-utils, sane-airscan und img2pdf. OCR ist in dieser API noch nicht enthalten.</p></div>")
            return page(body)
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return fail(exc)
    @app.route('/scanner/check',methods=['POST'])
    def scanner_check():
        try:
            rows=e.check(e.load());body=_ui_html("<div class='card'><h2>API & Scanner prüfen</h2><p>Es wurde kein Scan ausgelöst. Die SANE-Prüfung läuft unter dem Server-Manager-Konto; der Dienstzugriff auf den Ausgabeordner wird beim Übernehmen separat geprüft.</p>")
            for r in rows:body+=_ui_html('<h3>')+('✅ ' if r['ok'] else '❌ ')+esc(r['name'])+_ui_html('</h3><pre>')+esc(r['message'])+_ui_html('</pre>')
            return page(body+_ui_html('</div>'))
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return fail(exc)
    @app.route('/scanner/discover',methods=['POST'])
    def scanner_discover():
        try:output=e.run(['airscan-discover'],timeout=25)
        except subprocess.TimeoutExpired:return fail('Netzwerksuche hat das Zeitlimit erreicht. Bekannte IP direkt in den Einstellungen eintragen.')
        except (OSError,ValueError) as exc:return fail(exc)
        return page(_ui_html("<div class='card'><h2>Gefundene Scanner</h2><pre>")+esc(output or 'Kein Scanner gefunden.')+_ui_html("</pre><p>IP, Port, Pfad und Protokoll können in die Einstellungen übernommen werden.</p></div>"))
    @app.route('/scanner/jobs/<key>')
    def scanner_job(key):
        try:j=e.job(key)
        except (OSError,ValueError) as exc:return fail(exc,404)
        labels={'queued':'Wartet','running':'Wird ausgeführt','completed':'Abgeschlossen','failed':'Fehlgeschlagen','interrupted':'Unterbrochen'}
        body=_ui_html("<div class='card'><h2>")+_ui_text(labels.get(j['state'],esc(_ui_text(j['state']))))+_ui_html('</h2><pre>')+esc(_ui_text(j['message']))+_ui_html('</pre></div>')
        if j['state'] not in e.TERMINAL:body+=_ui_html('<script>setTimeout(()=>location.reload(),3000)</script>')
        return page(body)
    @app.route('/scanner/home-assistant')
    def scanner_ha():
        c=e.load();host=urlsplit(request.host_url).hostname or 'SERVER-IP'
        if c['bind'] not in ('0.0.0.0','127.0.0.1'):host=c['bind']
        base='http://'+host+':'+str(c['port'])
        text='rest_command:\n'
        for key,path,timeout in [('pdf','pdfscan',180),('quick','quickscan',120),('jpg','jpgscan',180),('tiff','tiffscan',180),('finish','finish',240),('cancel','cancel',30)]:
            text+='  scan_'+key+':\n    url: '+json.dumps(base+'/'+path)+'\n    method: GET\n    timeout: '+str(timeout)+'\n'
        text+='\nrest:\n  - resource: '+json.dumps(base+'/status')+'\n    scan_interval: 10\n    sensor:\n      - name: Scanner Status\n        value_template: "{{ \'Aktiv\' if value_json.active else \'Bereit\' }}"\n        json_attributes:\n          - session\n'
        if request.args.get('download')=='1':return Response(text,mimetype='text/yaml',headers={'Content-Disposition':'attachment; filename=scanner-home-assistant.yaml'})
        guide=_ui_html("""<div class='card'><h2>Scanner API für Home Assistant einrichten</h2>
<ol><li><b>Scanner vorbereiten:</b> Unter „IP / Einstellungen“ die Scanner-IP und den Ausgabeordner einstellen, dann „Scanner-API installieren / reparieren“ und „API &amp; Scanner prüfen“ ausführen.</li>
<li><b>API erreichbar machen:</b> Home Assistant verbindet sich mit dem Rechner, auf dem die Scanner-API läuft – nicht direkt mit der Scanner-IP. API-Port und LAN-Adresse dieses Rechners verwenden. Bei 127.0.0.1 ist nur ein lokaler Zugriff möglich; für eine andere VM oder einen anderen Rechner die LAN-IP oder 0.0.0.0 als API-Bind-Adresse einstellen. Diese API hat keine eigene Anmeldung: nur im vertrauenswürdigen LAN verwenden, keine Router-Portfreigabe einrichten.</li>
<li><b>Datei öffnen:</b> In Home Assistant die <code>configuration.yaml</code> bearbeiten. Bei Home Assistant OS beispielsweise über die App „File editor“ oder „Studio Code Server“; die Datei liegt normalerweise unter <code>/config/configuration.yaml</code>. Vorher eine Kopie sichern. Bei Container/Core die Datei im dort eingebundenen Konfigurationsordner verwenden.</li>
<li><b>YAML einfügen:</b> Wenn <code>rest_command:</code> und <code>rest:</code> noch nicht existieren, den gesamten folgenden Block am Dateiende auf oberster Ebene ergänzen. Nicht unter <code>homeassistant:</code> oder <code>sensor:</code> einrücken. Leerzeichen statt Tabulatoren verwenden.</li>
<li><b>Vorhandene Abschnitte zusammenführen:</b> Jeden Hauptschlüssel nur einmal verwenden. Bei vorhandenem <code>rest_command:</code> nur die Einträge ab <code>scan_pdf:</code> darunter ergänzen (zwei Leerzeichen). Bei vorhandenem <code>rest:</code> nur den Listeneintrag ab <code>- resource:</code> ergänzen. Gleichnamige scan_*-Einträge ersetzen statt doppelt anlegen. Bei <code>rest_command: !include rest_commands.yaml</code> gehören die scan_*-Einträge ohne die Kopfzeile rest_command: in diese Datei, dort ohne die zwei äußeren Leerzeichen. Bei <code>rest: !include rest.yaml</code> entsprechend die Liste ab - resource: ohne äußere Einrückung in rest.yaml einfügen.</li>
<li><b>Prüfen und laden:</b> Speichern, in den Entwicklerwerkzeugen/Werkzeugen unter YAML die Konfiguration prüfen. Fehler zuerst korrigieren, danach Home Assistant neu starten. Ein Neustart des Heimserver Managers ist dafür nicht nötig.</li>
<li><b>Testen:</b> Papier einlegen. In Home Assistant unter Entwicklerwerkzeuge → Aktionen <code>rest_command.scan_pdf</code> auswählen und ausführen. Das startet einen echten Scan. Für weitere Seiten dieselbe Aktion erneut ausführen; erst danach <code>rest_command.scan_finish</code> ausführen. Die fertige Datei liegt im Ausgabeordner des Scanner-Servers, nicht automatisch in Home Assistant.</li></ol>
<p>Die URLs unten werden aus der aktuell aufgerufenen Manageradresse und dem eingestellten API-Port erzeugt. Prüfen, ob Home Assistant diese Adresse erreichen kann. Bei Zugriff auf den Manager über einen Proxy gegebenenfalls überall durch die LAN-Adresse des Scanner-Servers ersetzen.</p></div>
<div class='card'><h3>Für configuration.yaml</h3><a class='btn' href='/scanner/home-assistant?download=1'>YAML herunterladen</a><pre>""")+esc(text)+_ui_html("""</pre></div>
<div class='card'><h3>Verfügbare Aktionen</h3><ul>
<li><code>rest_command.scan_pdf</code>: Seite für eine PDF-Sitzung scannen.</li>
<li><code>rest_command.scan_quick</code>: Seite für eine Schnell-PDF-Sitzung scannen.</li>
<li><code>rest_command.scan_jpg</code> / <code>rest_command.scan_tiff</code>: Seite im jeweiligen Bildformat scannen.</li>
<li><code>rest_command.scan_finish</code>: Sitzung abschließen und Dateien fertigstellen.</li>
<li><code>rest_command.scan_cancel</code>: Sitzung abbrechen; temporäre Scans der Sitzung werden verworfen.</li></ul>
<p>Während einer Sitzung beim gleichen Format bleiben. Zum Wechseln zuerst abschließen oder abbrechen. Der Sensor „Scanner Status“ zeigt Aktiv/Bereit; die tatsächliche Entitäts-ID unter Entwicklerwerkzeuge → Zustände suchen, bei bestehenden Sensoren kann sie abweichen.</p>
<h3>Häufige Fehler</h3><p>„Verbindung verweigert“: API-Dienst, Bind-Adresse und Port prüfen. Zeitüberschreitung: Erreichbarkeit von Home Assistant aus und Firewall prüfen; nur die benötigte LAN-Verbindung zulassen. Aktion fehlt: YAML-Einrückung, doppelte Schlüssel und Home-Assistant-Neustart prüfen. Fehler beim Speichern: Dienstbenutzer und Rechte aller Elternordner des Ausgabeordners prüfen.</p>
<p>Offizielle Anleitung: <a href='https://www.home-assistant.io/integrations/rest_command/'>RESTful Command</a> · <a href='https://www.home-assistant.io/integrations/rest/'>RESTful-Sensoren</a> · <a href='https://www.home-assistant.io/docs/tools/dev-tools'>Entwicklerwerkzeuge</a></p></div>""")
        return page(guide)
