"""Read and narrowly edit explicit external redirects in enabled Apache sites."""
import re,base64,json,fnmatch
from pathlib import Path
from urllib.parse import urlsplit
from . import engine as e,apache_editor as editor

RULE=re.compile(r'^(\s*RewriteRule\s+)(\S+)(\s+)(https?://\S+)(\s+\[([^\]]+)\]\s*)$',re.I)
DIRECT=re.compile(r'^(\s*Redirect\s+)(301|302|303|307|308|permanent|temp)(\s+)(\S+)(\s+)(https?://\S+)(\s*)$',re.I)

DISABLED='# server-manager-redirect-disabled: '
REMOVED='# server-manager-redirect-deleted (HTTP 410 remains)'

def gone(original):
 match=RULE.fullmatch(original)
 if match:return match[1]+match[2]+match[3]+'- [G,L]'
 match=DIRECT.fullmatch(original)
 if match:return match[1]+'gone'+match[3]+match[4]
 raise e.Problem('Weiterleitung nicht unterstützt.')

def rows(row):
 result=[];host='';ports='';lines=row['content'].splitlines()
 for index,line in enumerate(lines):
  disabled=False;original=line
  if index and lines[index-1].startswith(DISABLED):
   try:
    original=base64.b64decode(lines[index-1][len(DISABLED):],validate=True).decode()
    if '\n' in original or '\r' in original or gone(original)!=line:continue
    disabled=True
   except (ValueError,UnicodeError):continue
   line=original
  if re.match(r'\s*<VirtualHost\b',line,re.I):host='';ports=line.strip()
  match=re.match(r'\s*ServerName\s+(\S+)',line,re.I)
  if match:host=match[1]
  match=RULE.fullmatch(line);direct=DIRECT.fullmatch(line)
  if match and not re.search(r'(?:^|,)\s*R(?:=(?:301|302|303|307|308))?\s*(?:,|$)',match[6],re.I):match=None
  if match or direct:
   result.append(dict(site=row['name'],base_hash=row['base_hash'],line=index,host=host or 'Standard-Host',ports=ports,target=match[4] if match else direct[6],kind='rewrite' if match else 'redirect',disabled=disabled,original=original))
  if re.match(r'\s*</VirtualHost>',line,re.I):host='';ports=''
 return result

def discover():
 result=[];warnings=[]
 for file in sorted((e.APACHE/'sites-enabled').glob('*.conf'))[:100]:
  try:result.extend(rows(editor.read(file.name)))
  except (OSError,ValueError):warnings.append('Website nicht auswertbar: '+file.name)
 return result,warnings

def target(value):
 value=str(value).strip()
 # Preserve only familiar existing Apache path placeholders; reject directive injection.
 checked=value.replace('%{REQUEST_URI}','').replace('$1','').replace('$2','')
 if not checked or re.search(r'[\s\x00-\x1f\x7f"\x27<>\\$%{}#]',checked):raise e.Problem('HTTP(S)-Ziel ohne Leerzeichen oder Apache-Anweisungen angeben. Zulässige Platzhalter: %{REQUEST_URI}, $1, $2.')
 try:
  parsed=urlsplit(checked);port=parsed.port
 except ValueError:raise e.Problem('Ungültige Zieladresse.') from None
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise e.Problem('Vollständige HTTP(S)-Zieladresse ohne Zugangsdaten angeben.')
 return value

def plan(data):
 row=editor.read(data.get('site',''))
 if row['base_hash']!=data.get('base_hash'):raise e.Problem('Konfiguration geändert. Weiterleitungen neu laden.')
 try:index=int(data.get('line',''))
 except ValueError:raise e.Problem('Weiterleitung erneut auswählen.')
 entry=next((v for v in rows(row) if v['line']==index),None)
 if not entry:raise e.Problem('Weiterleitung nicht mehr vorhanden.')
 lines=row['content'].splitlines(keepends=True);old=entry['original'];ending='\n' if lines[index].endswith('\n') else ''
 match=RULE.fullmatch(old) if entry['kind']=='rewrite' else DIRECT.fullmatch(old)
 operation=data.get('operation')
 if operation in ('remove','disable'):
  if entry['disabled']:raise e.Problem('Weiterleitung ist bereits ausgeschaltet.')
  new=DISABLED+base64.b64encode(old.encode()).decode()+'\n'+gone(old)
 elif operation=='enable':
  if not entry['disabled']:raise e.Problem('Weiterleitung ist bereits eingeschaltet.')
  new=old
 elif operation=='delete':
  new=REMOVED+'\n'+gone(old)
 elif operation=='change':
  if 'target_base' in data:
   if not entry['target'].endswith('%{REQUEST_URI}'):raise e.Problem('Weiterleitung erneut laden.')
   base=target(data.get('target_base',''))
   if any(char in base for char in ('%', '$', '?')):raise e.Problem('Zieladresse ohne Platzhalter oder Suchparameter angeben; der Unterpfad wird automatisch übernommen.')
   value=base.rstrip('/')+'%{REQUEST_URI}'
  else:value=target(data.get('target',''))
  if entry['kind']=='rewrite':new=match[1]+match[2]+match[3]+value+match[5]
  else:new=''.join(match[i] for i in range(1,6))+value+match[7]
 else:raise e.Problem('Gültige Weiterleitungsaktion auswählen.')
 if operation=='change' and entry['disabled']:new=DISABLED+base64.b64encode(new.encode()).decode()+'\n'+gone(new)
 lines[index]=new+ending
 if entry['disabled']:del lines[index-1]
 return editor.plan('edit_apache_site',dict(site=row['name'],base_hash=row['base_hash'],content=''.join(lines),enabled='yes' if row['enabled'] else 'no'))

