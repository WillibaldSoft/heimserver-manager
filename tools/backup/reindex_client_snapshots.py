#!/usr/bin/python3
"""Local administrator maintenance; keep complete archive bytes unchanged."""
import sys,json,subprocess,fcntl,os
from pathlib import Path
if os.geteuid()!=0:raise SystemExit('Bitte mit sudo ausführen.')
sys.path.insert(0,'/opt/server-manager')
from modules.backup import client_api as api,chunks,reblock
root=api.direct(api.base(0).parent)
roots=[p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p.name.lstrip('-').isdigit() or p.name.startswith('pc-'))]
for p in roots:
 if list(p.glob('.upload-*')):raise SystemExit('Unvollständiger oder aktiver Auftrag vorhanden. Im Client erst prüfen/abschließen/abbrechen. Keine Änderung.')
 with (p/'.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SystemExit('Sicherungsspeicher noch beschäftigt. Keine Änderung.')
active=subprocess.run(['systemctl','is-active','--quiet','server-manager']).returncode==0
print('Der Manager wird für die Umstellung angehalten. Währenddessen keine anderen Manager-Aufträge ausführen. Dies kann bei großen Sicherungen länger dauern.')
if input('Zum Starten UMSTELLEN eingeben: ').strip()!='UMSTELLEN':raise SystemExit('Keine Änderung.')
if active:subprocess.run(['systemctl','stop','server-manager'],check=True)
try:
 # Recheck after stopping the service to cover a request racing the first check.
 for p in roots:
  if list(p.glob('.upload-*')):raise SystemExit('Zwischenzeitlich neuer Auftrag gestartet. Keine Umstellung.')
 for p in roots:
  rows=[m for m in api.listing(p) if m.get('format')==chunks.FORMAT]
  if not rows:continue
  before=chunks.used(p)
  for m in rows:
   print('Prüfen/Umstellen:',m['id'],m.get('component',''),m['bytes']//1024**2,'MiB',flush=True)
   print(json.dumps(reblock.migrate(p,m['id'],api)),flush=True)
  with api.locked(p):removed=chunks.collect_unused(p,api)
  print('Nicht mehr referenzierte Blöcke entfernt:',removed,'Speicher vorher/nachher (MiB):',before//1024**2,chunks.used(p)//1024**2,flush=True)
 print('Umstellung abgeschlossen. Fertige Archiv-Inhalte und IDs unverändert. Neue Sicherung im Client starten.',flush=True)
finally:
 if active:subprocess.run(['systemctl','start','server-manager'],check=True)
