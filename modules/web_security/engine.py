"""Bounded argv-only checks and reviewed actions; private keys are never read."""
from pathlib import Path
import datetime
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import time
from . import installer
from server_settings import CONFIG_DIR,STATE_DIR,atomic

ROOT=STATE_DIR/'web-security'
CONFIG=CONFIG_DIR/'web_security.json'
APACHE=Path('/etc/apache2')
LETSENCRYPT=Path('/etc/letsencrypt')
F2B=Path('/etc/fail2ban')
MARKER='# Managed by Server Manager: web-security'
SERVICE_CONFIG_ROOTS=[Path('/etc/nginx'),Path('/etc/postfix'),Path('/etc/dovecot'),Path('/etc/haproxy'),Path('/etc/systemd/system')]
TERMINAL={'completed','failed','interrupted'}
Problem=installer.Problem


def run(args,timeout=30,check=True):return installer.command(args,timeout,check)
def service(name):return run(['systemctl','is-active',name],check=False).stdout.strip() or 'unknown'
def available(name):return shutil.which(name) is not None

def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',str(value)) or value in ('.','..'):raise Problem('Ungültiger Name.')
    return value

def hostname(value):
    try:value=str(value).strip().rstrip('.').encode('idna').decode().lower()
    except UnicodeError:raise Problem('Ungültiger Hostname.') from None
    if len(value)>253 or '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):raise Problem('Vollständigen Domainnamen ohne Wildcard angeben.')
    try:ipaddress.ip_address(value)
    except ValueError:return value
    raise Problem('Bitte einen Domainnamen statt einer IP-Adresse verwenden.')

def load():
    try:return json.loads(CONFIG.read_text())
    except FileNotFoundError:return {'targets':[]}

def targets(value):
    if not isinstance(value,list) or len(value)>30:raise Problem('Höchstens 30 HTTPS-Ziele konfigurieren.')
    out=[]
    for row in value:
        host=hostname(row['host']);port=int(row.get('port',443));connect=str(row.get('connect','')).strip()
        if not 1<=port<=65535:raise Problem('Ungültiger HTTPS-Port.')
        if connect:connect=str(ipaddress.ip_address(connect))
        cert=str(row.get('cert_name','')).strip()
        if cert:identifier(cert)
        out.append(dict(host=host,port=port,connect=connect,cert_name=cert))
    return out

def save_targets(rows):atomic(CONFIG,{'targets':targets(rows)})

