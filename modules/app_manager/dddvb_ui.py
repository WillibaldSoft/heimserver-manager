"""Driver card, explicit release check and confirmed DKMS jobs."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html,secrets,time
from flask import request,session,redirect
from . import dddvb as d,apt_jobs as jobs
from .install_ui import token
E=lambda value:html.escape(str(value),quote=True)
def card():
 # Overview rendering must never run DKMS, APT or vendor diagnostics.
 try:text='Geladener Treiber: '+(d.read('/sys/module/ddbridge/version') or 'nicht geladen')
 except OSError:text='Geladener Treiber nicht lesbar'
 return _ui_html("<div class='card'><h3>Digital Devices · DVB-Treiber</h3><p>")+E(text)+_ui_html("</p><a class='btn' href='/apps/dddvb/installer'>Version &amp; Updates</a>")+_ui_html("</div>")
def register(app,ctx):
 @app.route('/apps/dddvb/installer',methods=['GET','POST'])
 def installer():
  message='';code=200
  try:
   state=d.status()
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return ctx.page(_ui_text('Digital Devices'),_ui_html('<p>Formular abgelaufen.</p>'),'Apps'),403
    action=request.form.get('action','')
    if action=='check':d.check_release();return redirect('/apps/dddvb/installer',303)
    if action=='run':
     saved=session.pop('dddvb_preview',None)
     if not saved or time.time()-saved['time']>600 or request.form.get('confirm')!='yes':raise ValueError('Bestätigte Vorschau fehlt oder ist abgelaufen.')
     plan=d.plan(saved['plan']['action'],state)
     if plan!=saved['plan']:raise ValueError('Bestand geändert. Vorschau erneut erstellen.')
     key=jobs.start(plan['action'],parameters=plan);return redirect('/apps/apt/jobs/'+key,303)
    plan=d.plan(action,state);session['dddvb_preview']={'time':time.time(),'plan':plan}
    body=_ui_html("<div class='card'><h2>Treiberaktion prüfen</h2><p>dddvb ")+E(plan['target'])+' · Kernel '+E(plan['kernel'])+_ui_html('</p><p>')+(_ui_text('Bestehende DKMS-Konfiguration bleibt erhalten.') if action=='dddvb-repair' else _ui_text('Kernel-eigener dvb-core; einige Herstellerfunktionen können fehlen.') if action.endswith('-native') else _ui_text('Hersteller-dvb-core wird ebenfalls installiert und kann andere DVB-Geräte beeinflussen.'))+_ui_html("</p><p>APT ergänzt DKMS, Build-Werkzeuge und passende Kernel-Header. Treiber werden gebaut und für diesen Kernel installiert. DKMS baut bei späteren Kernelupdates erneut, soweit Kernel und Treiber kompatibel sind. Keine Garantie für künftige Kernel.</p><p>Keine geladenen Treiber werden entladen, keine TV-Dienste neu gestartet. Aktivierung beim separat geplanten Neustart. Vorhandene Moduldateien können durch DKMS ersetzt werden. Bei Fehlern sind Teiländerungen möglich; keine automatische vollständige Rücknahme.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='run'><label><input type='checkbox' name='confirm' value='yes' required> Treiberinstallation und geplanten Neustart verstanden</label><button class='btn'>Bestätigt ausführen</button></form><a href='/apps/dddvb/installer'>Abbrechen</a></div>")
    return ctx.page(_ui_text('Digital Devices · Vorschau'),body,'Apps')
  except (ValueError,OSError) as e:
   message=str(e);code=400
   try:state=d.status()
   except (ValueError,OSError):return ctx.page(_ui_text('Digital Devices'),_ui_html('<p>')+E(_ui_text(message))+_ui_html('</p>'),'Apps'),503
  body=_ui_html("<div class='card'><h2>Digital Devices · dddvb</h2><p><a class='btn' href='/apps'>Apps</a> <a class='btn' href='/apps/manage'>Apps verwalten</a></p><p>Kernel: <code>")+E(state['kernel'])+_ui_html('</code><br>Geladene Treiberversion: <b>')+E(state['loaded'] or _ui_text('nicht geladen'))+_ui_html('</b><br>Auf Datenträger installiert: ')+E(state['module'].get('version') or _ui_text('nicht erkannt'))+_ui_html('<br>Kernel-Header: ')+(_ui_text('vorhanden') if state['headers'] else _ui_text('fehlen – werden bei Installation angefordert'))+_ui_html('<br>Secure Boot: ')+E(state['secure_boot'])+_ui_html('</p>')
  if state['loaded'] and state['module'].get('version') and state['loaded']!=state['module']['version']:body+=_ui_html("<p class='warn'>Installierter und geladener Treiber unterscheiden sich. Neustart nach Abschluss laufender Aufnahmen planen.</p>")
  if state.get('reboot_pending'):body+=_ui_html("<p class='warn'>Treiberinstallation in diesem Systemstart erfolgt. Neustart zur Aktivierung noch ausstehend.</p>")
  if message:body+=_ui_html("<p class='warn'>")+E(_ui_text(message))+_ui_html('</p>')
  for error in state['errors']:body+=_ui_html("<p class='warn'>")+E(_ui_text(error))+_ui_html('</p>')
  body+=_ui_html('<h3>Erkannte Karten</h3><ul>')
  for c in state['cards']:body+=_ui_html('<li>PCI ')+E(c['slot'])+' · Digital Devices '+E(c['device'])+' · PCI-Revision '+E(c.get('revision') or _ui_text('unbekannt'))+' · Treiber '+E(c['driver'])+_ui_html('</li>')
  body+=(_ui_html('</ul>') if state['cards'] else _ui_html('<li>Keine Digital-Devices-PCI-Karte erkannt.</li></ul>'))
  body+=_ui_html('<h3>DKMS je Kernel</h3><table><tr><th>Version</th><th>Kernel</th><th>Status</th></tr>')
  for r in state['registrations']:body+=_ui_html('<tr><td>')+E(r['version'])+_ui_html('</td><td>')+E(r['kernel'] or _ui_text('noch nicht gebaut'))+_ui_html('</td><td>')+E(_ui_text(r['state']))+_ui_html('</td></tr>')
  body+=_ui_html('</table><h3>Version und Updates</h3><p>Für automatische Installation geprüft: <b>')+E(d.VERSION)+_ui_html("</b>. Neuere Hersteller-Versionen werden angezeigt, aber erst nach eigener Kompatibilitätsprüfung freigegeben.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='check'><button class='btn'>Herstellerversion prüfen</button></form>")
  latest=d.latest()
  if latest.get('status')=='checked':
   body+=_ui_html('<p>Neueste stabile Herstellerversion: <b>')+E(latest['version'])+_ui_html('</b> · geprüft ')+E(time.strftime('%d.%m.%Y %H:%M',time.localtime(latest['checked'])))+_ui_html('</p>')
   if latest['version']==state['module'].get('version'):body+=_ui_html('<p>Installierter Treiber entspricht dem geprüften Herstellerstand.</p>')
   elif latest['version']!=d.VERSION:body+=_ui_html("<p class='warn'>Abweichender Herstellerstand verfügbar. Automatische Installation dieser Version ist noch nicht freigegeben.</p>")
   else:body+=_ui_html('<p>Installierter Treiber weicht vom verfügbaren Zielstand ab. Installationsvorschau unten prüfen.</p>')
  elif latest:body+=_ui_html("<p class='warn'>")+E(_ui_text(latest.get('error','Versionsprüfung nicht möglich')))+_ui_html('</p>')
  else:body+=_ui_html('<p>Herstellerversion noch nicht geprüft.</p>')
  body+=_ui_html('<h3>Installation / Update / Reparatur</h3>')
  for action,label in [('dddvb-install','0.9.41 installieren / aktualisieren · Hersteller-dvb-core'),('dddvb-install-native','0.9.41 installieren / aktualisieren · Kernel-dvb-core'),('dddvb-repair','0.9.41 für laufenden Kernel neu bauen / reparieren')]:
   try:d.plan(action,state);problem=''
   except ValueError as e:problem=str(e)
   if problem:body+=_ui_html("<details><summary>")+E(_ui_text(label))+_ui_html(' – nicht verfügbar</summary><p>')+E(problem)+_ui_html('</p></details>')
   else:body+=_ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='")+action+_ui_html("'><button class='btn'>")+E(_ui_text(label))+_ui_html(' …</button></form>')
  job=jobs.latest()
  if job and job['action'] in d.ACTIONS:body+=_ui_html("<p><a href='/apps/apt/jobs/")+E(job['id'])+_ui_html("'>Letzten Treiberauftrag und Protokoll öffnen</a></p>")
  body+=_ui_html("<p>Bestehende Quellen, Moduloptionen (z. B. fmode), Firmware und TV-Konfiguration bleiben erhalten. Keine automatische Deinstallation oder Firmwareaktualisierung.</p><p><a href='https://support.digital-devices.eu/index.php?article=187' target='_blank' rel='noopener noreferrer'>Digital-Devices-DKMS-Anleitung</a></p></div>")
  return ctx.page(_ui_text('Digital Devices · DVB-Treiber'),body,'Apps'),code
