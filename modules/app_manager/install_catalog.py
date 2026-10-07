"""Data-driven app installer recipes and browser-facing WebUI addresses."""
import os
from server_settings import get as host_setting
import copy,json,os,re,tempfile,platform
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
ROOT=Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app-installers'))
CONFIG=ROOT/'profiles.json'

CATALOG={
 'pihole':dict(label='Pi-hole',kind='container',image='pihole/pihole:latest',port=8088,container_port=80,container='servermgr-pihole',mount='/etc/pihole',target=host_setting('custom_apps_root')+'/pihole',service='pihole-FTL.service',existing='/etc/pihole',web_url='http://127.0.0.1:8088/admin/',docs='https://docs.pi-hole.net/docker/'),
 'kvm':dict(label='KVM / libvirt',kind='kvm_setup',port=0,service='libvirtd.service',target='/opt/servermgr-installers/kvm',web_url='/kvm',network='nat',docs='https://wiki.debian.org/KVM'),
 'plex':dict(label='Plex',kind='container',image='plexinc/pms-docker:latest',port=32400,container_port=32400,container='servermgr-plex',mount='/config',target=host_setting('custom_apps_root')+'/plex',service='plexmediaserver.service',existing='/var/lib/plexmediaserver',web_url='http://127.0.0.1:32400/web',docs='https://github.com/plexinc/pms-docker'),
 'jellyfin':dict(label='Jellyfin',kind='container',image='jellyfin/jellyfin:latest',port=8096,container_port=8096,container='servermgr-jellyfin',mount='/config',target=host_setting('custom_apps_root')+'/jellyfin',service='jellyfin.service',existing='/var/lib/jellyfin',docs='https://jellyfin.org/docs/general/installation/container/'),
 'open_webui':dict(label='Open WebUI',local_ai=True,kind='container',image='ghcr.io/open-webui/open-webui:ollama',port=3000,container_port=8080,container='open-webui',mount='/app/backend/data',target='/opt/open-webui',docs='https://docs.openwebui.com/getting-started/quick-start/'),
 'immich':dict(label='Immich',kind='immich',port=2283,container='immich_server',target='/opt/immich',docs='https://docs.immich.app/install/docker-compose/'),
 'paperless':dict(label='Paperless-ngx',kind='paperless',port=8010,container='paperless-ngx',target='/opt/paperless-ngx',docs='https://docs.paperless-ngx.com/setup/'),
 'stirling':dict(label='Stirling PDF',kind='container',image='docker.stirlingpdf.com/stirlingtools/stirling-pdf:latest',port=8085,container_port=8080,container='stirling-pdf',mount='/configs',target='/opt/stirling-pdf',docs='https://docs.stirlingpdf.com/Installation/Docker%20Install/'),
 'nextcloud':dict(label='Nextcloud',kind='nextcloud',port=8080,container='servermgr-nextcloud',service='apache2.service',existing='/var/www/nextcloud',target='/opt/servermgr-nextcloud',docs='https://hub.docker.com/_/nextcloud'),
 'comfyui':dict(label='ComfyUI',kind='comfyui',port=8188,service='comfyui.service',target='/opt/comfyui/ComfyUI',docs='https://docs.comfy.org/installation/manual_install'),
 'tvheadend':dict(label='Tvheadend',kind='packages',packages=['tvheadend'],port=9981,service='tvheadend.service',target='/opt/servermgr-installers/tvheadend',docs='https://tvheadend.org/p/downloads'),
 'shares_mounts':dict(label='SMB / NFS · Server und Clients',kind='packages',packages=['samba','samba-common-bin','smbclient','nfs-kernel-server','nfs-common','cifs-utils','acl','attr','passwd'],port=0,target='/opt/servermgr-installers/shares-mounts',web_url='/freigaben',docs='https://www.debian.org/doc/manuals/debian-reference/ch05.en.html'),
 'oscam':dict(label='OSCam',kind='oscam_bundle',port=8888,service='oscam.service',existing='/usr/local/bin/oscam',target='/opt/servermgr-installers/oscam',docs=''),
 'server_manager':dict(label='Heimserver Manager',kind='server_bundle',port=9877,service='server-manager.service',target='/opt/server-manager',docs=''),
}
CATALOG['nextcloud_docker']=dict(CATALOG['nextcloud'],label='Nextcloud · Docker',setup={'mode':'docker','data_root':'/srv/nextcloud-docker-data'})
PORTABLE_CATALOG=copy.deepcopy(CATALOG)
PORTABLE_CATALOG['pihole']['target']='/opt/servermgr-apps/pihole'
PORTABLE_CATALOG['plex']['target']='/opt/servermgr-apps/plex'
PORTABLE_CATALOG['jellyfin']['target']='/opt/servermgr-apps/jellyfin'

