"""Additive private HTTPS for the manager; public HTTPS uses the reviewed proxy installer."""
import fcntl
import fnmatch
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import http.client
import time
import tempfile
from pathlib import Path
from . import engine as e, apache_editor as editor

CONFIG = e.CONFIG_DIR / 'manager-https.json'
TLS = e.CONFIG_DIR / 'manager-tls'
SITE_NAME = 'server-manager-private.conf'
MARKER = '# Managed by Heimserver Manager: private HTTPS\n'
DEFAULT_NETWORKS = '127.0.0.0/8 ::1/128 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fc00::/7 fe80::/10'


def load():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def default_hostname():
    label = re.sub('[^a-z0-9-]', '-', socket.gethostname().split('.')[0].lower())[:63].strip('-') or 'heimserver'
    return label if not label.isdecimal() else 'heimserver'


def backend_port():
    port = int(os.environ.get('SERVER_MANAGER_PORT', '9877'))
    if not 1 <= port <= 65535:
        raise e.Problem('Ungültiger Manager-Port.')
    return port


def files():
    return (e.APACHE / 'sites-available' / SITE_NAME,
            e.APACHE / 'sites-enabled' / SITE_NAME,
            e.APACHE / 'conf-available' / 'server-manager-https-port.conf',
            e.APACHE / 'conf-enabled' / 'server-manager-https-port.conf')


def private_hostname(value):
    try:value=str(value).strip().rstrip('.').encode('idna').decode().lower()
    except UnicodeError:raise e.Problem('Ungültiger privater Hostname.') from None
    if len(value)>253 or value.isdecimal() or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):
        raise e.Problem('Privaten Rechnernamen oder vollständigen lokalen Hostnamen angeben.')
    try:ipaddress.ip_address(value)
    except ValueError:return value
    raise e.Problem('Hostname statt IP-Adresse angeben.')


def validate(data):
    host = private_hostname(data.get('hostname', default_hostname()))
    try:
        port = int(data.get('port', 443))
        networks = [str(ipaddress.ip_network(x, strict=False)) for x in str(data.get('networks', DEFAULT_NETWORKS)).split()]
    except ValueError:
        raise e.Problem('Gültigen HTTPS-Port und IP-Netze in CIDR-Schreibweise angeben.') from None
    if not 1 <= port <= 65535 or port == backend_port():
        raise e.Problem('HTTPS-Port muss vom internen Manager-Port verschieden sein.')
    if not networks or len(networks) > 32 or any(ipaddress.ip_network(x).prefixlen == 0 for x in networks):
        raise e.Problem('Private Zugangsnetze angeben; keine Freigabe für alle Adressen.')
    ip = str(data.get('ip_address', '')).strip()
    try:
        ip_port = int(data.get('ip_port', 8443))
        if ip:
            address = ipaddress.ip_address(ip)
            if address.is_unspecified or address.is_multicast or address.is_link_local or '%' in ip:
                raise ValueError()
            ip = str(address)
    except ValueError:
        raise e.Problem('Gültige feste Server-IP und IP-HTTPS-Port angeben.') from None
    if ip and (not 1 <= ip_port <= 65535 or ip_port in (port, backend_port())):
        raise e.Problem('IP-HTTPS benötigt einen eigenen Port, verschieden von Domain- und Manager-Port.')
    return dict(hostname=host, port=port, networks=' '.join(networks), ip_address=ip, ip_port=ip_port)


