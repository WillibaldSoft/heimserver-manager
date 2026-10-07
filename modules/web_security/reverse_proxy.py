"""Reviewed, additive Apache reverse-proxy setup; never replaces existing sites."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import ipaddress,json,re,socket,ssl,fnmatch
from pathlib import Path
from urllib.parse import urlsplit
from . import engine as e,apache_editor as editor

ACME=Path('/var/www/server-manager-proxy-acme')

NETWORKS=tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','fc00::/7','::1/128'))

def backend(value):
 value=str(value).strip()
 if len(value)>2048:raise e.Problem('Zieladresse ist zu lang.')
 if re.search(r'[\s\x00-\x1f\x7f"\x27<>\\%$#{}]',value):raise e.Problem('Interne HTTP(S)-Adresse ohne Sonderzeichen oder Zugangsdaten angeben.')
 try:
  u=urlsplit(value);port=u.port if u.port is not None else (443 if u.scheme=='https' else 80)
 except ValueError:raise e.Problem('Ungültige interne Adresse.') from None
 if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):raise e.Problem('HTTP(S)-Adresse mit Host und Port, ohne Unterpfad angeben; eine ganze Anwendung wird weitergereicht.')
 if not 1<=port<=65535:raise e.Problem('Ungültiger Zielport.')
 try:ips=[str(ipaddress.ip_address(u.hostname))]
 except ValueError:
  if not re.fullmatch(r'[a-zA-Z0-9.-]+',u.hostname):raise e.Problem('Ungültiger Zielhostname.')
  response=e.run(['getent','ahosts',u.hostname],timeout=10)
  ips=sorted(set(line.split()[0] for line in response.stdout.splitlines() if line.split()))
 if not ips:raise e.Problem('Interner Zielhostname konnte nicht aufgelöst werden.')
 for ip in ips:
  addr=ipaddress.ip_address(ip)
  if addr.is_multicast or addr.is_unspecified or addr.is_link_local:raise e.Problem('Keine Multicast-, unbestimmte oder Link-Local-Adresse als Proxy-Ziel verwenden.')
  if not (addr.is_global or any(addr.version==net.version and addr in net for net in NETWORKS)):raise e.Problem('Zieladresse ist weder eine nutzbare LAN-/VPN-Adresse noch eine öffentliche Adresse.')
 host='['+u.hostname+']' if ':' in u.hostname else u.hostname
 return dict(url=u.scheme+'://'+host+':'+str(port)+'/',host=u.hostname,port=port,scheme=u.scheme,ips=ips)

def locations(domain):
 name='server-manager-proxy-'+domain+'.conf'
 return e.APACHE/'sites-available'/name,e.APACHE/'sites-enabled'/name

def target_fields(data):
 host=str(data.get('target_host','')).strip()
 if not host:return str(data.get('backend',''))
 scheme=data.get('target_scheme','http');port=str(data.get('target_port','')).strip()
 if scheme not in ('http','https') or not port.isdigit() or not 1<=int(port)<=65535:raise e.Problem('HTTP/HTTPS und Zielport 1–65535 auswählen.')
 if any(c in host for c in '/@?#') or re.search(r'\s',host):raise e.Problem('Nur IP oder Hostname ohne Protokoll und Pfad angeben.')
 if ':' in host:
  try:host='['+str(ipaddress.IPv6Address(host.strip('[]')))+']'
  except ValueError:raise e.Problem('Ungültige Ziel-IP.')
 return scheme+'://'+host+':'+port+'/'

def dependencies():
 return dict(apache=e.available('apache2ctl'),certbot=e.available('certbot'))

def plan(data):
 mode=data.get('connection','proxy')
 if mode=='redirect':
  from . import redirects
  return redirects.add_plan(dict(domain=data.get('domain',''),target_base=target_fields(data).rstrip('/')))
 if mode!='proxy':raise e.Problem('Proxy oder Weiterleitung auswählen.')
 domain=e.hostname(data.get('domain',''));up=backend(target_fields(data));tls=data.get('tls','new')
 if tls not in ('http','new','existing'):raise e.Problem('HTTP oder HTTPS auswählen.')
 if up['host'].lower()==domain:raise e.Problem('Domain und internes Ziel dürfen nicht gleich sein (Proxy-Schleife).')
 deps=dependencies()
 if not deps['apache'] or e.service('apache2.service')!='active':raise e.Problem('Apache zuerst über den Installer auf der Einrichtungsseite installieren/aktivieren.')
 if tls=='new' and not deps['certbot']:raise e.Problem('Certbot zuerst über den Installer auf der Einrichtungsseite installieren.')
 # Local port 80/443 would route back into this very proxy.
 local=e.run(['ip','-j','address','show'],timeout=10)
 addresses={v.get('local') for iface in json.loads(local.stdout) for v in iface.get('addr_info',[])}
 if up['port'] in (80,443) and any(ip in addresses or ipaddress.ip_address(ip).is_loopback for ip in up['ips']):raise e.Problem('Ziel führt auf den lokalen Webport 80/443 zurück. Einen eigenen Dienstport verwenden.')
 path,link=locations(domain)
 for file in (path,link):
  if file.exists() or file.is_symlink():raise e.Problem('Proxy-Datei für diese Domain bereits vorhanden. Bestehende Website unter Web & Sicherheit bearbeiten.')
 sources=editor.included_files()
 for file in sources:
  for line in file.read_text(errors='replace').splitlines():
   m=re.match(r'\s*Server(?:Name|Alias)\s+(.+)',line,re.I)
   if m and any(fnmatch.fnmatch(domain,name.strip(chr(34)+chr(39)).lower().removeprefix('http://').removeprefix('https://').split(':')[0]) for name in m[1].split()):raise e.Problem('Domain bereits in Apache verwendet. Bestehende Verbindung wird nicht ersetzt; zuerst unter Web & Sicherheit prüfen.')
 cert='';email=''
 if tls=='existing':
  matches=[c for c in e.certificates() if domain in c.get('domains',[]) and c.get('state') in ('ok','warning','critical')]
  if not matches:raise e.Problem('Kein gültiges lokales Let’s-Encrypt-Zertifikat für diese Domain gefunden.')
  cert=e.identifier(matches[0]['name'])
 if tls=='new':
  email=str(data.get('email','')).strip()
  if not re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email) or data.get('terms')!='1':raise e.Problem('E-Mail und Zustimmung zu Let’s Encrypt für das neue Zertifikat erforderlich.')
  if (e.LETSENCRYPT/'live'/domain).exists() or (e.LETSENCRYPT/'renewal'/(domain+'.conf')).exists():raise e.Problem('Zertifikat bereits vorhanden. Vorhandenes Zertifikat auswählen.')
  cert=domain
 snapshot={str(p):e.local_hash(p) for p in sorted(sources)}
 if tls=='existing':snapshot['certificate']=e.local_hash(e.LETSENCRYPT/'live'/cert/'cert.pem')
 return dict(action='setup_reverse_proxy',data=dict(domain=domain,backend=up['url'],tls=tls,email=email,terms='1' if tls=='new' else ''),snapshot=snapshot,backend=up,certificate=cert,steps=['Domain '+domain+' → interner Dienst '+up['url'],'TCP-Verbindung zum Ziel prüfen; bei HTTPS auch Zertifikat des Zielservers prüfen.','Benötigte Apache-Module aktivieren und eine eigene Proxy-Website anlegen. Bestehende Websites bleiben erhalten.','HTTP ohne Verschlüsselung einrichten.' if tls=='http' else 'HTTPS einrichten; HTTP auf HTTPS umleiten.'+(' Neues Let’s-Encrypt-Zertifikat anfordern: DNS und öffentliche Ports 80/443 müssen auf diesen Server zeigen.' if tls=='new' else ' Vorhandenes gültiges Zertifikat verwenden.'),'Apache-Konfiguration prüfen und neu laden. Bei Fehlern die neue Website entfernen; Modulaktivierungen und ggf. angefordertes Zertifikat bleiben zur Diagnose erhalten.','DNS, Router und Zielanwendung werden nicht automatisch geändert. In der App ggf. die öffentliche URL und diesen Server als vertrauenswürdigen Proxy eintragen.'])

def proxy_body(p):
 up=p['backend']
 text=' ProxyRequests Off\n ProxyPreserveHost On\n RequestHeader unset Forwarded\n RequestHeader unset X-Forwarded-For\n RequestHeader unset X-Forwarded-Host\n RequestHeader set X-Forwarded-Proto "expr=%{REQUEST_SCHEME}"\n'
 if p.get('manager_https'):
  from . import manager_https
  text+=' LimitRequestBody 0\n'+manager_https.proxy_headers()
 if up['scheme']=='https':text+=' SSLProxyEngine On\n SSLProxyVerify require\n SSLProxyCheckPeerName on\n SSLProxyCheckPeerExpire on\n SSLProxyCACertificateFile /etc/ssl/certs/ca-certificates.crt\n'
 text+=' ProxyPass /.well-known/acme-challenge/ !\n ProxyPass / '+up['url']+' connectiontimeout=5 timeout=300 upgrade=websocket\n ProxyPassReverse / '+up['url']+'\n'
 return text

def config(p,challenge,final=True):
 domain=p['data']['domain'];tls=p['data']['tls'];cert=p['certificate']
 acme=' Alias /.well-known/acme-challenge/ '+str(challenge)+'/.well-known/acme-challenge/\n <Directory '+str(challenge)+'>\n Require all granted\n AllowOverride None\n Options None\n </Directory>\n'
 text='# Managed by Server Manager: reverse proxy\n<VirtualHost *:80>\n ServerName '+domain+'\n'+acme
 if final and tls!='http':text+=' RewriteEngine On\n RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/\n RewriteRule ^ https://'+domain+'%{REQUEST_URI} [R=302,L,NE]\n'
 elif tls=='new' and not final:text+=' RewriteEngine On\n RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/\n RewriteRule ^ - [R=503,L]\n'
 else:text+=proxy_body(p)
 text+='</VirtualHost>\n'
 if final and tls!='http':
  text+='<VirtualHost *:443>\n ServerName '+domain+'\n SSLEngine on\n SSLCertificateFile '+str(e.LETSENCRYPT/'live'/cert/'fullchain.pem')+'\n SSLCertificateKeyFile '+str(e.LETSENCRYPT/'live'/cert/'privkey.pem')+'\n'+acme+proxy_body(p)+'</VirtualHost>\n'
 return text

def execute(p,folder):
 up=p['backend'];domain=p['data']['domain'];path,link=locations(domain)
 connected=False
 for ip in up['ips']:
  try:
   with socket.create_connection((ip,up['port']),timeout=5) as conn:
    if up['scheme']=='https':
     with ssl.create_default_context().wrap_socket(conn,server_hostname=up['host']):pass
   connected=True;break
  except (OSError,ValueError):continue
 if not connected:raise e.Problem('Zieldienst nicht erreichbar oder sein TLS-Zertifikat ungültig. Keine Proxy-Website angelegt.')
 challenge=ACME/domain
 if any(p.is_symlink() for p in (ACME,challenge,challenge/'.well-known',challenge/'.well-known/acme-challenge')):raise e.Problem('ACME-Ordner darf kein symbolischer Link sein.')
 # ACME challenge files are public; no credentials or application data go here.
 challenge.mkdir(parents=True,exist_ok=True)
 (challenge/'.well-known/acme-challenge').mkdir(parents=True,exist_ok=True)
 for directory in (ACME,challenge,challenge/'.well-known',challenge/'.well-known/acme-challenge'):directory.chmod(0o755)
 e.atomic(folder/'proxy-install.json',dict(site=str(path),enabled=str(link),domain=domain,backend=up['url']))
 modules=['proxy','proxy_http','headers','rewrite']
 if p['data']['tls']!='http' or up['scheme']=='https':modules.append('ssl')
 e.run(['a2enmod',*modules]);created=False;linked=False;reload_attempted=False
 try:
  with path.open('x') as out:created=True;out.write(config(p,challenge,final=p['data']['tls']!='new'))
  path.chmod(0o600 if p.get('manager_https') else 0o644);link.symlink_to('../sites-available/'+path.name);linked=True
  e.run(['apache2ctl','configtest']);reload_attempted=True;e.run(['systemctl','reload','apache2.service'])
  if p['data']['tls']=='new':
   e.run(['certbot','certonly','--webroot','-w',str(challenge),'--non-interactive','--agree-tos','--email',p['data']['email'],'--cert-name',domain,'-d',domain,'--deploy-hook','/usr/bin/systemctl reload apache2.service'],timeout=600)
   meta=path.stat();editor.write_file(path,config(p,challenge).encode(),meta.st_mode & 0o777,meta.st_uid,meta.st_gid)
   e.run(['apache2ctl','configtest']);e.run(['systemctl','reload','apache2.service']);e.run(['systemctl','enable','--now','certbot.timer'])
 except Exception:
  if linked:link.unlink()
  if created:path.unlink()
  if reload_attempted:e.run(['apache2ctl','configtest']);e.run(['systemctl','reload','apache2.service'])
  raise
 return {'message':'Reverse Proxy eingerichtet. Zielanschluss und Apache-Konfiguration geprüft. Anmeldung und Funktionen der Ziel-App sowie öffentlichen Zugriff anschließend prüfen.','url':('http' if p['data']['tls']=='http' else 'https')+'://'+domain}

def register(app,page,esc):
 from flask import request,session
 import secrets
 from urllib.parse import urlencode
 from modules.dyndns import targets,engine as dyndns
 @app.route('/dyndns/proxy')
 def setup_form():
  session.setdefault('web_security_csrf',secrets.token_urlsafe(32))
  def hidden(name,value):return "<input type='hidden' name='"+name+"' value='"+esc(value)+"'>"
  def field(name,label,value='',kind='text'):
   return _ui_html("<label style='display:block;margin:12px 0'>")+_ui_text(label)+_ui_html("<input style='display:block;width:100%;max-width:720px' name='")+name+"' type='"+kind+"' value='"+esc(value)+_ui_html("'></label>")
  try:
   mappings=targets.load();hosts=sorted(set(mappings)|set(targets.apache())|{p['host'] for p in dyndns.load()['providers']})
   domain=request.args.get('host','');mapping=mappings.get(domain,{})
   csrf=hidden('csrf',session['web_security_csrf']);deps=dependencies()
   body=_ui_html("<div class='card'><h2>Verbindung einrichten</h2><p><a href='/dyndns/targets'>Zurück zu Ziele & Dienste</a></p><p>Dieser Assistent richtet eine neue Apache-Website auf diesem Server ein. Bestehende Websites und Verbindungen werden nicht überschrieben. DNS und Routerfreigaben musst du passend einrichten.</p>")
   for component,label,needed in [('apache','Apache installieren / aktivieren',not deps['apache'] or e.service('apache2.service')!='active'),('certbot','Zertifikatsinstaller starten',not deps['certbot'])]:
    if needed:body+=_ui_html("<p>")+(_ui_text('Apache wird für beide Varianten benötigt.') if component=='apache' else _ui_text('Certbot wird für ein neues HTTPS-Zertifikat benötigt.'))+_ui_html("</p><form method='post' action='/web-security/preview'>")+csrf+hidden('action','install_'+component)+_ui_html("<button class='btn'>")+_ui_text(label)+_ui_html("</button></form>")
   body+=_ui_html("<form method='post' action='/web-security/preview'>")+csrf+hidden('action','setup_reverse_proxy')
   body+=_ui_html("<label style='display:block;margin:12px 0'>Verbindungsart<select id='connection-mode' name='connection' style='display:block;width:100%;max-width:720px'><option value='proxy'>Reverse Proxy – Domain bleibt sichtbar</option><option value='redirect'>Weiterleitung – Browser wechselt zur Zieladresse</option></select></label><p>Proxy: Dieser Server ruft den Zieldienst auf. Weiterleitung: Das Gerät des Besuchers ruft das Ziel selbst auf; eine private IP ist deshalb nur im LAN/VPN erreichbar.</p>")
   body+=_ui_html("<label style='display:block;margin:12px 0'>Domain auf diesem Server<input name='domain' list='proxy-domains' value='")+esc(domain)+_ui_html("' required style='display:block;width:100%;max-width:720px'></label><datalist id='proxy-domains'>")+''.join("<option value='"+esc(host)+"'>" for host in hosts)+"</datalist>"
   body+=field('target_host','Ziel-IP oder Hostname (ohne http://)',request.args.get('target_host',mapping.get('target','')))+field('target_port','Zielport',request.args.get('target_port',mapping.get('internal_port') or '8080'),'number')
   body+=_ui_html("<label style='display:block;margin:12px 0'>Protokoll am Ziel<select name='target_scheme' style='display:block;width:100%;max-width:720px'><option value='http'>HTTP</option><option value='https'>HTTPS</option></select></label><p>Beispiel: IP <code>192.168.1.20</code>, Port <code>8096</code>, HTTP. Öffentliches HTTPS am Proxy ist davon unabhängig. Beim HTTPS-Ziel muss dessen Zertifikat für die eingegebene Zieladresse gültig sein.</p>")
   body+=_ui_html("<div id='proxy-options'><label style='display:block;margin:12px 0'>Zugang zur Domain<select name='tls' style='display:block;width:100%;max-width:720px'><option value='new'>HTTPS – neues Let’s-Encrypt-Zertifikat</option><option value='existing'>HTTPS – vorhandenes Zertifikat verwenden</option><option value='http'>Nur HTTP – ohne Verschlüsselung</option></select></label>")+field('email','E-Mail für neues Zertifikat','','email')+_ui_html("<label><input type='checkbox' name='terms' value='1'> Für ein neues Zertifikat: <a href='https://letsencrypt.org/repository/' target='_blank' rel='noopener noreferrer'>Let’s-Encrypt-Bedingungen</a> akzeptieren</label><p>Für neue Zertifikate müssen DNS und öffentliche Ports 80/443 auf diesen Server zeigen. Die automatische Zertifikatserneuerung wird eingerichtet.</p></div><p id='redirect-options' hidden>Eine neue Weiterleitung startet mit HTTP an der Ausgangsadresse und Status 302. Das Ziel darf HTTP oder HTTPS nutzen. HTTPS für die Ausgangsadresse anschließend unter Web & Sicherheit ergänzen. Unterpfade bleiben erhalten.</p>")
   body+=_ui_html("<p><button class='btn'>Verbindung prüfen und Vorschau öffnen …</button></p></form><details><summary>Was muss ich in der Ziel-App beachten?</summary><p>Ein Proxy ersetzt keine Anmeldung. Nur Dienste veröffentlichen, deren Zugangsschutz eingerichtet ist. Nextcloud kann die Domain in trusted_domains und diesen Proxy in trusted_proxies benötigen. Home Assistant benötigt gegebenenfalls use_x_forwarded_for und trusted_proxies. Diese App-Einstellungen werden nicht automatisch geändert. Die Verbindung wird für die ganze Domain eingerichtet, nicht für einen Unterordner.</p><p>WebSocket-Verbindungen werden unterstützt. HTTPS zum Ziel wird mit Zertifikatsprüfung verwendet; selbstsignierte Zertifikate ohne passende Vertrauenskette werden nicht automatisch akzeptiert.</p></details></div><script>document.getElementById('connection-mode').onchange=function(){var redirect=this.value==='redirect';document.getElementById('proxy-options').hidden=redirect;document.getElementById('redirect-options').hidden=!redirect;};</script>")
   return page(_ui_text('Verbindung einrichten'),body)
  except (OSError,ValueError) as exc:return page(_ui_text('Verbindung einrichten'),_ui_html("<div class='card'>")+esc(str(exc))+_ui_html("</div>")),400
