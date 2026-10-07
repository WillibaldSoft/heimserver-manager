"""Optional modules; absent configuration preserves existing installations."""
import json
import server_settings as host
FILE=host.CONFIG_DIR/'installation.json'
CATALOG={
 'shares':('Freigaben & Benutzer',('/freigaben',),('shares',),(),'/apps/manage'),
 'kvm':('Virtuelle Maschinen',('/kvm',),('kvm_manager',),('python3-libvirt',),'/apps/kvm/installer'),
 'tv':('TV & Aufnahmen',('/tv',),('tvheadend',),(),'/apps/manage'),
 'photos':('Fotolabor',('/fotolabor',),('fotolabor',),('python3-pil',),'/fotolabor'),
 'scanner':('Scanner API',('/scanner',),('scanner',),(),'/scanner'),
 'dyndns':('DynDNS',('/dyndns',),('dyndns',),(),'/dyndns'),
 'backup':('Backup & Recovery',('/backup',),('backup',),(),'/backup/central'),
 'downloads':('Downloads',('/downloads',),('downloads',),(),'/downloads'),
 'storage':('Speicher und SMART',('/speicher',),('storage_monitor',),('smartmontools',),'/speicher'),
 'alarms':('Alarme',('/alarme',),('alarms',),(),'/alarme'),
 'network':('Heimnetz & Client-Agenten',('/heimnetz','/clients','/presence'),('heimnetz_clients','presence_manager','heimnetz_extra'),(),'/settings/modules'),
 'sleep':('Schlaf & Wake',('/sleep',),('sleep_engine',),(),'/sleep'),
}
def load():
 try:data=json.loads(FILE.read_text())
 except FileNotFoundError:return None
 if not isinstance(data,dict) or not isinstance(data.get('modules'),list) or any(k not in CATALOG for k in data['modules']):raise ValueError('Ungültige Installationsauswahl.')
 return data

def initialize():
 if not FILE.exists():host.atomic(FILE,{'pending':True,'modules':[]})
def selected():
 data=load();return set(CATALOG) if data is None else set(data['modules'])
def plugin_enabled(name):
 key=name.split('.')[1]
 return all(key not in row[2] or ident in selected() for ident,row in CATALOG.items())
def path_enabled(path):
 return all(not any(path==prefix or path.startswith(prefix+'/') for prefix in row[1]) or key in selected() for key,row in CATALOG.items())
def navigation(groups):
 result=[]
 for label,url,children in groups:
  children=[(title,path) for title,path in children if path_enabled(path)]
  if not path_enabled(url):
   if children:url=children[0][1]
   else:continue
  result.append((label,url,children))
 return result

def packages(keys):
 if not isinstance(keys,list) or any(k not in CATALOG for k in keys):raise ValueError('Ungültige Module.')
 return sorted({p for k in keys for p in CATALOG[k][3]})
