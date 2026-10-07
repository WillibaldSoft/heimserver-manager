"""Nextcloud setup form: credentials remain in protected server-side storage."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html,json,secrets,time
from pathlib import Path
from flask import request,session,redirect,Response
from . import nextcloud_setup as setup,install_catalog as c,install_jobs as jobs
from server_settings import get as setting

def register(app,ctx,token):
    esc=lambda value:html.escape(str(value),quote=True)
    def page(body,code=200):
        response=app.make_response((ctx.page(_ui_text('Nextcloud · Installation'),_ui_html("<div class='card'><a href='/apps/manage'>Apps verwalten</a></div>")+body,'Apps'),code));response.headers['Cache-Control']='no-store';return response
    def fail(exc):return page(_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html("</p><a href='/apps/nextcloud/installer'>Zurück zum Installer</a></div>"),400)
    def input(name,label,value='',kind='text'):
        return _ui_html('<label style="display:block;margin:12px 0">')+_ui_text(label)+_ui_html("<input style='display:block;width:95%' name='")+name+"' type='"+kind+"' value='"+esc(value)+_ui_html("' required></label>")
    @app.route('/apps/nextcloud/https')
    def https_later():
        from .nextcloud_detect import discover,websites
        found,warnings=discover()
        inventory=_ui_html("<div class='card'><h3>Erkannter Bestand</h3><p>Native Installationen und Docker-Container aus der Bestandserkennung. Die Anzeige ändert keine Einrichtung.</p>")
        for warning in warnings:inventory+=_ui_html("<p class='warn'>")+esc(warning)+_ui_html("</p>")
        for item in found:
            inventory+=_ui_html("<h4>")+esc(('Nativ' if item['kind']=='native' else 'Docker')+' · '+item['label'])+_ui_html("</h4><p>Ort: <code>")+esc(item['path'] or 'Kein Hostpfad erkannt')+_ui_html("</code><br>Erkannt über: ")+esc(item['origin'])+_ui_html("</p>")
            if item['kind']=='docker':inventory+=_ui_html("<p>Container: ")+(_ui_text('läuft') if item.get('running') else _ui_text('gestoppt'))+_ui_html(" · Image: <code>")+esc(item.get('image',''))+_ui_html("</code></p>")
            sites=websites(item)
            for site in sites:
                inventory+=_ui_html("<p><b>")+esc(', '.join(site['domains']) or _ui_text('Kein Domainname angegeben'))+_ui_html("</b><br>Apache-Website: <code>")+esc(site['site'])+_ui_html("</code><br>")+('URL-Pfad: '+esc(', '.join(site.get('routes',[])))+_ui_html('<br>') if site.get('routes') else '')+esc(site['certificate'])+_ui_html("</p>")
            if not sites:inventory+=_ui_html("<p>Domain und Zertifikat konnten dieser Installation nicht eindeutig zugeordnet werden.</p>")
        if not found:inventory+=_ui_html("<p>Keine Installation in den geprüften Quellen erkannt. Eigene Pfade unter <a href='/settings/server-paths'>Server & Modulpfade</a> prüfen.</p>")
        inventory+=_ui_html("<p>Websites zeigen die lokale Apache-Konfiguration, nicht die tatsächliche externe Erreichbarkeit. Andere Reverse-Proxys oder Zertifikate in Containern werden hier nicht zugeordnet. <a href='/web-security'>Zertifikate und HTTPS-Ziele prüfen</a></p></div>")
        session.setdefault('web_security_csrf',secrets.token_urlsafe(32))
        body=_ui_html("<div class='card'><h2>Nextcloud · Domain & HTTPS nachträglich</h2><p>Für mit diesem Manager eingerichtete lokale Installationen. Lokale Adresse und HTTP-Zugang bleiben erhalten. DNS und Portweiterleitung für 80/443 vorher einrichten. Öffentliches HTTPS ist optional; für reinen VPN-Zugriff nicht erforderlich.</p><form method='post' action='/web-security/preview'><input type='hidden' name='csrf' value='")+esc(session['web_security_csrf'])+_ui_html("'><input type='hidden' name='action' value='nextcloud_https'><label style='display:block;margin:12px 0'>Installation<select style='display:block;width:100%;max-width:720px' name='app_id'><option value='nextcloud'>Nativ</option><option value='nextcloud_docker'>Docker</option></select></label>")+input('domain','Öffentliche Domain')+input('email','E-Mail für Let’s Encrypt',kind='email')+_ui_html("<label><input type='checkbox' name='terms' value='1' required> Let’s-Encrypt-Bedingungen akzeptieren</label><p><button class='btn'>Änderungen prüfen</button></p></form><p>Vor Ausführung erscheint eine Vorschau. Konfiguration wird gesichert; ein Fehlschlag kann Teilschritte hinterlassen. Bereits vorhandene fremde Websites und Zertifikate werden nicht überschrieben.</p></div>")
        from modules.web_security.redirects import discover as find_redirects
        redirects,redirect_warnings=find_redirects()
        forwarding=_ui_html("<details class='card'><summary><b>Weiterleitungen · alte Adressen weiter nutzen</b></summary><p>Eine Weiterleitung bringt Besucher von einer bisherigen Adresse automatisch zur neuen Adresse. Hier kannst du Weiterleitungen hinzufügen, einschalten, ausschalten, ändern und löschen.</p>")
        forwarding+=_ui_html("<p><b>Serverwechsel:</b> Das Ziel kann auf einem anderen Server liegen. Der Browser wechselt dabei zur Zieladresse. Soll dieselbe Domain direkt einen anderen Server erreichen, müssen DNS, Router oder Reverse Proxy angepasst werden.</p><details style='margin:16px 0'><summary>Weiterleitung hinzufügen</summary><p>Für eine neue, noch nicht in Apache verwendete Ausgangsadresse. HTTP wird eingerichtet; für HTTPS der Ausgangsadresse anschließend unter <a href='/web-security'>Web & Sicherheit</a> ein Zertifikat einrichten. DNS und Portweiterleitung müssen bereits auf diesen Server zeigen.</p><form method='post' action='/web-security/preview'><input type='hidden' name='csrf' value='")+esc(session['web_security_csrf'])+_ui_html("'><input type='hidden' name='action' value='add_nextcloud_redirect'>")+input('domain','Ausgangsadresse (Domain ohne http://)')+input('target_base','Weiterleiten zu (z. B. https://cloud.example.org)')+_ui_html("<p>Unterpfade bleiben automatisch erhalten. Verwendet wird eine vorläufige Weiterleitung (302), damit spätere Wechsel leichter möglich sind.</p><button class='btn'>Neue Weiterleitung prüfen …</button></form></details>")
        for warning in redirect_warnings:forwarding+=_ui_html("<p>")+esc(warning)+_ui_html("</p>")
        for number,row in enumerate(redirects,1):
            keeps_path=row['target'].endswith('%{REQUEST_URI}')
            destination=row['target'][:-len('%{REQUEST_URI}')] if keeps_path else row['target']
            access='HTTPS · verschlüsselt' if ':443' in row['ports'] else 'HTTP · unverschlüsselt' if ':80' in row['ports'] else 'Website-Regel'
            forwarding+=_ui_html("<section style='border:1px solid #64748b;border-radius:10px;padding:16px;margin:16px 0;max-width:780px;overflow-wrap:anywhere'><h4 style='margin-top:0'>")+esc(row['host'])+_ui_html("</h4><p><b>Bisherige Adresse:</b> ")+esc(row['host'])+_ui_html("<br><b>Weiterleiten zu:</b> ")+esc(destination)+_ui_html("<br><span class='muted'>")+esc(access+' · '+('Ausgeschaltet' if row.get('disabled') else 'Eingeschaltet')+' · Eintrag '+str(number))+_ui_html("</span></p>")
            if keeps_path:forwarding+=_ui_html("<p>Der aufgerufene Unterpfad bleibt erhalten. Zum Beispiel führt <code>/nextcloud/</code> auch am neuen Ziel zu <code>/nextcloud/</code>.</p>")
            forwarding+=_ui_html("<details><summary>Ziel ändern</summary><form method='post' action='/web-security/preview'>")
            hidden=dict(csrf=session['web_security_csrf'],action='nextcloud_redirect',site=row['site'],base_hash=row['base_hash'],line=row['line'])
            fields=''.join("<input type='hidden' name='"+name+"' value='"+esc(value)+"'>" for name,value in hidden.items())
            forwarding+=fields+input('target_base' if keeps_path else 'target','Neue Zieladresse',destination)+_ui_html("<p><button class='btn' name='operation' value='change'>Änderung ansehen …</button></p></form></details>")
            operation='enable' if row.get('disabled') else 'disable'
            label='Weiterleitung einschalten' if row.get('disabled') else 'Weiterleitung ausschalten'
            explanation='Besucher werden wieder zum gespeicherten Ziel weitergeleitet.' if row.get('disabled') else 'Die Weiterleitung wird pausiert. Das Ziel bleibt gespeichert und kann später wieder eingeschaltet werden. Betroffene Besucher erhalten inzwischen „Nicht mehr verfügbar“.'
            forwarding+=_ui_html("<details style='margin-top:12px'><summary>")+_ui_text(label)+_ui_html("</summary><p>")+explanation+_ui_html(" Nur dieser Eintrag wird geändert; weitere Einträge derselben Adresse bleiben bestehen.</p><form method='post' action='/web-security/preview'>")+fields+_ui_html("<button class='btn' name='operation' value='")+operation+_ui_html("'>Änderung vorbereiten …</button></form></details>")
            forwarding+=_ui_html("<details style='margin-top:12px'><summary>Weiterleitung löschen</summary><p>Entfernt diesen Eintrag und sein gespeichertes Ziel. Danach lässt er sich nicht mehr einschalten. Die bisher passenden Anfragen bleiben mit „Nicht mehr verfügbar“ gesperrt, damit keine fremde Standard-Website erscheint. Die Ziel-Website, DNS und Zertifikate bleiben erhalten. Andere Einträge derselben Adresse bleiben bestehen.</p><form method='post' action='/web-security/preview'>")+fields+_ui_html("<button class='btn' name='operation' value='delete'>Löschen prüfen …</button></form></details>")
            forwarding+=_ui_html("<details style='margin-top:12px'><summary>Technische Details</summary><p>")+esc(row['site']+' · '+row['ports']+' · Zeile '+str(row['line']+1))+_ui_html("</p><p>Vollständiges Ziel: <code>")+esc(row['target'])+_ui_html("</code></p><p>Beim Abschalten antwortet diese Regel mit HTTP 410. Bestehende Ausnahmen, etwa für die Zertifikatserneuerung, bleiben bestehen.</p></details></section>")
        if not redirects:forwarding+=_ui_html("<p>Keine passenden Weiterleitungen gefunden.</p>")
        forwarding+=_ui_html("<p><b>Du prüfst zuerst die Änderung und bestätigst sie danach.</b> Vor der Ausführung wird die Konfiguration gesichert und geprüft.</p><details><summary>Warum erscheint eine Adresse mehrfach?</summary><p>HTTP und HTTPS können eigene Einträge haben. Außerdem können mehrere Website-Dateien dieselbe Adresse enthalten. Deshalb wird jeder Eintrag einzeln angezeigt und bearbeitet.</p></details><details><summary>Hinweise zur Erkennung</summary><p>Angezeigt werden unterstützte externe Weiterleitungen aus aktiven Apache-Website-Dateien. Komplexe Regeln oder andere Proxys können fehlen. Browser können frühere Weiterleitungen zwischenspeichern.</p></details></details>")
        return page(inventory+forwarding+body)

    def detail():
        docker_selected=request.args.get('mode')=='docker'
        from .nextcloud_detect import discover
        found,warnings=discover()
        selected=next((v for v in found if v['id']==request.args.get('found')),None)
        body=_ui_html("<div class='card'><h2>Nextcloud einrichten</h2><p><a class='btn' href='/apps/nextcloud/https'>Domain & HTTPS nachträglich einrichten</a></p><h3>Erkannter Bestand</h3><p>Prüfung des eingestellten Pfads, typischer Ordner, Apache-/Nginx-Websites und Docker-Container. Keine vollständige Suche über alle Datenträger; eigene Installationsorte bleiben unter Server & Modulpfade einstellbar.</p>")
        for warning in warnings:body+=_ui_html("<p class='warn'>")+esc(warning)+_ui_html("</p>")
        if found:
            body+=_ui_html("<form method='get'><label>Installation auswählen <select name='found'>")
            for item in found:body+=_ui_html("<option value='")+item['id']+"'"+(' selected' if selected and item['id']==selected['id'] else '')+">"+esc(item['kind']+' · '+item['label'])+_ui_html("</option>")
            body+=_ui_html("</select></label> <button class='btn'>Bestand anzeigen</button></form>")
            if selected:
                body+=_ui_html("<p>Art: <b>")+esc(selected['kind'])+_ui_html("</b><br>Ort: <code>")+esc(selected['path'] or 'Docker-Volume / kein Hostpfad erkannt')+_ui_html("</code><br>Erkannt über: ")+esc(selected['origin'])+_ui_html("</p>")
                if selected['kind']=='native':body+=_ui_html("<form method='post' action='/apps/nextcloud/installer/adopt-path'>")+token()+_ui_html("<input type='hidden' name='found' value='")+selected['id']+_ui_html("'><button class='btn'>Als Nextcloud-Programmpfad übernehmen</button></form><p>Übernimmt nur den Programmpfad. Datenordner und Dienstbenutzer anschließend unter Server & Modulpfade prüfen.</p>")
                else:body+=_ui_html("<p>Image: <code>")+esc(selected['image'])+_ui_html("</code>. Vorhandener Container wird nicht neu installiert oder verändert. <a href='/apps/manage'>Apps verwalten</a></p>")
            body+=_ui_html("<p><a href='/settings/server-paths'>Server & Modulpfade prüfen</a></p></div>")
            if request.args.get('new')!='1':return page(body+_ui_html("<div class='card'><p>Bestehende Installation gefunden. Für eine zusätzliche getrennte Installation:</p><a class='btn' href='/apps/nextcloud/installer?new=1'>Neue Installation vorbereiten</a></div>"))
        else:body+=_ui_html("<p>Keine Installation in den geprüften Quellen gefunden. Der eingestellte Standardpfad wird für die Neuinstallation vorgeschlagen.</p></div>")
        body+=_ui_html("<div class='card'><h3>Neuinstallation</h3><p>Neuinstallation auf Debian 13. Bestehende Daten werden nicht überschrieben. Nativ: Apache/PHP, MariaDB und Redis. Docker: Nextcloud, MariaDB und Redis als Container; Apache übernimmt HTTPS auf dem Host.</p><form method='post' action='/apps/nextcloud/installer/preview'>")+token()
        body+=_ui_html("<label>Zugang <select name='access' id='nc-access'><option value='public'>Öffentlich mit HTTPS / Let’s Encrypt</option><option value='local'>Lokal / über WireGuard (HTTP)</option></select></label><p>Lokaler Modus: private LAN-/WireGuard-IP und eigener Port, keine öffentliche Domain und kein Zertifikatsantrag. HTTP ist im LAN unverschlüsselt; Fernzugriff nur über den bereits eingerichteten VPN-Tunnel. Keine Routerfreigabe einrichten. WireGuard wird nicht installiert.</p><label>Private Bind-IP (nur lokal) <input name='bind' placeholder='z. B. 192.168.1.10'></label><label>Lokaler Webport <input name='web_port' type='number' value='8081' min='1024' max='65535'></label>")
        body+=_ui_html("<label>Installationsart <select name='mode' id='nc-mode'><option value='native'>Nativ (Apache/PHP + MariaDB)</option><option value='docker'>Docker</option></select></label>")
        if docker_selected:body=body.replace("value='docker'","value='docker' selected")
        for name,label,value in [('domain','Nextcloud-Adresse: öffentliche Domain oder lokale IPv4 / interner DNS-Name',''),('email','E-Mail für Zertifikat und Administrator',''),('admin','Nextcloud-Administrator','admin'),('target','Programm- / Docker-Ordner',setting('nextcloud_container_root') if docker_selected else setting('nextcloud_root')),('data_root','Separater Datenordner','/srv/nextcloud-docker-data' if docker_selected else setting('nextcloud_data')),('port','Interner Docker-Port (nur für Docker)',8080)]:body+=input(name,label,value,'email' if name=='email' else 'number' if name=='port' else 'text')
        body+=input('password','Neues Admin-Passwort (mindestens 12 Zeichen)','','password')+input('password_repeat','Admin-Passwort wiederholen','','password')
        body+=_ui_html("<p>Datenbankpasswörter werden automatisch erzeugt. Bei öffentlichem HTTPS muss die Domain auf den Server zeigen; Ports 80 und 443 müssen erreichbar sein. Lokal muss die angegebene Adresse im LAN/VPN erreichbar sein. Router und DNS werden nicht automatisch umgestellt.</p><label><input type='checkbox' id='nc-terms' name='terms' value='1' required> Den <a href='https://letsencrypt.org/repository/' target='_blank' rel='noopener noreferrer'>Bedingungen von Let’s Encrypt</a> zustimmen</label><p><button class='btn'>Angaben und Installation prüfen</button></p></form></div>")
        body+=_ui_html("<script>document.getElementById('nc-access').onchange=function(){document.getElementById('nc-terms').required=this.value==='public';};document.getElementById('nc-mode').onchange=function(){document.querySelector('[name=target]').value=this.value==='docker'?")+json.dumps(setting('nextcloud_container_root'))+":"+json.dumps(setting('nextcloud_root'))+_ui_html(";};</script>")
        body+=_ui_html("<p>Nach der Eingabe kann auch ein fertig parametrisiertes Installerpaket für einen anderen Debian-13-Server heruntergeladen werden.</p>")
        return page(body)
    @app.route('/apps/nextcloud/installer/adopt-path',methods=['POST'])
    def adopt_path():
        from .nextcloud_detect import discover
        import server_settings as cfg
        found,_=discover()
        item=next((v for v in found if v['id']==request.form.get('found') and v['kind']=='native'),None)
        if not item:return fail('Installation nicht mehr erkannt. Erneut prüfen.')
        current=cfg.read(cfg.CONFIG);current['nextcloud_root']=item['path'];cfg.atomic(cfg.CONFIG,current);cfg.ACTIVE['nextcloud_root']=item['path']
        return redirect('/apps/nextcloud/installer?found='+item['id'],303)

    def pending():
        key=session.get('nextcloud_setup_id','')
        if len(key)!=32 or any(ch not in '0123456789abcdef' for ch in key):raise setup.SetupError('Vorschau erneut öffnen.')
        file=c.ROOT/'nextcloud-pending'/(key+'.json')
        data=json.loads(file.read_text())
        if time.time()-data['time']>600:file.unlink(missing_ok=True);raise setup.SetupError('Vorschau abgelaufen. Angaben erneut eingeben.')
        return file,data
    @app.route('/apps/nextcloud/installer/preview',methods=['POST'],endpoint='nextcloud_setup_preview')
    def preview():
        try:
            values=setup.validate(request.form);pw=setup.password(request.form.get('password',''))
            if pw!=request.form.get('password_repeat'):raise setup.SetupError('Passwörter stimmen nicht überein.')
            profile=dict(c.recipe('nextcloud_docker' if values['mode']=='docker' else 'nextcloud'),kind='nextcloud_setup',target=values['target'],setup=values)
            folder=c.ROOT/'nextcloud-pending';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            for old in folder.glob('*.json'):
                if time.time()-old.stat().st_mtime>600:old.unlink(missing_ok=True)
            key=secrets.token_hex(16);setup.write(folder/(key+'.json'),json.dumps(dict(profile=profile,password=pw,time=time.time())))
            session['nextcloud_setup_id']=key
            issues=setup.checks(profile)
            body=_ui_html("<div class='card'><h2>Installationsvorschau</h2><dl>")+''.join('<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>' for k,v in [('Art',values['mode']),('Zugang',values['access']),('Webadresse',setup.base_url(values)),('Bind-IP',values['bind']),('Domain',values['domain']),('Admin',values['admin']),('E-Mail',values['email']),('Programmordner',values['target']),('Datenordner',values['data_root'])])+_ui_html("</dl><p>Abhängigkeiten installieren, eigene MariaDB-Datenbank und Admin einrichten, Redis und Hintergrundaufgaben konfigurieren, Apache-Website erstellen; nur bei öffentlichem Zugang HTTPS-Zertifikat und Erneuerung einrichten und Erreichbarkeit prüfen.</p><p>Passwörter werden nicht angezeigt oder in Downloadpakete übernommen. Bei einem Fehler bleiben bereits angelegte Daten erhalten; der Auftrag meldet keinen Erfolg.</p>")
            if issues:body+=_ui_html('<h3>Installation auf diesem Server gesperrt</h3><ul>')+''.join(_ui_html('<li>')+esc(i)+_ui_html('</li>') for i in issues)+_ui_html('</ul>')
            else:body+=_ui_html("<form method='post' action='/apps/nextcloud/installer/start'>")+token()+_ui_html("<button class='btn'>Jetzt vollständig installieren</button></form>")
            body+=_ui_html("<form method='post' action='/apps/nextcloud/installer/configured-download'>")+token()+_ui_html("<button class='btn'>Installer für anderen Server herunterladen</button></form><p>Das Paket enthält diese Vorgaben; das Admin-Passwort wird auf dem Zielserver im Terminal erneut abgefragt.</p><a href='/apps/nextcloud/installer'>Angaben ändern</a></div>")
            return page(body)
        except (OSError,ValueError) as exc:return fail(exc)
    def start():
        try:
            from .lifecycle import record
            file,data=pending()
            if record(data['profile']['app_id']):raise setup.SetupError('Aufbewahrte Installation vorhanden. Wiederherstellung unter Apps verwalten verwenden.')
            key=jobs.start(data['profile'],'127.0.0.1',credentials={'password':data['password']})
            file.unlink();session.pop('nextcloud_setup_id',None)
            return redirect('/apps/installers/jobs/'+key,303)
        except (OSError,ValueError) as exc:return fail(exc)
    @app.route('/apps/nextcloud/installer/configured-download',methods=['POST'],endpoint='nextcloud_setup_download')
    def download():
        try:
            from .install_ui import package
            _,data=pending()
            result=package(data['profile'])
            return Response(result,mimetype='application/zip',headers={'Content-Disposition':'attachment; filename=nextcloud-setup.zip','Cache-Control':'no-store'})
        except (OSError,ValueError) as exc:return fail(exc)
    return detail,start

def remember_installation(profile):
    """Publish only a completed installation; no credentials enter manager metadata."""
    import server_settings as cfg
    values=profile['setup'];mode=values['mode']
    data=c.read();saved=dict(profile,kind='nextcloud' if mode=='docker' else 'nextcloud_native',web_url=setup.base_url(values))
    if mode=='docker':saved.pop('service',None)
    key='nextcloud_docker' if mode=='docker' else 'nextcloud'
    saved['app_id']=key
    data.setdefault('custom',{})[key]=saved;data.setdefault('web',{})[key]=setup.base_url(values);c.write(data)
    current=cfg.read(cfg.CONFIG)
    if mode=='native':current.update(nextcloud_root=values['target'],nextcloud_data=values['data_root'],nextcloud_user='www-data')
    else:current['nextcloud_container_root']=values['target']
    cfg.atomic(cfg.CONFIG,current)
