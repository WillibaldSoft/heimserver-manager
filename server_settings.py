"""Validated host configuration. A pending revision is activated by core startup only."""
from pathlib import Path
import copy
import hashlib
import ipaddress
import json
import os
import pwd
import re
import tempfile
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get('SERVER_MANAGER_CONFIG', '/etc/server-manager'))
STATE_DIR = Path(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'))
CONFIG = CONFIG_DIR / 'server.json'
PENDING = CONFIG_DIR / 'server.pending.json'
# Neutral defaults. Existing hosts retain explicit settings in server.json.
FIELDS = {
 'download_root': ('Downloads', 'Hauptordner für Datei-Downloads', 'path', '/srv/server-manager/downloads'),
 'fotolabor_root': ('Fotolabor', 'Bildbestand', 'path', '/srv/fotolabor'),
 'vm_root': ('KVM', 'Neue VM-Datenträger', 'path', '/srv/vm'),
 'rescuezilla_backup_root': ('KVM', 'Rescuezilla: Quellordner der Sicherungen', 'path', '/srv/backups/rescuezilla'),
 'rescuezilla_iso': ('KVM', 'Rescuezilla: Start-ISO (vollständiger Dateipfad, optional)', 'iso_optional', ''),
 'iso_roots': ('KVM', 'ISO-Ordner (eine Zeile je Ordner)', 'paths', ['/srv/iso']),
 'media_roots': ('KVM', 'Erlaubte Disk-Importordner', 'paths', ['/srv/vm','/srv/iso']),
 'kvm_ssh_host': ('KVM', 'SSH-Host für virt-viewer', 'host', '127.0.0.1'),
 'kvm_ssh_user': ('KVM', 'SSH-Benutzer für virt-viewer', 'user', 'admin'),
 'system_backup_root': ('Sicherungen', 'Zentrale Server- und Client-Sicherungen', 'path', '/srv/backups'),
 'backup_root': ('Sicherungen', 'App-Sicherungen', 'path', '/srv/backups/apps'),
 'restore_log_root': ('Sicherungen', 'Restore-Protokolle', 'path', '/srv/backups/apps/restore_runs'),
 'update_log_root': ('Sicherungen', 'Update-Protokolle', 'path', '/srv/backups/apps/update_runs'),
 'share_roots': ('Freigaben', 'Datenbereiche im Ordnerbrowser', 'paths', ['/srv','/mnt','/media']),
 'lan_network': ('Netzwerk', 'Lokales IPv4-Netz für Clients', 'network', '192.168.1.0/24'),
 'server_wol_mac': ('Netzwerk', 'Server-MAC für Wake-on-LAN (leer = LAN-/Bridge-Schnittstelle automatisch)', 'mac_optional', ''),
 'recover_url': ('Netzwerk', 'Recovery-Adresse (optional)', 'url_optional', ''),
 'custom_apps_root': ('Apps · Installation', 'Neue eigene Container-Apps', 'app_path', '/opt/servermgr-apps'),
 'open_webui_root': ('Apps · Installation', 'Neue Open-WebUI-Installation', 'app_path', '/opt/open-webui'),
 'nextcloud_container_root': ('Apps · Installation', 'Neue Nextcloud-Containerinstallation', 'app_path', '/opt/servermgr-nextcloud'),
 'immich_root': ('Apps · Immich', 'Compose-Ordner', 'app_path', '/opt/immich'),
 'paperless_root': ('Apps · Paperless', 'Compose-Ordner', 'app_path', '/opt/paperless-ngx'),
 'paperless_data': ('Apps · Paperless', 'Daten', 'app_path', '/srv/paperless/data'),
 'paperless_media': ('Apps · Paperless', 'Dokumente', 'app_path', '/srv/paperless/media'),
 'paperless_export': ('Apps · Paperless', 'Export', 'app_path', '/srv/paperless/export'),
 'paperless_consume': ('Apps · Paperless', 'Eingang', 'app_path', '/srv/scanner/output'),
 'paperless_url': ('Apps · Paperless', 'Interne Prüfadresse', 'url', 'http://127.0.0.1:8010'),
 'stirling_root': ('Apps · Stirling PDF', 'Compose-Ordner', 'app_path', '/opt/stirling-pdf'),
 'nextcloud_root': ('Apps · Nextcloud', 'Installationsordner', 'app_path', '/var/www/html/nextcloud'),
 'nextcloud_data': ('Apps · Nextcloud', 'Datenordner', 'app_path', '/srv/nextcloud-data'),
 'nextcloud_user': ('Apps · Nextcloud', 'Lokaler PHP-Benutzer', 'local_user', 'www-data'),
 'comfyui_root': ('Apps · ComfyUI', 'Repository', 'app_path', '/opt/comfyui/ComfyUI'),
 'comfyui_user': ('Apps · ComfyUI', 'Lokaler Update-Benutzer', 'local_user', 'comfyui'),
 'oscam_root': ('Apps · OSCam', 'Quellcode', 'app_path', '/opt/oscam'),
 'oscam_build': ('Apps · OSCam', 'Update-Arbeitsordner', 'app_path', '/opt/oscam-build'),
 'oscam_config': ('Apps · OSCam', 'Konfiguration', 'app_path', '/var/lib/oscam/config'),
 'oscam_logs': ('Apps · OSCam', 'Protokolle', 'app_path', '/var/log/oscam'),
 'oscam_user': ('Apps · OSCam', 'Lokaler Update-Benutzer', 'local_user', 'oscam'),
}
BACKUPS = []
STORAGE = {}

def read(path):
    try:
        value=json.loads(path.read_text())
    except FileNotFoundError:return {}
    if not isinstance(value,dict):raise ValueError('Konfiguration muss ein Objekt sein: '+str(path))
    return value

def defaults():
    result={key:copy.deepcopy(spec[3]) for key,spec in FIELDS.items()}
    # Preserve paths already configured in the previous settings page.
    old=read(CONFIG_DIR/'app_manager.json')
    for key in ('backup_root','restore_log_root','update_log_root'):
        if old.get(key):result[key]=old[key]
    result.update(backup_items=copy.deepcopy(BACKUPS),storage_labels=dict(STORAGE))
    return result

def load(pending=False):
    result=defaults(); result.update(read(CONFIG))
    if pending:result.update(read(PENDING))
    return result

ACTIVE=load()
def get(key):return copy.deepcopy(ACTIVE[key])

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.server-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def revision():
    return hashlib.sha256(json.dumps(load(True),sort_keys=True).encode()).hexdigest()

def path_value(value,app=False):
    if not isinstance(value,str):raise ValueError('Ordner muss Text sein.')
    value=value.strip(); p=Path(value)
    if not p.is_absolute() or '..' in p.parts or str(p)=='/' or any(ord(c)<32 for c in value):
        raise ValueError('Vollständigen Unterordner ohne .. oder Steuerzeichen angeben.')
    if p.parts[1] in ('proc','sys','dev','run','bin','sbin','lib','lib64','boot','etc'):
        raise ValueError('Dieser Systembereich ist kein Datenordner.')
    if any(q.is_symlink() for q in (p,*p.parents)):
        raise ValueError('Einen direkten Ordnerpfad ohne symbolische Links verwenden.')
    if p.exists() and not p.is_dir():raise ValueError('Pfad ist kein Ordner.')
    # Existing native app update commands require shell-safe paths throughout.
    if app and not re.fullmatch(r'/[A-Za-z0-9_./:+@=-]+',value):
        raise ValueError('App-Pfade benötigen Buchstaben A–Z, Ziffern oder _ . / : + @ = -; keine Leerzeichen.')
    return str(p)

def validate(values,current=None):
    current=current or load(True)
    result=copy.deepcopy(current)
    for key,(_,label,kind,_) in FIELDS.items():
        if key not in values:continue
        v=values[key]
        if v==current.get(key):continue  # Unavailable legacy mounts do not block unrelated edits.
        try:
            if kind in ('path','app_path'):v=path_value(v,kind=='app_path')
            elif kind=='iso_optional':
                if not isinstance(v,str):raise ValueError('ISO-Dateipfad muss Text sein.')
                v=v.strip()
                if v:
                    p=Path(v)
                    if not p.is_absolute() or p.suffix.lower()!='.iso' or any(ord(c)<32 or c==',' for c in v):raise ValueError('Vollständigen ISO-Dateipfad ohne Komma oder Steuerzeichen angeben.')
                    path_value(str(p.parent))
                    if p.is_symlink() or not p.is_file() or not os.access(p,os.R_OK):raise ValueError('ISO-Datei fehlt, ist nicht lesbar oder ist ein symbolischer Link.')
                    v=str(p)
            elif kind=='paths':
                v=v.splitlines() if isinstance(v,str) else v
                if not isinstance(v,list) or not v or len(v)>32:raise ValueError('1–32 Ordner angeben.')
                v=list(dict.fromkeys(path_value(p) for p in v if str(p).strip()))
                if not v:raise ValueError('Mindestens einen Ordner angeben.')
            elif kind=='network':
                net=ipaddress.ip_network(v,strict=True)
                if net.version!=4 or net.prefixlen<20:raise ValueError('Ein IPv4-Netz mit höchstens 4096 Adressen angeben.')
                v=str(net)
            elif kind in ('user','local_user'):
                if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',v):raise ValueError('Ungültiger Benutzername.')
                if kind=='local_user':pwd.getpwnam(v)
            elif kind=='mac_optional':
                v=str(v).strip().lower()
                if v and (not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',v) or int(v[:2],16)&1 or v=='00:00:00:00:00:00'):
                    raise ValueError('Gültige Unicast-MAC im Format aa:bb:cc:dd:ee:ff angeben.')
            elif kind=='host':
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',v):raise ValueError('Hostname oder IPv4-Adresse angeben.')
            elif kind.startswith('url'):
                if v or kind!='url_optional':
                    url=urlsplit(v);url.port
                    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or any(c in v for c in "'\"`$\\ \n\r"):
                        raise ValueError('HTTP(S)-Adresse ohne Zugangsdaten oder Sonderzeichen angeben.')
        except (ValueError,KeyError,TypeError) as exc:raise ValueError(label+': '+str(exc)) from None
        result[key]=v
    if 'backup_items' in values:
        rows=values['backup_items']
        if not isinstance(rows,list) or len(rows)>100:raise ValueError('Höchstens 100 Sicherungen angeben.')
        clean=[]
        for row in rows:
            name=str(row['name']).strip(); pattern=str(row['pattern']).strip()
            if not name or len(name)>100 or not pattern or Path(pattern).is_absolute() or '..' in Path(pattern).parts or '**' in pattern:raise ValueError('Ungültiger Sicherungsname oder Dateifilter.')
            warn,crit=int(row['warn_h']),int(row['crit_h'])
            if not 0<warn<=crit<=87600:raise ValueError('Altersgrenzen: 1 bis 87600 Stunden; kritisch ab Warnschwelle.')
            clean.append(dict(name=name,path=path_value(row['path']),pattern=pattern,warn_h=warn,crit_h=crit,required=bool(row.get('required',True))))
        result['backup_items']=clean
    if 'storage_labels' in values:
        if not isinstance(values['storage_labels'],dict) or len(values['storage_labels'])>100:raise ValueError('Ungültige Speicherliste.')
        result['storage_labels']={path_value(k):str(v).strip()[:100] for k,v in values['storage_labels'].items()}
    return result

def stage(values,expected):
    if expected!=revision():raise ValueError('Einstellungen wurden inzwischen geändert. Bitte neu laden.')
    data=validate(values)
    current=load(True)
    for key,spec in FIELDS.items():
        if data[key] != current[key] and spec[2] in ('path','app_path','paths'):
            for value in (data[key] if spec[2]=='paths' else [data[key]]):
                status=inspect_path(value)
                if not status['readable']:raise ValueError(spec[1]+': Ordner nicht zugänglich.')
                if key in ('vm_root','system_backup_root','backup_root','restore_log_root','update_log_root') and not status['writable']:
                    raise ValueError(spec[1]+': Ziel nicht schreibbar.')
    atomic(PENDING,data)
    return data

def activate_pending():
    global ACTIVE
    if PENDING.exists():
        try:
            data=validate(read(PENDING),load())
            atomic(CONFIG_DIR/'server.previous.json',load())
            atomic(CONFIG,data);PENDING.unlink()
            (CONFIG_DIR/'server.apply-error.json').unlink(missing_ok=True)
        except (ValueError,KeyError,OSError,TypeError) as exc:
            # A missing mount or invalid pending edit must not disable the whole UI.
            try:atomic(CONFIG_DIR/'server.apply-error.json',{'error':str(exc)})
            except OSError:pass
    ACTIVE=load()

def inspect_path(value):
    p=Path(value); existing=p
    while not existing.exists() and existing!=existing.parent:existing=existing.parent
    mount=existing
    while not mount.is_mount() and mount!=mount.parent:mount=mount.parent
    return {'exists':p.is_dir(),'readable':os.access(existing,os.R_OK|os.X_OK),
            'writable':os.access(existing,os.W_OK|os.X_OK),'mount':str(mount),
            'free_gb':round(os.statvfs(existing).f_bavail*os.statvfs(existing).f_frsize/1024**3,1)}

# Only code literals use this adapter; never apply it to user input or arbitrary commands.
APP_FIELDS={
 'immich':['immich_root'],
 'paperless':['paperless_root','paperless_data','paperless_media','paperless_export','paperless_consume','paperless_url'],
 'stirling':['stirling_root'],
 'nextcloud':['nextcloud_root','nextcloud_data'],
 'comfyui':['comfyui_root'],
 'oscam':['oscam_build','oscam_root','oscam_config','oscam_logs'],
}
def app_literal(app_id,text):
    replacements={FIELDS[k][3]:get(k) for k in APP_FIELDS.get(app_id,[])}
    user_key={'comfyui':'comfyui_user','oscam':'oscam_user','nextcloud':'nextcloud_user'}.get(app_id)
    if user_key:
        old=FIELDS[user_key][3]
        for prefix in ('-u ', 'User=', 'user='):
            replacements[prefix+old]=prefix+get(user_key)
    # One pass prevents overlapping prefix replacements and chained mappings.
    if not replacements:return text
    pattern='|'.join(re.escape(k) for k in sorted(replacements,key=len,reverse=True))
    return re.sub(pattern,lambda m:replacements[m.group()],text)
