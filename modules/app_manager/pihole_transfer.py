"""Local Pi-hole v6 Teleporter and bounded exact-domain text exchange."""
import hashlib,io,json,os,re,sqlite3,stat,subprocess,tempfile,zipfile
from pathlib import Path
from . import install_catalog as c,install_runtime as runtime
ROOT=c.ROOT/'pihole-transfer'
LIMIT=50*1024*1024
MEMBERS={'lists':'etc/pihole/gravity.db','config':'etc/pihole/pihole.toml','leases':'etc/pihole/dhcp.leases'}

def target():
 rows=runtime.pihole_existing()
 if len(rows)!=1:raise ValueError('Genau eine lokale Pi-hole-Installation erforderlich.')
 row=rows[0]
 if row['kind']=='native':return {'kind':'native'}
 # Only manager-owned container; validate its Compose ownership first.
 from .pihole_network import current
 path,raw,data,ports,web=current()
 return {'kind':'docker','container':data['services']['app']['container_name']}

def run(args,cwd=None):
 result=subprocess.run(args,cwd=cwd,capture_output=True,timeout=300)
 if result.returncode:raise ValueError('Pi-hole-Austausch fehlgeschlagen. Sicherung und lokalen Pi-hole-Status prüfen.')
 return result.stdout

def export(where,folder):
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
 if where['kind']=='native':run(['pihole-FTL','--teleporter'],cwd=folder)
 else:
  name=where['container'];remote=run(['docker','exec',name,'mktemp','-d','/tmp/manager-teleporter-XXXXXXXX']).decode().strip()
  if not re.fullmatch('/tmp/manager-teleporter-[A-Za-z0-9]+',remote):raise ValueError('Ungültiger temporärer Containerpfad.')
  try:
   run(['docker','exec','-w',remote,name,'pihole-FTL','--teleporter'])
   run(['docker','cp',name+':'+remote+'/.',str(folder)])
  finally:run(['docker','exec',name,'rm','-rf','--',remote])
 files=list(folder.glob('*.zip'))
 if len(files)!=1 or files[0].is_symlink() or files[0].stat().st_size>LIMIT:raise ValueError('Kein eindeutiges Teleporter-ZIP erzeugt.')
 os.chmod(files[0],0o600)
 return files[0]

def inspect(data):
 if len(data)>LIMIT:raise ValueError('Maximal 50 MiB pro Import.')
 try:
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   infos=z.infolist();names=[i.filename for i in infos]
   if len(names)>100 or len(set(names))!=len(names) or sum(i.file_size for i in infos)>200*1024*1024:raise ValueError('Archiv zu groß oder enthält doppelte Dateien.')
   for i in infos:
    p=Path(i.filename)
    if p.is_absolute() or '..' in p.parts or '\\' in i.filename or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:raise ValueError('Unsicherer oder verschlüsselter Archiveintrag.')
   available=[key for key,name in MEMBERS.items() if name in names]
   if not available:raise ValueError('Kein unterstütztes Pi-hole-v6-Teleporter-ZIP. Ältere Formate über Pi-hole selbst importieren.')
   if z.testzip():raise ValueError('Archiv-Prüfsumme fehlerhaft.')
   return available
 except zipfile.BadZipFile:raise ValueError('Ungültiges ZIP-Archiv.') from None

def selected_zip(data,keys):
 available=inspect(data)
 if not keys or set(keys)-set(available):raise ValueError('Keine gültigen Importbestandteile ausgewählt.')
 out=io.BytesIO()
 with zipfile.ZipFile(io.BytesIO(data)) as src,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dst:
  for key in keys:dst.writestr(MEMBERS[key],src.read(MEMBERS[key]))
 return out.getvalue()

def domains(text):
 result=set()
 for raw in text.splitlines():
  value=raw.strip().lower()
  if not value or value.startswith('#'):continue
  try:value=value.encode('idna').decode()
  except UnicodeError:raise ValueError('Ungültige Domain.') from None
  if len(value)>253 or '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):raise ValueError('Nur genaue Domainnamen, eine pro Zeile; keine URLs, Wildcards oder Regex.')
  result.add(value)
 if not result or len(result)>500:raise ValueError('Zwischen 1 und 500 unterschiedliche Domains erforderlich.')
 return sorted(result)

def fritz_export(data,kind):
 if kind not in ('allow','deny'):raise ValueError('Ungültiger Listentyp.')
 inspect(data)
 with tempfile.TemporaryDirectory() as tmp,zipfile.ZipFile(io.BytesIO(data)) as z:
  if MEMBERS['lists'] not in z.namelist():raise ValueError('Keine Listendatenbank im Export.')
  path=Path(tmp)/'gravity.db';path.write_bytes(z.read(MEMBERS['lists']))
  con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
  try:
   con.execute('PRAGMA trusted_schema=OFF')
   rows=con.execute('SELECT domain FROM domainlist WHERE enabled=1 AND type=? ORDER BY domain',(0 if kind=='allow' else 1,)).fetchall()
  finally:con.close()
 values=domains('\n'.join(str(row[0]) for row in rows))
 return ('\n'.join(values)+'\n').encode()

def validate(plan):
 if plan.get('target')!=target():raise ValueError('Pi-hole-Installation geändert; Import erneut vorbereiten.')
 key=plan.get('upload','')
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Ungültiger Upload.')
 path=ROOT/(key+'.upload')
 if path.is_symlink() or not path.is_file() or path.stat().st_size>LIMIT:raise ValueError('Upload nicht verfügbar.')
 data=path.read_bytes()
 if hashlib.sha256(data).hexdigest()!=plan.get('digest'):raise ValueError('Upload verändert.')
 if plan['mode']=='teleporter':selected_zip(data,plan['keys'])
 elif plan['mode'] in ('allow','deny'):domains(data.decode('utf-8-sig'))
 else:raise ValueError('Ungültiger Importmodus.')
 return data

def execute(plan,folder):
 data=validate(plan);where=plan['target'];folder=Path(folder)
 before=export(where,folder/'before-import')
 print('Rücksicherung vor Import: '+str(before),flush=True)
 try:
  if plan['mode']=='teleporter':
   archive=folder/'selected-import.zip';archive.write_bytes(selected_zip(data,plan['keys']));os.chmod(archive,0o600)
   if where['kind']=='native':run(['pihole-FTL','--teleporter',str(archive)])
   else:
    remote='/tmp/manager-import-'+plan['upload']+'.zip';name=where['container']
    try:
     run(['docker','cp',str(archive),name+':'+remote]);run(['docker','exec',name,'pihole-FTL','--teleporter',remote])
    finally:run(['docker','exec',name,'rm','-f','--',remote])
  else:
   values=domains(data.decode('utf-8-sig'));args=['pihole',plan['mode'],*values]
   run(args if where['kind']=='native' else ['docker','exec',where['container'],*args])
  run(['systemctl','restart','pihole-FTL.service'] if where['kind']=='native' else ['docker','restart',where['container']])
  print('Import ausgeführt. DNS-Auflösung, Gruppen und Listen in Pi-hole prüfen. Bei Listen-Abonnements anschließend Gravity aktualisieren. Bei Konfigurationsimport können Adresse und Zugang geändert sein.',flush=True)
 except Exception:raise ValueError('Import fehlgeschlagen oder teilweise erfolgt. Vorherige Teleporter-Sicherung im Auftrag aufbewahrt; keine automatische Rücknahme.') from None
 finally:(ROOT/(plan['upload']+'.upload')).unlink(missing_ok=True)
