"""NVIDIA card and single-use installation previews."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,html,json,secrets,time
from flask import request,session,redirect
from . import nvidia as n,apt_jobs as jobs
from .install_ui import token
E=lambda value:html.escape(str(value),quote=True)
def card():
 # Overview rendering must never run DKMS, APT or vendor diagnostics.
 try:text='Geladener Treiber: '+(n.read('/sys/module/nvidia/version') or 'nicht geladen')
 except OSError:text='Geladener Treiber nicht lesbar'
 return _ui_html("<div class='card'><h3>NVIDIA · Grafiktreiber</h3><p>")+E(text)+_ui_html("</p><a class='btn' href='/apps/nvidia/installer'>GPU, Version &amp; Updates</a>")+_ui_html("</div>")
def register(app,ctx):
 @app.route('/apps/nvidia/installer',methods=['GET','POST'])
 def nvidia_installer():
  message='';code=200
  try:
   s=n.status()
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return ctx.page(_ui_text('NVIDIA'),_ui_html('<p>Formular abgelaufen.</p>'),'Apps'),403
    action=request.form.get('action','')
    if action=='refresh':return redirect('/apps/apt/jobs/'+jobs.start('update'),303)
    if action=='run':
     saved=session.pop('nvidia_preview',None)
     if not saved or time.time()-saved['time']>600 or request.form.get('confirm')!='yes':raise ValueError('Bestätigte Vorschau fehlt oder ist abgelaufen.')
     p=n.plan(saved['action'],s)
     if hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()!=saved['digest']:raise ValueError('Bestand geändert. Vorschau erneut erstellen.')
     return redirect('/apps/apt/jobs/'+jobs.start(p['action'],parameters=p),303)
    p=n.plan(action,s);session['nvidia_preview']={'time':time.time(),'action':action,'digest':hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()}
    body=_ui_html("<div class='card'><h2>NVIDIA · Vorschau</h2><p>Kernel ")+E(p['kernel'])+_ui_html('</p><p>')+E(', '.join(p['packages']))+_ui_html('</p><pre>')+E(p['changes'] or 'Keine Paketänderung laut Simulation.')+_ui_html("</pre><p>Installation über konfigurierte Paketquellen. Vor Ausführung wird der Paketplan erneut geprüft. Laufende GPU-Anwendungen und grafische Sitzungen vorher beenden. Paketaktualisierungen können Anwendungen beeinflussen; bei Fehlern sind Teiländerungen möglich. Keine automatische vollständige Rücknahme.</p><p>Der Manager entlädt keine Module und führt keinen Neustart aus. Nach Treiberänderungen Neustart separat planen. Paket-Skripte können Dienste neu starten. Die Hardwareprüfung allein installiert keinen Grafiktreiber.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='run'><label><input type='checkbox' name='confirm' value='yes' required> Paketaktion wie angezeigt ausführen</label><button class='btn'>Bestätigt ausführen</button></form><a href='/apps/nvidia/installer'>Abbrechen</a></div>")
    return ctx.page(_ui_text('NVIDIA · Vorschau'),body,'Apps')
  except (OSError,ValueError) as e:
   message=str(e);code=400
   try:s=n.status()
   except (OSError,ValueError):return ctx.page(_ui_text('NVIDIA'),_ui_html('<p>')+E(_ui_text(message))+_ui_html('</p>'),'Apps'),503
  body=_ui_html("<div class='card'><h2>NVIDIA · Grafiktreiber</h2><p><a class='btn' href='/apps'>Apps</a> <a class='btn' href='/apps/manage'>Apps verwalten</a></p>")
  if message:body+=_ui_html("<p class='warn'>")+E(_ui_text(message))+_ui_html('</p>')
  body+=_ui_html('<p>')+E(s['gpu'])+_ui_html('<br>Kernel: ')+E(s['kernel'])+_ui_html('<br>Geladener Treiber: ')+E(s['loaded'] or _ui_text('nicht geladen'))+_ui_html('<br>Modul auf Datenträger: ')+E(s['module']['version'] or _ui_text('nicht erkannt'))+_ui_html('<br>Secure Boot: ')+E(s['secure_boot'])+_ui_html('<br>Kernel-Header: ')+(_ui_text('vorhanden') if s['headers'] else _ui_text('fehlen'))+_ui_html('</p>')
  if s.get('reboot_pending') or (s['loaded'] and s['module']['version'] and s['loaded']!=s['module']['version']):body+=_ui_html("<p class='warn'>Neustart zur Treiberaktivierung einplanen.</p>")
  body+=_ui_html('<h3>Grafikkarten</h3><ul>')
  for c in s['cards']:body+=_ui_html('<li>PCI ')+E(c['slot'])+' · NVIDIA '+E(c['device'])+' · '+E(c['driver'])+_ui_html('</li>')
  body+=(_ui_html('</ul>') if s['cards'] else _ui_html('<li>Keine NVIDIA-Grafikkarte erkannt.</li></ul>'))
  body+=_ui_html('<h3>Installiert und verfügbar</h3><p>Kandidaten aus den eingerichteten Paketquellen anhand vorhandener Paketlisten; keine Aussage über die neueste NVIDIA-Herstellerversion.</p><table><tr><th>Paket</th><th>Installiert</th><th>Kandidat</th></tr>')
  for p in n.PACKAGES:body+=_ui_html('<tr><td>')+E(p)+_ui_html('</td><td>')+E(s['installed'].get(p,_ui_text('nicht installiert')))+_ui_html('</td><td>')+E(s['candidates'].get(p) or _ui_text('nicht verfügbar'))+_ui_html('</td></tr>')
  body+=_ui_html("</table><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='refresh'><button class='btn'>Paketlisten / verfügbare Versionen aktualisieren</button></form><p>Nach Abschluss diese Seite erneut öffnen.</p><h3>DKMS je Kernel</h3><pre>")+E(s['dkms'] or 'Keine NVIDIA-DKMS-Registrierung')+_ui_html('</pre><h3>Hardwareempfehlung</h3><pre>')+E(s['detect_text'])+_ui_html('</pre>')
  for error in s['errors']:body+=_ui_html("<p class='warn'>")+E(_ui_text(error))+_ui_html('</p>')
  body+=_ui_html('<h3>Installation / Update / Reparatur</h3><p>Neue Installationen benötigen eine passende Empfehlung von nvidia-detect. Vorhandene Debian-Standardtreiber können in derselben Paketfamilie aktualisiert werden. Kein automatischer Wechsel zu Open-, Tesla-, Legacy- oder .run-Treibern. NVIDIA-Treiber haben eigene, teilweise proprietäre Lizenzbedingungen; die GPL-Lizenz des Managers ändert diese nicht.</p>')
  for action,label in [('nvidia-detect','Hardwareprüfung installieren / aktualisieren'),('nvidia-install','Treiber installieren / aktualisieren'),('nvidia-repair','Treiberpakete und DKMS neu installieren')]:
   # Simulations are deliberately limited to an explicit POST preview.
   body+=_ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='")+action+_ui_html("'><button class='btn'>")+E(_ui_text(label))+_ui_html(' · Vorschau</button></form>')
  job=jobs.latest()
  if job and (job['action'] in n.ACTIONS or job['action']=='update'):body+=_ui_html("<p><a href='/apps/apt/jobs/")+E(job['id'])+_ui_html("'>Letzten Paketauftrag und Protokoll öffnen</a></p>")
  body+=_ui_html("<p><a href='https://wiki.debian.org/NvidiaGraphicsDrivers' target='_blank' rel='noopener noreferrer'>Debian: NVIDIA-Treiber und Secure Boot</a></p></div>")
  return ctx.page(_ui_text('NVIDIA · Grafiktreiber'),body,'Apps'),code
