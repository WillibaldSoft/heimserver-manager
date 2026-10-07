"""Bridge to the sleep scheduler; only graceful guest shutdown is requested."""
import json
from . import blocker_provider
MODES={'block':'Server wach halten', 'managed':'Durch Schlaf & Wake herunterfahren', 'ignore':'Keinen Blocker melden'}

def managed_blocker(row):
    return row.get('source')=='KVM' and row.get('type') in ('kvm-managed-vm','kvm-schedule-job')

def prepare(decision,manual=False):
    rows=decision.get('blockers',[])
    if not rows or any(not managed_blocker(row) for row in rows):return
    service=blocker_provider._SERVICE
    if service is None:raise RuntimeError('KVM-Modul nicht initialisiert')
    if service.active():return
    recent=set()
    if not manual:
        with service.db() as con:
            jobs=con.execute("SELECT vm,action,payload FROM kvm_jobs WHERE action IN ('schedule-shutdown','schedule-shutdown-all') AND created > datetime('now','localtime','-5 minutes')").fetchall()
        for job in jobs:
            if job['action']=='schedule-shutdown':recent.add(job['vm'])
            else:recent.update(json.loads(job['payload']).get('vms',[]))
    uids=list(dict.fromkeys(row['vm'] for row in rows if row.get('vm') and row['vm'] not in recent and service.sleep_mode(row['vm'])=='managed'))
    if len(uids)==1:return service.submit('schedule-shutdown',uids[0],{})
    if uids:return service.submit('schedule-shutdown-all',uids[0],{'vms':uids})
