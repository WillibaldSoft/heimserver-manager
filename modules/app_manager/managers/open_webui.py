"""Manage the existing standalone Open WebUI container without converting it."""
import json,subprocess,re
from urllib import request,error
from .base import BaseManager

class Manager(BaseManager):
    app_id='open_webui'
    label='Open WebUI'
    kind='docker'
    web_url='http://127.0.0.1:3000'
    container='open-webui'
    @property
    def paths(self):
        if hasattr(self,'_paths_override'):return self._paths_override
        try:
            result=subprocess.run(['docker','inspect','--format','{{json .Mounts}}',self.container],capture_output=True,text=True,timeout=5)
            for mount in json.loads(result.stdout or '[]'):
                if mount.get('Destination')=='/app/backend/data' and mount.get('Type')=='volume':return {'data':mount['Source']}
        except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):pass
        return {}
    @paths.setter
    def paths(self,value):self._paths_override=value
    config_files={}
    def container_status(self):
        try:
            r=subprocess.run(['docker','inspect','--format','{{json .State}}',self.container],capture_output=True,text=True,timeout=10)
            if r.returncode:return {'found':False,'running':False,'error':'Container nicht gefunden oder Docker nicht verfügbar.'}
            state=json.loads(r.stdout)
            return {'found':True,'running':bool(state.get('Running')),'status':state.get('Status'),'health':state.get('Health',{}).get('Status')}
        except (OSError,ValueError,subprocess.TimeoutExpired):return {'found':False,'running':False,'error':'Docker-Status nicht prüfbar.'}
    def installation_status(self):
        state=self.container_status();return {'installed':state['found'],'state':'installed' if state['found'] else 'missing','reason':'Docker-Container '+self.container,'checks':[]}
    def status(self):
        state=self.container_status();warnings=[] if state['running'] else [state.get('error') or 'Container ist gestoppt.']
        version={}
        if state['found']:
            try:
                image=subprocess.run(['docker','inspect','--format','{{.Config.Image}}',self.container],capture_output=True,text=True,timeout=5)
                if image.returncode==0:version={'value':image.stdout.strip(),'source':'container-image'}
            except (OSError,subprocess.TimeoutExpired):pass
        if self.app_id=='open_webui' and state['running']:
            try:version={'value':self.installed_version(),'source':'open-webui-api'}
            except (ValueError,OSError):pass
        return {'id':self.app_id,'label':self.label,'kind':self.kind,'ok':state['running'],'warnings':warnings,'installation':{'installed':state['found'],'state':'installed' if state['found'] else 'missing'},'container':state,'version':version,'web':self._web_check()}
    def info(self):return {'id':self.app_id,'label':self.label,'container':self.container,'web_url':self.web_url,'paths':self.paths}

    def health(self):
        data=self.status()
        try:
            r=subprocess.run(['systemctl','is-active','ollama.service'],capture_output=True,text=True,timeout=5)
            data['ollama']={'local_service':r.stdout.strip() or 'unbekannt','note':'Die konfigurierte Modellverbindung kann in Open WebUI unter Administration → Verbindungen geprüft werden.'}
        except (OSError,subprocess.TimeoutExpired):data['ollama']={'local_service':'nicht prüfbar'}
        try:
            version=self.read_json('http://127.0.0.1:11434/api/version').get('version')
            data['ollama'].update(api_reachable=bool(version),version=version)
        except (OSError,ValueError):data['ollama']['api_reachable']=False
        return data

    @staticmethod
    def version_tuple(value):
        match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',str(value).strip())
        if not match:raise ValueError('Keine eindeutig vergleichbare Release-Version.')
        return tuple(int(part) for part in match.groups())

    @staticmethod
    def read_json(url):
        req=request.Request(url,headers={'Accept':'application/json','User-Agent':'ServerManager-OpenWebUI-UpdateCheck'})
        with request.urlopen(req,timeout=12) as response:
            data=response.read(262145)
            if len(data)>262144:raise ValueError('Versionsantwort zu groß.')
            return json.loads(data)

    def installed_version(self):
        data=self.read_json(self.web_url.rstrip('/')+'/api/version')
        value=data.get('version') if isinstance(data,dict) else None
        self.version_tuple(value)
        return str(value).lstrip('v')

    def update_check(self):
        if self.app_id!='open_webui':return super().update_check()
        result=dict(supported=True,ok=False,state='missing',label='Nicht prüfbar',app_id=self.app_id,app_label=self.label,kind=self.kind,current_version=None,latest_version=None,update_available=None,method='Open-WebUI API / GitHub Stable Release',safe_to_update=False,requires_backup=True)
        try:result['current_version']=self.installed_version()
        except (OSError,ValueError,error.URLError):
            return dict(result,message='Installierte Version nicht lesbar. Open-WebUI-Dienst und /api/version prüfen.')
        try:
            release=self.read_json('https://api.github.com/repos/open-webui/open-webui/releases/latest')
            if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):raise ValueError('Kein stabiles Release.')
            latest=release.get('tag_name');latest_tuple=self.version_tuple(latest)
            result['latest_version']=str(latest).lstrip('v')
        except (OSError,ValueError,error.URLError):
            return dict(result,message='Offizielles GitHub-Release nicht abrufbar (Netzwerk oder API-Limit). Später erneut prüfen.')
        current=self.version_tuple(result['current_version']);available=latest_tuple>current
        return dict(result,ok=True,state='available' if available else 'current',label='Update verfügbar' if available else 'Aktuell',update_available=available,message=('Neues stabiles Release verfügbar. Vor einer Aktualisierung Daten sichern.' if available else 'Installierte Version entspricht dem neuesten Release.' if current==latest_tuple else 'Installierte Version ist neuer als das veröffentlichte Stable-Release; kein Downgrade empfohlen.'))

    def update_plan(self):
        if self.app_id!='open_webui':return super().update_plan()
        check=self.update_check()
        return dict(supported=True,ok=check.get('ok',False),app_id=self.app_id,label=self.label,kind=self.kind,update_available=check.get('update_available'),state=check.get('state'),requires_backup=True,safe_to_update=False,message=check.get('message'),steps=[
            {'id':'preflight','label':'Container und freien Speicher prüfen','required':True},
            {'id':'pull_image','label':'Offizielles Stable-Image herunterladen','required':True},
            {'id':'backup_data','label':'Anhalten und vollständige Datenkopie erstellen','required':True},
            {'id':'replace_container','label':'Neuen Container mit bisherigen Einstellungen starten','required':True},
            {'id':'verify','label':'Version und Gesundheit prüfen; bei Fehler zum Original zurückkehren','required':True}])

    def update_execute(self,session=None):
        if self.app_id!='open_webui':return super().update_execute(session)
        from ..settings import bool_setting
        if not session or session.get('simulate',True):
            return dict(ok=True,supported=True,mode='simulate',message='Simulation: Keine Container oder Daten geändert.',steps=[dict(id='simulation',status='simulated',changed=False,message='Stable-Image laden, Daten kopieren und Container prüfen.')])
        if not bool_setting('update_execution_enabled',False) or not session.get('execution_gate_passed'):
            return dict(ok=False,supported=True,message='Bestätigter Echtlauf und bestandene Sicherheitsprüfung erforderlich.',steps=[dict(id='gate',status='blocked',changed=False,message='Echtlauf nicht freigegeben.')])
        from ..openwebui_update import execute
        result=execute(self,session)
        if result.get('ok'):self._expected_update_version=result.get('target_version')
        return result

    def update_verify(self):
        if self.app_id!='open_webui':return super().update_verify()
        try:
            version=self.installed_version();running=self.container_status()['running']
            expected=getattr(self,'_expected_update_version',None)
            ok=running and (not expected or version==expected)
            return dict(ok=ok,supported=True,current_version=version,message='Open WebUI läuft mit bestätigter Version.' if ok else 'Version oder Containerzustand weicht ab.')
        except (OSError,ValueError):return dict(ok=False,supported=True,message='Open WebUI nach Update nicht erreichbar.')
