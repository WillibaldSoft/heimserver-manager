"""Read-only alarm adapters; no repair, update or backup is started here."""
import glob,hashlib,os,subprocess,time,json
from server_settings import get
LABELS={'kvm':'Virtuelle Maschinen','storage':'Speicher & SMART','backup':'Sicherungen','dyndns':'DynDNS','certificates':'Zertifikate','services':'Systemdienste'}
SERVICES={'apache2.service':'Apache','fail2ban.service':'Fail2ban','tvheadend.service':'Tvheadend','scanner-api.service':'Scanner-API','docker.service':'Docker','smbd.service':'SMB','nfs-server.service':'NFS'}

def item(key,text,level='warning'):
    return dict(key=hashlib.sha256(str(key).encode()).hexdigest()[:24],text=text,level=level)

def collect(source,ctx,cfg):
    result=[]
    if source=='kvm':return kvm_alerts(ctx)
    if source=='storage':
        from modules.storage_monitor.monitor import check_storage
        for p in check_storage(ctx,send=False)['problems']:
            row=p.get('row',{})
            alarm=item(p['type']+':'+str(row.get('mount') or row.get('dev')),p['text'],'critical' if p['level']=='CRIT' else 'warning')
            from modules.storage_monitor.disks import mount_description
            identity=dict(mountpoints=[row['mount']]) if row.get('mount') else row
            alarm['notification']='Speicherwarnung: '+str(row.get('dev') or row.get('fs') or '')+' · '+mount_description(identity)+'. Details unter Alarme.'
            result.append(alarm)
    elif source=='backup':
        for p in get('backup_items'):
            if not p.get('required',True):continue
            from modules.backup.daily import monitored
            scheduled=monitored(p)
            if scheduled is not None:
                if scheduled['state']!='OK':result.append(item(p['name'],'Sicherung fehlt oder ist überfällig: '+p['name'],'warning' if scheduled['state']=='WARN' else 'critical'))
                continue
            matches=[f for f in glob.glob(os.path.join(p['path'],p['pattern'])) if os.path.exists(f)]
            if not matches:result.append(item(p['name'],'Sicherung fehlt: '+p['name'],'critical'));continue
            age=(time.time()-max(os.path.getmtime(f) for f in matches))/3600
            if age>int(p['warn_h']):result.append(item(p['name'],'Sicherung überfällig: '+p['name'],'critical' if age>int(p['crit_h']) else 'warning'))
        from modules.backup.daily import state as daily_state
        if daily_state().get('state')=='failed':result.append(item('daily-chain','Tägliche Sicherungskette fehlgeschlagen. Details unter Backup & Recovery.','critical'))
        from modules.backup.external import status as external_status
        if external_status().get('state') in ('failed','interrupted'):result.append(item('external-backup','Externe Gesamtsicherung fehlgeschlagen oder unterbrochen. Details unter Backup & Recovery.','critical'))
        from modules.backup.central import status
        job=status()
        if job.get('state')=='failed':result.append(item('central-job','Letzte zentrale Serversicherung fehlgeschlagen.','critical'))
    elif source=='dyndns':
        from modules.dyndns import engine
        config=engine.load()
        for p in config['providers']:
            if not p.get('enabled'):continue
            state=engine.provider_state(p['id']);stamp=state.get('checked',0)
            if state.get('status') in ('error','limited'):
                result.append(item(p['id'],'DynDNS-Fehler: '+p.get('name',p['host']),'critical'))
            elif not stamp or time.time()-float(stamp)>max(1800,int(config.get('interval',5))*180):
                result.append(item(p['id'],'DynDNS-Prüfung fehlt oder ist veraltet: '+p.get('name',p['host'])))
    elif source=='certificates':
        from modules.web_security.engine import certificates
        for cert in certificates():
            if cert['state'] in ('expired','not_yet_valid','critical','warning','unknown'):
                result.append(item(cert['name'],'Zertifikat '+cert['name']+': '+str(cert.get('days','?'))+' Tage Restlaufzeit / '+cert['state'],'critical' if cert['state'] in ('expired','not_yet_valid','critical') else 'warning'))
    elif source=='services':
        for unit in cfg['services']:
            proc=subprocess.run(['systemctl','show',unit,'--property=LoadState,ActiveState','--no-pager'],capture_output=True,text=True,timeout=10)
            if proc.returncode:raise ValueError('Dienststatus nicht lesbar')
            values=dict(line.split('=',1) for line in proc.stdout.splitlines() if '=' in line)
            if values.get('LoadState')=='not-found':result.append(item(unit,SERVICES[unit]+': Dienst nicht installiert.'));continue
            if values.get('ActiveState') not in ('active','activating','reloading'):result.append(item(unit,SERVICES[unit]+': Dienst nicht aktiv.','critical'))
    return result


