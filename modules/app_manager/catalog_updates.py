"""Read-only catalog checks: image configuration digests and APT candidates."""
import json,subprocess,shutil

def command(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=45)
 if r.returncode:raise ValueError('Prüfung fehlgeschlagen: '+args[0]+'. Netzwerk, Registry-Anmeldung bzw. Dienst prüfen.')
 return r.stdout

def result(manager,**values):
 return dict(dict(supported=True,ok=False,state='unknown',label='Nicht prüfbar',app_id=manager.app_id,app_label=manager.label,kind=manager.kind,current_version=None,latest_version=None,update_available=None,safe_to_update=False,requires_backup=True),**values)

def remote_config(manifest,local):
 entries=manifest if isinstance(manifest,list) else [manifest]
 matches=[]
 for entry in entries:
  platform=entry.get('Descriptor',{}).get('platform',{})
  if platform and any(platform.get(k,'')!=local.get(v,'') for k,v in [('os','Os'),('architecture','Architecture')]):continue
  if platform.get('variant') and local.get('Variant') and platform['variant']!=local['Variant']:continue
  digest=entry.get('SchemaV2Manifest',{}).get('config',{}).get('digest') or entry.get('OCIManifest',{}).get('config',{}).get('digest')
  if digest:matches.append(digest)
 if len(set(matches))!=1:raise ValueError('Kein eindeutiges Registry-Image für die installierte Plattform gefunden.')
 return matches[0]

def container_check(manager):
 try:
  if not shutil.which('docker'):return result(manager,ok=True,state='missing',label='Nicht installiert',message='Docker fehlt.')
  names=command(['docker','ps','-a','--format','{{.Names}}']).splitlines()
  if manager.container not in names:return result(manager,ok=True,state='missing',label='Nicht installiert',message='App-Container fehlt.')
  container=json.loads(command(['docker','container','inspect',manager.container]))[0]
  reference=container['Config']['Image'];image=json.loads(command(['docker','image','inspect',container['Image']]))[0]
  remote=remote_config(json.loads(command(['docker','manifest','inspect','--verbose',reference])),image)
  changed=remote!=image['Id'];pinned='@sha256:' in reference
  return result(manager,ok=True,state='available' if changed else 'current',label='Update verfügbar' if changed else 'Aktuell im gewählten Image-Kanal',current_version=image['Id'][:19],latest_version=remote[:19],update_available=changed,method='Registry-Konfigurationsdigest / installierte Plattform',message=('Neues Image für '+reference+' verfügbar.' if changed else 'Installiertes Image entspricht '+reference+'.')+(' Auf festen Digest fixiert; neuere Releases außerhalb dieser Referenz werden nicht geprüft.' if pinned else ' Andere Tags/Versionskanäle werden nicht geprüft.'),details={'image':reference})
 except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError) as exc:return result(manager,message=str(exc),method='Registry-Digest')

def apt_check(manager,names):
 values={name:manager.native_apt_update_check(name,method='APT-Paketindex',requires_backup=True) for name in names}
 present={n:r for n,r in values.items() if r.get('state')!='missing'}
 available=[n for n,r in present.items() if r.get('update_available') is True]
 uncertain=[n for n,r in present.items() if not r.get('ok') or r.get('state') in ('unknown','error')]
 state='available' if available else 'unknown' if uncertain else 'current' if present else 'missing'
 return result(manager,ok=not uncertain,state=state,label={'available':'Update verfügbar','unknown':'Nicht vollständig prüfbar','current':'Aktuell laut APT','missing':'Nicht installiert'}[state],update_available=True if available else None if uncertain or not present else False,method='Lokaler APT-Paketindex',message=('Aktualisierbar: '+', '.join(available)) if available else 'Vergleich mit den konfigurierten Paketquellen. Für aktuelle Ergebnisse zuerst APT-Paketlisten aktualisieren.',details={'packages':values})

def fallback(manager):
 if getattr(manager,'container',None):return container_check(manager)
 if manager.app_id=='shares_mounts':
  from .install_catalog import recipe
  return apt_check(manager,recipe('shares_mounts')['packages'])
 return result(manager,supported=False,message='Keine verlässliche Updatequelle für diese Installation konfiguriert.')

def catalog_check(key):
 from .registry import get_manager
 from .managers.base import BaseManager
 if key=='docker':
  from .docker_setup import PACKAGES
  m=BaseManager();m.app_id='docker';m.label='Docker Engine & Compose';m.kind='native'
  return apt_check(m,PACKAGES)
 manager=get_manager(key)
 if manager is None:
  m=BaseManager();m.app_id=key;m.label=key
  return result(m,ok=True,state='missing',label='Nicht installiert',message='Keine verwaltete Installation erkannt. Nach Installation erneut prüfen.')
 from .lifecycle import installation
 if installation(manager).get('state')=='missing':return result(manager,ok=True,state='missing',label='Nicht installiert',message='Keine installierte App zu aktualisieren.')
 return manager.update_check()