def portable_recipe(app_id):
    if app_id not in PORTABLE_CATALOG:return recipe(app_id)
    return dict(copy.deepcopy(PORTABLE_CATALOG[app_id]),app_id=app_id)

for _app, _key in {'open_webui':'open_webui_root','nextcloud':'nextcloud_container_root','immich':'immich_root','paperless':'paperless_root','stirling':'stirling_root','comfyui':'comfyui_root'}.items():
    CATALOG[_app]['target'] = host_setting(_key)
CATALOG['server_manager']['target'] = str(Path(__file__).resolve().parents[2])
CATALOG['nextcloud']['existing'] = host_setting('nextcloud_root')
CATALOG['nextcloud_docker']['target']=host_setting('nextcloud_container_root')
CATALOG['nextcloud_docker']['existing']=host_setting('nextcloud_root')
CATALOG['nextcloud_docker']['native_data']=host_setting('nextcloud_data')
class Invalid(ValueError):pass

def read():
    try:return json.loads(CONFIG.read_text())
    except FileNotFoundError:return {'custom':{},'web':{}}

def write(data):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(dir=ROOT)
    try:
        with os.fdopen(fd,'w') as stream:os.fchmod(stream.fileno(),0o600);json.dump(data,stream,ensure_ascii=False,indent=2)
        os.replace(name,CONFIG)
    finally:
        if os.path.exists(name):os.unlink(name)

def recipes():return dict(CATALOG,**read().get('custom',{}))
def recipe(app_id):
    p=recipes().get(app_id)
    if p is None:raise Invalid('Noch kein Installationsprofil vorhanden. Profil für diese App anlegen.')
    result=dict(copy.deepcopy(p),app_id=app_id)
    if result['kind']=='oscam_bundle':result['architecture']=platform.machine()
    return result

def valid_url(url):
    if not url:return ''
    if url.startswith('/') and not url.startswith('//') and '\\' not in url and not any(ord(c)<32 for c in url):return url
    try:p=urlsplit(url);p.port
    except ValueError:raise Invalid('Ungültige WebUI-Adresse.') from None
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or '\\' in url or any(ord(c)<32 for c in url):raise Invalid('Nur HTTP(S)-Adressen ohne Zugangsdaten oder lokale Modulpfade verwenden.')
    return url

def browser_url(manager,host_url):
    saved=read()
    override=saved.get('web',{}).get(manager.app_id)
    if manager.app_id=='nextcloud' and not getattr(manager,'container',None) and saved.get('custom',{}).get('nextcloud',{}).get('kind')=='nextcloud':
        override=None  # Docker metadata must never redirect the native card.
    if override:return valid_url(override)
    url=getattr(manager,'web_url',None) or CATALOG.get(manager.app_id,{}).get('web_url','')
    if not url:return ''
    if manager.app_id=='nextcloud':url=url.replace('/status.php','/')
    if manager.app_id=='server_manager':url=url.replace('/api/health','/')
    p=urlsplit(valid_url(url))
    if p.hostname in ('127.0.0.1','localhost','::1','0.0.0.0'):
        host=urlsplit(host_url).hostname
        if not host:return ''
        host='['+host+']' if ':' in host else host
        url=urlunsplit((p.scheme,host+(':'+str(p.port) if p.port else ''),p.path,p.query,p.fragment))
    return url

def custom(data):
    key=data.get('app_id','').strip()
    if not re.fullmatch('[a-z][a-z0-9_]{1,47}',key):raise Invalid('App-ID: Kleinbuchstaben, Zahlen und Unterstriche, 2–48 Zeichen.')
    label=data.get('label','').strip();image=data.get('image','').strip();mount=data.get('mount','/data').strip()
    if not label or len(label)>80:raise Invalid('App-Name fehlt oder ist zu lang.')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:@-]{1,240}',image) or ':' not in image:raise Invalid('Container-Image einschließlich Tag oder Digest eingeben.')
    if not re.fullmatch(r'/[a-zA-Z0-9_./-]+',mount) or '..' in mount.split('/'):raise Invalid('Ungültiges Datenverzeichnis im Container.')
    try:port=int(data.get('port',''));internal=int(data.get('container_port',''))
    except ValueError:raise Invalid('Ports müssen Zahlen sein.') from None
    if not 1024<=port<=65535 or not 1<=internal<=65535:raise Invalid('Ungültiger Portbereich.')
    return key,dict(label=label,kind='container',image=image,port=port,container_port=internal,container='servermgr-'+key.replace('_','-'),mount=mount,target=host_setting('custom_apps_root')+'/'+key,docs='')