def cert_info(path):
    text=run(['openssl','x509','-in',str(path),'-noout','-subject','-issuer','-dates','-ext','subjectAltName','-fingerprint','-sha256']).stdout
    def value(label):
        match=re.search(r'^'+re.escape(label)+r'\s*=\s*(.+)$',text,re.M|re.I)
        return match[1].strip() if match else ''
    end=ssl.cert_time_to_seconds(value('notAfter'));start=ssl.cert_time_to_seconds(value('notBefore'))
    days=int((end-time.time())//86400)
    return dict(subject=value('subject'),issuer=value('issuer'),expires=datetime.datetime.fromtimestamp(end,datetime.timezone.utc).isoformat(),
                days=days,valid_from=datetime.datetime.fromtimestamp(start,datetime.timezone.utc).isoformat(),
                domains=re.findall(r'DNS:([^,\s]+)',text),fingerprint=value('sha256 Fingerprint').replace(':','').lower(),
                state='expired' if end<=time.time() else 'not_yet_valid' if start>time.time() else 'critical' if days<=7 else 'warning' if days<=30 else 'ok')

def certificates():
    rows=[]
    if not available('openssl'):return []
    for folder in sorted((LETSENCRYPT/'live').glob('*')):
        if not folder.is_dir() or not (folder/'cert.pem').is_file():continue
        try:
            info=cert_info(folder/'cert.pem')
            renewal=LETSENCRYPT/'renewal'/(folder.name+'.conf')
            auth='unbekannt'
            if renewal.exists():
                m=re.search(r'^authenticator\s*=\s*(\S+)',renewal.read_text(),re.M)
                if m:auth=m[1]
            rows.append(dict(name=folder.name,authenticator=auth,**info))
        except (OSError,ValueError,subprocess.SubprocessError) as exc:rows.append(dict(name=folder.name,state='unknown',error=str(exc)))
    return rows

def apache_status():
    if not available('apache2ctl'):return {'installed':False,'state':service('apache2.service'),'sites':[]}
    config=run(['apache2ctl','configtest'],check=False);vhosts=run(['apache2ctl','-S'],check=False)
    sites=[]
    for file in sorted((APACHE/'sites-enabled').glob('*.conf')):
        # Return only selected directives, never whole configs containing credentials.
        if not file.is_file():continue
        row={'file':file.name,'names':[],'roots':[],'certificates':[],'listeners':[]}
        for line in file.read_text(errors='replace').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            m=re.match(r'(ServerName|ServerAlias|DocumentRoot|SSLCertificateFile)\s+(.+)',line,re.I)
            if m:
                key={'servername':'names','serveralias':'names','documentroot':'roots','sslcertificatefile':'certificates'}[m[1].lower()]
                if key=='names':row[key].extend(m[2].split())
                else:row[key].append(m[2].strip('"'))
            m=re.match(r'<VirtualHost\s+([^>]+)>',line,re.I)
            if m:row['listeners'].append(m[1])
        sites.append(row)
    return dict(installed=True,state=service('apache2.service'),config_ok=config.returncode==0,
                config_message=(config.stdout+config.stderr)[-3000:],vhosts=(vhosts.stdout+vhosts.stderr)[-20000:],sites=sites)

def f2b_status():
    if not available('fail2ban-client'):return dict(installed=False,state=service('fail2ban.service'),jails=[])
    r=run(['fail2ban-client','status'],check=False)
    if r.returncode:return dict(installed=True,state=service('fail2ban.service'),error=(r.stderr or r.stdout)[-1500:],jails=[])
    m=re.search(r'Jail list:\s*(.*)',r.stdout);names=[v.strip() for v in (m[1].split(',') if m else []) if v.strip()]
    rows=[]
    for name in names[:100]:
        try:
            identifier(name);r=run(['fail2ban-client','status',name],check=False)
            if r.returncode:rows.append(dict(name=name,error=(r.stderr or r.stdout)[-1000:]));continue
            def count(label):
                match=re.search(re.escape(label)+r':\s*(\d+)',r.stdout)
                return int(match[1]) if match else None
            m=re.search(r'Banned IP list:\s*(.*)',r.stdout);ips=[]
            for value in (m[1].split() if m else []):
                try:ips.append(str(ipaddress.ip_address(value)))
                except ValueError:pass
            rows.append(dict(name=name,failed=count('Currently failed'),total_failed=count('Total failed'),banned=count('Currently banned'),total_banned=count('Total banned'),ips=ips))
        except (ValueError,OSError,subprocess.SubprocessError) as exc:rows.append(dict(name=name,error=str(exc)))
    return dict(installed=True,state=service('fail2ban.service'),jails=rows)

def renewal_status():
    r=run(['systemctl','show','certbot.timer','-p','ActiveState','-p','NextElapseUSecRealtime','--no-pager'],check=False)
    timer=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    r=run(['systemctl','show','certbot.service','-p','Result','-p','ExecMainStatus','-p','ExecMainExitTimestamp','--no-pager'],check=False)
    last=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    return dict(installed=available('certbot'),timer=timer,last=last)

def tls_probe(row):
    row=targets([row])[0];host=row['host'];port=row['port'];address=row['connect'] or host
    result=dict(**row,checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),verified=False)
    der=None
    try:
        with socket.create_connection((address,port),timeout=6) as raw:
            with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as sock:
                der=sock.getpeercert(binary_form=True);result['verified']=True
    except (OSError,ssl.SSLError) as exc:
        result['error']=str(exc)
        # Diagnostic only: an invalid certificate must never be reported as valid.
        try:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
            with socket.create_connection((address,port),timeout=6) as raw:
                with context.wrap_socket(raw,server_hostname=host) as sock:der=sock.getpeercert(binary_form=True)
        except (OSError,ssl.SSLError):pass
    if der:
        result['fingerprint']=hashlib.sha256(der).hexdigest()
        if row['cert_name']:
            file=LETSENCRYPT/'live'/identifier(row['cert_name'])/'cert.pem'
            if file.is_file():result['matches_local']=cert_info(file)['fingerprint']==result['fingerprint']
            else:result['matches_local']=None;result['local_error']='Lokales Zertifikat nicht gefunden.'
    return result

