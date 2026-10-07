from ui_translation import html_literal as _ui_html, text as _ui_text
from werkzeug.exceptions import RequestEntityTooLarge
"""Authenticated upload, review and execution of local Manager packages."""
import html,secrets,subprocess
from flask import request,session,redirect
from . import engine
from modules.app_manager import install_jobs as jobs
from version import VERSION
E=lambda value:html.escape(str(value),quote=True)

def register(app,ctx):
    def token():
        session.setdefault('manager_update_csrf',secrets.token_urlsafe(32))
        return "<input type='hidden' name='csrf' value='"+session['manager_update_csrf']+"'>"
    def page(body,code=200):return ctx.page(_ui_text('Manager aktualisieren'),_ui_html("<div class='card'><a href='/settings'>Einstellungen</a> · <a href='/settings/manager-update'>Manager aktualisieren</a></div>")+body,'Einstellungen'),code
    @app.route('/settings/manager-update',methods=['GET','POST'])
    def update():
        request.max_content_length=engine.LIMIT+1024*1024
        try:
            if request.method=='POST':
                if not secrets.compare_digest(request.form.get('csrf',''),session.get('manager_update_csrf','!')):return page(_ui_html('Formular abgelaufen.'),403)
                if request.form.get('action')=='install':
                    plan=session.get('manager_update_plan')
                    if request.form.get('confirm')!='yes':raise ValueError('Bitte die Installation dieses Pakets bestätigen.')
                    engine.validate(plan)
                    key=jobs.start(dict(app_id='server_manager',label='Heimserver Manager · Paketupdate'),'127.0.0.1',action='manager_update',plan=plan)
                    session.pop('manager_update_plan',None)
                    return redirect('/settings/manager-update/jobs/'+key,303)
                item=request.files.get('package')
                if item is None or not item.filename:raise ValueError('Bitte eine .deb-Datei auswählen.')
                plan=engine.stage(item.stream,item.filename);session['manager_update_plan']=plan
                return page(_ui_html("<div class='card'><h2>Manager-Update prüfen</h2><p>Aktuell: ")+E(VERSION)+_ui_html(" → Paket: <b>")+E(plan['version'])+_ui_html("</b> · Architektur: ")+E(plan['architecture'])+_ui_html("</p><p>Paket: server-manager · ")+str(plan['size'])+_ui_html(" Bytes</p><p>SHA256: <code>")+E(plan['sha256'])+_ui_html("</code></p><p>Die Prüfung bestätigt Paketformat, Name, Architektur und Version, nicht die Herkunft. Nur eine selbst erstellte oder aus vertrauenswürdiger Quelle erhaltene DEB verwenden: Paketskripte laufen mit root-Rechten.</p><p>Programm und Konfiguration sowie die Manager-Datenbank werden vorher gesichert. Lokale Änderungen am Programm werden durch den Paketstand ersetzt. Bestehende Konfiguration und Port werden vom Installer übernommen. Der Manager startet neu; die Oberfläche ist kurz nicht erreichbar. Eine automatische Rücknahme erfolgt nicht.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='install'><label><input type='checkbox' name='confirm' value='yes' required> Ich vertraue diesem Paket und möchte den Manager damit aktualisieren</label><p><button class='btn'>Update installieren</button></p></form></div>"))
            body=_ui_html("<div class='card'><h2>Heimserver Manager aktualisieren</h2><p>Installierter Programmstand: <b>")+E(VERSION)+_ui_html("</b></p><p>Neue oder gleiche Version als DEB hochladen, prüfen und anschließend installieren. Ältere Versionen werden abgewiesen. Maximal 256 MiB. Dieser Upload installiert ausschließlich den Heimserver Manager.</p><form method='post' enctype='multipart/form-data'>")+token()+_ui_html("<label>Manager-DEB <input type='file' name='package' accept='.deb' required></label><button class='btn'>Paket hochladen und prüfen</button></form></div>")
            problem=engine.installation_problem()
            if problem:
                body=_ui_html("<div class='card'><h2>Heimserver Manager aktualisieren</h2><p>Installierter Programmstand: <b>")+E(VERSION)+_ui_html("</b></p><p>")+E(problem)+_ui_html("</p><p>Der laufende Manager bleibt unverändert. Frühere Aufträge und Protokolle stehen unten.</p></div>")
            shown=0
            for path in sorted(jobs.JOBS.glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                state=jobs.load(path.parent.name)
                if state.get('action')!='manager_update':continue
                shown+=1
                body+=_ui_html("<div class='card'><a href='/settings/manager-update/jobs/")+E(state['id'])+"'>Update auf "+E(state.get('plan',{}).get('version',''))+_ui_html("</a> · ")+E(_ui_text(state['state']))+_ui_html('</div>')
                if shown>=2:break
            return page(body)
        except RequestEntityTooLarge:return page(_ui_html('Upload zu groß. Maximal 256 MiB erlaubt.'),413)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:return page(_ui_html("<div class='card'><p>")+E(_ui_text(exc))+_ui_html('</p></div>'),400)
    @app.route('/settings/manager-update/jobs/<key>')
    def update_job(key):
        try:
            state=jobs.load(key)
            if state.get('action')!='manager_update':return page(_ui_html('Update-Auftrag nicht gefunden.'),404)
            path=jobs.job_path(key)/'install.log';output='Noch keine Ausgabe.'
            if path.exists():
                with path.open('rb') as f:f.seek(max(0,path.stat().st_size-100000));output=f.read().decode('utf-8','replace')
            body=_ui_html("<div class='card'><h2>Manager-Update auf ")+E(state['plan']['version'])+_ui_html("</h2><p>")+E(_ui_text(state['state']))+' · '+E(_ui_text(state['message']))+_ui_html("</p><p>Auftrag: <code>")+E(key)+_ui_html("</code></p><p>Der Auftrag läuft unabhängig vom Webdienst. Beim Neustart kurz warten und diese Seite erneut öffnen. Protokoll und Sicherung bleiben auf dem Server erhalten.</p><p>Sicherung: <code>")+E(engine.folder(state['plan']['key'])/'before-update')+_ui_html("</code></p><pre>")+E(output)+_ui_html("</pre></div>")
            if state['state'] not in jobs.TERMINAL:
                body+=_ui_html("<script>setTimeout(async()=>{try{let r=await fetch(location.href,{cache:'no-store'});if(r.ok)location.reload();else setTimeout(()=>location.reload(),10000)}catch(e){setTimeout(()=>location.reload(),10000)}},5000)</script>")
            return page(body)
        except (ValueError,OSError) as exc:return page(E(_ui_text(exc)),404)
