"""Security maintenance notifications using existing ntfy credentials and privacy settings."""
import hashlib,json,os,sqlite3
from pathlib import Path
from types import SimpleNamespace
import server_settings as cfg
from modules.alarms import engine
RECORD=cfg.STATE_DIR/'security-notifications.json'

def context():
 def db():
  path=Path(os.environ.get('SERVER_MANAGER_DB',str(cfg.STATE_DIR/'server-manager.sqlite3')))
  con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=10);con.row_factory=sqlite3.Row;return con
 return SimpleNamespace(db=db)

def send(result):
 try:
  conf=engine.config(context())
  if not conf['enabled'] or not conf['topic']:return 'disabled'
  try:record=json.loads(RECORD.read_text())
  except FileNotFoundError:record={}
  installed=result.get('updated_packages',[])
  # Repeated unchanged pending reboots/services are not sent every two hours.
  event={'failed':result.get('state')=='failed','reboot':bool(result.get('reboot_required')),
         'services':sorted(result.get('pending_services',[])),'packages':sorted(result.get('pending_security_packages',[]))}
  if installed:event['update_job']=result.get('job')
  if not installed and not any(event.values()):
   cfg.atomic(RECORD,{'signature':None});return 'nothing-due'
  signature=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
  if record.get('signature')==signature:return 'unchanged'
  lines=['Security updates / Sicherheitsupdates: '+str(len(installed))+' installed / installiert.']
  if event['failed']:lines.append('Update/check failed / Aktualisierung oder Kontrolle fehlgeschlagen. See Manager log / Manager-Protokoll prüfen.')
  if event['reboot']:lines.append('Server reboot required / Server-Neustart erforderlich. No automatic reboot / Kein automatischer Neustart.')
  if event['services']:lines.append(str(len(event['services']))+' service restarts pending / Dienstneustarts ausstehend.')
  if event['packages']:lines.append(str(len(event['packages']))+' security packages pending / Sicherheitspakete verbleiben.')
  if conf['details']:
   for label,values in [('Updated / Aktualisiert',installed),('Services / Dienste',event['services']),('Pending packages / Verbleibende Pakete',event['packages'])]:
    if values:lines.append(label+': '+', '.join(values)[:1500])
  if not engine.publish(conf,'Heimserver Manager · Security / Sicherheit','\n'.join(lines)):return 'failed'
  cfg.atomic(RECORD,{'signature':signature});return 'sent'
 except Exception:return 'failed'
