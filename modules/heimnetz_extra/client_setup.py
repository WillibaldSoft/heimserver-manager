"""Personal bootstrap downloads; expiring one-use codes stored only as hashes."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,json,secrets,time,re,ssl
from flask import request,g,session,jsonify,Response,current_app
from . import client_bindings as binding
from server_settings import get as host_setting

def profile_filename(name):
 # ASCII attachment name; never allow path or HTTP header characters.
 label=re.sub(r'[^A-Za-z0-9._-]+','_',str(name)).strip('._-')[:64] or 'Benutzer'
 return 'Heimserver-Client-'+label+'.json'

def schema(con):
 binding.schema(con)
 con.execute('CREATE TABLE IF NOT EXISTS client_setup_codes (digest TEXT PRIMARY KEY, account_key TEXT NOT NULL, principal TEXT NOT NULL, expires REAL NOT NULL)')
def current(old):
 auth=current_app.extensions['server_manager_auth'].read()
 p=(dict(kind='local',name=auth['username'],role='admin',revision=auth['revision']) if old['kind']=='local' else current_app.extensions['server_manager_users'].principal(old['name'],auth['session_secret']))
 if not p or binding.key(p)!=binding.key(old) or p['revision']!=old['revision'] or p.get('stamp')!=old.get('stamp'):raise ValueError('Einrichtung abgelaufen oder Freigabe geändert.')
 if p['role'] not in ('admin','user') or (p['role']!='admin' and 'client' not in p.get('modules',[])):raise ValueError('Client-Steuerung nicht freigegeben.')
 return p

def profile(p,code,mac):
 from modules.web_security import manager_https as mh
 state=mh.load()
 if not state.get('enabled'):raise ValueError('Zuerst HTTPS-Zugang im Manager einrichten.')
 recover=host_setting('recover_url') or ''
 cfg=dict(SERVER_URL=mh.public_url(state),TOKEN='setup:'+code,CLIENT_NAME=p['name'],CLIENT_MAC='',CLIENT_MODE='without_server',IPMI_RECOVER_URL=recover,WAKE_METHOD=(('both' if mac else 'recover') if recover else ('wol' if mac else 'none')),SERVER_MAC=mac,WAKE_TIMEOUT='40')
 result=dict(format='heimserver-manager-client',version=1,config=cfg,enrollment=dict(expires_in_seconds=900,account=p['name'],one_time=True))
 if (mh.TLS/'root-ca.crt').is_file():
  pem=(mh.TLS/'root-ca.crt').read_text();result['https']=dict(hostname=state['hostname'],port=state['port'],ip=state.get('ip_address') or '',ca_pem=pem,sha256=hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest())
 return result

def register(app,ctx,init_tables,server_mac):
 @app.get('/clients/setup')
 def setup_page():
  body=_ui_html("<div class='card'><h2>Meinen Client einrichten</h2><p>Angemeldet als <b>")+ctx.esc(g.auth_principal['name'])+_ui_html("</b>. Für jeden PC und jede lokale Benutzeranmeldung ein eigenes Profil einrichten.</p><ol><li><a class='btn' href='/clients/desktop/download'>Linux (.deb)</a> <a class='btn' href='/clients/windows/download'>Windows (.exe, experimentell)</a> herunterladen und installieren.</li><li>Persönliches Profil unten herunterladen und im Client importieren. Falls erforderlich, privates HTTPS nach Prüfung des Zertifikats-Fingerabdrucks einrichten. Zertifikatvertrauen wird nicht automatisch erteilt.</li><li>Im Client speichern und <b>Agent aktivieren</b> wählen. Das Profil wird über geprüftes HTTPS einmalig gegen ein eigenes Benutzer-Geräte-Token getauscht.</li></ol><p>Das Profil gilt 15 Minuten. Ein neues Profil macht frühere unbenutzte Profile dieses Kontos ungültig. Bei Ablauf oder verloren gegangener Antwort neues Profil herunterladen. Kein Passwort im Download. Profil bis zur Verwendung geschützt aufbewahren.</p><p>Serveradresse, Server-MAC für Wake-on-LAN und die im Manager eingestellte Recovery-Adresse werden übernommen. Der Client-Name wird bei Aktivierung automatisch aus Manager-Benutzer und Rechnername gebildet. Der Rechnername stammt aus dem Betriebssystem; eine BIOS-Bezeichnung wird nicht benötigt. Modus anfangs: Ohne Server starten. Bedarf später selbst einstellen. Eigene Backups erfordern weiterhin die Manager-Anmeldung im Client.</p>")
  if g.auth_principal['role']=='admin':body+=_ui_html("<p><a class='btn' href='/settings/server-paths#field-recover_url'>Recovery-Adresse ändern</a></p>")
  if g.auth_principal['role'] in ('admin','user'):
   body+=_ui_html("<form method='post' action='/clients/setup/profile'><input type='hidden' name='auth_csrf' value='")+ctx.esc(session['auth_csrf'])+_ui_html("'><button>Persönliches Einrichtungsprofil herunterladen</button></form>")
  else:body+=_ui_html('<p>Nur Lesen: keine neue Gerätekopplung erlaubt.</p>')
  return ctx.page(_ui_text('Client einrichten'),body+_ui_html('</div>'),'Clients')
 @app.post('/clients/setup/profile')
 def setup_profile():
  try:
   p=current(g.auth_principal);code=secrets.token_urlsafe(32);data=profile(p,code,server_mac());con=ctx.db()
   try:
    init_tables(con);schema(con);con.execute('BEGIN IMMEDIATE');con.execute('DELETE FROM client_setup_codes WHERE expires<? OR account_key=?',(time.time(),binding.key(p)))
    con.execute('INSERT INTO client_setup_codes VALUES(?,?,?,?)',(hashlib.sha256(code.encode()).hexdigest(),binding.key(p),json.dumps(p),time.time()+900));con.commit()
   finally:con.close()
   return Response(json.dumps(data),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="'+profile_filename(p['name'])+'"','Cache-Control':'no-store','Pragma':'no-cache','X-Content-Type-Options':'nosniff'})
  except (ValueError,OSError,KeyError):return 'Einrichtungsprofil nicht verfügbar. HTTPS und Benutzerfreigabe prüfen.',400
 @app.post('/api/clients/enroll')
 def enroll():
  try:
   if request.content_length is None or request.content_length>8192:raise ValueError('Ungültige Anfrage.')
   data=request.get_json();code=data.get('code','')
   if not isinstance(code,str) or not re.fullmatch('[A-Za-z0-9_-]{43}',code):raise ValueError('Ungültiger Einrichtungscode.')
   con=ctx.db()
   try:
    init_tables(con);schema(con);con.execute('BEGIN IMMEDIATE');digest=hashlib.sha256(code.encode()).hexdigest()
    row=con.execute('SELECT * FROM client_setup_codes WHERE digest=?',(digest,)).fetchone()
    if not row or row['expires']<=time.time():raise ValueError('Einrichtungscode abgelaufen oder bereits verwendet. Neues Profil herunterladen.')
    p=current(json.loads(row['principal']));result=binding.create_agent(con,p,data)
    con.execute('DELETE FROM client_setup_codes WHERE digest=?',(digest,));con.commit()
   finally:con.close()
   result['server_mac']=server_mac();response=jsonify(result);response.headers['Cache-Control']='no-store';return response
  except (ValueError,TypeError,AttributeError,KeyError):return jsonify(error='Einrichtung nicht möglich: Profil abgelaufen, verwendet oder Freigabe geändert. Neues Profil im Manager herunterladen.'),400
