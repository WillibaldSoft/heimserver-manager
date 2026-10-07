#!/usr/bin/python3
"""Narrow privileged helper: one verified CA and one optional marked hosts entry."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import argparse,hashlib,ipaddress,json,os,re,subprocess,tempfile
from pathlib import Path

def validate(pem,fingerprint,host,ip):
    if not re.fullmatch(r'\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*',pem):raise ValueError(tr('Genau ein öffentliches PEM-Zertifikat erforderlich.'))
    if len(pem)>32768 or not re.fullmatch('[a-fA-F0-9]{64}',fingerprint):raise ValueError(tr('Ungültiges Zertifikatprofil.'))
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*',host) or len(host)>253 or host.isdecimal():raise ValueError(tr('Ungültiger Hostname.'))
    try:ipaddress.ip_address(host)
    except ValueError:pass
    else:raise ValueError(tr('Hostname statt IP-Adresse erforderlich.'))
    if ip:ipaddress.ip_address(ip)
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'ca.crt';p.write_text(pem)
        der=subprocess.check_output(['/usr/bin/openssl','x509','-in',str(p),'-outform','DER'],stderr=subprocess.DEVNULL)
        if hashlib.sha256(der).hexdigest()!=fingerprint.lower():raise ValueError(tr('Zertifikat-Fingerabdruck stimmt nicht.'))
        info=subprocess.check_output(['/usr/bin/openssl','x509','-in',str(p),'-noout','-ext','basicConstraints'],text=True)
        if 'CA:TRUE' not in info:raise ValueError(tr('Kein Stammzertifikat.'))
        subprocess.run(['/usr/bin/openssl','verify','-check_ss_sig','-CAfile',str(p),str(p)],check=True,capture_output=True)
    return fingerprint.lower()

def matching_hosts_entry(lines,host,ip,marker):
    found=False
    for line in lines:
        if line.endswith(marker):continue
        words=line.split('#',1)[0].split()
        if host.lower().rstrip('.') not in [w.lower().rstrip('.') for w in words[1:]]:continue
        try:matches=ipaddress.ip_address(words[0])==ipaddress.ip_address(ip)
        except ValueError:matches=False
        if not matches:raise ValueError(tr('Hostname steht in hosts mit abweichender IP; vorhandenen Eintrag zuerst prüfen.'))
        found=True
    return found


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','remove']);p.add_argument('profile');a=p.parse_args()
    if os.geteuid()!=0:raise ValueError(tr('Administratorrechte erforderlich.'))
    path=Path(a.profile)
    if path.stat().st_size>65536:raise ValueError(tr('Profil zu groß.'))
    cfg=json.loads(path.read_text());fp=validate(cfg['ca_pem'],cfg['sha256'],cfg['hostname'],cfg.get('ip',''))
    cert=Path('/usr/local/share/ca-certificates')/('heimserver-manager-'+fp+'.crt')
    state_dir=Path('/var/lib/heimserver-manager-client');state_dir.mkdir(mode=0o700,exist_ok=True)
    state_file=state_dir/(fp+'.json');state=json.loads(state_file.read_text()) if state_file.exists() else {'added':False,'hosts':[]}
    marker='# Heimserver-Manager '+fp+' '+cfg['hostname']
    hosts=Path('/etc/hosts');text=hosts.read_text();lines=text.splitlines()
    if a.action=='install':
        if cert.is_symlink():raise ValueError(tr('Zertifikatpfad ist ein Link.'))
        if cert.exists() and cert.read_text()!=cfg['ca_pem']:raise ValueError(tr('Vorhandene Zertifikatdatei weicht ab.'))
        existing = bool(cfg.get('ip')) and matching_hosts_entry(lines,cfg['hostname'],cfg['ip'],marker)
        if not cert.exists():state['added']=True
        cert.write_text(cfg['ca_pem']);cert.chmod(0o644)
        state['hosts']=list(set(state['hosts'])|{cfg['hostname']})
        lines=[line for line in lines if not line.endswith(marker)]
        if cfg.get('ip') and not existing:lines.append(cfg['ip']+' '+cfg['hostname']+' '+marker)
    else:
        state['hosts']=[h for h in state['hosts'] if h!=cfg['hostname']]
        if cert.exists() and state['added'] and not state['hosts']:
            if cert.is_symlink() or cert.read_text()!=cfg['ca_pem']:raise ValueError(tr('Zertifikat wurde extern geändert; nicht entfernt.'))
            cert.unlink()
        lines=[line for line in lines if not line.endswith(marker)]
    state_file.write_text(json.dumps(state));state_file.chmod(0o600)
    subprocess.run(['/usr/sbin/update-ca-certificates'],check=True)
    content='\n'.join(lines)+'\n'
    if content!=text:
        # Keep unrelated entries and a root-only before-change backup.
        backup=Path('/etc/hosts.heimserver-manager.before');backup.write_text(text);backup.chmod(0o600)
        with hosts.open('w') as f:f.write(content);f.flush();os.fsync(f.fileno())
    print(tr('Zertifikat und optionaler Namenseintrag aktualisiert.'))
if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit(str(exc))
