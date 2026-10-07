"""Human-readable host settings with a staged restart boundary."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json
import os
import secrets
import shlex
import subprocess
import threading
import time
from pathlib import Path
from flask import request, session, redirect, jsonify, Response, g
import server_settings as cfg


def register(app,ctx):
    e=lambda value:ctx.esc(str(value))
    requests_lock=threading.Lock()
    activity={'posts':0,'restart_until':0}
    @app.before_request
    def protect_settings_restart():
        if request.method != 'POST' or request.path in ('/settings/server-paths','/settings/server-port'):return
        with requests_lock:
            if activity['restart_until'] > time.monotonic():
                return 'Heimserver Manager startet neu. Bitte danach erneut versuchen.',503
            activity['posts']+=1;g.server_paths_post=True
    @app.teardown_request
    def finish_settings_request(error=None):
        if getattr(g,'server_paths_post',False):
            with requests_lock:activity['posts']-=1
            g.server_paths_post=False
    def token():
        session.setdefault('server_paths_csrf',secrets.token_urlsafe(32))
        return "<input type='hidden' name='csrf' value='"+e(session['server_paths_csrf'])+"'>"
    def protected():
        return secrets.compare_digest(request.form.get('csrf',''),session.get('server_paths_csrf','!'))
    def page(body,code=200):return ctx.page(_ui_text('Server & Modulpfade'),body,'Einstellungen'),code
    def busy():
        from modules.app_manager.apt_jobs import active as apt_active
        if apt_active():return ['APT-Systemupgrade']
        from modules.backup.central import get_blockers as backup_blockers
        if backup_blockers():return ['Server-/Client-Sicherung']
        from modules.downloads.files import get_blockers as download_blockers
        result=['Dateidownload'] if download_blockers() else []
        with requests_lock:
            if activity['posts']:result.append('Laufende Web-Aktion')
        if any(t.name.startswith('app-update-') and t.is_alive() for t in threading.enumerate()):result.append('App-Update')
        if any(t.name=='server-manager-manual-sleep' and t.is_alive() for t in threading.enumerate()):result.append('Manuelle Server-Aktion')
        if result:return result
        con=ctx.db()
        try:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('fotolabor_jobs','fotolabor_slideshows','kvm_jobs'):
                if table in tables and con.execute('SELECT 1 FROM '+table+" WHERE state IN ('queued','running') LIMIT 1").fetchone():result.append(table)
        finally:con.close()
        photo=app.extensions.get('fotolabor')
        if photo and photo.ctx.db_path != ctx.db_path:
            if photo.query("SELECT id FROM fotolabor_jobs WHERE state IN ('queued','running')") or photo.query("SELECT id FROM fotolabor_slideshows WHERE state IN ('queued','running')"):
                result.append('Fotolabor')
        from modules.app_manager.plugin import get_active_job
        from modules.app_manager.install_jobs import active as installers
        from modules.app_manager.qwen_models import active as models
        from modules.scanner.engine import active as scanner
        from modules.web_security.jobs import active as web_security
        for name,check in [('Web & Sicherheit',web_security),('App-Auftrag',get_active_job),('App-Installation',installers),('Modelldownload',models),('Scanner',scanner)]:
            if check():result.append(name)
        units=subprocess.run(['systemctl','list-units','--type=service','--state=running,activating','--no-legend','--plain','server-manager-appbackup-*'],capture_output=True,text=True,timeout=10,check=True)
        if units.stdout.strip():result.append('Geplantes App-Backup')
        return result

    @app.route('/settings/server-paths',methods=['GET','POST'])
    def server_paths():
        message=''; values=cfg.load(True)
        if request.method=='POST':
            if not protected():return page(_ui_html('<p>Formular abgelaufen. Bitte neu laden.</p>'),403)
            try:
                action=request.form.get('action','save')
                if action=='discard':
                    if request.form.get('revision')!=cfg.revision():raise ValueError('Einstellungen wurden inzwischen geändert. Bitte neu laden.')
                    cfg.PENDING.unlink(missing_ok=True);return redirect('/settings/server-paths',303)
                if action=='restart':
                    if request.form.get('revision')!=cfg.revision():raise ValueError('Einstellungen wurden inzwischen geändert. Bitte neu laden.')
                    jobs=busy()
                    if jobs:raise ValueError('Bitte laufende Aufträge abwarten: '+', '.join(jobs))
                    with requests_lock:
                        if activity['posts']:raise ValueError('Eine Web-Aktion wurde gerade gestartet. Bitte erneut versuchen.')
                        activity['restart_until']=time.monotonic()+30
                    subprocess.run(['systemd-run','--quiet','--collect','--on-active=3s','--unit=server-manager-settings-restart-'+secrets.token_hex(4),'/usr/bin/systemctl','restart','server-manager.service'],check=True,timeout=10)
                    return page(_ui_html("<div class='card'><h2>Heimserver Manager wird neu gestartet</h2><p>Die vorgemerkten Einstellungen werden beim Start übernommen.</p><p><a class='btn' href='/settings/server-paths'>Einstellungen erneut öffnen</a></p></div>"))
                changed={key:request.form.get(key,'').strip() for key in cfg.FIELDS}
                for key,spec in cfg.FIELDS.items():
                    if spec[2]=='paths':changed[key]=[v.strip() for v in changed[key].splitlines() if v.strip()]
                # The editable rows contain only monitor metadata, never credentials.
                rows=[]
                for i in range(101):
                    if request.form.get('backup_name_'+str(i),'').strip():
                        rows.append({**{k:request.form.get('backup_'+k+'_'+str(i),'').strip() for k in ('name','path','pattern','warn_h','crit_h')},'required':request.form.get('backup_required_'+str(i)) in ('1','True','true')})
                if rows!=values['backup_items']:
                    normalized=[dict(r,warn_h=int(r['warn_h']),crit_h=int(r['crit_h'])) for r in rows]
                    if normalized!=values['backup_items']:changed['backup_items']=normalized
                labels={}
                for i in range(101):
                    path=request.form.get('storage_path_'+str(i),'').strip()
                    if path:labels[path]=request.form.get('storage_label_'+str(i),'').strip()
                if labels!=values['storage_labels']:changed['storage_labels']=labels
                values=cfg.stage(changed,request.form.get('revision',''))
                message='Gespeichert und geprüft. Wirksam nach Neustart des Heimserver Managers; vorhandene Daten wurden nicht verschoben.'
            except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
                return page(_ui_html("<div class='card'><p class='err'>")+e(_ui_text(exc))+_ui_html("</p><a href='/settings/server-paths'>Zurück zu den Einstellungen</a></div>"),400)
        body=_ui_html("<div class='card'><h2>Server & Modulpfade</h2><p><a class='btn' href='/settings/server-port'>Webport ändern</a></p><p>Ordner, Netzwerk und App-Zuordnung für diesen Server. Neue Werte werden erst beim nächsten Start des Heimserver Managers aktiv.</p>")
        body+=_ui_html("<p>Ein anderer Pfad verschiebt keine Daten und ändert keine Docker-Mounts, VM-Definitionen oder App-Dienste. Bereits installierte Apps zuerst in einem Wartungsfenster umziehen.</p><p><a class='btn' href='/settings/server-paths/move'>Datenumzug vorbereiten</a> <a class='btn' href='/scanner'>Scanner-Einstellungen</a> <a class='btn' href='/apps/manage'>App-Webadressen und Installer</a></p>")
        apply_error=cfg.read(cfg.CONFIG_DIR/'server.apply-error.json').get('error')
        if apply_error:body+=_ui_html("<p class='err'>Vormerkung konnte nicht übernommen werden; aktiven Stand prüfen: ")+e(apply_error)+_ui_html("</p>")
        if message:body+=_ui_html("<p class='ok'>")+e(_ui_text(message))+_ui_html("</p>")
        if cfg.PENDING.exists():
            body+=_ui_html("<p class='warn'>Änderungen gespeichert, aber noch nicht aktiv. Die Module verwenden bis zum Neustart die bisherigen Werte.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='revision' value='")+cfg.revision()+_ui_html("'><button class='btn' name='action' value='restart'>Heimserver Manager neu starten</button> <button class='btn' name='action' value='discard'>Vormerkung verwerfen</button></form>")
        body+=_ui_html("</div><form method='post'>")+token()+_ui_html("<input type='hidden' name='revision' value='")+cfg.revision()+"'>"
        body+=_ui_html("<div class='card' style='position:sticky;top:8px;z-index:20;display:flex;flex-wrap:wrap;align-items:center;gap:12px'><button class='btn active' type='submit' name='action' value='save'>Speichern</button><span>Speichert alle Pfadanpassungen. Aktivierung anschließend durch Neustart des Heimserver Managers.</span></div>")
        group=None
        for key,(section,label,kind,_) in cfg.FIELDS.items():
            if group!=section:
                if group is not None:body+=_ui_html('</div>')
                group=section;body+=_ui_html("<div class='card'><h3>")+e(section)+_ui_html("</h3>")
            value=values[key]
            body+=_ui_html("<p><label>")+e(_ui_text(label))+_ui_html('<br>')
            if kind=='paths':body+="<textarea name='"+key+"' rows='3' style='width:90%'>"+e('\n'.join(value))+"</textarea>"
            else:body+="<input id='field-"+key+"' name='"+key+"' value='"+e(value)+"' style='width:85%'>"
            body+=_ui_html('</label>')
            if key=='recover_url':body+=_ui_html("<br><small>Vollständige HTTP-/HTTPS-Adresse des Recovery-Dienstes einschließlich Port und /recover. Wird in neue Client-JSON-Profile übernommen. Leer lassen, um Recovery nicht vorzugeben. Nach Änderung speichern und Manager neu starten; auf vorhandenen Clients ein neues Profil importieren. Dies installiert oder startet keinen Recovery-Dienst.</small>")
            if kind in ('path','app_path'):
                body+=_ui_html(" <button class='btn' type='button' onclick=\"pickFolder('field-")+key+_ui_html("')\">Ordner wählen</button>")
                try:
                    status=cfg.inspect_path(value)
                    body+=_ui_html('<br><small>')+e((_ui_text('Vorhanden') if status['exists'] else _ui_text('Noch nicht vorhanden'))+_ui_text(' · Datenträger: ')+status['mount']+' · '+str(status['free_gb'])+_ui_text(' GB frei · Zugriff des Heimserver Managers: ')+(_ui_text('schreibbar') if status['writable'] else _ui_text('nicht schreibbar')))+_ui_html('</small>')
                except OSError:body+=_ui_html('<br><small>Pfad aktuell nicht prüfbar.</small>')
            if value!=cfg.get(key):body+=_ui_html('<br><small>Derzeit aktiv: ')+e(cfg.get(key))+_ui_html('</small>')
            body+=_ui_html('</p>')
        body+=_ui_html("</div><div class='card'><h3>Überwachte Sicherungen</h3><p>Leeren Namen verwenden, um eine Zeile zu entfernen. Dateifilter z. B. *.sql.gz oder */db.sql. Diese Liste überwacht Sicherungen; sie erstellt keine Sicherungsaufträge.</p><div style='overflow-x:auto'><table><tr><th>Name</th><th>Ordner</th><th>Dateifilter</th><th>Warnung nach Stunden</th><th>Kritisch nach Stunden</th><th>Für Gesamtstatus erforderlich</th></tr>")
        for i,row in enumerate(values['backup_items']+[dict(name='',path='',pattern='*',warn_h=48,crit_h=168)]):
            body+=_ui_html('<tr>')+''.join(_ui_html("<td><input name='backup_")+k+'_'+str(i)+"' value='"+e(row[k])+_ui_html("'></td>") for k in ('name','path','pattern','warn_h','crit_h'))+_ui_html("<td><input type='checkbox' name='backup_required_")+str(i)+"' value='1' "+('checked' if row.get('required',True) else '')+_ui_html("></td></tr>")
        body+=_ui_html("</table></div></div><div class='card'><h3>Speicherbezeichnungen</h3><p>Die Laufwerkerkennung bleibt automatisch. Hier erhalten Mountpunkte eigene Namen und Vorrang in der Anzeige.</p><table><tr><th>Mountpunkt</th><th>Name</th></tr>")
        for i,(path,label) in enumerate(list(values['storage_labels'].items())+[('','')]):
            body+=_ui_html("<tr><td><input name='storage_path_")+str(i)+"' value='"+e(path)+_ui_html("'></td><td><input name='storage_label_")+str(i)+"' value='"+e(_ui_text(label))+_ui_html("'></td></tr>")
        body+=_ui_html("</table></div><div class='card'><p>Ein anderer Fotolabor-Hauptordner erhält einen getrennten Prüfverlauf und eigene Zeitpläne; alte Freigaben werden nicht auf neue Bilder angewendet. Beim Zurückwechseln ist der alte Verlauf wieder verfügbar. App-Pfade unterstützen wegen bestehender Update-Werkzeuge derzeit keine Leerzeichen. Ordnerprüfungen erfolgen als Heimserver Manager; Zugriffsrechte der App-Dienstbenutzer müssen beim Umzug zusätzlich passen.</p><button class='btn active' name='action' value='save'>Speichern</button></div></form>")
        body+=_ui_html("<div class='card'><h3>Interne Installation</h3><p>Programm: <code>")+e(cfg.BASE_DIR)+_ui_html("</code><br>Konfiguration: <code>")+e(cfg.CONFIG_DIR)+_ui_html("</code><br>Statusdaten: <code>")+e(cfg.STATE_DIR)+_ui_html("</code></p><p>Diese Orte werden bei Installation über SERVER_MANAGER_CONFIG, SERVER_MANAGER_STATE und den Programmstandort festgelegt. Dienste und Hintergrundaufträge müssen dieselben Werte verwenden.</p></div>")
        body+=_ui_html(PICKER)
        return page(body)

    @app.route('/settings/server-port',methods=['GET','POST'],endpoint='server_port_settings')
    def port_settings():
        return redirect('/settings/https',303)

    @app.route('/api/settings/server-folders')
    def folders():
        try:
            value=request.args.get('path','')
            if not value:
                roots=set(cfg.get('share_roots'))|{'/opt','/home','/var/www','/var/lib','/srv','/mnt','/media'}
                return jsonify(path='',parent='',folders=sorted(p for p in roots if Path(p).is_dir() and not Path(p).is_symlink()))
            p=Path(cfg.path_value(value))
            return jsonify(path=str(p),parent='' if len(p.parts)<3 else str(p.parent),folders=[str(x) for x in sorted(p.iterdir()) if x.is_dir() and not x.is_symlink()][:300])
        except (ValueError,OSError) as exc:return jsonify(error=str(exc)),400

    @app.route('/settings/server-paths/move',methods=['GET','POST'])
    def move():
        body=_ui_html("<div class='card'><h2>Datenumzug vorbereiten</h2><p>Diese Hilfe prüft Quelle und Ziel und erstellt Kopier- und Kontrollbefehle. Sie führt keinen Umzug aus. Vor der Kopie alle schreibenden Apps und Aufträge stoppen; erst nach erfolgreicher Kontrolle Pfade, Docker-Mounts und Dienste umstellen. Die Quelle bleibt als Rückfall erhalten.</p>")
        if request.method=='POST':
            if not protected():return page(_ui_html('Formular abgelaufen.'),403)
            try:
                source=Path(cfg.path_value(request.form.get('source','')));target=Path(cfg.path_value(request.form.get('target','')))
                if not source.is_dir():raise ValueError('Quellordner fehlt.')
                if source==target or source in target.parents or target in source.parents:raise ValueError('Quelle und Ziel dürfen nicht ineinander liegen.')
                if target.exists() and any(target.iterdir()):raise ValueError('Ziel muss leer oder noch nicht vorhanden sein.')
                info=cfg.inspect_path(str(target))
                if not info['writable']:raise ValueError('Ziel ist nicht schreibbar.')
                src=shlex.quote(str(source)+'/'); dst=shlex.quote(str(target)+'/')
                commands='sudo mkdir -p -- '+shlex.quote(str(target))+'\n# Vorschau (keine Kopie):\nsudo rsync -aHAXn --numeric-ids --itemize-changes -- '+src+' '+dst+'\n# Im Wartungsfenster kopieren, nachdem alle Schreiber gestoppt sind:\nsudo rsync -aHAX --numeric-ids --info=progress2 -- '+src+' '+dst+'\n# Inhalt und Metadaten vergleichen (Ausgabe muss geprüft werden):\nsudo rsync -aHAXnc --numeric-ids --itemize-changes -- '+src+' '+dst
                body+=_ui_html('<h3>Vorbereitung</h3><p>Ziel-Datenträger: ')+e(info['mount'])+' · '+str(info['free_gb'])+_ui_html(' GB frei. Der Platzbedarf der Quelle wurde nicht vollständig ermittelt.</p><pre>')+e(commands)+_ui_html('</pre><p>Bei einem externen Datenträger vor der Kopie dessen Einbindung prüfen. Vorhandene Dateien werden nicht automatisch entfernt. Nach erfolgreichem Wechsel die Quelle erst separat und nach eigener Prüfung löschen.</p>')
            except (ValueError,OSError) as exc:body+=_ui_html("<p class='err'>")+e(_ui_text(exc))+_ui_html("</p>")
        body+=_ui_html("<form method='post'>")+token()+_ui_html("<p>Quelle <input name='source' required></p><p>Ziel <input name='target' required></p><button class='btn'>Umzug prüfen</button></form><p><a href='/settings/server-paths'>Zurück zu den Modulpfaden</a></p></div>")
        return page(body)

PICKER="""<dialog id='folder-dialog'><h3>Ordner auswählen</h3><p id='folder-current'></p><div id='folder-list'></div><p id='folder-error'></p><button type='button' id='folder-parent'>Zurück</button> <button type='button' id='folder-use'>Übernehmen</button> <button type='button' onclick="document.getElementById('folder-dialog').close()">Schließen</button></dialog>
<script>
let folderField='',folderPath='',folderParent='';
async function showFolders(path){const err=document.getElementById('folder-error');err.textContent='';document.getElementById('folder-use').disabled=true;try{const r=await fetch('/api/settings/server-folders?'+new URLSearchParams({path}));const d=await r.json();if(!r.ok)throw Error(d.error);folderPath=d.path;folderParent=d.parent;document.getElementById('folder-current').textContent=d.path||'Ordnerbereiche';const list=document.getElementById('folder-list');list.replaceChildren();for(const p of d.folders){const b=document.createElement('button');b.type='button';b.textContent=p;b.onclick=()=>showFolders(p);list.append(b,document.createElement('br'));}document.getElementById('folder-use').disabled=!d.path;}catch(e){err.textContent=e.message;}}
function pickFolder(id){folderField=id;document.getElementById('folder-dialog').showModal();showFolders('');}
document.getElementById('folder-parent').onclick=()=>showFolders(folderParent);
document.getElementById('folder-use').onclick=()=>{document.getElementById(folderField).value=folderPath;document.getElementById('folder-dialog').close();};
</script>"""
