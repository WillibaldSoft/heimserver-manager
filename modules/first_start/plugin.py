from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from flask import request,session,redirect
from . import config as c

def register(app,ctx):
 @app.before_request
 def first_installation():
  data=c.load()
  if request.path=='/' and data and data.get('pending'):return redirect('/settings/installation',303)
 @app.route('/settings/installation',methods=['GET','POST'])
 def installation():
  session.setdefault('installation_csrf',secrets.token_urlsafe(32));message='';error='';data=c.load();e=lambda v:ctx.esc(str(v))
  if request.method=='POST':
   if not secrets.compare_digest(request.form.get('csrf',''),session['installation_csrf']):return 'Formular abgelaufen.',403
   try:
    if data is None:raise ValueError('Bestehende Installation bleibt unverändert. Ihre Module sind bereits verfügbar.')
    from modules.app_manager import apt_jobs
    keys=request.form.getlist('modules');packages=c.packages(keys)
    if data.get('job'):
     job=apt_jobs.load(data['job'])
     if job['state'] not in apt_jobs.TERMINAL:raise ValueError('Installation läuft noch. Protokoll prüfen.')
     if job['state']!='completed' and request.form.get('action')!='install':raise ValueError('Paketinstallation fehlgeschlagen. APT-Protokoll prüfen; danach erneut installieren.')
    if request.form.get('action')=='install':
     job=apt_jobs.start('module-dependencies',{'modules':keys}) if packages else None
     c.host.atomic(c.FILE,dict(pending=True,modules=data['modules'],requested=keys,job=job))
     return redirect('/settings/installation',303)
    if data.get('requested') is not None and set(keys)!=set(data['requested']):raise ValueError('Auswahl geändert: zuerst Schritt 1 erneut ausführen.')
    keys=data.get('requested',keys)
    missing=[]
    import subprocess
    for package in c.packages(keys):
     result=subprocess.run(['dpkg-query','-W','-f=${Status}',package],capture_output=True,text=True,timeout=10)
     if result.returncode or result.stdout.strip()!='install ok installed':missing.append(package)
    if missing:raise ValueError('Zuerst Abhängigkeiten installieren: '+', '.join(missing))
    c.host.atomic(c.FILE,dict(pending=False,modules=keys))
    message='Auswahl gespeichert. Über Server & Modulpfade den geschützten Manager-Neustart ausführen; danach sind die Module aktiv.'
   except (ValueError,OSError) as exc:error=str(exc)
  data=c.load();chosen=set(c.CATALOG) if data is None else set(data.get('requested',data['modules']))
  body=_ui_html("<div class='card'><h2>Heimserver einrichten</h2><p>Grundsystem: Anmeldung, Einstellungen, Anwendungen, Updates und HTTPS. Wähle die zusätzlichen Manager-Module. Nicht gewählte Bereiche werden beim Start nicht geladen. Ihre Programmbestandteile bleiben im gemeinsamen Manager-Paket; zusätzliche Systempakete werden nur nach Auswahl installiert.</p><p>Serverprogramme wie Samba, KVM oder TVHeadend anschließend über die jeweiligen Installer einrichten. Apache bleibt für HTTPS Bestandteil des Grundsystems.</p>")
  if data is None:body+=_ui_html("<p>Bestehende Installation erkannt: keine automatische Änderung Ihrer Module.</p></div>");return ctx.page(_ui_text('Ersteinrichtung'),body,'Einstellungen')
  if message:body+=_ui_html('<p>')+e(_ui_text(message))+_ui_html(" <a href='/settings/server-paths'>Neustart prüfen</a></p>")
  if error:body+=_ui_html("<p class='err'>")+e(_ui_text(error))+_ui_html('</p>')
  if data.get('job'):
   from modules.app_manager import apt_jobs
   job=apt_jobs.load(data['job']);body+=_ui_html('<p>Paketinstallation: ')+e(_ui_text(job['state']))+_ui_html(" · <a href='/apps/apt/jobs/")+e(job['id'])+_ui_html("'>Protokoll öffnen</a></p>")
  body+=_ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='")+e(session.get('auth_csrf',''))+_ui_html("'><input type='hidden' name='csrf' value='")+e(session['installation_csrf'])+"'>"
  for key,row in c.CATALOG.items():
   body+=_ui_html("<p><label><input type='checkbox' name='modules' value='")+key+"' "+('checked' if key in chosen else '')+"> "+e(row[0])+_ui_html("</label> · Pakete: ")+e(', '.join(row[3]) or _ui_text('keine zusätzlichen Manager-Pakete'))+_ui_html('</p>')
  body+=_ui_html("<button name='action' value='install'>1. Gewählte Abhängigkeiten installieren</button> <button name='action' value='finish'>2. Auswahl übernehmen</button></form><p>Später wieder über Einstellungen → Installationsauswahl öffnen. Abwählen deinstalliert keine Programme und löscht keine Daten; laufende Dienste werden dadurch nicht beendet.</p></div>")
  if not data.get('pending'):
   body+=_ui_html("<div class='card'><h3>Gewählte Bereiche einrichten</h3>")
   for key in data['modules']:body+=_ui_html("<p><a href='")+c.CATALOG[key][4]+"'>"+e(c.CATALOG[key][0])+_ui_html("</a></p>")
   body+=_ui_html('</div>')
  return ctx.page(_ui_text('Ersteinrichtung'),body,'Einstellungen'),400 if error else 200
