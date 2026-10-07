"""Keep native Nextcloud identity stable while selecting a managed Docker instance."""
import copy
import json
from pathlib import Path
from .managers.open_webui import Manager as ContainerManager
from .runner import run


class DockerNextcloud(ContainerManager):
    app_id = 'nextcloud_docker'
    label = 'Nextcloud'
    installation_mode = 'Docker'
    update_backup_profile = 'full'

    def __init__(self, profile):
        self.container = profile['container']
        self.web_url = profile.get('web_url') or 'http://127.0.0.1:'+str(profile['port'])
        self.root = Path(profile['target'])
        self.compose_dir = str(self.root)
        self.config_files = {'compose': str(self.root/'compose.json'), 'config.php':str(self.root/'html/config/config.php'), 'installation':str(self.root/'.server-manager-install.json')}
        for name in ('root_password','db_password','admin_password'):
            self.config_files[name]=str(self.root/'secrets'/name)
        self.paths = {'nextcloud_app': str(self.root/'html'), 'secrets': str(self.root/'secrets')}
        data = (profile.get('setup') or {}).get('data_root')
        if data:
            self.paths['nextcloud_data'] = data
        # Never fall back to the host's native MariaDB or Apache for Docker.
        self.database = {'type': 'nextcloud-docker', 'database':'nextcloud'}

    def occ_status(self):
        result = run(['docker', 'exec', '--user', 'www-data', self.container,
                      'php', 'occ', 'status', '--output=json'], timeout=30)
        try:
            data = json.loads(result.get('stdout') or '{}')
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        return dict(data, ok=bool(result.get('ok') and data.get('installed')
                                and data.get('maintenance') is False
                                and data.get('needsDbUpgrade') is False))

    def status(self):
        result = super().status()
        occ = self.occ_status() if result.get('ok') else {'ok': False}
        result['occ'] = occ
        result['ok'] = bool(result.get('ok') and occ['ok'])
        if not occ['ok']:
            result.setdefault('warnings', []).append('Nextcloud ist noch nicht betriebsbereit; OCC, Wartungsmodus und Datenbank prüfen.')
        if occ.get('versionstring'):
            result['version'] = {'value': occ['versionstring'], 'source': 'nextcloud-occ'}
        return result

    def health(self):
        return self.status()

    def info(self):
        return dict(super().info(), installation_mode=self.installation_mode, occ=self.occ_status())

    def backup_context(self):
        from .nextcloud_docker import quiesce
        return quiesce(self)

    def copy_backup_path(self, source, destination, key):
        from .nextcloud_docker import copy_path
        return copy_path(source,destination,key)

    def database_backup(self, target):
        from .nextcloud_docker import dump
        return dump(self,target)

    def update_check(self):
        from .nextcloud_docker import check
        if not self.container_status().get('found'):
            return dict(supported=True,ok=False,state='missing',label='Inaktiv',message='Nextcloud Docker ist nicht installiert.',update_available=None,requires_backup=True)
        return check(self)

    def update_plan(self):
        from .nextcloud_docker import plan
        return plan(self)

    def update_execute(self, session=None):
        from .nextcloud_docker import execute
        return execute(self,session)

    def update_verify(self):
        status=self.occ_status()
        expected=getattr(self,'_expected_update_version',None)
        ok=bool(status.get('ok') and (not expected or status.get('versionstring')==expected) and self._web_check().get('ok'))
        return dict(supported=True,ok=ok,message='Nextcloud Docker geprüft.' if ok else 'Nextcloud Docker nachprüfen.',details=status)


def combine(builtins, dynamic):
    """One card normally; keep separate identities if both installations exist."""
    dynamic = dict(dynamic)
    result = []
    for manager in builtins:
        selected = dynamic.pop(manager.app_id, manager)
        native_candidate=manager if isinstance(selected,DockerNextcloud) else selected
        if manager.app_id=='nextcloud':
            docker=dynamic.pop('nextcloud_docker',None)
            if docker is not None and (docker.root/'.server-manager-install.json').is_file():
                selected=docker
            elif docker is not None:
                result.append(docker)
        if (manager.app_id == 'nextcloud' and isinstance(selected, DockerNextcloud)
                and (Path(native_candidate.paths['nextcloud_app'])/'occ').is_file()):
            native = copy.copy(native_candidate)
            native.label = 'Nextcloud · Nativ'
            docker = copy.copy(selected)
            docker.label = 'Nextcloud · Docker'
            result.extend((native, docker))
        else:
            result.append(selected)
    result.extend(dynamic.values())
    return result