def kvm_alerts(ctx):
    from modules.kvm_manager import blocker_provider as provider,backend
    result=[];names={};active={}
    if provider.local_installation_present():
        try:
            with backend.connection() as conn:
                for dom in conn.listAllDomains():
                    uid=dom.UUIDString();names[uid]=dom.name()
                    if dom.isActive():active[uid]=dom.name()
                    if dom.info()[0]==6:result.append(item('crashed:'+uid,'VM '+dom.name()+': abgestürzt.','critical'))
        except Exception:
            result.append(item('connection','KVM-Status nicht prüfbar. Verbindung zu libvirt prüfen.','critical'))
    con=ctx.db()
    try:
        tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'kvm_jobs' in tables:
            rows=con.execute("SELECT * FROM kvm_jobs WHERE id IN (SELECT max(id) FROM kvm_jobs GROUP BY vm,action) AND state IN ('failed','interrupted') AND created >= datetime('now','localtime','-7 days') ORDER BY id DESC LIMIT 30").fetchall()
            labels={'schedule-shutdown':'Herunterfahren','schedule-shutdown-all':'VMs herunterfahren','backup':'Sichern','restore-backup':'Wiederherstellen','start':'Starten','shutdown':'Herunterfahren'}
            for row in rows:
                label=labels.get(row['action'],row['action']);subject=names.get(row['vm'],row['vm'] or 'VM-Auftrag')
                reason=next((line.strip() for line in row['log'].splitlines() if line.startswith('Fehler:')),'Protokoll unter Virtuelle Maschinen → Aufträge prüfen.')[:400]
                alarm=item('job:'+str(row['id']),'VM '+subject+' · '+label+' (#'+str(row['id'])+'): '+('fehlgeschlagen' if row['state']=='failed' else 'unterbrochen')+'. '+reason,'critical' if row['state']=='failed' else 'warning')
                alarm['notification']='VM-Auftrag #'+str(row['id'])+' ('+label+'): '+('fehlgeschlagen' if row['state']=='failed' else 'unterbrochen')+'. Details unter Virtuelle Maschinen → Aufträge.'
                result.append(alarm)
        if 'kvm_shutdown_requests' in tables:
            for row in con.execute('SELECT vm,requested FROM kvm_shutdown_requests'):
                if row['vm'] in active and time.time()-row['requested']>=300:
                    alarm=item('shutdown:'+row['vm'],'VM '+active[row['vm']]+': fünf Minuten nach der Herunterfahr-Anfrage noch aktiv. Der Server wartet; VM prüfen.','critical')
                    alarm['notification']='Eine VM reagiert seit mindestens fünf Minuten nicht auf das reguläre Herunterfahren. Der Server bleibt an. Details unter Alarme.'
                    result.append(alarm)
        if 'sleep_engine_settings' in tables:
            row=con.execute("SELECT value FROM sleep_engine_settings WHERE key='manual_shutdown_status'").fetchone()
            state=json.loads(row['value']) if row else {}
            if state.get('state') in ('failed','interrupted'):
                alarm=item('manual-shutdown','Manuelle Server-Aktion nicht abgeschlossen: '+state.get('message','Status unter Schlaf & Wake prüfen.'),'critical')
                alarm['notification']='Manuelle Server-Aktion nicht abgeschlossen. VM-Zustände und Blocker unter Schlaf & Wake prüfen.'
                result.append(alarm)
    finally:con.close()
    return result