def plan(action, data):
    if action == 'manager_https_public':
        from . import reverse_proxy
        if not load().get('proxy_token'):
            raise e.Problem('Zuerst privaten HTTPS-Zugang einrichten.')
        if e.CONFIG_DIR.joinpath('authentication.json').exists():
            if json.loads(e.CONFIG_DIR.joinpath('authentication.json').read_text()).get('default_password'):
                raise e.Problem('Vor öffentlichem Zugang das Installationspasswort unter Zugang ändern ersetzen.')
        p = reverse_proxy.plan(dict(domain=data.get('domain', ''), email=data.get('email', ''), terms=data.get('terms', ''), tls=data.get('tls', 'new'), backend='http://127.0.0.1:' + str(backend_port())))
        if p['data']['tls'] == 'http':
            raise e.Problem('Öffentlicher Manager-Zugang benötigt HTTPS.')
        return dict(action=action, data=dict(domain=p['data']['domain'], email=p['data']['email'], terms=p['data']['terms'], tls=p['data']['tls']), proxy=p,
                    snapshot=e.local_hash(CONFIG), steps=['Öffentlichen HTTPS-Zugang zusätzlich zum privaten Zugang einrichten.'] + p['steps'])
    if action == 'manager_https_disable':
        raise e.Problem('HTTPS ist der einzige Netzwerkzugang und kann nicht deaktiviert werden. Namen oder Port stattdessen ändern.')
    if action not in ('manager_https_private',):
        raise e.Problem('Unbekannte Manager-HTTPS-Aktion.')
    for command in ('apache2ctl', 'openssl'):
        if not e.available(command):
            raise e.Problem(command + ' fehlt. Apache/OpenSSL über Web & Sicherheit installieren.')
    path, link, port_file, port_link = files()
    for p in (CONFIG, TLS, path, port_file):
        if p.is_symlink():
            raise e.Problem('Unerwarteter symbolischer Link: ' + str(p))
    if path.exists() and not path.read_text().startswith(MARKER):
        raise e.Problem('Vorhandene fremde Apache-Konfiguration wird nicht überschrieben.')
    for p, target in ((link, path), (port_link, port_file)):
        if (p.exists() or p.is_symlink()) and (not p.is_symlink() or p.resolve() != target.resolve()):
            raise e.Problem('Vorhandene Apache-Aktivierung gehört nicht zur Manager-Datei.')
    values = validate(data) if action == 'manager_https_private' else {}
    if values:
        ports = {values['port']}
        if values['ip_address']: ports.add(values['ip_port'])
        # Debian's ports.conf enables Listen 443 as soon as mod_ssl is enabled.
        if not (e.APACHE/'mods-enabled/ssl.load').exists(): ports.add(443)
        for port in ports:
            listeners = e.run(['ss', '-H', '-ltnp', 'sport = :' + str(port)], check=False)
            if listeners.returncode:
                raise e.Problem('HTTPS-Portbelegung konnte nicht geprüft werden.')
            for line in listeners.stdout.splitlines():
                if line.strip() and '"apache2"' not in line:
                    raise e.Problem('Port '+str(port)+' ist durch einen anderen oder nicht identifizierbaren Dienst belegt. Port/Webserver prüfen; vorhandene Dienste werden nicht geändert.')
    sources = editor.included_files()
    if values:
        for source in sources:
            if source.resolve() == path.resolve():
                continue
            for line in source.read_text(errors='replace').splitlines():
                if values['ip_address'] and re.search(r'<VirtualHost\s+[^>]*:' + str(values['ip_port']) + r'(?:\s|>)', line, re.I):
                    raise e.Problem('IP-HTTPS-Port wird bereits von einer Apache-Website verwendet.')
                m = re.match(r'\s*Server(?:Name|Alias)\s+(.+)', line, re.I)
                if m and any(fnmatch.fnmatch(values['hostname'], name.strip('"\'').lower()) for name in m[1].split()):
                    raise e.Problem('Hostname bereits von einer Apache-Website verwendet.')
    if values and values['ip_address']:
        addresses = e.run(['ip', '-j', 'address', 'show'])
        local = {str(ipaddress.ip_address(a['local'])) for interface in json.loads(addresses.stdout) for a in interface.get('addr_info', []) if a.get('local')}
        if values['ip_address'] not in local:
            raise e.Problem('Die IP-Adresse ist diesem Server nicht zugewiesen.')
    snapshot = {str(p): e.local_hash(p) for p in sorted(set(sources) | {CONFIG, path, port_file})}
    snapshot['enabled'] = str(link.is_symlink())
    steps = ['Nur den privaten HTTPS-VHost deaktivieren; Zertifikate und HTTP-Zugang bleiben erhalten.'] if not values else [
        'Privater Zugang: https://' + values['hostname'] + (':' + str(values['port']) if values['port'] != 443 else ''),
        'Zugang nur aus diesen Netzen: ' + values['networks'],
        'Lokale Zertifizierungsstelle und Serverzertifikat erzeugen/weiterverwenden. Keine externen Zertifikatsanfragen.',
        'Hostname im lokalen DNS oder in hosts-Dateien auf die Server-IP legen; Stammzertifikat auf Client-Geräten importieren.',
        'Eigene Apache-Datei anlegen, Konfiguration prüfen und Apache neu laden; bei Fehlern eigene Dateien zurücksetzen.',
        'Manager-HTTP ist nur intern auf 127.0.0.1 erreichbar. Clients benötigen HTTPS und Vertrauen des Stammzertifikats.',
        'Täglichen Timer zur Erneuerung des privaten Serverzertifikats aktivieren.']
    if values and values['ip_address']:
        steps.append('Zusätzlicher IP-Zugang: ' + ip_url(values) + ' · gleicher Netzschutz und gleiche Anmeldung; eigene Portbindung.')
    return dict(action=action, data=values, snapshot=snapshot, steps=steps)


