"""Admin-only opt-in security maintenance controls; never activated on GET."""
import html,json,secrets,time
from flask import request,session,redirect
from . import apt_jobs,security_updates as security
import i18n

def register(app,ctx):
 @app.route('/apps/apt/security',methods=['GET','POST'])
 def security_page():
  en=i18n.language()=='en'
  def t(de,english):return english if en else de
  def e(value):return html.escape(str(value),quote=True)
  message=''
  if request.method=='POST':
   if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'CSRF',403
   try:
    action=request.form.get('action')
    if action=='disable':security.configure(False)
    elif request.form.get('confirm')!='yes':raise ValueError(t('Aktion zuerst bestätigen.','Confirm the action first.'))
    elif action=='enable':security.configure(True)
    elif action=='setup':return redirect('/apps/apt/jobs/'+apt_jobs.start('security-setup'),303)
    elif action=='run':
     reason=security.busy()
     if reason:raise ValueError(reason)
     return redirect('/apps/apt/jobs/'+apt_jobs.start('security-update'),303)
    else:raise ValueError('Invalid action')
    return redirect('/apps/apt/security',303)
   except Exception as exc:message=str(exc)
  try:config=security.settings();state=security.state();missing=security.prerequisites()
  except Exception as exc:config={'enabled':False};state={};missing=['unsupported'];message=str(exc)
  body="<div class='card'><h2>"+t('Automatische Sicherheitsupdates','Automatic security updates')+"</h2><a class='btn' href='/apps/apt'>APT</a>"
  body+='<p>'+t('Alle zwei Stunden, mit bis zu fünf Minuten Verzögerung. Ein ausgeschalteter Server wird nicht geweckt; ein verpasster Termin wird beim nächsten Start nachgeholt.','Every two hours, with up to five minutes delay. A powered-off server is not woken; a missed run is caught up at the next boot.')+'</p>'
  body+='<p>'+t('Installiert verfügbare Updates aus den offiziellen Sicherheitsquellen der Distribution, einschließlich notwendiger Abhängigkeiten. Keine vollständige CVE-Prüfung und kein Filter „nur kritisch“. App-/Container-Updates sind nicht enthalten. Paket-Holds, Sperrlisten und Konfigurationsdateien bleiben erhalten.','Installs available updates from official distribution security repositories, including required dependencies. Not a full CVE scan or a critical-only filter. Application/container updates are not included. Package holds, blacklists and configuration files are retained.')+'</p>'
  body+='<p>'+t('Betroffene Dienste werden über needrestart automatisch neu gestartet und danach erneut geprüft. Lokale needrestart-Ausnahmen bleiben wirksam. Erforderliche Server-Neustarts und verbleibende Dienste werden nur gemeldet. Laufende Sicherungen oder Installationen verschieben den automatischen Lauf. Ein laufender APT-Auftrag blockiert Sleep & Wake.','Affected services are restarted automatically through needrestart, then checked again. Local needrestart exclusions remain effective. Required server reboots and remaining services are only reported. Active backups or installations defer the automatic run. A running APT job blocks Sleep & Wake.')+'</p>'
  body+='<p>'+t('Andere bereits eingerichtete APT-Timer bleiben unverändert. Deaktivieren stoppt künftige Termine, keinen bereits laufenden Updateauftrag.','Other existing APT timers remain unchanged. Disabling stops future runs, not an update job already in progress.')+'</p>'
  body+='<p><b>'+t('Automatik: ','Automation: ')+t('Aktiv' if config['enabled'] else 'Inaktiv','Enabled' if config['enabled'] else 'Disabled')+'</b></p>'
  if message:body+="<p class='warn'>"+e(message)+'</p>'
  def form(action,label,confirm=True):
   return "<form method='post'><input type='hidden' name='auth_csrf' value='"+e(session.get('auth_csrf',''))+"'><input type='hidden' name='action' value='"+action+"'>"+("<label><input type='checkbox' name='confirm' value='yes' required> "+t('Installation und Dienstneustarts erlauben','Allow installation and service restarts')+"</label> " if confirm else '')+"<button class='btn'>"+label+'</button></form>'
  if missing:body+=form('setup',t('Voraussetzungen installieren','Install prerequisites'))
  else:
   body+=form('disable' if config['enabled'] else 'enable',t('Automatik deaktivieren' if config['enabled'] else 'Alle zwei Stunden aktivieren','Disable automation' if config['enabled'] else 'Enable every two hours'),not config['enabled'])
   body+=form('run',t('Jetzt prüfen und Sicherheitsupdates ausführen','Check and install security updates now'))
  body+='<p>'+t('ntfy meldet installierte Sicherheitsupdates, Fehler und offene Neustarts über die vorhandene Alarm-Konfiguration. Unveränderte Hinweise werden nicht alle zwei Stunden erneut gesendet. Ohne Detailfreigabe werden nur Anzahlen gemeldet.','ntfy reports installed security updates, errors and pending restarts using the existing alarm configuration. Unchanged alerts are not repeated every two hours. Without detail consent, only counts are sent.')+" <a href='/alarme'>ntfy</a></p>"
  body+='</div>'
  if state:
   labels={'queued':t('Wartet','Queued'),'running':t('Läuft','Running'),'completed':t('Abgeschlossen','Completed'),'attention':t('Nacharbeit erforderlich','Attention required'),'failed':t('Fehlgeschlagen','Failed'),'deferred':t('Verschoben','Deferred')}
   body+="<div class='card'><h3>"+t('Letzter Lauf','Last run')+'</h3><p>'+e(labels.get(state.get('state'),state.get('state')))+' · '+e(time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(state.get('checked_at',0))))+'</p>'
   if state.get('notification') in ('failed','disabled'):body+="<p class='warn'>"+t('ntfy nicht gesendet: ','ntfy not sent: ')+e(state['notification'])+'</p>'
   if state.get('message'):body+='<p>'+e(state['message'])+'</p>'
   if state.get('reboot_required'):body+="<p class='warn'>"+t('Server-Neustart erforderlich – wird nicht automatisch ausgeführt.','Server reboot required – will not run automatically.')+'</p>'
   if state.get('pending_security_packages'):body+="<p class='warn'>"+t('Sicherheitsupdates verbleiben (z. B. gesperrte Pakete): ','Security updates remain (e.g. held packages): ')+e(', '.join(state['pending_security_packages']))+'</p>'
   if state.get('pending_services'):body+='<p>'+t('Weiterhin neu zu starten: ','Still requiring restart: ')+e(', '.join(state['pending_services']))+'</p>'
   if state.get('job'):body+="<a class='btn' href='/apps/apt/jobs/"+e(state['job'])+"'>"+t('Auftrag und Protokoll','Job and log')+'</a>'
   body+='</div>'
   if state.get('state') in ('queued','running'):body+='<script>setTimeout(()=>location.reload(),10000)</script>'
  return ctx.page(t('Sicherheitsupdates','Security updates'),body,'Anwendungen')
