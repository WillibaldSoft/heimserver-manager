"""Explicit app removal plans; persistent data and shared host services stay intact."""
import os
import shutil
import copy, hashlib, json, os, re, subprocess, time
from pathlib import Path
from urllib.parse import quote
from . import install_catalog as c
from .openwebui_update import api, saved, UpdateError

ROOT = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app-lifecycle'))
PROTECTED = {
    'kvm': 'KVM wird von virtuellen Maschinen gemeinsam genutzt. Automatische Deinstallation ist gesperrt; Ausblenden ist möglich.',
    'server_manager': 'Der laufende Server Manager kann sich nicht selbst deinstallieren. Ausblenden ist möglich.',
    'shares_mounts': 'Gemeinsam genutzte Mount-/Freigabewerkzeuge werden hier nicht deinstalliert. Ausblenden ist möglich.',
    'nextcloud': 'Die native Nextcloud nutzt gemeinsame Apache-, PHP-, Datenbank- und Cron-Dienste. Eine automatische Deinstallation ist für diese Installationsart nicht freigegeben.',
}

def record_path(app_id):
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,47}', app_id):
        raise c.Invalid('Ungültige App-ID.')
    return ROOT / (app_id + '.json')

def record(app_id):
    path = record_path(app_id)
    return json.loads(path.read_text()) if path.exists() else None