def local_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def certificate_usage(name,domains,inactive=None):
    """Check loaded Apache configuration; report inactive copies separately."""
    prefixes=[str(LETSENCRYPT/part/name)+'/' for part in ('live','archive')]
    references=[]
    from .apache_editor import included_files
    included=included_files() if APACHE.exists() else set()
    roots=[APACHE,*SERVICE_CONFIG_ROOTS,LETSENCRYPT/'renewal-hooks']
    for root in roots:
        if not root.exists():continue
        for file in sorted(root.rglob('*')):
            if not file.is_file():continue
            if file.suffix in ('.pem','.key','.crt','.p12','.pfx'):continue
            if file.stat().st_size>2*1024*1024:raise Problem('Konfigurationsdatei zu groß für Verwendungsprüfung: '+str(file))
            text=file.read_text(errors='replace')
            lines=[line.strip() for line in text.splitlines() if not line.lstrip().startswith(('#',';'))]
            text='\n'.join(lines)
            if any(prefix in text for prefix in prefixes) or (root==LETSENCRYPT/'renewal-hooks' and name in text):
                if root==APACHE:
                    if file.resolve() not in included:
                        if inactive is not None:inactive.append(str(file.resolve()))
                        continue
                    references.append(str(file.resolve()))
                else:references.append(str(file))
    for target in targets(load().get('targets',[])):
        if target['cert_name']==name or target['host'] in domains:
            references.append('HTTPS-Ziel: '+target['host']+':'+str(target['port']))
    return sorted(set(references))

def deletion_details(name):
    name=identifier(name)
    renewal=LETSENCRYPT/'renewal'/(name+'.conf');cert=LETSENCRYPT/'live'/name/'cert.pem'
    if not renewal.is_file() or not cert.is_file():raise Problem('Lokales Certbot-Zertifikat nicht vollständig gefunden.')
    info=cert_info(cert)
    inactive=[];references=certificate_usage(name,info['domains'],inactive)
    return dict(name=name,domains=info['domains'],references=references,inactive=sorted(set(inactive)),
                snapshot={'renewal':local_hash(renewal),'cert':local_hash(cert)})

