"""Nextcloud wake setup: explicit profile transfer and separate public routing."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json,secrets
from flask import request,session,Response,redirect
from . import engine
from modules.app_manager.install_ui import esc,token

def register(app,ctx):
    @app.route('/apps/nextcloud/wake',methods=['GET','POST'])
    def nextcloud_wake():
        from modules.app_manager import install_jobs as jobs
        message=''
        try:state=engine.info();stored=engine.load()
        except Exception:state=dict(installed=False,active='unbekannt',revision='');stored={};message='Bestand nicht lesbar oder fremder Dienst. Installation prüfen.'
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return 'Formular abgelaufen.',403
            try:
                if request.form.get('confirm')!='yes':raise ValueError('Einrichtung bestätigen.')
                config={k:request.form.get(k,'').strip() for k in ('domain','backend','manager_url','recovery_url','port','wake_wait','hold_seconds','wake_cooldown')}
                credentials={k:stored.get(k,'') for k in ('token','ca_pem')}
                upload=request.files.get('profile')
                if upload and upload.filename:
                    data=json.loads(upload.stream.read(65537))
                    if data.get('format')!='nextcloud-wake-blocker':raise ValueError('Dediziertes Nextcloud-Wake-Profil erforderlich.')
                    credentials=dict(token=data['token'],ca_pem=data.get('ca_pem',''));config['manager_url']=data['manager_url']
                checked=engine.validate(dict(config,**credentials));public={k:v for k,v in checked.items() if k not in ('token','ca_pem')}
                key=jobs.start(dict(app_id='nextcloud_wake',label='Nextcloud Wake Gateway'),'127.0.0.1',action='nextcloud_wake',plan=dict(config=public,revision=request.form.get('revision','')),credentials=credentials)
                return redirect('/apps/installers/jobs/'+key,303)
            except (ValueError,KeyError,OSError) as exc:message='Einrichtung nicht gestartet: '+esc(str(exc))
        body=_ui_html("<div class='card'><h2>Nextcloud bei Zugriff wecken</h2><p>Auf dem Dauerläufer installieren. Der Gateway ruft bei nicht erreichbarem Nextcloud-Ziel die Recovery-API auf, wartet begrenzt auf status.php und hält während Übertragungen sowie der Nachlaufzeit einen eigenen Schlafblocker.</p><p><a class='btn' href='/apps/manage'>Apps verwalten</a> <a class='btn' href='/apps/power_api/installer'>Recovery API</a> <a class='btn' href='/dyndns/targets'>Ziele &amp; Dienste</a></p><p>Lokaler Gateway: ")+esc(state['active'])+_ui_html('</p>')
        if message:body+=_ui_html("<p class='err'>")+_ui_text(message)+_ui_html('</p>')
        body+=_ui_html("<h3>1. Auf dem Nextcloud-Server: Blocker-Profil</h3><p>Diese Seite im Manager des schlafenden Nextcloud-Servers öffnen. Netzwerk/Client-Schlafblocker müssen dort aktiviert sein. Der Download legt einen eigenen Dienst-Client an. Token geschützt aufbewahren; keine persönlichen Client-Profile verwenden. Der Dienst-Client lässt sich unter Client-Agenten deaktivieren oder löschen. Bei erneutem Download alten Eintrag nach erfolgreicher Umstellung entfernen.</p><form method='post' action='/apps/nextcloud/wake/profile'>")+token()+_ui_html("<button>Eigenen Wake-Blocker anlegen und Profil herunterladen</button></form></div>")
        body+=_ui_html("<div class='card'><h3>2. Auf dem Dauerläufer: Gateway einrichten</h3><form method='post' enctype='multipart/form-data'>")+token()+_ui_html("<input type='hidden' name='revision' value='")+esc(state['revision'])+_ui_html("'><p><label>Blocker-Profil vom Nextcloud-Server<input type='file' name='profile' accept='.json'></label><br>Bei bestehendem Gateway leer lassen, um Zugang und CA zu behalten. Das Profil enthält vertrauliche Zugangsdaten.</p>")
        defaults={'domain':'','backend':'','manager_url':'','recovery_url':'http://127.0.0.1:8182/recover','port':'8183','wake_wait':'60','hold_seconds':'600','wake_cooldown':'120'}
        labels={'domain':'Öffentliche Nextcloud-Domain','backend':'Nextcloud-Ziel (HTTP/HTTPS, feste LAN-IP und Port, ohne Unterpfad)','manager_url':'Manager-Adresse auf dem Nextcloud-Server (HTTPS; Profil hat Vorrang)','recovery_url':'Recovery-Adresse auf dem Dauerläufer','port':'Lokaler Gateway-Port (nur Loopback)','wake_wait':'Warten pro Anfrage (10–180 Sekunden)','hold_seconds':'Nachlaufzeit (30–3600 Sekunden)','wake_cooldown':'Mindestabstand Recovery-Aufrufe (30–1800 Sekunden)'}
        for k in defaults:body+=_ui_html("<p><label>")+_ui_text(labels[k])+_ui_html("<br><input name='")+k+"' value='"+esc(str(stored.get(k,defaults[k])))+_ui_html("'></label></p>")
        body+=_ui_html("<p>HTTPS zum Nextcloud-Ziel prüft das Zertifikat gegen die öffentliche Nextcloud-Domain; die Verbindung geht an die eingetragene LAN-IP. Profil-CA wird nur für diesen Gateway vertraut. Kein systemweiter Zertifikatsimport.</p><label><input type='checkbox' required name='confirm' value='yes'> Lokalen Gateway installieren/aktualisieren; Zertifikatsvertrauen aus dem eigenen Profil bestätigen</label><p><button>Gateway bereitstellen</button></p></form></div>")
        from urllib.parse import urlencode
        link='/dyndns/proxy?'+urlencode(dict(host=stored.get('domain',''),target_host='127.0.0.1',target_port=stored.get('port',8183),target_scheme='http'))
        body+=_ui_html("<div class='card'><h3>3. Öffentlichen Zugang separat aktivieren</h3><p>Erst nach Test: HTTPS-Proxy auf diesem Dauerläufer zur Gateway-Adresse einrichten. Nextcloud trusted_proxies und ggf. overwriteprotocol konfigurieren. IPv4-/IPv6-Zugriff und Router auf den Dauerläufer umstellen. Bestehende Websites werden vom Proxy-Assistenten nicht überschrieben. Unterpfadinstallationen und WebSockets werden von diesem Gateway nicht unterstützt.</p><a class='btn' href='")+esc(link)+_ui_html("'>HTTPS-Proxy einrichten …</a><p><b>Die Gateway-Installation ändert weder die aktive Nextcloud-Verbindung noch DNS, Router oder Zertifikate.</b> Öffentliche Bots und häufige Handy-Synchronisation können den Server wecken. Clients können vor Ablauf der Wartezeit abbrechen. Schreibanfragen werden nicht automatisch wiederholt. Bei fehlendem Schlafblocker werden keine Nutzdaten weitergeleitet.</p></div>")
        return ctx.page(_ui_text('Nextcloud Wake'),body,'Apps')
    @app.post('/apps/nextcloud/wake/profile')
    def wake_profile():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return 'Formular abgelaufen.',403
        from modules.module_selection.config import network_enabled
        from modules.web_security import manager_https as mh
        from modules.heimnetz_clients import init_tables
        if not network_enabled():return 'Netzwerk-/Client-Schlafblocker zuerst aktivieren.',400
        state=mh.load()
        if not state.get('enabled'):return 'HTTPS im Manager zuerst einrichten.',400
        secret=secrets.token_urlsafe(32);con=ctx.db()
        try:
            init_tables(con)
            con.execute("INSERT INTO client_agents(name,hostname,token,mode,enabled) VALUES(?,?,?,?,1)",('Nextcloud Wake Gateway','wake-proxy',secret,'with_server'));con.commit()
        finally:con.close()
        data=dict(format='nextcloud-wake-blocker',manager_url=mh.public_url(state),token=secret,ca_pem=(mh.TLS/'root-ca.crt').read_text() if (mh.TLS/'root-ca.crt').exists() else '')
        return Response(json.dumps(data),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="Nextcloud-Wake-Blocker.json"','Cache-Control':'no-store'})