def command(args, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise c.Invalid('Aktion fehlgeschlagen: ' + args[0] + '. Der Auftrag wurde abgebrochen.')
    return result.stdout

def installation(manager):
    """Probe presence, never web health: a stopped app remains installed."""
    try:
        if manager.app_id=='nextcloud_docker' and not shutil.which('docker'):
            return {'state':'missing','installed':False}
        if manager.app_id == 'shares_mounts':
            found = all(subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', p], capture_output=True, text=True, timeout=10).stdout == 'installed' for p in ('cifs-utils', 'nfs-common', 'samba', 'nfs-kernel-server', 'acl'))
            return {'state': 'installed' if found else 'missing', 'installed': found}
        names = list((getattr(manager, 'containers', {}) or {}).values())
        if getattr(manager, 'container', None):
            names = [manager.container]
        if names:
            # A daemon failure is unknown, never proof that an app is missing.
            data = command(['docker', 'container', 'ls', '-a', '--format', '{{.Names}}'])
            present = set(data.splitlines())
            count = sum(name in present for name in names)
            state = 'installed' if count == len(names) else 'partial' if count else 'missing'
            return {'state': state, 'installed': state == 'installed'}
        if manager.app_id == 'nextcloud':
            found = (Path(getattr(manager,'paths',{}).get('nextcloud_app','/var/www/html/nextcloud'))/'occ').is_file()
            return {'state': 'installed' if found else 'missing', 'installed': found}
        return manager.installation_status()
    except Exception:
        return {'state': 'unknown', 'installed': None, 'reason': 'Installationsstatus nicht zuverlässig prüfbar.'}

def digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()

def plan(manager, purge=False):
    app_id = manager.app_id
    result = dict(app_id=app_id, label=manager.label, kind='', items=[], blocked='')
    names = list((getattr(manager, 'containers', {}) or {}).values())
    if getattr(manager, 'container', None):
        names = [manager.container]
    if names:
        # A fresh multi-service recipe may have only its primary container in the manager.
        try:
            primary = api('GET', '/containers/'+quote(names[0], safe='')+'/json')
        except UpdateError:
            result['blocked'] = 'App-Container nicht erreichbar. Docker und Installation prüfen.'
            return result
        project = (primary['Config'].get('Labels') or {}).get('com.docker.compose.project')
        if project:
            members = api('GET', '/containers/json?all=1&filters='+quote(json.dumps({'label':['com.docker.compose.project='+project]})))
            known = set(names)
            expanded = {name.lstrip('/') for item in members for name in item.get('Names', [])}
            if not known.issubset(expanded):
                result['blocked'] = 'Container gehören nicht eindeutig zum selben Compose-Projekt.'
                return result
            names = sorted(expanded)
        containers = []
        for name in names:
            try:
                info = api('GET', '/containers/' + quote(name, safe='') + '/json')
            except UpdateError:
                result['blocked'] = 'Nicht alle App-Container sind eindeutig erreichbar. Docker und App-Zustand prüfen.'
                return result
            if info['HostConfig'].get('AutoRemove'):
                result['blocked'] = 'AutoRemove-Container benötigen eine manuelle Deinstallation.'
                return result
            containers.append(dict(name=name, id=info['Id'], image=info['Image'], mounts=info.get('Mounts', []), config_hash=digest({'config':info['Config'], 'host':info['HostConfig']})))
        result.update(kind='containers', containers=containers, items=['Container ' + x['name'] + ' stoppen und entfernen' for x in containers])
    elif app_id in PROTECTED:
        result['blocked'] = PROTECTED[app_id]
    elif app_id in ('comfyui', 'oscam'):
        binary = '/opt/comfyui/ComfyUI' if app_id == 'comfyui' else '/usr/local/bin/oscam'
        unit = '/etc/systemd/system/' + app_id + '.service'
        fragment = command(['systemctl', 'show', app_id + '.service', '-p', 'FragmentPath', '--value']).strip()
        if fragment != unit or not Path(binary).exists() or Path(binary).is_symlink() or Path(unit).is_symlink():
            result['blocked'] = 'Installationspfad oder Dienst weicht von der unterstützten Installation ab.'
        else:
            result.update(kind='native', paths=[binary, unit], service=app_id+'.service', items=['Dienst '+app_id+' stoppen und deaktivieren', 'Programm und Dienstdatei geschützt aufbewahren; Daten und Konfiguration bleiben erhalten'])
    elif app_id == 'tvheadend':
        preview = command(['apt-get', '-s', 'remove', 'tvheadend'])
        removed = re.findall(r'^Remv (\S+)', preview, re.M)
        if removed != ['tvheadend']:
            result['blocked'] = 'APT würde zusätzliche Pakete entfernen oder Tvheadend ist nicht als Paket installiert.'
        else:
            result.update(kind='package', items=['Paket tvheadend entfernen; Konfiguration und Aufnahmen behalten'])
    else:
        result['blocked'] = 'Für diese Installationsart ist noch kein Deinstallationsprofil hinterlegt.'
    if purge:
        result['mode']='purge'
        try:
            from .purge import prepare
            result['purge']=prepare(manager,result)
            result['items']+=['App-Verzeichnis einschließlich Konfiguration, Datenbank, Cache und aller darin gespeicherten Dateien endgültig löschen: '+result['purge']['root'], 'Eigene Container-Netzwerke entfernen', 'Exklusiv genutztes Image entfernen' if result['purge']['image'] else 'Gemeinsam genutztes Image behalten']
        except (c.Invalid,UpdateError,OSError,ValueError) as exc:result['blocked']=str(exc)
    return result

def execute(manager, expected):
    current = plan(manager, purge=expected.get('mode')=='purge')
    if current['blocked'] or digest(current) != digest(expected):
        raise c.Invalid(current['blocked'] or 'Installation hat sich geändert. Deinstallation erneut prüfen.')
    if current.get('mode')=='purge':
        from .purge import execute as purge_execute
        return purge_execute(manager,current)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = record_path(manager.app_id)
    if path.exists():
        raise c.Invalid('Es besteht bereits ein Wiederherstellungsstand; zuerst diesen prüfen.')
    state = dict(plan=current, state='removing', containers=[], moved=[], created=time.time())
    if current['kind'] == 'containers':
        # Save full settings privately before stopping anything. No secrets in logs.
        state['containers'] = [api('GET', '/containers/'+item['id']+'/json') for item in current['containers']]
    saved(path, state)
    if current['kind'] == 'containers':
        for item in state['containers']:
            api('POST', '/containers/'+item['Id']+'/stop?t=60')
        for item in state['containers']:
            api('DELETE', '/containers/'+item['Id'])  # no force, no volume deletion
    elif current['kind'] == 'native':
        command(['systemctl', 'disable', '--now', current['service']])
        for raw in current['paths']:
            source = Path(raw)
            dest = source.with_name(source.name+'.servermgr-uninstalled-'+str(int(state['created'])))
            if dest.exists():
                raise c.Invalid('Sicherungspfad existiert bereits.')
            state['moved'].append([str(source), str(dest)])
            saved(path, state)
            source.rename(dest)
        command(['systemctl', 'daemon-reload'])
    elif current['kind'] == 'package':
        # Recheck dependency plan immediately before execution, no autoremove/purge.
        command(['apt-get', '-y', '--no-auto-remove', 'remove', 'tvheadend'], 600)
    state['state'] = 'removed'
    saved(path, state)
    print('Deinstallation abgeschlossen. Daten, Konfiguration und vorhandene Images bleiben erhalten.')

def restore(manager):
    path = record_path(manager.app_id); state = record(manager.app_id)
    if not state or state['state'] != 'removed':
        raise c.Invalid('Kein vollständig deinstallierter Wiederherstellungsstand verfügbar.')
    plan_data = state['plan']
    if plan_data['kind'] == 'containers':
        # Preflight all names and images before creating any container.
        present = set(command(['docker', 'container', 'ls', '-a', '--format', '{{.Names}}']).splitlines())
        if any(item['Name'].lstrip('/') in present for item in state['containers']):
            raise c.Invalid('Ein Containername ist inzwischen wieder belegt.')
        for item in state['containers']:
            api('GET', '/images/'+quote(item['Image'], safe='')+'/json')
            for mount in item.get('Mounts', []):
                if mount['Type'] == 'volume':
                    api('GET', '/volumes/'+quote(mount['Name'], safe=''))
                elif mount['Type'] == 'bind' and not Path(mount['Source']).exists():
                    raise c.Invalid('Ein aufbewahrtes Datenverzeichnis fehlt.')
        created = []
        try:
            for item in reversed(state['containers']):
                spec = copy.deepcopy(item['Config']); spec['Image'] = item['Image']
                spec['HostConfig'] = copy.deepcopy(item['HostConfig'])
                # Preserve anonymous volumes as well as named volumes by explicit source.
                mounts = item.get('Mounts', [])
                binds = spec['HostConfig'].get('Binds') or []
                targets = {value.split(':')[1] for value in binds if ':' in value}
                targets.update(x.get('Target') for x in spec['HostConfig'].get('Mounts') or [])
                for mount in mounts:
                    if mount['Type'] in ('bind', 'volume') and mount['Destination'] not in targets:
                        source = mount.get('Name') if mount['Type']=='volume' else mount['Source']
                        binds.append(source+':'+mount['Destination']+(':rw' if mount.get('RW') else ':ro'))
                spec['HostConfig']['Binds'] = binds
                endpoints = {}
                for name, network in item.get('NetworkSettings', {}).get('Networks', {}).items():
                    if name not in ('bridge', 'host', 'none'):
                        endpoints[name] = {key:network[key] for key in ('Aliases', 'IPAMConfig') if network.get(key)}
                if endpoints: spec['NetworkingConfig'] = {'EndpointsConfig': endpoints}
                result = api('POST', '/containers/create?name='+quote(item['Name'].lstrip('/')), spec)
                created.append(result['Id'])
            for key in created: api('POST', '/containers/'+key+'/start')
        except Exception:
            # Only this attempt's replacement containers; retained data remains untouched.
            for key in reversed(created):
                try: api('DELETE', '/containers/'+key+'?force=1')
                except UpdateError: pass
            raise
    elif plan_data['kind'] == 'native':
        for old, new in state['moved']:
            if Path(old).exists() or not Path(new).exists():
                raise c.Invalid('Ursprünglicher Pfad belegt oder Sicherung fehlt.')
        for old, new in state['moved']: Path(new).rename(old)
        command(['systemctl', 'daemon-reload'])
        command(['systemctl', 'enable', '--now', plan_data['service']])
    elif plan_data['kind'] == 'package':
        command(['apt-get', 'install', '-y', 'tvheadend'], 1200)
    path.rename(path.with_name(path.stem+'-restored-'+str(time.time_ns())+'.json'))
    print('App mit aufbewahrten Daten wieder installiert. Betriebszustand in der App-Verwaltung prüfen.')
