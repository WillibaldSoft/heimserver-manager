from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from flask import request,session,redirect
from . import pihole_setup as setup,install_jobs as jobs,install_catalog as c,install_runtime as runtime

def register(app,ctx,token):
 @app.route('/apps/pihole/installer/native',methods=['GET','POST'])
 def native_install():
  from .install_ui import esc,field
  body=_ui_html("<div class='card'><h2>Pi-hole nativ installieren</h2><p>Alternative zur Docker-Installation: Pi-hole läuft als Linux-Dienst mit Autostart. Der offizielle Installer lädt Pi-hole und benötigte Pakete aus dem Internet. Kein Docker erforderlich. Vorhandene native oder Docker-Installationen werden nicht überschrieben oder konvertiert.</p><p>Benötigt eine feste LAN-IP und freie Ports 53/TCP und UDP sowie den gewählten Webport. Router, DHCP, Client-DNS und bestehende DNS-Dienste werden nicht automatisch geändert. Die native Installation kann Systempakete ergänzen; bei Fehlern verbleiben Teilinstallationen zur Diagnose.</p><a class='btn' href='/apps/pihole/installer'>Docker / vorhandene Installation</a> <a class='btn' href='/apps/manage'>Apps verwalten</a></div>")
  code=200
  try:
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return 'Formular abgelaufen.',403
    if request.form.get('confirm')!='1':raise ValueError('Native Installation bitte bestätigen.')
    from .pihole_network import validate_password
    password=validate_password(request.form.get('password',''))
    if not password or password!=request.form.get('password_confirm',''):raise ValueError('Eigenes Adminpasswort zweimal identisch eingeben.')
    plan=setup.validate({'bind':request.form.get('bind','').strip(),'port':request.form.get('port',''),'upstream':request.form.get('upstream','').strip()})
    key=jobs.start(c.recipe('pihole'),plan['bind'],action='pihole_native_install',plan=plan,credentials={'password':password})
    return redirect('/apps/installers/jobs/'+key,303)
   if runtime.pihole_existing() or setup.CONFIG.exists():
    body+=_ui_html("<div class='card'><p>Pi-hole oder eine vorhandene Konfiguration erkannt. Native Neuinstallation gesperrt.</p><a class='btn' href='/apps/pihole'>Vorhandenes Pi-hole verwalten</a></div>")
   else:
    body+=_ui_html("<div class='card'><form method='post'>")+token()+field('bind','Feste LAN-IPv4 dieses Servers',request.host.split(':')[0])+field('port','Webport (1024–65535)',8088)+field('upstream','Upstream-DNS (IPv4, z. B. Router oder eigener Resolver)')+_ui_html("<label>Adminpasswort (12–128 Zeichen, keine Dollarzeichen)<input type='password' name='password' autocomplete='new-password' required></label><label>Passwort wiederholen<input type='password' name='password_confirm' autocomplete='new-password' required></label><p><label><input type='checkbox' name='confirm' value='1' required> Pi-hole nativ mit Abhängigkeiten auf diesem Server installieren.</label></p><button class='btn'>Prüfen und nativ installieren</button></form><p>Nach Abschluss die WebUI öffnen, mit dem gewählten Passwort anmelden und Blocklisten sowie DNS-Auflösung prüfen. Anschließend bei Bedarf Clients auf die Server-IP als DNS umstellen.</p></div>")
  except (ValueError,OSError) as exc:body+=_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html('</p></div>');code=400
  return ctx.page(_ui_text('Pi-hole nativ installieren'),body,'Apps'),code
