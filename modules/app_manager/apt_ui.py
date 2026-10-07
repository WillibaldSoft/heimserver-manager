from ui_translation import html_literal as _ui_html, text as _ui_text
import html
from flask import request,session,redirect
from . import apt_jobs as jobs
E=lambda s:html.escape(str(s),quote=True)
def token():return "<input type='hidden' name='auth_csrf' value='"+E(session.get('auth_csrf',''))+"'>"
def form(action,label):return _ui_html("<form method='post' action='/apps/apt/run' style='display:inline'>")+token()+_ui_html("<input type='hidden' name='action' value='")+action+_ui_html("'><button class='btn'>")+_ui_text(label)+_ui_html('</button></form>')
def card():
 return _ui_html("<div class='card'><h3>Systempakete · APT</h3><p>Debian-/Ubuntu-Pakete und installierte Paketquellen verwalten.</p>")+form('update','apt update')+form('list','Updates anzeigen')+_ui_html("<a class='btn' href='/apps/apt'>apt upgrade …</a> <a class='btn' href='/apps/apt#full-upgrade'>apt full-upgrade …</a><p><a href='/apps/apt'>Status und Protokoll</a></p></div>")
def register(app,ctx):
 @app.route('/apps/docker/installer',methods=['GET','POST'])
 def docker_installer():
  from . import docker_setup as d
  from .install_ui import token as installer_token
  message=''
  try:
   state=d.status()
   if request.method=='POST':
    import secrets
    if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'Formular abgelaufen.',403
    action=request.form.get('action')
    if action not in ('docker-install','docker-remove','docker-start') or request.form.get('confirm')!='yes':raise ValueError('Aktion zuerst bestätigen.')
    if action=='docker-remove':d.removal_packages()
    elif action=='docker-start':
     if state['action']!='start':raise ValueError('Docker kann in diesem Zustand nicht gestartet werden.')
    else:
     if state['action'] not in ('install','compose'):raise ValueError('Installation nicht erforderlich oder Status unklar. Seite neu laden.')
     d.install_packages(state['packages'])
    key=jobs.start(action);return redirect('/apps/apt/jobs/'+key,303)
  except (ValueError,OSError) as exc:
   message=str(exc);state=d.status()
  body=_ui_html("<div class='card'><h2>Docker Engine & Compose</h2><p><a class='btn' href='/apps/manage'>Apps verwalten</a></p><p>Grundlage für Jellyfin, Plex und weitere Container-Apps. Neuinstallation aus den vorhandenen Debian-/Ubuntu-Paketquellen. Bestehende Docker-CE-Installationen behalten ihre Paketfamilie; Compose wird aus der vorhandenen Quelle ergänzt.</p>")
  body+=_ui_html('<p>Engine: <b>')+(_ui_text('Installiert') if state['engine'] else _ui_text('Nicht als unterstütztes Paket installiert'))+_ui_html('</b> · Dienst: ')+(_ui_text('Erreichbar') if state['ready'] else _ui_text('Nicht erreichbar'))+' · Compose: '+(_ui_text('Verfügbar') if state['compose'] else _ui_text('Fehlt'))+_ui_html('</p>')
  if message:body+=_ui_html("<p class='warn'>")+E(_ui_text(message))+_ui_html('</p>')
  body+=_ui_html("<p>Installieren ergänzt Pakete und aktiviert den Docker-Autostart. Vorhandene Container, Images, Volumes und Konfigurationen werden nicht zurückgesetzt. Es erfolgt keine Aufnahme von Benutzern in die Docker-Gruppe.</p>")
  if state['action'] in ('install','compose','start'):
   action='docker-start' if state['action']=='start' else 'docker-install'
   label={'install':'Docker & Compose installieren','compose':'Compose ergänzen','start':'Docker starten'}[state['action']]
   body+=_ui_html("<form method='post'>")+token()+installer_token()+_ui_html("<input type='hidden' name='action' value='")+action+_ui_html("'><label><input type='checkbox' name='confirm' value='yes' required> ")+E(_ui_text(label))+_ui_html(" bestätigen</label> <button class='btn'>")+E(_ui_text(label))+_ui_html("</button></form>")
  elif state['action']=='complete':
   body+=_ui_html("<button class='btn' disabled style='opacity:.55;cursor:not-allowed'>Bereits vollständig installiert</button><p>Docker-Updates erfolgen über die <a href='/apps/apt'>APT-Verwaltung</a>.</p>")
  else:
   body+=_ui_html("<button class='btn' disabled style='opacity:.55'>Installation gesperrt</button><details open><summary>Diagnose anzeigen</summary><p>Der Installations- oder Dienstzustand ist nicht eindeutig. Vorhandene Installation prüfen; sie wird nicht ersetzt.</p><p>Dienstzustand: ")+E(state['service'])+_ui_html("<br>Erkannte Pakete: ")+E(', '.join(state['packages']) or _ui_text('Keine'))+_ui_html("</p><a href='/server?unit=docker.service#journal'>Docker-Dienstprotokoll öffnen</a></details>")

  body+=_ui_html("<h3>Deinstallation</h3><p>Entfernt Docker-Pakete ohne purge oder autoremove. Images, Volumes, Medien und Konfiguration bleiben erhalten. Bei vorhandenen Containern (auch gestoppt), aktivem Swarm oder nicht prüfbarem Docker-Dienst gesperrt. Gemeinsam genutzte containerd-/runc-Pakete bleiben installiert.</p><form method='post'>")+token()+installer_token()+_ui_html("<input type='hidden' name='action' value='docker-remove'><label><input type='checkbox' name='confirm' value='yes' required> Docker Engine und Compose deinstallieren</label> <button class='btn'>Deinstallieren</button></form></div>")
  return ctx.page(_ui_text('Docker Engine & Compose'),body,'Apps')

 @app.route('/apps/apt')
 def overview():
  job=jobs.latest()
  body=_ui_html("<div class='card'><h2>Systempakete aktualisieren</h2><p>1. Paketlisten aktualisieren · 2. verfügbare Updates prüfen · 3. Upgrade starten.</p>")+form('update','sudo apt update')+form('list','apt list --upgradable')+_ui_html("</div><div class='card'><h3>sudo apt upgrade</h3><p>Installiert verfügbare Paketupdates. Dienste können dabei neu starten. Geänderte lokale Konfigurationsdateien werden beibehalten; es erfolgt kein automatischer Rechnerneustart und kein full-upgrade.</p><form method='post' action='/apps/apt/run'>")+token()+_ui_html("<input type='hidden' name='action' value='upgrade'><label><input type='checkbox' name='confirm' value='yes' required> Systempakete jetzt aktualisieren</label> <button class='btn'>Upgrade starten</button></form></div>")
  body+=_ui_html("<div class='card' id='full-upgrade'><h3>apt full-upgrade</h3><p>Aktualisiert Pakete und löst geänderte Abhängigkeiten; dabei können auch Pakete entfernt werden. Zuerst die Simulation ausführen und deren Protokoll prüfen. Technisch verwendet der Manager das gleichwertige apt-get dist-upgrade. Dienste können neu starten; lokale Konfigurationen bleiben erhalten, der Rechner wird nicht automatisch neu gestartet.</p>")+form('full-preview','Full-Upgrade simulieren')
  if job and job['action']=='full-preview' and job['state']=='completed' and job.get('returncode')==0:
   body+=_ui_html("<h4>Vorschau der geplanten Änderungen</h4><pre style='white-space:pre-wrap;max-height:28rem;overflow:auto'>")+E(jobs.log_tail(job['id']))+_ui_html("</pre><p>Die Simulation ist eine Momentaufnahme. Bei zwischenzeitlichen Paketänderungen erneut simulieren.</p><form method='post' action='/apps/apt/run'>")+token()+_ui_html("<input type='hidden' name='action' value='full-upgrade'><input type='hidden' name='preview' value='")+E(job['id'])+_ui_html("'><label><input type='checkbox' name='confirm' value='yes' required> Vorschau geprüft; Paketentfernungen und Full-Upgrade ausführen</label> <button class='btn'>Full-Upgrade starten</button></form>")
  body+=_ui_html('</div>')
  if job:body+=_ui_html("<div class='card'><p>Letzter Auftrag: ")+E(_ui_text(jobs.LABELS[job['action']]))+' · '+E(_ui_text(job['state']))+_ui_html("</p><a class='btn' href='/apps/apt/jobs/")+job['id']+_ui_html("'>Status und Protokoll öffnen</a></div>")
  return ctx.page(_ui_text('APT · Systempakete'),body,'Anwendungen')
 @app.route('/apps/apt/run',methods=['POST'])
 def run():
  try:
   action=request.form.get('action','')
   if action.startswith('nvidia-'):raise ValueError('NVIDIA-Aktionen über die Treibervorschau bestätigen.')
   if action.startswith('dddvb-'):raise ValueError('Treiberaktionen über die Digital-Devices-Vorschau bestätigen.')
   if action in ('docker-install','docker-remove','docker-start'):raise ValueError('Docker-Aktionen über Apps verwalten bestätigen.')
   if action in ('upgrade','full-upgrade') and request.form.get('confirm')!='yes':raise ValueError('Upgrade zuerst bestätigen.')
   if action=='full-upgrade':
    preview=jobs.latest()
    if not preview or preview['id']!=request.form.get('preview') or preview['action']!='full-preview' or preview['state']!='completed' or preview.get('returncode')!=0:raise ValueError('Zuerst eine erfolgreiche Full-Upgrade-Simulation ausführen und prüfen.')
   key=jobs.start(action);return redirect('/apps/apt/jobs/'+key,303)
  except (ValueError,OSError) as exc:return ctx.page(_ui_text('APT'),_ui_html('<p>')+E(_ui_text(exc))+_ui_html("</p><a href='/apps/apt'>Zurück</a>")),400
  except Exception:return ctx.page(_ui_text('APT'),_ui_html("<p>Auftrag konnte nicht gestartet werden. Dienstberechtigungen und Protokoll prüfen.</p><a href='/apps/apt'>Zurück</a>")),500
 @app.route('/apps/apt/jobs/<key>')
 def status(key):
  try:job=jobs.load(key);log=jobs.log_tail(key)
  except (ValueError,OSError):return ctx.page(_ui_text('APT'),_ui_html('<p>Auftrag nicht gefunden.</p>')),404
  labels=dict(queued='Wartet',running='Läuft',completed='Erfolgreich',failed='Fehlgeschlagen',interrupted='Unterbrochen')
  body=_ui_html("<div class='card'><p><a class='btn' href='/apps'>Apps</a> <a class='btn' href='/apps/apt'>APT-Verwaltung</a> <a class='btn' href=''>Aktualisieren</a></p><h2>")+E(_ui_text(jobs.LABELS[job['action']]))+_ui_html('</h2><p>')+E(_ui_text(labels[job['state']]))+' · '+E(_ui_text(job['message']))+_ui_html('</p>')
  if job.get('reboot_required'):body+=_ui_html("<p class='warn'>Das System meldet einen erforderlichen Neustart. Bitte passend zu laufenden Diensten planen.</p>")
  if job['action'].startswith('nvidia-') or job['action']=='update':body+=_ui_html("<p><a class='btn' href='/apps/nvidia/installer'>NVIDIA · Status</a></p>")
  if job['action'].startswith('dddvb-'):body+=_ui_html("<p><a class='btn' href='/apps/dddvb/installer'>Digital Devices · Status</a></p>")
  body+=_ui_html('</div><div class="card"><h3>Ergebnisprotokoll</h3><pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:65vh;overflow:auto;line-height:1.5">')+E(log)+_ui_html('</pre><p>Bei langen Protokollen werden die letzten 100 KB angezeigt.</p></div>')
  if job['state'] not in jobs.TERMINAL:body+=_ui_html("<script>setTimeout(()=>location.reload(),5000)</script>")
  return ctx.page(_ui_text('APT · Auftrag'),body,'Anwendungen')