def text_file(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def certificates(host, renew=False, ip_address=""):
    ip_address = str(ipaddress.ip_address(ip_address)) if ip_address else ""
    TLS.mkdir(parents=True, exist_ok=True, mode=0o700)
    ca, key = TLS/'root-ca.crt', TLS/'root-ca.key'
    if ca.exists() != key.exists():
        raise e.Problem('Lokale CA unvollständig; vor einer Neuerstellung Sicherung prüfen.')
    if not ca.exists():
        with tempfile.TemporaryDirectory(dir=TLS) as tmp:
            tmp = Path(tmp)
            e.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '3650', '-sha256', '-subj', '/CN=Heimserver Manager Local CA', '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', str(tmp/'ca.key'), '-out', str(tmp/'ca.crt')], timeout=60)
            os.chmod(tmp/'ca.key', 0o600)
            os.replace(tmp/'ca.key', key); os.replace(tmp/'ca.crt', ca)
    if e.run(['openssl', 'x509', '-checkend', str(86400*366), '-noout', '-in', str(ca)], check=False).returncode:
        raise e.Problem('Lokale CA läuft bald ab. Neue CA und erneutes Vertrauen auf Clients geplant einrichten; keine automatische CA-Rotation.')
    directory = TLS/host
    cert, private = directory/'cert.pem', directory/'key.pem'
    if cert.exists() and private.exists() and not renew:
        valid = e.run(['openssl', 'x509', '-checkend', str(86400*30), '-noout', '-in', str(cert)], check=False).returncode == 0
        valid = valid and e.run(['openssl', 'verify', '-CAfile', str(ca), '-verify_hostname', host, str(cert)], check=False).returncode == 0
        if valid and ip_address:
            valid = e.run(['openssl', 'verify', '-CAfile', str(ca), '-verify_ip', ip_address, str(cert)], check=False).returncode == 0
        if valid: return cert, private
    directory.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        tmp = Path(tmp)
        ext = tmp/'extensions.cnf'
        ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:' + host + (',IP:' + ip_address if ip_address else '') + '\n')
        e.run(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN='+host, '-keyout', str(tmp/'key'), '-out', str(tmp/'request')], timeout=60)
        e.run(['openssl', 'x509', '-req', '-in', str(tmp/'request'), '-CA', str(ca), '-CAkey', str(key), '-set_serial', '0x'+secrets.token_hex(16), '-days', '365', '-sha256', '-extfile', str(ext), '-out', str(tmp/'cert')])
        e.run(['openssl', 'verify', '-CAfile', str(ca), '-verify_hostname', host, str(tmp/'cert')])
        os.chmod(tmp/'key', 0o600)
        for old in (cert, private):
            if old.exists(): shutil.copyfile(old, old.with_suffix(old.suffix+'.previous')); old.with_suffix(old.suffix+'.previous').chmod(0o600)
        os.replace(tmp/'key', private); os.replace(tmp/'cert', cert)
    return cert, private


def proxy_headers(config=None):
    token = (config or load()).get('proxy_token', '')
    if not re.fullmatch('[a-f0-9]{64}', token):
        raise e.Problem('Interner Proxy-Schlüssel fehlt.')
    return (' RequestHeader set X-Server-Manager-HTTPS "on"\n'
            ' RequestHeader set X-Server-Manager-Proxy-Token "'+token+'"\n'
            ' RequestHeader set X-Server-Manager-Client-IP "expr=%{REMOTE_ADDR}"\n')


def ip_url(values):
    ip = values.get('ip_address', '')
    return 'https://' + ('[' + ip + ']' if ':' in ip else ip) + ':' + str(values.get('ip_port', 8443))


def render(values, config, cert, key):
    text = render_host(values, config, cert, key)
    if values.get('ip_address'):
        ip = values['ip_address']
        binding = ('[' + ip + ']' if ':' in ip else ip)
        text += render_host(dict(values, hostname=ip, port=values['ip_port']), config, cert, key, binding)
    return text


def render_host(values, config, cert, key, binding='*'):
    return (MARKER+'<VirtualHost '+binding+':'+str(values['port'])+'>\n ServerName '+values['hostname']+'\n SSLEngine on\n SSLProtocol -all +TLSv1.2 +TLSv1.3\n'
            ' SSLCertificateFile '+str(cert)+'\n SSLCertificateKeyFile '+str(key)+'\n LimitRequestBody 0\n ProxyRequests Off\n ProxyPreserveHost On\n'+proxy_headers(config)+
            ' ProxyPass / http://127.0.0.1:'+str(backend_port())+'/ connectiontimeout=5 timeout=300\n'
            ' ProxyPassReverse / http://127.0.0.1:'+str(backend_port())+'/\n'
            ' <Location />\n Require ip '+values['networks']+'\n </Location>\n</VirtualHost>\n')


def execute(p, folder):
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (CONFIG.parent/'manager-https.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return apply(p, folder)


def apply(p, folder):
    if p['action'] == 'manager_https_disable':
        raise e.Problem('HTTPS darf nicht deaktiviert werden; interner HTTP-Port ist kein Netzwerkzugang.')
    if p['action'] == 'manager_https_public':
        from . import reverse_proxy
        proxy = dict(p['proxy'], manager_https=True)
        result = reverse_proxy.execute(proxy, folder)
        state = load(); state['public_hostname'] = p['data']['domain']; e.atomic(CONFIG, state)
        return result
    path, link, port_file, port_link = files()
    state = load()
    before = {p: (p.read_bytes() if p.exists() else None) for p in (CONFIG, path, port_file)}
    linked = {p: os.readlink(p) if p.is_symlink() else None for p in (link, port_link)}
    folder.mkdir(parents=True, exist_ok=True)
    for i, (file, data) in enumerate(before.items()):
        if data is not None:
            backup = folder/('before-'+str(i)); backup.write_bytes(data); backup.chmod(0o600)
    try:
        if p['action'] == 'manager_https_disable':
            link.unlink(missing_ok=True); state['enabled'] = False
        else:
            values = p['data']; cert, key = certificates(values['hostname'], ip_address=values.get('ip_address', ''))
            state.update(values, enabled=True, proxy_token=state.get('proxy_token') or secrets.token_hex(32))
            e.run(['a2enmod', 'ssl', 'proxy', 'proxy_http', 'headers'])
            # Search active configuration including Debian's conditional Listen 443.
            port_link.unlink(missing_ok=True)
            listeners = []
            for source in editor.included_files():
                if source.resolve() == port_file.resolve(): continue
                listeners.extend(re.findall(r'^\s*Listen\s+(?:\[[^\]]+\]:|[^\s:]+:)?(\d+)', source.read_text(errors='replace'), re.M))
            listen = []
            if str(values['port']) not in listeners:
                listen.append('Listen ' + str(values['port']))
            if values.get('ip_address'):
                ip = values['ip_address']
                listen.append('Listen ' + ('[' + ip + ']' if ':' in ip else ip) + ':' + str(values['ip_port']))
            if listen:
                text_file(port_file, '\n'.join(listen)+'\n', 0o644)
                port_link.symlink_to('../conf-available/'+port_file.name)
            text_file(path, render(values, state, cert, key))
            if not link.is_symlink(): link.symlink_to('../sites-available/'+path.name)
        e.atomic(CONFIG, state)
        e.run(['apache2ctl', 'configtest'])
        if e.service('apache2.service') == 'active': e.run(['systemctl', 'reload', 'apache2.service'])
        else: e.run(['systemctl', 'start', 'apache2.service'])
    except Exception:
        for file, data in before.items():
            if data is None: file.unlink(missing_ok=True)
            else: text_file(file, data.decode())
        for file, target in linked.items():
            file.unlink(missing_ok=True)
            if target is not None: file.symlink_to(target)
        e.run(['apache2ctl', 'configtest'], check=False); e.run(['systemctl', 'reload', 'apache2.service'], check=False)
        raise
    publish_url(state)
    # A manually deployed development tree also needs the renewal units.
    source = Path(__file__).resolve().parents[2]/'packaging/debian'
    for name in ('server-manager-https-renew.service', 'server-manager-https-renew.timer'):
        if not (Path('/usr/lib/systemd/system')/name).exists() and not (Path('/etc/systemd/system')/name).exists():
            text_file(Path('/etc/systemd/system')/name, (source/name).read_text(), 0o644)
    e.run(['systemctl', 'daemon-reload'])
    timer = e.run(['systemctl', 'enable', '--now', 'server-manager-https-renew.timer'], check=False)
    return dict(message='Privater HTTPS-Zugang eingerichtet. Lokales DNS und Vertrauen des Stammzertifikats auf den Clients einrichten.' if state.get('enabled') else 'Privater HTTPS-Zugang deaktiviert.', renewal_timer=timer.returncode == 0,
                url='https://'+state.get('hostname', '')+(':'+str(state.get('port')) if state.get('port') != 443 else ''))


def renew():
    state = load()
    if not state.get('enabled'): return
    host = private_hostname(state['hostname']); cert = TLS/host/'cert.pem'
    if e.run(['openssl', 'x509', '-checkend', str(86400*30), '-noout', '-in', str(cert)], check=False).returncode:
        with (CONFIG.parent/'manager-https.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            certificates(host, renew=True, ip_address=state.get('ip_address', ''))
            try:
                e.run(['apache2ctl', 'configtest']); e.run(['systemctl', 'reload', 'apache2.service'])
            except Exception:
                for file in (cert, cert.with_name('key.pem')):
                    old = file.with_suffix(file.suffix+'.previous')
                    if old.exists(): shutil.copyfile(old, file)
                raise


def public_url(state=None):
    state = state if state is not None else load()
    return 'https://' + private_hostname(state.get('hostname', default_hostname())) + (':' + str(state.get('port',443)) if int(state.get('port',443)) != 443 else '')


def publish_url(state):
    if state.get('enabled'):
        text_file(Path('/usr/share/server-manager/desktop-url'), public_url(state)+'\n', 0o644)


def bootstrap_ip():
    # Route lookup does not send packets. Never pick a Docker/VM address at random.
    route=e.run(['ip','-j','route','get','192.0.2.1'],check=False)
    if route.returncode==0:
        for row in json.loads(route.stdout or '[]'):
            address=row.get('prefsrc') or row.get('src')
            if address:
                ip=ipaddress.ip_address(address)
                if ip.version==4 and not ip.is_loopback and not ip.is_unspecified:return str(ip)
    raise e.Problem('Keine eindeutige LAN-IPv4 erkannt. Netzwerk einrichten und HTTPS-Bootstrap erneut ausführen.')


def verify_https(state=None):
    state=state if state is not None else load()
    if not state.get('enabled'):raise e.Problem('HTTPS ist nicht aktiviert.')
    context=ssl.create_default_context(cafile=str(TLS/'root-ca.crt'))
    targets=[(state['hostname'],int(state['port']),'127.0.0.1')]
    if state.get('ip_address'):targets.append((state['ip_address'],int(state['ip_port']),state['ip_address']))
    for host,port,address in targets:
        class LocalHTTPS(http.client.HTTPSConnection):
            def connect(self):
                self.sock=context.wrap_socket(socket.create_connection((address,port),timeout=5),server_hostname=host)
        connection=LocalHTTPS(host,port,context=context)
        try:
            connection.request('GET','/login')
            response=connection.getresponse();body=response.read()
            if response.status!=200 or b'auth_csrf' not in body:raise e.Problem('HTTPS liefert nicht die Manager-Anmeldung.')
        finally:connection.close()


def bootstrap(https_port=443,ip_port=8443):
    state=load()
    if not state.get('enabled'):
        values=dict(state) if state else dict(port=https_port,ip_port=ip_port,ip_address=bootstrap_ip())
        folder=e.ROOT/'manager-https-bootstrap'
        execute(plan('manager_https_private',values),folder)
        state=load()
    last=None
    for attempt in range(10):
        try:verify_https(state);last=None;break
        except (OSError,ValueError,http.client.HTTPException) as exc:last=exc;time.sleep(.5)
    if last:raise e.Problem('HTTPS-Prüfung fehlgeschlagen; kein externer HTTP-Ersatzzugang. Apache/Port/Zertifikat prüfen: '+str(last))
    publish_url(state)
    print('Manager: '+public_url(state))
    if state.get('ip_address'):print('Ohne DNS über IP: '+ip_url(state))
    print('HTTP-Port '+str(backend_port())+' ist ausschließlich intern auf 127.0.0.1 erreichbar.')
    print('Privates Stammzertifikat: '+str(TLS/'root-ca.crt'))
    print(e.run(['openssl','x509','-in',str(TLS/'root-ca.crt'),'-noout','-fingerprint','-sha256']).stdout)
    print('Stammzertifikat auf Clients importieren; bestehende HTTP-Agenten auf HTTPS umstellen.')
