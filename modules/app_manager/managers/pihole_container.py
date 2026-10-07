"""Pi-hole installed through the optional managed container recipe."""
from .open_webui import Manager as ContainerManager

class PiHoleManager(ContainerManager):
    # Instantiated only for a managed installation; not auto-registered as a native app.
    app_id='pihole'
    label='Pi-hole'
    container='servermgr-pihole'
    web_url='http://127.0.0.1:8088/admin/'

    def health(self):
        data=self.status()
        data['note']='Container- und Webstatus. DNS-Auflösung vom Client und dessen DNS-Einstellung zusätzlich prüfen.'
        return data


from .base import BaseManager
class NativePiHoleManager(BaseManager):
    app_id='pihole'
    label='Pi-hole'
    kind='native'
    service='pihole-FTL.service'
    paths={'configuration':'/etc/pihole'}
    config_files={}

    def installed_components(self):
        import re,subprocess
        result=subprocess.run(['/usr/local/bin/pihole','-v','-c'],capture_output=True,text=True,timeout=15)
        if result.returncode:raise ValueError('Installierte Pi-hole-Versionen konnten nicht gelesen werden.')
        versions={name:version for name,version in re.findall(r'^(Core|Web|FTL) version is (v[0-9]+(?:\.[0-9]+){1,3})(?: \(Latest: [^\r\n]*\))?\s*$',result.stdout,re.M)}
        if set(versions)!={'Core','Web','FTL'}:raise ValueError('Core-, Web- oder FTL-Version ist nicht eindeutig lesbar (z. B. Entwicklungsstand).')
        return versions

    @staticmethod
    def comparable(value):
        import re
        if not isinstance(value,str) or not re.fullmatch(r'v?[0-9]+(?:\.[0-9]+){1,3}',value):raise ValueError('Keine stabile numerische Pi-hole-Version.')
        parts=tuple(int(p) for p in value.lstrip('v').split('.'))
        return parts+(0,)*(4-len(parts))

    def update_check(self):
        current={};latest={}
        display=lambda values:' · '.join(name+' '+values[name] for name in ('Core','Web','FTL') if name in values)
        try:
            current=self.installed_components()
            for name,repo in [('Core','pi-hole'),('Web','web'),('FTL','FTL')]:
                release=ContainerManager.read_json('https://api.github.com/repos/pi-hole/'+repo+'/releases/latest')
                if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):raise ValueError('Kein stabiles Pi-hole-Release verfügbar.')
                value=release.get('tag_name');self.comparable(value);latest[name]=value
            available=any(self.comparable(latest[k])>self.comparable(current[k]) for k in current)
            return self.native_update_result(state='available' if available else 'current',label='Update verfügbar' if available else 'Aktuell',current_version=display(current),latest_version=display(latest),update_available=available,method='Pi-hole CLI / offizielle GitHub-Releases',details={'installed':current,'available':latest},message='Neue Pi-hole-Komponenten verfügbar. Die Prüfung installiert keine Updates.' if available else 'Keine neueren stabilen Pi-hole-Komponenten verfügbar.')
        except Exception as exc:
            return self.native_update_result(ok=False,state='unknown',label='Nicht prüfbar',current_version=display(current) or None,method='Pi-hole CLI / offizielle GitHub-Releases',message='Versionsprüfung fehlgeschlagen: '+str(exc),details={'installed':current})

    def extra_backup(self,workdir):
        from ..pihole_update import snapshot
        return snapshot(self,workdir)

    def update_plan(self):
        return dict(supported=True,ok=True,app_id=self.app_id,label=self.label,kind=self.kind,requires_backup=True,safe_to_update=False,message='Native Pi-hole-Aktualisierung mit dem offiziellen pihole -up. Vorher neues Backup vorbereiten; alte Metadaten-Backups reichen nicht. DNS kann während des Updates kurz ausfallen. Keine automatische Rücknahme von Programm- oder Paketänderungen.',steps=[dict(id='backup',label='Pi-hole-Konfiguration und konsistente SQLite-Sicherungen prüfen',required=True),dict(id='update',label='Offiziellen Pi-hole-Updater ausführen',required=True),dict(id='verify',label='Core/Web/FTL-Versionen, Dienst, Weboberfläche und DNS prüfen',required=True)])

    def update_execute(self,session=None):
        from ..pihole_update import execute
        return execute(self,session)

    def update_verify(self):
        from ..pihole_update import dns_ok
        try:
            current=self.installed_components();expected=getattr(self,'_expected_versions',{})
            status=self.status();versions=bool(expected) and all(self.comparable(current[k])>=self.comparable(v) for k,v in expected.items())
            dns=dns_ok();ok=versions and status.get('service',{}).get('active')=='active' and status.get('web',{}).get('ok') and dns
            return dict(ok=bool(ok),supported=True,versions=current,expected=expected,dns_ok=dns,message='Pi-hole-Versionen, Dienst, Weboberfläche und DNS bestätigt.' if ok else 'Pi-hole-Nachprüfung fehlgeschlagen. Protokoll prüfen; keine automatische Rücknahme.')
        except Exception as exc:return dict(ok=False,supported=True,message=str(exc))