def add_plan(data):
 domain=e.hostname(data.get('domain',''))
 destination=target(data.get('target_base',''))
 if any(char in destination for char in ('%', '$', '?')):raise e.Problem('Zielbasis ohne Platzhalter oder Suchparameter angeben.')
 parsed=urlsplit(destination)
 if parsed.hostname.lower()==domain:raise e.Problem('Quelle und Ziel müssen unterschiedliche Hostnamen haben, um Schleifen zu vermeiden.')
 if e.service('apache2.service')!='active':raise e.Problem('Apache muss installiert sein und laufen.')
 if not (e.APACHE/'mods-enabled/rewrite.load').exists():raise e.Problem('Apache-Modul rewrite fehlt; zuerst unter Web & Sicherheit einrichten.')
 path=e.APACHE/'sites-available'/('server-manager-redirect-'+domain+'.conf')
 link=e.APACHE/'sites-enabled'/path.name
 if path.exists() or path.is_symlink() or link.exists() or link.is_symlink():raise e.Problem('Eine Datei für diese Domain besteht bereits. Vorhandene Website bearbeiten.')
 sources=editor.included_files()
 for source in sources:
  for line in source.read_text(errors='replace').splitlines():
   match=re.match(r'\s*Server(?:Name|Alias)\s+(.+)',line,re.I)
   if match and any(fnmatch.fnmatch(domain,name.strip(chr(34)+chr(39)).lower().removeprefix('https://').removeprefix('http://').split(':')[0]) for name in match[1].split()):raise e.Problem('Ausgangsadresse bereits in Apache eingerichtet. Vorhandene Weiterleitung bearbeiten; bestehende Websites werden nicht ersetzt.')
 destination=destination.rstrip('/')
 content='# Managed HTTP redirect by Server Manager\n<VirtualHost *:80>\n ServerName '+domain+'\n RewriteEngine On\n RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/\n RewriteRule ^ '+destination+'%{REQUEST_URI} [R=302,L,NE]\n</VirtualHost>\n'
 return dict(action='add_nextcloud_redirect',data=dict(domain=domain,target_base=destination),snapshot={str(p):e.local_hash(p) for p in sorted(sources)},content=content,steps=['Neue HTTP-Weiterleitung: http://'+domain+' → '+destination,'Unterpfade bleiben erhalten. Vorläufige Weiterleitung (302) erlaubt spätere Zielwechsel ohne dauerhaften Browser-Cache.','DNS und Router werden nicht geändert. Die Ausgangsadresse muss diesen Server erreichen. HTTPS der Ausgangsadresse benötigt zusätzlich ein Zertifikat.','Neue Website-Datei anlegen, Apache prüfen und neu laden; bei Fehlern neue Datei entfernen und bisherigen Zustand wieder laden.'])

def add_execute(p,folder):
 domain=p['data']['domain'];path=e.APACHE/'sites-available'/('server-manager-redirect-'+domain+'.conf');link=e.APACHE/'sites-enabled'/path.name
 # Exclusive creation prevents overwriting a concurrently created file.
 created=False;linked=False;reloaded=False
 e.atomic(folder/'created-website.json',dict(site=str(path),enabled=str(link)))
 try:
  with path.open('x') as out:created=True;out.write(p['content'])
  path.chmod(0o644)
  link.symlink_to('../sites-available/'+path.name);linked=True
  e.run(['apache2ctl','configtest']);reloaded=True;e.run(['systemctl','reload','apache2.service'])
 except Exception:
  if linked:link.unlink()
  if created:path.unlink()
  if reloaded:e.run(['apache2ctl','configtest']);e.run(['systemctl','reload','apache2.service'])
  raise
 return {'message':'HTTP-Weiterleitung angelegt. Für HTTPS der Ausgangsadresse zusätzlich ein Zertifikat unter Web & Sicherheit einrichten.'}
