"""Authenticated repair preview, execution and retained job output."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html,secrets
from flask import request,session,redirect,send_file
from . import engine
from modules.app_manager import install_jobs as jobs
E=lambda value:html.escape(str(value),quote=True)
DESCRIPTION='Behebt typische XRDP-Abbrüche nach der Anmeldung: installiert XRDP, Xorg-Unterstützung, XFCE und D-Bus erneut, ergänzt die Zertifikatsgruppe und richtet eine XFCE-Sitzung für den gewählten Linux-Benutzer ein. Vorhandene Sitzungsdateien werden gesichert; .xsessionrc und .Xclients werden in die Sicherung verschoben. XRDP-Dienste werden neu gestartet, laufende RDP-Verbindungen können getrennt werden. Es entsteht eine eigene Desktop-Sitzung; nicht der am Monitor geöffnete Desktop.'

def register(app,ctx):
    def token():
        session.setdefault('repair_csrf',secrets.token_urlsafe(32))
        return "<input type='hidden' name='csrf' value='"+session['repair_csrf']+"'>"
    def page(body,code=200):return ctx.page(_ui_text('Reparaturskripte'),_ui_html("<div class='card'><a href='/settings'>Einstellungen</a> · <a href='/settings/repairs'>Reparaturskripte</a></div>")+body,'Einstellungen'),code
    @app.route('/settings/repairs',methods=['GET','POST'])
    def repairs():
        try:
            if request.method=='POST':
                if not secrets.compare_digest(request.form.get('csrf',''),session.get('repair_csrf','!')):return page(_ui_html('<p>Formular abgelaufen.</p>'),403)
                if request.form.get('action')=='run':
                    p=session.pop('repair_plan',None)
                    if request.form.get('confirm')!='yes':raise ValueError('Reparaturplan ausdrücklich bestätigen.')
                    engine.validate(p)
                    key=jobs.start(dict(app_id='xrdp_repair',label='XRDP / XFCE · Reparatur'),'127.0.0.1',action='repair',plan=p)
                    return redirect('/settings/repairs/jobs/'+key,303)
                p=engine.plan(request.form.get('username',''),request.form.get('xwrapper')=='yes',request.form.get('tmp')=='yes');session['repair_plan']=p
                body=_ui_html("<div class='card'><h2>Reparatur prüfen: XRDP / XFCE</h2><p>")+E(DESCRIPTION)+_ui_html('</p><p>Benutzer: <b>')+E(p['username'])+_ui_html('</b> · UID ')+str(p['uid'])+' · '+E(p['home'])+_ui_html('</p>')
                if p['xwrapper']:body+=_ui_html('<p>Xwrapper wird auf allowed_users=anybody gesetzt. Das erlaubt allen lokalen Benutzern den Start über den Xorg-Wrapper.</p>')
                if p['tmp']:body+=_ui_html('<p>/tmp erhält Besitzer root:root und Modus 1777. Das betrifft alle Benutzer.</p>')
                body+=_ui_html("<p>Ausführung mit Administratorrechten auf diesem Server. Internet für APT erforderlich. Sicherungen werden im Benutzerverzeichnis und unter dem lokalen State-Verzeichnis in repair-backups erstellt. Keine automatische Rücknahme von Paketänderungen.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='run'><label><input type='checkbox' name='confirm' value='yes' required> Diesen Reparaturplan ausführen und XRDP neu starten</label><p><button>Reparatur jetzt ausführen</button></p></form></div>")
                return page(body)
            body=_ui_html("<div class='card'><h2>XRDP / XFCE reparieren</h2><p>")+E(DESCRIPTION)+_ui_html("</p><p>Grundlage: fix-xrdp-xfce.sh, für den Serverlauf mit Benutzerauswahl angepasst. Bestehende Passwörter, Firewall und RDP-Port werden nicht geändert.</p><form method='post'>")+token()+_ui_html("<label>Desktop-Benutzer <select name='username' required><option value=''>Bitte auswählen</option>")+''.join(_ui_html("<option value='")+E(u.pw_name)+"'>"+E(u.pw_name)+_ui_html(' · UID ')+str(u.pw_uid)+_ui_html('</option>') for u in engine.users())+_ui_html("</select></label><details><summary>Zusätzliche systemweite Reparaturen</summary><p><label><input type='checkbox' name='xwrapper' value='yes'> Xwrapper für alle lokalen Benutzer freigeben (allowed_users=anybody)</label></p><p><label><input type='checkbox' name='tmp' value='yes'> /tmp-Besitzer und Rechte auf root:root / 1777 korrigieren</label></p></details><button>Reparatur prüfen</button></form><p><a href='/settings/repairs/xrdp/download'>Angepasstes Skript herunterladen</a></p></div>")
            for path in sorted(jobs.JOBS.glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                state=jobs.load(path.parent.name)
                if state.get('action')=='repair':body+=_ui_html("<div class='card'><a href='/settings/repairs/jobs/")+E(state['id'])+_ui_html("'>XRDP-Reparaturlauf</a> · ")+E(_ui_text(state['state']))+_ui_html('</div>')
            return page(body)
        except (ValueError,OSError) as exc:return page(_ui_html("<div class='card'><p>")+E(_ui_text(exc))+_ui_html('</p></div>'),400)
    @app.route('/settings/repairs/xrdp/download')
    def repair_download():return send_file(engine.SCRIPT,as_attachment=True,download_name='fix-xrdp-xfce.sh',mimetype='text/x-shellscript')
    @app.route('/settings/repairs/jobs/<key>')
    def repair_job(key):
        try:
            state=jobs.load(key)
            if state.get('action')!='repair':return page(_ui_html('Reparaturlauf nicht gefunden.'),404)
            path=jobs.job_path(key)/'install.log';output='Noch keine Ausgabe.'
            if path.exists():
                with path.open('rb') as f:f.seek(max(0,path.stat().st_size-100000));output=f.read().decode('utf-8','replace')
            body=_ui_html("<div class='card'><h2>XRDP / XFCE · Reparaturlauf</h2><p>")+E(_ui_text(state['state']))+' · '+E(_ui_text(state['message']))+_ui_html('</p><pre>')+E(output)+_ui_html('</pre></div>')
            if state['state'] not in jobs.TERMINAL:body+=_ui_html('<script>setTimeout(()=>location.reload(),4000)</script>')
            return page(body)
        except (ValueError,OSError) as exc:return page(E(_ui_text(exc)),404)
