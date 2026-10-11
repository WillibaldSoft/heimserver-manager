"""Shared PC system snapshots. Download/mutation requires a manager admin session.

Machine IDs only select a namespace; they never grant access to system archives.
A paired non-admin may see only the date/ID of its machine's completed baseline.
Personal data continues to use the existing isolated account/agent namespace.
"""
import re,sqlite3
from flask import request,g

def machine(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise ValueError('Gültige PC-Kennung erforderlich. Client aktualisieren und koppeln.')
    return value

def admin():
    p=getattr(g,'auth_principal',{})
    return request.path=='/api/account/backup' and (p.get('role')=='admin' or (p.get('role')=='user' and 'client' in p.get('modules',[]) and p.get('system_backup') is True))

def current(ctx,agent):
    device=machine(request.headers.get('X-HSM-Device',''))
    if admin():return device
    if ctx is None or not hasattr(ctx,'db'):raise ValueError('Benutzer und PC zuerst im Manager koppeln.')
    from modules.heimnetz_extra.client_bindings import key
    con=ctx.db()
    try:
        if request.path=='/api/account/backup':
            row=con.execute('SELECT b.device_id FROM client_bindings b JOIN client_agents a ON a.id=b.agent_id WHERE b.account_key=? AND b.device_id=? AND b.local_user=? AND a.enabled=1',
                (key(g.auth_principal),device,request.headers.get('X-HSM-User',''))).fetchone()
        else:
            row=con.execute('SELECT device_id FROM client_bindings WHERE agent_id=? AND device_id=? AND local_user=?',
                (agent['id'],device,request.headers.get('X-HSM-User',''))).fetchone()
        if not row:raise ValueError('Benutzer und PC zuerst im Manager koppeln.')
        return device
    except sqlite3.OperationalError:raise ValueError('Benutzer und PC zuerst im Manager koppeln.') from None
    finally:con.close()

def root(api,device):
    path=api.direct(api.base(0).parent/('pc-'+machine(device)))
    path.mkdir(mode=0o700,exist_ok=True)
    return path

def status(api,ctx,agent):
    device=current(ctx,agent);rows=api.listing(root(api,device))
    completed=[r for r in rows if r.get('component')=='system' and r.get('device_id')==device]
    latest=completed[0] if completed else None
    personal=[r for r in api.listing(api.base(agent['id'])) if r.get('component')=='personal' and r.get('device_id')==device]
    return dict(personal=({k:personal[0][k] for k in ('id','created')} if personal else None),device_id=device,system=({k:latest[k] for k in ('id','created')} if latest else None),system_admin=admin())

def metadata(api,ctx,agent,pc):
    if pc:
        if not admin():raise ValueError('Gemeinsamer Systemstand: Manager-Administrator oder Benutzer mit Systemsicherungsfreigabe anmelden.')
        return dict(component='system',device_id=machine(pc))
    if request.args.get('personal')=='1':
        device=current(ctx,agent);ref=request.get_json(silent=True) or {}
        baseline=api.identifier(ref.get('system_id')) if ref.get('system_id') else ''
        if baseline and not any(r['id']==baseline and r.get('component')=='system' for r in api.listing(root(api,device))):
            raise ValueError('Gemeinsamer Systemstand fehlt oder wurde entfernt.')
        name=ref.get('personal_user','');home=ref.get('personal_home','')
        if name and not re.fullmatch('[a-z_][a-z0-9_-]*',name):raise ValueError('Ungültiger persönlicher Benutzer.')
        if home and not re.fullmatch('/home/[a-zA-Z0-9_.-]+',home):raise ValueError('Ungültiger persönlicher Home-Pfad.')
        return dict(component='personal',device_id=device,system_id=baseline,personal_user=name,personal_home=home)
    return {}

def visible(api):
    if not admin():return []
    rows=[]
    for path in api.base(0).parent.glob('pc-*'):
        if not re.fullmatch('pc-[a-f0-9]{64}',path.name) or path.is_symlink():continue
        for item in api.listing(api.direct(path)):
            rows.append(dict(item,shared_pc=path.name[3:],source_agent=0,source_label=item.get('source_host','')))
    return rows
