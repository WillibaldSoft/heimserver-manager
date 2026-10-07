#!/usr/bin/env python3
"""Shared port validation and durable service configuration; no shell evaluation."""
import argparse,errno,os,re,socket,subprocess,tempfile
from pathlib import Path
CONFIG=Path(os.environ.get('SERVER_MANAGER_CONFIG','/etc/server-manager'))
ENV=CONFIG/'server-manager.env'
DROPIN=Path('/etc/systemd/system/server-manager.service.d/port.conf')
JAIL=Path('/etc/fail2ban/jail.d/server-manager-login.local')
PUBLIC_PORT=Path('/usr/share/server-manager/desktop-port')
MARKER='# Managed by Server Manager: port'

def validate(value):
    if not re.fullmatch(r'[0-9]{1,5}',str(value)) or not 1<=int(value)<=65535:raise ValueError('Port muss zwischen 1 und 65535 liegen.')
    return int(value)

def configured_port(fallback=None):
    try:text=ENV.read_text()
    except FileNotFoundError:text=''
    values=re.findall(r'^\s*SERVER_MANAGER_PORT\s*=\s*["\']?(\d+)["\']?\s*$',text,re.M)
    return validate(values[-1] if values else fallback if fallback is not None else os.environ.get('SERVER_MANAGER_PORT','9877'))

def own_listener(port):
    try:
        pid=subprocess.run(['systemctl','show','server-manager.service','--property=MainPID','--value'],capture_output=True,text=True,timeout=10,check=True).stdout.strip()
        if not pid.isdigit() or int(pid)<=0:return False
        listeners=subprocess.run(['ss','-H','-ltnp','sport = :'+str(port)],capture_output=True,text=True,timeout=10,check=True).stdout.splitlines()
        return bool(listeners) and all(re.findall(r'pid=(\d+)',line) and set(re.findall(r'pid=(\d+)',line))=={pid} for line in listeners)
    except (OSError,subprocess.SubprocessError):return False

def check(port):
    port=validate(port)
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('0.0.0.0',port))
    except OSError:
        if not own_listener(port):raise ValueError('Port '+str(port)+' ist bereits belegt. Bitte einen anderen Port wählen.') from None
    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('::',port))
        except OSError as exc:
            if exc.errno not in (errno.EAFNOSUPPORT,errno.EADDRNOTAVAIL,errno.ENOPROTOOPT) and not own_listener(port):raise ValueError('Port '+str(port)+' ist für IPv6 bereits belegt oder nicht nutzbar.') from None
    return port

def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.port-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:os.fchmod(stream.fileno(),0o600);stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def apply(port):
    port=check(port)
    if os.geteuid()!=0:raise ValueError('Portänderung benötigt root.')
    if any(p.is_symlink() for p in (ENV,DROPIN,JAIL)):raise ValueError('Portkonfiguration darf kein symbolischer Link sein.')
    old={p:p.read_text() if p.exists() else None for p in (ENV,DROPIN,JAIL)}
    if old[DROPIN] is not None and not old[DROPIN].startswith(MARKER):raise ValueError('Vorhandene fremde Port-Konfiguration bitte manuell prüfen.')
    if old[JAIL] is not None and not old[JAIL].startswith('# Managed by Server Manager: web-security'):raise ValueError('Vorhandene Login-Fail2ban-Regel muss vor der Portänderung manuell geprüft werden.')
    text=old[ENV] or ''
    text=re.sub(r'^\s*SERVER_MANAGER_PORT\s*=.*(?:\n|$)','',text,flags=re.M).rstrip()+'\nSERVER_MANAGER_PORT='+str(port)+'\n'
    changed=[]
    try:
        atomic(ENV,text);changed.append(ENV)
        atomic(DROPIN,MARKER+'\n[Service]\nEnvironmentFile=-'+str(ENV)+'\n');changed.append(DROPIN)
        if old[JAIL] is not None:
            jail,count=re.subn(r'^port\s*=.*$', 'port = '+str(port),old[JAIL],flags=re.M)
            if count!=1:raise ValueError('Port der Login-Fail2ban-Regel nicht eindeutig.')
            atomic(JAIL,jail);changed.append(JAIL)
            subprocess.run(['fail2ban-client','-t'],capture_output=True,text=True,check=True,timeout=30)
            subprocess.run(['systemctl','reload','fail2ban.service'],capture_output=True,text=True,check=True,timeout=30)
    except Exception:
        for p in reversed(changed):
            if old[p] is None:p.unlink(missing_ok=True)
            else:atomic(p,old[p])
        if JAIL in changed:subprocess.run(['systemctl','reload','fail2ban.service'],capture_output=True,timeout=30)
        raise
    if PUBLIC_PORT.is_file() and not PUBLIC_PORT.is_symlink():
        atomic(PUBLIC_PORT,str(port)+'\n');PUBLIC_PORT.chmod(0o644)
    return port

def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--show',action='store_true');group.add_argument('--check');group.add_argument('--apply')
    args=parser.parse_args()
    try:print(configured_port() if args.show else apply(args.apply) if args.apply is not None else check(args.check));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:print(str(exc));return 1
if __name__=='__main__':raise SystemExit(main())
