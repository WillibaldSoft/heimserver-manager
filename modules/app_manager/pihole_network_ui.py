from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from pathlib import Path
from flask import request,session,redirect
from . import pihole_network as n,install_catalog as c,install_jobs as jobs

def register(app,ctx,token):
 @app.route('/apps/pihole/installer/network',methods=['GET','POST'])
 def pihole_network_page():
  from .install_ui import esc,field
  body=_ui_html("<div class='card'><h2>Pi-hole · Netzwerk &amp; Zugang</h2><p>Webadresse und Webport für natives Pi-hole v6 oder eine vom Manager angelegte Docker-Installation ändern. Bei Docker werden Webzugriff und DNS (53/TCP und UDP) an diese Adresse gebunden. Bei nativer Installation wird nur der Webzugang geändert. Pi-hole wird kurz neu gestartet; DNS ist dabei kurz unterbrochen. Daten und Filter bleiben erhalten; ein neues Adminpasswort kann optional gesetzt werden. Router, DHCP und Client-DNS werden nicht verändert.</p><p>127.0.0.1 bedeutet: nur auf diesem Server erreichbar. Für andere Geräte eine feste LAN-IP dieses Servers verwenden. Keine Freigabe ins Internet.</p><a class='btn' href='/apps/pihole'>Zurück zur App</a></div>")
  body+=_ui_html("<div class='card'><h3>Adminpasswort ändern</h3><p>Eigenständige Passwortänderung für native und vom Manager angelegte Docker-Installationen. Netzwerk und Ports bleiben unverändert. Pi-hole startet kurz neu; DNS kann dabei kurz unterbrochen sein.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='password'><label>Neues Adminpasswort <input type='password' name='password' autocomplete='new-password' minlength='12' maxlength='128' required></label><label>Passwort wiederholen <input type='password' name='password_confirm' autocomplete='new-password' required></label><p>12–128 Zeichen, keine Dollarzeichen. Passwort erscheint nicht im Auftragsprotokoll.</p><label><input type='checkbox' name='confirm' value='1' required> Passwort ändern und kurzen Neustart bestätigen.</label><p><button class='btn'>Adminpasswort ändern</button></p></form></div>")
  code=200
  try:
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return 'Formular abgelaufen.',403
    if request.form.get('action')=='password':
     from . import pihole_password
     password=n.validate_password(request.form.get('password',''))
     if not password or password!=request.form.get('password_confirm',''):raise ValueError('Neues Passwort zweimal identisch eingeben.')
     if request.form.get('confirm')!='1':raise ValueError('Passwortänderung und kurzen Neustart bestätigen.')
     key=jobs.start(c.recipe('pihole'),'127.0.0.1',action='pihole_password',plan=pihole_password.prepare(),credentials={'password':password})
     return redirect('/apps/installers/jobs/'+key,303)
    if request.form.get('action')=='apply':
     plan=session.get('pihole_network_plan')
     if not plan or request.form.get('confirm')!='1':raise ValueError('Umstellung zuerst prüfen und bestätigen.')
     password=n.validate_password(request.form.get('password',''))
     if password!=request.form.get('password_confirm',''):raise ValueError('Die Passwörter stimmen nicht überein.')
     key=jobs.start(c.recipe('pihole'),plan['bind'],action='pihole_network',plan=plan,credentials={'password':password})
     session.pop('pihole_network_plan',None);return redirect('/apps/installers/jobs/'+key,303)
    if request.form.get('action')=='protect':
     path,raw,data,ports,web=n.current()
     if any(ip!=web[0] or (inside==53 and host!=53) for ip,host,inside,proto in ports):raise ValueError('Abweichende DNS-Bindung; Netzwerkumstellung gezielt prüfen.')
     plan=n.prepare(web[0],web[1])
    else:plan=n.prepare(request.form.get('bind','').strip(),request.form.get('port',''))
    session['pihole_network_plan']=plan
    body+=_ui_html("<div class='card'><h3>Umstellung prüfen</h3><p>Bisher: ")+esc(plan['old_ports'] if plan.get('mode')=='native' else ', '.join(f'{ip}:{host}/{proto}' for ip,host,inside,proto in plan['old_ports']))+_ui_html('</p><p>Neu: ')+esc(plan['bind'])+':'+str(plan['port'])+_ui_html(' für Web; ')+esc(plan['bind'])+_ui_html(":53 für DNS (nur Docker; nativ bleibt DNS unverändert).</p><p>Bei Docker wird zusätzlich der interne Webport dauerhaft auf 80 festgelegt, passend zur Portweiterleitung. Die bisherige Konfiguration wird geschützt gesichert. Bei Fehler wird die bisherige Konfiguration wieder aktiviert. Der WebUI-Link wird nach erfolgreicher Prüfung angepasst.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='apply'><h3>Ersteinrichtung / Adminpasswort</h3><p>Optional ein eigenes Passwort setzen. Beide Felder leer lassen, um das vorhandene Passwort zu behalten. 12–128 Zeichen, keine Dollarzeichen. Nach erfolgreicher Umstellung die WebUI öffnen und mit diesem Passwort anmelden; anschließend DNS-Weiterleitung und Filter prüfen. Bei Docker liegt das Installationspasswort geschützt im App-Ordner in admin-password.txt. Nativ kann hier ebenfalls ein neues Passwort gesetzt werden.</p><label>Neues Adminpasswort <input type='password' name='password' autocomplete='new-password'></label><label>Passwort wiederholen <input type='password' name='password_confirm' autocomplete='new-password'></label><p></p><label><input type='checkbox' name='confirm' value='1' required> Kurze DNS-Unterbrechung und neue Erreichbarkeit bestätigt.</label><p><button class='btn'>Netzwerk umstellen</button></p></form></div>")
   else:
    native=not (Path(c.recipe('pihole')['target'])/'compose.json').exists()
    if native:
     from . import pihole_native_network
     raw,ports,entry=pihole_native_network.current()
     web=(entry[1] if entry[1]!='0.0.0.0' else request.host.split(':')[0],entry[2])
     body+=_ui_html("<div class='card'><b>Native Installation erkannt.</b><p>Geändert wird der erste IPv4-HTTP-Webzugang. DNS-Einstellungen sowie weitere HTTP-/HTTPS-Listener bleiben unverändert. Aktuelle Weblistener: ")+esc(ports)+_ui_html("</p></div>")
    else:
     path,raw,data,ports,web=n.current()
     protected=data['services']['app'].get('environment',{}).get('FTLCONF_webserver_port')=='80'
     body+=_ui_html("<div class='card'><h3>Schutz vor importierten Webports</h3><p>")+(_ui_text('Aktiv: interner Webport ist fest auf 80 gesetzt.') if protected else _ui_text('Noch nicht aktiv. Ein Konfigurationsimport kann den internen Webport verändern und den Zugriff unterbrechen.'))+_ui_html("</p><p>Der äußere Webport bleibt frei wählbar. Die feste interne Portvorgabe hat Vorrang vor importierten Einstellungen.</p>")
     if not protected:body+=_ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='protect'><button class='btn'>Webportschutz vorbereiten</button></form>")
     body+=_ui_html('</div>')
    body+=_ui_html("<div class='card'><form method='post'>")+token()+field('bind','Lokale LAN-IPv4-Adresse (Web und DNS)',web[0])+field('port','Webport (nativ 1–65535; Docker 1024–65535)',web[1])+_ui_html("<button class='btn'>Änderung prüfen</button></form></div>")
  except (ValueError,OSError) as exc:body+=_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html('</p></div>');code=400
  return ctx.page(_ui_text('Pi-hole · Netzwerk & Zugang'),body,'Apps'),code
