"""Installer catalog, portable downloads and WebUI settings; no GET runs installers."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,html,io,json,platform,secrets,subprocess,tarfile,zipfile
from pathlib import Path
from flask import request,session,redirect,Response
from . import install_catalog as c,install_runtime as runtime,install_jobs as jobs

def esc(value):return html.escape(str(value if value is not None else ''),quote=True)
def token():
    if 'app_install_csrf' not in session:session['app_install_csrf']=secrets.token_urlsafe(32)
    return "<input type='hidden' name='csrf' value='"+esc(session['app_install_csrf'])+"'>"
def field(name,label,value=''):
    return _ui_html('<label style="display:block;margin:14px 0">')+esc(_ui_text(label))+_ui_html("<input style='display:block;width:95%;padding:9px' name='")+name+"' value='"+esc(value)+_ui_html("'></label>")

def buttons(manager, include_manage=False):
    url=c.browser_url(manager,request.host_url)
    web=(_ui_html("<a class='btn' target='_blank' rel='noopener noreferrer' href='")+esc(url)+_ui_html("'>WebUI öffnen ↗</a> ")) if url else ''
    models=_ui_html("<a class='btn' href='/apps/open_webui/models'>Qwen-Modelle</a> ") if manager.app_id=='open_webui' else ''
    if include_manage:
        manage=_ui_html("<a class='btn' href='/apps/")+esc(manager.app_id)+_ui_html("'>Verwalten</a> ")
        return manage+web+models
    return web+models+(_ui_html("<a class='btn' href='/apps/pihole/installer/network'>Netzwerk &amp; Zugang</a> <a class='btn' href='/apps/pihole/installer/transfer'>Einstellungen &amp; Listen übertragen</a> ") if manager.app_id=='pihole' else '')

def source_bundle():
    root=Path(__file__).resolve().parents[2]
    r=subprocess.run(['git','-c','safe.directory='+str(root),'-C',str(root),'ls-files','-z'],capture_output=True,timeout=15)
    if r.returncode:
        from tools.build_deb import source_files
        r.stdout=b'\0'.join(str(path.relative_to(root)).encode() for path in source_files(root))
    from tools.build_deb import source_files
    portable={str(path.relative_to(root)) for path in source_files(root)}
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        names=set(r.stdout.split(b'\0'));names.update(name.encode() for name in portable)
        names.update((b'version.py',b'server_settings.py',b'authentication.py',b'tools/authenticated_request.py',b'tools/migrate_auth_timers.py',b'tools/build_deb.py',b'tools/package_first_start.py'))
        for folder in ('modules/server_settings','modules/fotolabor','modules/web_security','modules/downloads'):
            names.update(str(path.relative_to(root)).encode() for path in (root/folder).glob('*.py'))
        names.update(('modules/app_manager/'+name).encode() for name in ('install_ui.py','install_catalog.py','install_runtime.py','installed_apps.py','install_jobs.py','openwebui_update.py','openwebui_https.py','qwen_models.py','qwen_ui.py','managers/open_webui.py','nextcloud_setup.py','nextcloud_ui.py','nextcloud_variants.py','nextcloud_docker.py','lifecycle.py','manage_ui.py','backup_rtc.py'))
        names.update(str(path.relative_to(root)).encode() for path in (root/"modules/scanner").glob("*.py"))
        for raw in sorted(names):
            if not raw:continue
            rel=Path(raw.decode());path=root/rel
            if rel.is_absolute() or '..' in rel.parts or path.is_symlink() or not path.is_file():continue
            if str(rel) not in portable:continue
            if path.stat().st_size>5*1024*1024:continue
            info=archive.gettarinfo(str(path),arcname=str(rel))
            info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0
            info.pax_headers={}
            with path.open('rb') as content:archive.addfile(info,content)
    return stream.getvalue()

def ai_variant(profile,mode):
    if profile['app_id']!='open_webui':return profile
    if mode not in ('complete','webui'):raise c.Invalid('Ungültige KI-Installationsart.')
    return dict(profile,https=True,local_ai=mode=='complete',image='ghcr.io/open-webui/open-webui:'+('ollama' if mode=='complete' else 'main'))


def package(profile):
    stream=io.BytesIO();assets={}
    if profile['kind']=='oscam_bundle':
        binary=Path('/usr/local/bin/oscam')
        if not binary.is_file():raise c.Invalid('Lokale OSCam-Binary fehlt; kein reproduzierbares Installerpaket verfügbar.')
        assets['oscam']=binary.read_bytes();profile=dict(profile,architecture=platform.machine())
    if profile['kind']=='server_bundle':assets['server-manager.tar']=source_bundle()
    if profile['kind']=='nextcloud_setup':assets['nextcloud_setup.py']=(Path(__file__).parent/'nextcloud_setup.py').read_bytes()
    if profile['kind']=='kvm_setup':assets['kvm_setup.py']=(Path(__file__).parent/'kvm_setup.py').read_bytes()
    if profile['kind']=='kvm_setup':
        assets['bridge_migration.py']=(Path(__file__).parent/'bridge_migration.py').read_bytes()
        assets['platform_check.py']=(Path(__file__).resolve().parents[2]/'tools/platform_check.py').read_bytes()
    if profile.get('https'):assets['openwebui_https.py']=(Path(__file__).parent/'openwebui_https.py').read_bytes()
    if profile.get('local_ai'):assets['docker_setup.py']=(Path(__file__).parent/'docker_setup.py').read_bytes()
    assets['installer.py']=Path(runtime.__file__).read_bytes()
    assets['profile.json']=json.dumps(profile,ensure_ascii=False,indent=2).encode()
    assets['README.txt']=(_ui_text(profile['label'])+' · Neuinstallationspaket\n\n'
      'Zielsystem: Debian 13 / Python 3.13.\n'
      '1. ZIP in ein eigenes Verzeichnis entpacken.\n'
      '2. python3 installer.py --check\n'
      '3. sudo python3 installer.py --install\n'
      'Optional LAN-Bindung: --bind <Server-IPv4> (Standard 127.0.0.1).\n'
      'Docker-Apps benötigen bereits Docker Engine und Compose.\n'
      'Bestand wird nicht überschrieben. Für Wiederherstellung die App-Backups verwenden.\n'
      'Keine Benutzerdaten, Reader, Zugangsdaten oder Modelle sind enthalten.\n'
      'OSCam benötigt dieselbe Architektur; WebIF zunächst nur lokal.\n'
      'ComfyUI wird als CPU-Installation eingerichtet, GPU-Treiber separat.\n'
      'Nextcloud-Neuinstallation verwendet Docker; bestehendes natives Nextcloud wird nicht umgebaut.\n'
      'Tvheadend benötigt eine konfigurierte Paketquelle mit einem Kandidaten.\n'
      'Heimserver Manager ist ein Code-Bootstrap; Hostdienste und bestehende Daten kommen aus separat eingerichteten Diensten/Backups.\n'
      'Upstream-Downloads/Image-Pulls erfolgen erst bei --install. Ersteinrichtung über die WebUI abschließen.\n'
      'Bei Fehlern bleiben neue Dateien zur Diagnose erhalten; kein automatisches Löschen.\n').encode()
    if profile['kind']=='nextcloud_setup':assets['README.txt']=('Nextcloud Komplettinstallation · Debian 13\n\n1. Paket entpacken.\n2. python3 installer.py --check\n3. sudo python3 installer.py --install\nAdmin-Passwort wird verdeckt im Terminal abgefragt. Öffentlicher Modus: DNS und Ports 80/443 vorher einrichten. Lokaler Modus: konfigurierte private Bind-IP und Webport verwenden; WireGuard bei Bedarf vorher einrichten, keine öffentliche Portfreigabe nötig. Keine Zugangsdaten sind im Paket enthalten. Vorhandene Installationen werden nicht überschrieben. Bei Fehlern bleiben Teilschritte bestehen; keine automatische Datenlöschung.\n').encode()
    if profile['kind']=='kvm_setup':assets['README.txt']=assets['README.txt'].replace(b'Zielsystem: Debian 13 / Python 3.13.',b'Zielsystem: Debian 13 / Python 3.13 oder Linux Mint 22.x (Noble) / Python 3.12. NAT ist die Vorgabe; LAN-Uebernahme nur nach eigener Vorschau und Bestaetigung.')
    if profile.get('https'):assets['README.txt']+='\nHTTPS wird automatisch mit Apache eingerichtet; Standardport 3443. Optional vor Installation https_host, https_ip und https_port in profile.json setzen. Stammzertifikat https/trust-ca.crt auf Clients importieren. HTTP bleibt nur lokal. Tägliche Erneuerung per Timer.\n'.encode()
    if profile.get('local_ai'):
        assets['README.txt']=assets['README.txt'].replace(b'Docker-Apps ben'+bytes([195,182])+b'tigen bereits Docker Engine und Compose.',b'Docker/Compose wird bei Bedarf mitinstalliert.')
        assets['README.txt']+='\nLokale KI: Ollama, Open WebUI und Qwen3 0.6B im CPU-Betrieb. Vorhandenes Ollama wird nicht ersetzt. API nur lokal; Erstkonto in WebUI anlegen. Daten und Modelle bleiben bei einfacher Deinstallation erhalten.\n'.encode()
    assets['SHA256SUMS']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in assets.items()).encode()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in assets.items():archive.writestr(name,data)
    return stream.getvalue()

def register(app,ctx):
    from .registry import get_manager,MANAGERS
    def page(title,body):return ctx.page(title,_ui_html("<div class='card'><a class='btn' href='/apps'>Apps</a> <a class='btn' href='/apps/manage'>Apps verwalten</a> <a class='btn' href='/apps/installers/new'>Neue Container-App</a></div>")+body,'Apps')
    def error(exc,code=400):return page(_ui_text('App-Installer'),_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html("</p></div>")),code
    from .nextcloud_ui import register as register_nextcloud
    nextcloud_detail,nextcloud_start=register_nextcloud(app,ctx,token)
    from .kvm_ui import register as register_kvm
    kvm_detail,kvm_start=register_kvm(app,ctx,token)
    @app.before_request
    def installer_csrf():
        protected=request.path.startswith('/apps/pihole/installer/') or request.path.startswith('/apps/nextcloud/installer/') or request.path.startswith('/apps/installers') or request.path.endswith('/installer') or request.path.endswith('/installer/start')
        if protected and request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return error('Formular abgelaufen. Bitte neu laden.',403)
    from .pihole_network_ui import register as network_register
    network_register(app,ctx,token)
    from .pihole_setup_ui import register as native_register
    native_register(app,ctx,token)
    from .pihole_transfer_ui import register as transfer_register
    transfer_register(app,ctx,token)
    @app.route('/apps/pihole/installer/settings',methods=['POST'])
    def pihole_settings():
        try:
            profile=c.recipe('pihole')
            if request.form.get('action')=='web':
                url=c.valid_url(request.form.get('web_url','').strip())
                saved=c.read();saved.setdefault('web',{})['pihole']=url;c.write(saved)
                return redirect('/apps/pihole/installer',303)
            if runtime.pihole_existing() or Path(profile['target']).exists():raise ValueError('Pi-hole ist bereits vorhanden. Den erkannten Webport übernehmen; eine bestehende Portzuordnung direkt in Pi-hole/Compose ändern. Die Webadresse kann im App-Installer unter WebUI-Adresse angepasst werden.')
            port=int(request.form.get('web_port',''))
            if not 1024<=port<=65535:raise ValueError('Webport zwischen 1024 und 65535 wählen.')
            profile.update(port=port,web_url='http://127.0.0.1:'+str(port)+'/admin/')
            profile.pop('app_id',None)
            saved=c.read();saved.setdefault('custom',{})['pihole']=profile;c.write(saved)
            return redirect('/apps/pihole/installer',303)
        except (ValueError,OSError) as exc:return error(exc)
    @app.route('/apps/installers',endpoint='app_installer_catalog')
    def catalog():
        return redirect('/apps/manage', 302)
    @app.route('/apps/<app_id>/installer',endpoint='app_installer_detail')
    def detail(app_id):
        if app_id=='kvm':return kvm_detail()
        if app_id=='nextcloud_docker':return redirect('/apps/nextcloud/installer?mode=docker',303)
        if app_id=='nextcloud':return nextcloud_detail()
        manager=get_manager(app_id)
        try:profile=ai_variant(c.recipe(app_id),request.args.get('ai','complete'))
        except c.Invalid as exc:return error(exc,404)
        problems=runtime.checks(profile)
        body=_ui_html("<div class='card'><h2>")+esc(_ui_text(profile['label']))+_ui_html(" · Installer</h2><p>Dieser Installer installiert das Programm auf diesem Server, wenn es noch nicht vorhanden ist. Eine vorhandene Installation wird nicht ersetzt oder zurückgesetzt.</p>")
        if manager:body+=_ui_html('<p>')+buttons(manager)+_ui_html('</p>')
        if app_id=='open_webui':
            body+=_ui_html("<h3>Lokale KI komplett</h3><p><a class='btn' href='?ai=complete'>Open WebUI + Ollama + Startmodell</a> <a class='btn' href='?ai=webui'>Nur Open WebUI (Ollama vorhanden)</a></p><p>Gewählt: ")+(_ui_text('Komplettinstallation') if profile.get('local_ai') else _ui_text('Nur Open WebUI'))+_ui_html(". Komplett installiert fehlendes Docker/Compose, Open WebUI mit Ollama und Qwen3 0.6B. Ollama-API nur auf 127.0.0.1:11434; Modelle und WebUI-Daten bleiben in getrennten Docker-Volumes. CPU-Betrieb ohne GPU-Treiber. Erstes Konto anschließend in Open WebUI anlegen. Updates erhalten die Ollama-Imagevariante; Modelldateien bleiben erhalten.</p>")

        if app_id=='open_webui':
            body+=_ui_html("<p>Neue Installation ausschließlich über HTTPS im LAN. Apache und private Zertifikate werden eingerichtet; tägliche Zertifikatserneuerung. HTTP-Port und Ollama-API bleiben nur intern erreichbar. Standard: https://RECHNERNAME:3443. Hostnamen im lokalen DNS/hosts auflösen und Stammzertifikat auf Clients importieren. Vorhandene Websites werden nicht umgestellt.</p>")
            ca=Path(profile['target'])/'https/trust-ca.crt'
            if ca.is_file():
                import ssl,hashlib
                fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(ca.read_text())).hexdigest()
                body+=_ui_html("<p><a class='btn' href='/apps/open_webui/installer/ca'>Privates Stammzertifikat herunterladen</a><br>SHA-256: <code>")+fingerprint+_ui_html("</code><br>Vor dem Import Fingerabdruck vergleichen. Import erteilt dieser Zertifizierungsstelle Vertrauen.</p>")

        if app_id=='pihole':
            body+=_ui_html("<p><a class='btn' href='/apps/pihole/installer/native'>Alternative: Pi-hole nativ installieren</a> <a class='btn' href='/apps/pihole/installer/transfer'>Einstellungen &amp; Listen übertragen</a></p>")
            body+=_ui_html("<p><a class='btn' href='/apps/pihole/installer/network'>Netzwerk &amp; Zugang</a></p>")
            existing=runtime.pihole_existing()
            if len(existing)>1:body+=_ui_html('<p>Mehrere Pi-hole-Installationen erkannt. Keine automatische Auswahl; Webadresse der gewünschten Installation separat festlegen.</p>')
            elif existing:
                body+=_ui_html('<p>Vorhandene Installation: ')+esc(existing[0]['kind'])+' · Webadresse: '+esc(existing[0]['web_url'] or _ui_text('Nicht eindeutig erkannt – Webadresse manuell festlegen'))+_ui_html('. Bestehende Ports werden nicht verändert.</p>')
                body+=_ui_html("<form method='post' action='/apps/pihole/installer/settings'>")+token()+_ui_html("<input type='hidden' name='action' value='web'>")+field('web_url','Webadresse korrigieren (ändert nur den Link, keine Dienstports)',c.read().get('web',{}).get('pihole') or existing[0]['web_url'])+_ui_html("<button class='btn'>Webadresse speichern</button></form>")
            else:
                body+=_ui_html("<form method='post' action='/apps/pihole/installer/settings'>")+token()+field('web_port','Webport für die Neuinstallation (1024–65535)',profile['port'])+_ui_html("<button class='btn'>Webport speichern</button></form><p>DNS bleibt auf 53/TCP und 53/UDP. Der Webport ist davon unabhängig.</p>")
        body+=_ui_html('<p>Installationsart: <b>')+esc(profile['kind'])+_ui_html('</b><br>Ziel: <code>')+esc(profile['target'])+_ui_html('</code></p>')
        notes={'nextcloud':'Neuinstallation als Docker-Stack. Bestehende native Installation bleibt unverändert.','comfyui':'CPU-Installation. GPU-Treiber, GPU-PyTorch und Modelle werden nicht mitinstalliert.','oscam_bundle':'Installer enthält die lokale Binary für '+platform.machine()+', aber keine Reader oder Zugangsdaten.','server_bundle':'Code-Bootstrap aus dem Repository. Hostdienste und vorhandene Daten sind separat einzurichten.','tvheadend':'Benötigt einen Paketkandidaten in den bereits konfigurierten APT-Quellen.'}
        if app_id=='pihole':notes[app_id]='Optionaler DNS-Werbeblocker als Docker-Container. Benötigt Docker mit Compose sowie freie Ports 53/TCP, 53/UDP und den gewählten Webport (aktuell '+str(profile['port'])+'/TCP). Konkrete LAN-IP wählen (für lokalen Test 127.0.0.1); 0.0.0.0 wird abgewiesen. Weboberfläche: http://SERVER-IP:'+str(profile['port'])+'/admin/. Konfiguration bleibt im Datenordner erhalten. Ein zufälliges Admin-Passwort wird erst bei Installation erzeugt und geschützt unter '+profile['target']+'/admin-password.txt gespeichert (sudo cat DATEIPFAD). DNS-Weiterleitung und Filter danach in Pi-hole prüfen. Router, DHCP, Firewall und bestehende DNS-Dienste werden nicht umgestellt. Anschließend einzelne Clients auf die Server-IP als DNS einstellen; für dauerhaften Betrieb eine feste IP verwenden.'
        if app_id in ('plex','jellyfin'):
            notes[app_id]='Optionale Docker-Installation. Port '+str(profile['port'])+'. Medienordner: '+profile['target']+'/media (in der App als /media nur lesbar). Konfiguration: '+profile['target']+'/data. Vorhandene Medienordner können später in compose.json eingebunden werden. Hardware-Transcoding und automatische Geräteerkennung werden nicht eingerichtet. Ersteinrichtung in der App abschließen.'
            if app_id=='plex':notes[app_id]+=' Plex benötigt die Zuordnung zum Plex-Konto; zur ersten Einrichtung gegebenenfalls einen SSH-Tunnel auf Port 32400 verwenden (siehe offizielle Anleitung).'
        if app_id=='shares_mounts':notes[app_id]='Installiert oder ergänzt Samba- und NFS-Server, Clientwerkzeuge und ACL-Unterstützung. Fehlende Grundkonfiguration wird erstellt, vorhandene Konfiguration bleibt erhalten. Anschließend werden Konfiguration und aktive Dienste geprüft. Auch nach einer früheren reinen Client-Installation erneut ausführbar.'
        if app_id in notes:body+=_ui_html('<p>')+esc(notes[app_id])+_ui_html('</p>')
        body+=_ui_html('<h3>Prüfung dieses Servers</h3>')
        if any('Docker Engine' in issue for issue in problems):body+=_ui_html("<p><a class='btn' href='/apps/docker/installer'>Docker Engine & Compose installieren / prüfen</a></p>")
        if problems:body+=_ui_html('<ul>')+''.join(_ui_html('<li>')+esc(text)+_ui_html('</li>') for text in problems)+_ui_html('</ul><p>Das Paket kann trotzdem für einen passenden, noch nicht eingerichteten Zielserver heruntergeladen werden.</p>')
        else:body+=_ui_html('<p>Ziel, Dienste und Ports sind frei. Der Installer prüft diese Bedingungen vor Ausführung erneut.</p>')
        running=jobs.active()
        if running:
            body+=_ui_html("<p><a class='btn' href='/apps/installers/jobs/")+esc(running['id'])+_ui_html("'>Laufende Installation anzeigen</a></p>")
        elif not problems:
            body+=_ui_html("<form method='post' action='/apps/")+esc(app_id)+"/installer/start'>"+token()+("<input type='hidden' name='ai' value='"+('complete' if profile.get('local_ai') else 'webui')+"'>" if app_id=='open_webui' else '')+(field('https_host','HTTPS-Hostname (leer = Rechnername)','')+field('https_ip','Zusätzliche lokale IPv4-Adresse im Zertifikat (optional)','')+field('https_port','HTTPS-Port','3443') if app_id=='open_webui' else field('bind','Konkrete LAN-IPv4-Adresse (127.0.0.1 = nur lokal)' if app_id=='pihole' else 'Erreichbar auf IPv4-Adresse (0.0.0.0 = alle Schnittstellen)','127.0.0.1' if app_id=='pihole' else '0.0.0.0'))+_ui_html("<button class='btn'>Jetzt auf diesem Server installieren</button></form>")
        else:
            body+=_ui_html("<p><b>Keine Installation gestartet.</b> Bei vorhandenem Programm bitte dessen Verwaltung verwenden.</p>")
        body+=_ui_html("<details><summary>Installer für einen anderen Server herunterladen</summary><p><a class='btn' href='/apps/")+esc(app_id)+_ui_html("/installer/download")+('?ai='+('complete' if profile.get('local_ai') else 'webui') if app_id=='open_webui' else '')+_ui_html("'>Installerpaket herunterladen</a></p></details>")
        if profile.get('docs'):body+=_ui_html("<p><a target='_blank' rel='noopener noreferrer' href='")+esc(profile['docs'])+_ui_html("'>Offizielle Installationsanleitung</a></p>")
        body+=_ui_html('</div>')
        return page(profile['label']+' · Installer',body)
    @app.route('/apps/open_webui/installer/ca',endpoint='openwebui_private_ca')
    def private_ca():
        from flask import send_file,abort
        path=Path(c.recipe('open_webui')['target'])/'https/trust-ca.crt'
        if not path.is_file() or path.is_symlink():abort(404)
        return send_file(path,as_attachment=True,download_name='Open-WebUI-Stammzertifikat.crt',mimetype='application/x-x509-ca-cert')
    @app.route('/apps/<app_id>/installer/start',methods=['POST'],endpoint='app_installer_start')
    def start_install(app_id):
        if app_id=='kvm':return kvm_start()
        if app_id in ('nextcloud','nextcloud_docker'):return nextcloud_start()
        try:
            from .lifecycle import record
            if record(app_id):raise c.Invalid('Aufbewahrter Installationsstand vorhanden. Bitte unter Apps verwalten wieder installieren.')
            profile=ai_variant(c.recipe(app_id),request.form.get('ai','complete'))
            if app_id=='open_webui':
                from .openwebui_https import values
                profile.update(https_host=request.form.get('https_host',''),https_ip=request.form.get('https_ip',''),https_port=request.form.get('https_port','3443'))
                host,port,ip=values(profile);profile.update(https_host=host,https_port=port,https_ip=ip)
            key=jobs.start(profile,request.form.get('bind','127.0.0.1'))
            return redirect('/apps/installers/jobs/'+key,303)
        except (c.Invalid,OSError,ValueError) as exc:return error(exc)
    @app.route('/apps/installers/jobs/<key>',endpoint='app_installer_job')
    def install_job(key):
        try:
            state=jobs.load(key);log=jobs.job_path(key)/'install.log'
            if log.exists():
                with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-20000));output=stream.read().decode('utf-8','replace')
            else:output='Noch keine Ausgabe.'
            body=_ui_html("<div class='card'><h2>")+esc(_ui_text(state['label']))+_ui_html(' · App-Auftrag</h2><p>')+esc(_ui_text(state['message']))+_ui_html('</p>')
            body+=_ui_html("<p><a class='btn' href='/apps/manage'>Apps verwalten</a> <a class='btn' href='/apps/")+esc(state['app_id'])+_ui_html("'>Zur App</a></p><pre style='white-space:pre-wrap'>")+esc(output)+_ui_html('</pre></div>')
            if state['state'] not in jobs.TERMINAL:body+=_ui_html("<script>setTimeout(()=>location.reload(),4000)</script>")
            return page(_ui_text('App-Installation'),body)
        except (c.Invalid,OSError) as exc:return error(exc,404)
    @app.route('/apps/<app_id>/installer/download',endpoint='app_installer_download')
    def download(app_id):
        if app_id in ('nextcloud','nextcloud_docker'):return redirect('/apps/nextcloud/installer'+('?mode=docker' if app_id=='nextcloud_docker' else ''),303)
        try:
            data=package(ai_variant(c.portable_recipe(app_id),request.args.get('ai','complete')))
            return Response(data,mimetype='application/zip',headers={'Content-Disposition':'attachment; filename='+app_id+'-installer.zip','Cache-Control':'no-store'})
        except (c.Invalid,OSError,subprocess.TimeoutExpired) as exc:return error(exc)
    @app.route('/apps/installers/new',methods=['GET','POST'],endpoint='app_installer_new')
    def new():
        message=''
        if request.method=='POST':
            try:
                key,profile=c.custom(request.form);data=c.read()
                if key in c.recipes() or get_manager(key):raise c.Invalid('App-ID existiert bereits.')
                data.setdefault('custom',{})[key]=profile;c.write(data)
                return redirect('/apps/'+key+'/installer',303)
            except c.Invalid as exc:message=str(exc)
        body=_ui_html("<div class='card'><h2>Neue Container-App</h2><p>Einzelcontainer mit persistentem Datenverzeichnis. Registrierung erzeugt WebUI-Zugang und Installer; sie startet noch keinen Container.</p><p>")+esc(_ui_text(message))+_ui_html("</p><form method='post'>")+token()
        for key,label,value in [('app_id','App-ID (z. B. meine_app)',''),('label','Anzeigename',''),('image','Image mit Tag oder Digest',''),('port','WebUI-Port am Server','8090'),('container_port','WebUI-Port im Container','8080'),('mount','Persistentes Datenverzeichnis im Container','/data')]:body+=field(key,label,request.form.get(key,value))
        body+=_ui_html("<button class='btn'>App & Installer anlegen</button></form></div>");return page(_ui_text('Neue App'),body)
