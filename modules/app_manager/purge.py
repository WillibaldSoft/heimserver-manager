"""Irreversible removal of an explicitly confirmed, manager-owned container app."""
import hashlib,json,os,re,shutil
from pathlib import Path
from urllib.parse import quote
from . import install_catalog as c
from .openwebui_update import api

def inside(path,root):
    return path==root or root in path.parents

def safe_root(raw):
    root=Path(raw)
    if not root.is_absolute() or len(root.parts)<3 or root in (Path('/var/lib'),Path('/usr/local'),Path('/opt/server-manager')):
        raise c.Invalid('App-Verzeichnis ist nicht eindeutig begrenzt.')
    if any(p.is_symlink() for p in (root,*root.parents)) or root.resolve()!=root or not root.is_dir():
        raise c.Invalid('App-Verzeichnis fehlt oder enthält symbolische Pfadverweise.')
    # Do not traverse another filesystem, including bind mounts on the same device.
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        mount=Path(re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),line.split()[4]))
        if inside(mount,root):raise c.Invalid('App-Verzeichnis enthält einen Mountpunkt. Vollständige Entfernung gesperrt.')
    if not shutil.rmtree.avoids_symlink_attacks:raise c.Invalid('Sicheres Löschen wird auf diesem System nicht unterstützt.')
    return root

def prepare(manager,base):
    if base.get('blocked'):raise c.Invalid(base['blocked'])
    profile=c.recipe(manager.app_id)
    if profile['kind']!='container' or base['kind']!='containers' or len(base['containers'])!=1:
        raise c.Invalid('Vollständige Entfernung ist derzeit für einzelne, vom Manager installierte Container-Apps verfügbar. Für diese Installationsart fehlt ein sicheres Löschprofil.')
    root=safe_root(profile['target']);marker=root/'.server-manager-install.json';compose=root/'compose.json'
    if any(p.is_symlink() or not p.is_file() for p in (marker,compose)):
        raise c.Invalid('Eigentumsnachweis des Manager-Installers fehlt.')
    installed=json.loads(marker.read_text())
    if installed.get('app_id')!=manager.app_id or installed.get('target')!=str(root) or installed.get('container')!=profile['container']:
        raise c.Invalid('Installationsnachweis passt nicht zur App.')
    spec=json.loads(compose.read_text())
    if set(spec.get('services',{}))!={'app'} or spec['services']['app'].get('container_name')!=profile['container']:
        raise c.Invalid('Erweiterte oder fremde Compose-Installation: vollständige Entfernung gesperrt.')
    own=base['containers'][0];info=api('GET','/containers/'+own['id']+'/json');labels=info['Config'].get('Labels') or {}
    project=labels.get('com.docker.compose.project')
    if not project or labels.get('com.docker.compose.project.working_dir')!=str(root) or labels.get('com.docker.compose.project.config_files')!=str(compose):
        raise c.Invalid('Container gehört nicht eindeutig zur Manager-Installation.')
    kept=[]
    for mount in info.get('Mounts',[]):
        if mount['Type']=='volume':raise c.Invalid('Zusätzliche Docker-Volumes benötigen ein gesondertes Löschprofil.')
        if mount['Type']=='bind':
            source=Path(mount['Source']).resolve()
            if not inside(source,root):
                if mount.get('RW'):raise c.Invalid('Externer beschreibbarer Datenpfad: vollständige Entfernung gesperrt.')
                kept.append(str(source))
    others=api('GET','/containers/json?all=1')
    shared_image=False
    for entry in others:
        if entry['Id']==own['id']:continue
        other=api('GET','/containers/'+entry['Id']+'/json')
        if other['Image']==own['image']:shared_image=True
        for mount in other.get('Mounts',[]):
            if mount.get('Type')=='bind':
                source=Path(mount['Source']).resolve()
                if inside(source,root) or inside(root,source):raise c.Invalid('Ein anderer Container verwendet das App-Verzeichnis. Vollständige Entfernung gesperrt.')
    networks=[]
    for name in info.get('NetworkSettings',{}).get('Networks',{}):
        if name in ('host','bridge','none'):continue
        network=api('GET','/networks/'+quote(name,safe=''))
        if (network.get('Labels') or {}).get('com.docker.compose.project')!=project or set(network.get('Containers',{}))-{own['id']}:
            kept.append('Docker-Netzwerk '+name);continue
        networks.append(network['Id'])
    image=api('GET','/images/'+quote(own['image'],safe='')+'/json')
    tags=image.get('RepoTags') or []
    # Never remove an image with additional tags or another container consumer.
    remove_image=not shared_image and len(tags)<=1
    if not remove_image:kept.append('Gemeinsam genutztes oder mehrfach markiertes Docker-Image')
    return dict(root=str(root),identity=[root.stat().st_dev,root.stat().st_ino],files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (marker,compose)},networks=sorted(networks),image=own['image'] if remove_image else '',kept=sorted(kept))

def execute(manager,plan):
    from . import lifecycle
    # lifecycle.execute already revalidates the complete reviewed plan.
    data=plan['purge'];root=safe_root(data['root'])
    lifecycle.ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=lifecycle.record_path(manager.app_id)
    if path.exists():raise c.Invalid('Vorhandenen Deinstallationsstand zuerst prüfen.')
    lifecycle.saved(path,dict(state='purging',plan=plan))
    for item in plan['containers']:
        info=api('GET','/containers/'+item['id']+'/json')
        if info.get('State',{}).get('Running'):api('POST','/containers/'+item['id']+'/stop?t=60')
        api('DELETE','/containers/'+item['id'])
    for key in data['networks']:api('DELETE','/networks/'+key)
    # Recheck filesystem boundaries after containers have stopped.
    root=safe_root(str(root))
    if [root.stat().st_dev,root.stat().st_ino]!=data['identity']:raise c.Invalid('App-Verzeichnis wurde zwischenzeitlich ersetzt.')
    shutil.rmtree(root)
    if data['image']:api('DELETE','/images/'+quote(data['image'],safe='')+'?force=0')
    settings=c.read();settings.get('web',{}).pop(manager.app_id,None);c.write(settings)
    path.unlink()
    print('App, eigenes Datenverzeichnis und zugeordnete Container-Netzwerke endgültig entfernt. Kein Wiederherstellungsstand angelegt. Bestehende Backups und Manager-Auftragsprotokolle bleiben erhalten.')
    for item in data['kept']:print('Erhalten: '+item)
