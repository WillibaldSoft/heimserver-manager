from ui_translation import html_literal as _ui_html, text as _ui_text
import html
from flask import request,session,redirect
from . import install_catalog as c,kvm_setup as setup,install_jobs as jobs,bridge_migration as migration
E=lambda v:html.escape(str(v),quote=True)
def register(app,ctx,token):
 def page(body,code=200):return ctx.page(_ui_text('KVM / libvirt · Installer'),_ui_html("<div class='card'><h2>KVM / libvirt</h2>")+body+_ui_html("<p><a href='/apps/manage'>Apps verwalten</a> · <a href='/kvm'>Virtuelle Maschinen</a></p></div>"),'Apps'),code
 def detail():
  current=migration.state()
  pending=current.get('status') in ('pending','applying','rolling-back')
  body=''
  if current:
   body+=_ui_html('<p>Bridge-Übernahme: <b>')+E(_ui_text(current.get('status')))+_ui_html('</b></p>')
  if current.get('status')=='pending':
   body+=_ui_html("<p>Nach erneutem Verbinden über die bisherige Serveradresse bestätigen. MAC und IP werden zusätzlich geprüft. Ohne Bestätigung innerhalb von fünf Minuten erfolgt die Rücksicherung.</p><form method='post' action='/apps/kvm/installer/confirm'>")+token()+_ui_html("<input type='hidden' name='transaction' value='")+E(current['id'])+_ui_html("'><button>Verbindung funktioniert – Bridge behalten</button></form>")
  if pending:return page(body)
  body+=_ui_html("<h3>VM-Backups & Wiederherstellung</h3><p>Die Installation umfasst squashfs-tools für schreibgeschützte Rescuezilla-Sicherungsmedien, qemu-utils sowie swtpm/swtpm-tools für Festplattenkonvertierung und emuliertes TPM 2.0. Im Heimserver Manager lassen sich ausgeschaltete VMs sichern und Backup-Pakete hochladen. Nach der Installation ein vorhandenes Backup unter neuem VM-Namen wiederherstellen; vorhandene VMs bleiben erhalten.</p><p><a class='btn' href='/kvm/backups'>VM-Backup hochladen / wiederherstellen</a></p>")
  body+=_ui_html('<p>QEMU/KVM, libvirt, UEFI-Firmware, Verwaltungs- und Bridge-Werkzeuge aus den eingerichteten Paketquellen (Debian 13 / Mint 22.x) installieren. APT installiert die Paketabhängigkeiten. Vorhandene VMs und Konfigurationen bleiben erhalten.</p>')
  try:
   active=setup.active_lan();body+=_ui_html('<p>Aktive LAN-Verbindung: <b>')+E(active['name'])+_ui_html('</b> · MAC ')+E(active['mac'])+' · IP '+E(', '.join(active['addresses']))+_ui_html('</p>')
  except (ValueError,OSError) as exc:body+=_ui_html('<p>')+E(_ui_text(exc))+_ui_html('</p>')
  body+=_ui_html("<form method='post' action='/apps/kvm/installer/start'>")+token()+_ui_html("<label>Netzwerk <select name='network'><option value='nat' selected>NAT – keine Änderung am Host-LAN (default / virbr0)</option><option value='auto'>LAN-Bridge – gewählte oder aktive LAN-Verbindung übernehmen</option><option value='existing'>Vorhandene LAN-Bridge</option><option value='migrate'>Aktive LAN-Karte übernehmen (NetworkManager / ifupdown, Rücksicherung)</option><option value='new'>Neue LAN-Bridge über freie LAN-Schnittstelle (ifupdown)</option></select></label>")
  try:
   choices=setup.lan_choices()
  except (ValueError,OSError):choices=[]
  body+=_ui_html("<p><label for='kvm-interface'><b>LAN-Schnittstelle auswählen ▾</b></label><br><select id='kvm-interface' name='interface' style='display:block;width:100%;min-height:48px;appearance:auto;border:2px solid #94a3b8'><option value=''>Automatisch anhand der aktiven LAN-Verbindung (nur LAN-Bridge-Modus)</option>")
  for i in choices:
   label=i['name']+' · '+('Bridge' if i['bridge'] else 'LAN-Karte')+' · '+i.get('state','UNKNOWN')+' · MAC '+i['mac']+' · IP '+(', '.join(i['addresses']) or 'keine')
   body+=_ui_html("<option value='")+E(i['name'])+"'>"+E(_ui_text(label))+_ui_html('</option>')
  body+=_ui_html("</select><small>Bei NAT und einer vorhandenen Bridge wird dieses Feld nicht verwendet. Für Übernahme oder neue Bridge die passende LAN-Karte auswählen. Die Umstellung erfolgt erst nach Prüfung und Bestätigung.</small></p>")
  if not choices:body+=_ui_html("<p class='warn'>Keine geeignete kabelgebundene Schnittstelle oder Bridge gefunden. NAT ist auch ohne LAN-Auswahl möglich.</p>")
  for name,label,value in [('bridge','Bridge-Name (nur für LAN-Bridge)','br0'),('user','Lokaler Benutzer für libvirt/kvm (optional)','')]:body+=_ui_html("<p><label>")+_ui_text(label)+_ui_html(" <input name='")+name+"' value='"+value+_ui_html("'></label></p>")
  body+=_ui_html('<p>Eine neue LAN-Bridge benötigt eine unbenutzte kabelgebundene Schnittstelle ohne IP, Route oder bestehende Konfiguration. Für aktive LAN-Karten gibt es die separate Übernahme mit Vorschau, beibehaltener MAC und automatischer Rücksicherung. NetworkManager und ifupdown werden unterstützt. WLAN und systemd-networkd werden nicht automatisch umgebaut. Dort zuvor eine Bridge einrichten und „Vorhandene LAN-Bridge“ wählen.</p><p>Der optionale Benutzer erhält Verwaltung aller lokalen VMs. Er bleibt ein normaler Linux-Benutzer; neue Gruppen gelten nach erneuter Anmeldung.</p>')
  body+=_ui_html("<button name='action' value='preview'>Installation prüfen</button></form><p><a href='/apps/kvm/installer/download'>Portablen Installer herunterladen (NAT-Vorgabe)</a></p>")
  body+=_ui_html("""<script>(function(){const f=document.querySelector('form[action="/apps/kvm/installer/start"]');if(!f)return;const n=f.elements.network,i=f.elements.interface,b=f.elements.bridge;function update(){i.disabled=n.value==='nat'||n.value==='existing';i.required=n.value==='migrate'||n.value==='new';b.disabled=n.value==='nat';}n.addEventListener('change',update);update();})();</script>""")
  return page(body)
 def start():
  try:
   if request.form.get('action')=='apply':
    profile=session.pop('kvm_install_plan',None)
    if not profile or request.form.get('confirm')!='yes':raise ValueError('Bitte Plan erneut prüfen und bestätigen.')
    key=jobs.start(profile,'127.0.0.1');return redirect('/apps/installers/jobs/'+key,303)
   profile=dict(c.recipe('kvm'),network=request.form.get('network','nat'),bridge=request.form.get('bridge','br0'),interface=request.form.get('interface',''),user=request.form.get('user','').strip())
   if profile['network']=='auto':
    chosen=profile['interface']
    if chosen:
     active=next((i for i in setup.lan_choices() if i['name']==chosen),None)
     if active is None:raise ValueError('Die ausgewählte LAN-Schnittstelle ist nicht mehr verfügbar. Auswahl erneuern.')
    else:active=setup.active_lan()
    profile['interface']=active['name']
    profile['network']='existing' if active['bridge'] else 'migrate'
    if active['bridge']:profile['bridge']=active['name']
   if profile['network'] in ('migrate','new') and not profile['interface']:raise ValueError('Bitte eine LAN-Schnittstelle aus dem Dropdown auswählen.')
   problems=setup.checks(profile)
   if problems:raise ValueError('; '.join(problems))
   plan=setup.network_plan(profile)
   if plan['mode']=='migrate':profile['migration_digest']=migration.digest(plan)
   session['kvm_install_plan']=profile
   body=_ui_html('<h3>Installationsplan</h3><p>')+E(_ui_text(plan['description']))+_ui_html('</p><p>Pakete: ')+E(', '.join(setup.packages()))+_ui_html('</p><p>Benutzer: ')+E(profile['user'] or _ui_text('Keine Gruppenänderung'))+_ui_html('</p>')
   if plan.get('text'):body+=_ui_html('<pre>')+E(plan['text'])+_ui_html('</pre>')
   if plan['mode']=='migrate':
    body+=_ui_html('<p>MAC: ')+E(plan['mac'])+' · bisherige IPs: '+E(', '.join(plan['addresses']))+_ui_html('</p><p>Verbindung kann kurz abbrechen. Innerhalb von fünf Minuten nach Aktivierung diese Installer-Seite erneut über die bisherige Serveradresse öffnen und bestätigen. Bei DHCP hängt dieselbe IP zusätzlich vom DHCP-Server und der Client-ID ab. Unbestätigte Änderungen werden auch beim nächsten Boot zurückgenommen.</p><h4>Neue Konfiguration</h4><pre>')+E(plan['replacement'])+_ui_html('</pre>')
   body+=_ui_html("<form method='post' action='/apps/kvm/installer/start'>")+token()+_ui_html("<label><input type='checkbox' name='confirm' value='yes' required> Diesen Installationsplan ausführen</label><button name='action' value='apply'>Installieren / ergänzen</button></form>")
   return page(body)
  except (ValueError,OSError) as exc:return page(_ui_html('<p>')+E(_ui_text(exc))+_ui_html('</p>'),400)
 @app.route('/apps/kvm/installer/confirm',methods=['POST'])
 def confirm_bridge():
  import secrets
  if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return page(_ui_html('Formular abgelaufen.'),403)
  try:
   migration.confirm(request.form.get('transaction',''));return redirect('/apps/kvm/installer',303)
  except (ValueError,OSError) as exc:return page(_ui_html('<p>')+E(_ui_text(exc))+_ui_html('</p>'),400)
 return detail,start