def plan(action,data=None):
    data=dict(data or {});steps=[];snapshot={}
    if action.startswith("manager_https_"):
        from . import manager_https
        return manager_https.plan(action,data)
    if action=='nextcloud_https':
        from modules.app_manager import nextcloud_https
        return nextcloud_https.plan(data)
    if action=='setup_reverse_proxy':
        from . import reverse_proxy
        return reverse_proxy.plan(data)
    if action=='nextcloud_redirect':
        from . import redirects
        return redirects.plan(data)
    if action=='add_nextcloud_redirect':
        from . import redirects
        return redirects.add_plan(data)
    if action=='edit_apache_site':
        from . import apache_editor
        return apache_editor.plan(action,data)
    if action.startswith('install_'):
        component=action.removeprefix('install_');p=installer.plan(component)
        if p['blocked']:raise Problem('; '.join(p['blocked']))
        return dict(action=action,data={'component':component},steps=p['steps'],snapshot=p)
    if action in ('apache_check','apache_reload'):
        if not available('apache2ctl'):raise Problem('Apache ist noch nicht installiert.')
        steps=['Apache-Konfiguration prüfen']+(['Apache ohne vollständigen Neustart neu laden'] if action=='apache_reload' else [])
        snapshot={str(p):local_hash(p) for p in (APACHE/'sites-enabled').glob('*.conf') if p.is_file()}
        data={}
    elif action in ('renew_test','renew'):
        if not available('certbot'):raise Problem('Certbot ist noch nicht installiert.')
        name=identifier(data.get('cert_name',''));file=LETSENCRYPT/'renewal'/(name+'.conf')
        if not file.is_file():raise Problem('Erneuerungskonfiguration nicht gefunden.')
        data={'cert_name':name};snapshot={'renewal':local_hash(file),'cert':local_hash(LETSENCRYPT/'live'/name/'cert.pem')}
        steps=['Zertifikat: '+name, 'Erneuerung gegen Test-CA prüfen; vorhandene Vor-/Nach-Hooks können laufen. Kein produktives Zertifikat wird ersetzt.' if action=='renew_test' else 'Fällige Erneuerung durchführen; gespeicherte Bereitstellungs-Hooks verwenden. Keine erzwungene Neuausstellung.']
    elif action=='delete_cert':
        if not available('certbot'):raise Problem('Certbot ist noch nicht installiert.')
        name=identifier(data.get('cert_name',''))
        details=deletion_details(name)
        if details['references']:raise Problem('Zertifikat wird noch referenziert. Zuerst Verwendungen umstellen oder entfernen: '+ '; '.join(details['references']))
        if data.get('confirm_name')!=name:raise Problem('Zum Löschen den vollständigen Zertifikatsnamen bestätigen.')
        data={'cert_name':name,'confirm_name':name};snapshot=details['snapshot']
        steps=['Zertifikat löschen: '+name,'Enthaltene Domains: '+', '.join(details['domains']),
               'Certbot entfernt dieses gesamte Zertifikat einschließlich privatem Schlüssel, lokalen Versionen und automatischer Erneuerung.',
               'Keine Domain, DNS-Einträge oder Website-Dateien werden gelöscht. Kopien auf anderen Servern bleiben bestehen. Das Zertifikat wird nicht widerrufen.',
               'Bekannte lokale Konfigurationen und gespeicherte HTTPS-Ziele sind ohne Verweis. Weitere externe Verwendungen müssen zuvor umgestellt sein.']
    elif action=='issue_cert':
        if not available('certbot') or not available('apache2ctl'):raise Problem('Apache und den Certbot-Installer zuerst installieren.')
        raw_domains=data.get('domains','')
        if isinstance(raw_domains,list):raw_domains=' '.join(raw_domains)
        domains=list(dict.fromkeys(hostname(v) for v in str(raw_domains).replace(',',' ').split()))
        if not domains or len(domains)>10:raise Problem('1–10 Domainnamen angeben.')
        email=str(data.get('email','')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email):raise Problem('Gültige E-Mail-Adresse angeben.')
        if data.get('terms')!='1':raise Problem('Bitte den Bedingungen von Let’s Encrypt zustimmen.')
        name=domains[0]
        if (LETSENCRYPT/'live'/name).exists() or (LETSENCRYPT/'renewal'/(name+'.conf')).exists():raise Problem('Zertifikat existiert bereits. Die Erneuerungsfunktion verwenden.')
        status=apache_status()
        if not status.get('config_ok'):raise Problem('Apache-Konfiguration zuerst korrigieren.')
        configured={name for row in status['sites'] for name in row['names']}
        if any(name not in configured for name in domains):raise Problem('Für jeden Domainnamen muss zuerst eine passende Apache-Website eingerichtet sein.')
        data=dict(domains=domains,email=email,terms='1',cert_name=name)
        steps=['Apache-Konfiguration sichern','Let’s-Encrypt-Zertifikat für '+', '.join(domains)+' anfordern','Certbot darf passende Apache-Websites für HTTPS konfigurieren. Öffentliches DNS und Port 80 müssen auf diesen Server zeigen.','Apache-Konfiguration prüfen und neu laden']
        snapshot={str(p):local_hash(p) for p in (APACHE/'sites-enabled').glob('*.conf') if p.is_file()}
    elif action=='create_site':
        domain=hostname(data.get('domain',''));root=Path(str(data.get('root','')).strip())
        if not available('apache2ctl'):raise Problem('Apache zuerst installieren.')
        if not root.is_absolute() or '..' in root.parts or not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(root)) or not any(root.is_relative_to(Path(p)) and root!=Path(p) for p in ('/var/www','/srv','/opt')):raise Problem('Webordner unter /var/www, /srv oder /opt ohne Leerzeichen angeben.')
        if any(p.is_symlink() for p in (root,*root.parents)):raise Problem('Webordner darf keine symbolischen Links enthalten.')
        if root.exists() and (not root.is_dir() or any(root.iterdir())):raise Problem('Für neue Websites einen leeren oder neuen Ordner verwenden; vorhandene Apps über ihre Apache-Konfiguration anbinden.')
        file=APACHE/'sites-available'/('server-manager-'+domain+'.conf')
        if file.exists() or file.is_symlink():raise Problem('Website-Konfiguration existiert bereits.')
        status=apache_status()
        if any(domain in row['names'] for row in status['sites']):raise Problem('Domain ist bereits in Apache eingerichtet.')
        data={'domain':domain,'root':str(root)};snapshot={}
        steps=['Leeren Webordner anlegen: '+str(root),'Eigene Apache-Website für '+domain+' auf Port 80 hinzufügen','Konfiguration prüfen und Apache neu laden. Vorhandene Websites bleiben erhalten.']
    elif action=='enable_login_jail':
        if not available('fail2ban-client'):raise Problem('Fail2ban zuerst installieren.')
        port=int(os.environ.get('SERVER_MANAGER_PORT','9877'))
        if not 1<=port<=65535:raise Problem('Ungültiger Server-Manager-Port.')
        ignore=['127.0.0.0/8','::1/128']
        for value in str(data.get('ignore','')).replace(',',' ').split():ignore.append(str(ipaddress.ip_network(value,strict=False)))
        if len(ignore)>32:raise Problem('Höchstens 30 zusätzliche Ausnahmen.')
        ignore=list(dict.fromkeys(ignore))
        data={'ignore':ignore,'port':port}
        for file in (F2B/'filter.d/server-manager-login.conf',F2B/'jail.d/server-manager-login.local'):
            if file.exists() and not file.read_text().startswith(MARKER):raise Problem('Vorhandene fremde Regel wird nicht überschrieben: '+file.name)
            snapshot[str(file)]=local_hash(file)
        if not (F2B/'action.d/nftables-multiport.conf').is_file():raise Problem('nftables-multiport-Aktion fehlt. Fail2ban-Installer ausführen.')
        steps=['Eigene Regel server-manager-login einrichten','Systemjournal des Server Managers auswerten; keine Benutzernamen oder Passwörter protokollieren','Nach 5 Fehlversuchen innerhalb von 10 Minuten die IP für 15 Minuten auf TCP-Port '+str(port)+' sperren','Ausgenommen: '+', '.join(ignore),'Fail2ban-Konfiguration prüfen und neu laden. Bestehende Jails bleiben erhalten.','Gilt für direkten Zugriff. Bei Reverseproxy wird dessen Verbindungs-IP erfasst; keine ungeprüften Forwarded-Header verwenden.']
    elif action=='unban':
        jail=identifier(data.get('jail',''));ip=str(ipaddress.ip_address(data.get('ip','')))
        status=f2b_status();row=next((r for r in status['jails'] if r['name']==jail),None)
        if not row or ip not in row.get('ips',[]):raise Problem('Diese IP ist in der ausgewählten Regel nicht mehr gesperrt.')
        data={'jail':jail,'ip':ip};steps=['Nur '+ip+' in der Regel '+jail+' entsperren.'];snapshot={}
    elif action=='tls_check':
        data={'targets':targets(load().get('targets',[]))}
        if not data['targets']:raise Problem('Zuerst HTTPS-Ziele konfigurieren.')
        steps=['TLS-Verbindung, Hostname und Vertrauenskette der gespeicherten Ziele prüfen','Ausgeliefertes Zertifikat mit ausgewähltem lokalen Zertifikat vergleichen'];snapshot={}
    else:raise Problem('Unbekannte Aktion.')
    return dict(action=action,data=data,steps=steps,snapshot=snapshot)

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def backup_tree(path,folder):
    with tarfile.open(folder/(path.name+'-config.tar.gz'),'w:gz',dereference=False) as archive:archive.add(path,arcname=path.name)

