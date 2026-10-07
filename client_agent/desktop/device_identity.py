"""Local identifiers are derived locally, never imported from a JSON profile."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,os,json,socket,urllib.request,urllib.error
from pathlib import Path

def identity():
 machine=Path('/etc/machine-id').read_text().strip()
 if len(machine)<16:raise ValueError(tr('Stabile Gerätekennung fehlt (/etc/machine-id).'))
 digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
 return dict(device_id=digest('hsm-device:'+machine),local_user=digest('hsm-user:'+str(os.getuid())))
def headers():
 i=identity();return {'X-HSM-Device':i['device_id'],'X-HSM-User':i['local_user']}
def pair():
 import backup,core
 if not backup.ACCOUNT:raise core.Error(tr('Zuerst am Manager anmelden.'))
 url,opener,access=backup.ACCOUNT;cfg=core.validate(core.load())
 if url!=cfg['SERVER_URL']:raise core.Error(tr('Server geändert; erneut anmelden.'))
 data=dict(identity(),hostname=socket.gethostname(),mac=cfg['CLIENT_MAC'],mode=cfg['CLIENT_MODE'])
 req=urllib.request.Request(url+'/api/account/agent/pair',json.dumps(data).encode(),{'Content-Type':'application/json','X-Server-Manager-CSRF':access['csrf']})
 try:
  with opener.open(req,timeout=30) as response:result=json.load(response)
 except urllib.error.HTTPError as e:
  raise core.Error(tr('Gerätekopplung abgelehnt (HTTP ')+str(e.code)+tr('). Freigabe im Manager prüfen.')) from None
 cfg.update(TOKEN=result['token'],CLIENT_NAME=result['name'],SERVER_MAC=result['server_mac'])
 if cfg['SERVER_MAC'] and cfg['WAKE_METHOD']=='none':cfg['WAKE_METHOD']='wol'
 core.save(cfg)
 return tr('Gekoppelt: ')+result['name']+tr('. Eigenes Token und eigener Schlafblocker gespeichert.')
def enroll(cfg):
 import core
 if not cfg['TOKEN'].startswith('setup:'):return cfg
 if not cfg['SERVER_URL'].startswith('https://'):raise core.Error(tr('Einrichtung benötigt geprüftes HTTPS. Zuerst privates HTTPS einrichten.'))
 data=dict(identity(),hostname=socket.gethostname(),mac=cfg['CLIENT_MAC'],mode=cfg['CLIENT_MODE'],code=cfg['TOKEN'][6:])
 req=urllib.request.Request(cfg['SERVER_URL']+'/api/clients/enroll',json.dumps(data).encode(),{'Content-Type':'application/json'})
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):return None
 try:
  with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as r:result=json.load(r)
 except urllib.error.HTTPError as e:raise core.Error(tr('Einrichtungscode nicht akzeptiert. Neues Profil im Manager herunterladen.')) from None
 result_cfg=dict(cfg,TOKEN=result['token'],CLIENT_NAME=result['name'],SERVER_MAC=result['server_mac'])
 return core.validate(result_cfg)

if __name__=='__main__':
 import sys
 print(headers()['X-HSM-Device' if sys.argv[1]=='device' else 'X-HSM-User'])
