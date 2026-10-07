"""Authenticated per-account/device agents. Legacy profiles remain explicit opt-in."""
import hashlib,re,secrets,json
from flask import request,jsonify,g,current_app

def schema(con):
 con.execute('''CREATE TABLE IF NOT EXISTS client_bindings (
 agent_id INTEGER PRIMARY KEY, account_key TEXT NOT NULL, principal TEXT NOT NULL,
 device_id TEXT NOT NULL, local_user TEXT NOT NULL,
 UNIQUE(account_key,device_id,local_user))''')

def key(p):return p['kind']+':'+p['name']+':'+str(p.get('uid',''))
def fingerprint(value):
 if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise ValueError('Ungültige Geräte-/Benutzerkennung. Client aktualisieren.')
 return value

def authorized(con,agent):
 schema(con);row=con.execute('SELECT * FROM client_bindings WHERE agent_id=?',(agent['id'],)).fetchone()
 if not row:return True
 if any(not re.fullmatch('[a-f0-9]{64}',request.headers.get(h,'')) for h in ('X-HSM-Device','X-HSM-User')):return False
 if not secrets.compare_digest(row['device_id'],request.headers.get('X-HSM-Device','')) or not secrets.compare_digest(row['local_user'],request.headers.get('X-HSM-User','')):return False
 try:
  old=json.loads(row['principal']);auth=current_app.extensions['server_manager_auth'].read()
  if old['kind']=='local':p=dict(kind='local',name=auth['username'],role='admin',revision=auth['revision'])
  else:p=current_app.extensions['server_manager_users'].principal(old['name'],auth['session_secret'])
  if not p or key(p)!=row['account_key'] or p['revision']!=old['revision'] or p.get('stamp')!=old.get('stamp'):return False
  if p['role'] not in ('admin','user') or (p['role']!='admin' and 'client' not in p.get('modules',[])):return False
  g.bound_client=True
  return True
 except (KeyError,ValueError,OSError):return False

def create_agent(con,p,data):
 device=fingerprint(data.get('device_id'));user=fingerprint(data.get('local_user'))
 label=data.get('hostname','Client')
 if not isinstance(label,str) or not re.fullmatch(r'[\w ._-]{1,80}',label):raise ValueError('Ungültiger Gerätename.')
 mac=data.get('mac','').lower()
 if mac and not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',mac):raise ValueError('Ungültige Client-MAC.')
 mode=data.get('mode','without_server')
 if mode not in ('with_server','without_server','wake_on_access'):raise ValueError('Ungültiger Modus.')
 token=secrets.token_urlsafe(32);name=p['name']+' · '+label
 row=con.execute('SELECT agent_id FROM client_bindings WHERE account_key=? AND device_id=? AND local_user=?',(key(p),device,user)).fetchone()
 aid=row['agent_id'] if row else None
 if aid and con.execute('SELECT id FROM client_agents WHERE id=?',(aid,)).fetchone():
  if not con.execute('SELECT enabled FROM client_agents WHERE id=?',(aid,)).fetchone()['enabled']:raise ValueError('Gerätekopplung deaktiviert. Administrator muss sie zuerst freigeben.')
  con.execute('UPDATE client_agents SET token=?,name=?,hostname=?,mac=?,mode=? WHERE id=?',(token,name,label,mac,mode,aid))
 else:
  if row:con.execute('DELETE FROM client_bindings WHERE agent_id=?',(aid,))
  if con.execute('SELECT count(*) FROM client_bindings WHERE account_key=?',(key(p),)).fetchone()[0]>=32:raise ValueError('Maximal 32 Gerätekopplungen pro Konto.')
  aid=con.execute('INSERT INTO client_agents(name,hostname,mac,token,mode,enabled) VALUES(?,?,?,?,?,1)',(name,label,mac,token,mode)).lastrowid
 con.execute('INSERT OR REPLACE INTO client_bindings VALUES(?,?,?,?,?)',(aid,key(p),json.dumps(p),device,user))
 return dict(token=token,name=name,account=p['name'],device_id=device,local_user=user,agent_id=aid)

def register(app,ctx,init_tables,server_mac):
 from .client_setup import register as setup_register
 setup_register(app,ctx,init_tables,server_mac)
 @app.post('/api/account/agent/pair')
 def pair():
  p=g.auth_principal
  if p['role'] not in ('admin','user') or (p['role']!='admin' and 'client' not in p.get('modules',[])):return jsonify(error='Client-Steuerung nicht freigegeben.'),403
  try:
   if request.content_length is None or request.content_length>8192:raise ValueError('Anfrage zu groß.')
   con=ctx.db()
   try:
    init_tables(con);schema(con);con.execute('BEGIN IMMEDIATE')
    result=create_agent(con,p,request.get_json());con.commit()
   finally:con.close()
   result['server_mac']=server_mac()
   return jsonify(result)
  except (ValueError,TypeError,AttributeError) as e:return jsonify(error=str(e)),400


def reported_hostname(con,agent,data):
 label=data.get('hostname')
 if label is None:return
 if not isinstance(label,str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,78}[A-Za-z0-9])?',label):return
 row=con.execute('SELECT principal FROM client_bindings WHERE agent_id=?',(agent['id'],)).fetchone()
 if not row:return
 account=json.loads(row['principal'])['name']
 con.execute('UPDATE client_agents SET hostname=?,name=? WHERE id=?',(label,account+' · '+label,agent['id']))