def execute(p,folder):
    action=p['action'];data=p['data']
    if action=='enable_login_jail':
        # The saved plan contains a validated list; the public planner expects text.
        input_data=dict(data,ignore=' '.join(data['ignore']))
    else:input_data=data
    current=plan(action,input_data)
    if digest(current)!=digest(p):raise Problem('Systemstand seit Vorschau verändert. Neue Vorschau erforderlich.')
    if action.startswith('manager_https_'):
        from . import manager_https
        return manager_https.execute(p,folder)
    if action=='nextcloud_https':
        from modules.app_manager import nextcloud_https
        return nextcloud_https.execute(p,folder)
    if action=='setup_reverse_proxy':
        from . import reverse_proxy
        return reverse_proxy.execute(p,folder)
    if action=='add_nextcloud_redirect':
        from . import redirects
        return redirects.add_execute(p,folder)
    if action=='edit_apache_site':
        from . import apache_editor
        return apache_editor.execute(p,folder)
    if action.startswith('install_'):return installer.install(data['component'],expected=p['snapshot'])
    if action in ('apache_check','apache_reload'):
        r=run(['apache2ctl','configtest'])
        if action=='apache_reload':run(['systemctl','reload','apache2.service'])
        return {'message':r.stdout+r.stderr}
    if action in ('renew_test','renew'):
        args=['certbot','renew','--non-interactive','--cert-name',data['cert_name']]
        if action=='renew_test':args.extend(['--dry-run','--no-random-sleep-on-renew'])
        r=run(args,timeout=1500)
        return {'message':(r.stdout+r.stderr)[-16000:]}
    if action=='delete_cert':
        result=run(['certbot','delete','--non-interactive','--cert-name',data['cert_name']],timeout=120)
        if (LETSENCRYPT/'renewal'/(data['cert_name']+'.conf')).exists() or (LETSENCRYPT/'live'/data['cert_name']).exists():raise Problem('Certbot meldete keinen vollständigen Abschluss. Zustand prüfen.')
        return {'message':'Zertifikat '+data['cert_name']+' und automatische Erneuerung entfernt. '+(result.stdout+result.stderr)[-8000:]}
    if action=='issue_cert':
        backup_tree(APACHE,folder)
        args=['certbot','--apache','--non-interactive','--agree-tos','--email',data['email'],'--cert-name',data['cert_name']]
        for domain in data['domains']:args+=['-d',domain]
        r=run(args,timeout=1500);run(['apache2ctl','configtest']);run(['systemctl','reload','apache2.service'])
        return {'message':(r.stdout+r.stderr)[-16000:]}
    if action=='create_site':
        domain=data['domain'];root=Path(data['root']);file=APACHE/'sites-available'/('server-manager-'+domain+'.conf')
        previous_umask=os.umask(0o022)
        try:root.mkdir(parents=True,exist_ok=True,mode=0o755)
        finally:os.umask(previous_umask)
        text=MARKER+'\n<VirtualHost *:80>\n ServerName '+domain+'\n DocumentRoot "'+str(root)+'"\n <Directory "'+str(root)+'">\n  Require all granted\n  Options -Indexes\n  AllowOverride None\n </Directory>\n</VirtualHost>\n'
        file.write_text(text)
        try:run(['a2ensite',file.name]);run(['apache2ctl','configtest']);run(['systemctl','reload','apache2.service'])
        except Exception:
            run(['a2dissite',file.name],check=False);file.unlink(missing_ok=True)
            raise
        return {'message':'HTTP-Website eingerichtet. Inhalte in '+str(root)+' ablegen; danach Zertifikat anfordern.'}
    if action=='enable_login_jail':
        files={F2B/'filter.d/server-manager-login.conf':MARKER+'\n[Definition]\nfailregex = ^(?:.*\\s)?SERVER_MANAGER_AUTH_FAILURE ip=<HOST>\\s*$\nignoreregex =\njournalmatch = _SYSTEMD_UNIT=server-manager.service\n',
               F2B/'jail.d/server-manager-login.local':MARKER+'\n[server-manager-login]\nenabled = true\nfilter = server-manager-login\nbackend = systemd\nport = '+str(data['port'])+'\nprotocol = tcp\nbanaction = nftables-multiport\nmaxretry = 5\nfindtime = 600\nbantime = 900\nignoreip = '+' '.join(data['ignore'])+'\n'}
        old={file:file.read_bytes() if file.exists() else None for file in files}
        backup_tree(F2B,folder)
        try:
            for file,text in files.items():file.write_text(text)
            run(['fail2ban-client','-t']);run(['systemctl','reload','fail2ban.service'])
            run(['fail2ban-client','status','server-manager-login'])
        except Exception:
            for file,content in old.items():
                if content is None:file.unlink(missing_ok=True)
                else:file.write_bytes(content)
            run(['systemctl','reload','fail2ban.service'],check=False)
            raise
        return {'message':'Server-Manager-Login wird durch Fail2ban überwacht.'}
    if action=='unban':return {'message':run(['fail2ban-client','set',data['jail'],'unbanip',data['ip']]).stdout}
    if action=='tls_check':
        rows=[tls_probe(row) for row in data['targets']];atomic(ROOT/'tls-status.json',rows)
        return {'targets':rows}
    raise Problem('Unbekannte Aktion.')
