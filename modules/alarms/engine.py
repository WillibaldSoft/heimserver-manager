"""Persistent deduplication and explicit ntfy delivery. No credentials in argv/logs."""
import json,re,threading,time,datetime
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler
from . import sources
_lock=threading.Lock()

def initialize(ctx):
    con=ctx.db()
    try:
        con.executescript('''CREATE TABLE IF NOT EXISTS alarm_items(source TEXT,key TEXT,text TEXT,level TEXT,active INTEGER,last_seen REAL,last_sent REAL DEFAULT 0,last_attempt REAL DEFAULT 0,PRIMARY KEY(source,key));
CREATE TABLE IF NOT EXISTS alarm_status(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS sleep_engine_settings(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);''');con.commit()
    finally:con.close()

def config(ctx):
    from modules.storage_monitor.helpers import setting
    val=lambda key,default='':setting(ctx,key,default)
    return dict(enabled=val('ntfy_enabled','0')=='1',url=val('ntfy_url','https://ntfy.sh'),topic=val('ntfy_topic'),token=val('ntfy_token'),automatic=val('alarms_automatic','0')=='1',details=val('alarms_details','0')=='1',interval=int(val('alarms_interval_minutes','5')),daily=val('alarms_daily_enabled','0' if val('alarms_reminder','24')=='0' else '1')=='1',daily_time=val('alarms_daily_time','09:00'),sources=[k for k in sources.LABELS if val('alarms_source_'+k,'1' if k=='storage' else '0')=='1'],services=[k for k in sources.SERVICES if val('alarms_service_'+k,'0')=='1'])

def validate(data,old):
    url=data.get('ntfy_url','').strip().rstrip('/');p=urlsplit(url)
    try:p.port
    except ValueError:raise ValueError('Ungültiger Port.')
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or any(c.isspace() or ord(c)<32 for c in url):raise ValueError('Gültige HTTP(S)-Serveradresse ohne Zugangsdaten oder Query angeben.')
    topic=data.get('ntfy_topic','').strip()
    if topic and not re.fullmatch('[A-Za-z0-9_-]{1,64}',topic):raise ValueError('Topic: maximal 64 Buchstaben, Zahlen, Bindestriche oder Unterstriche verwenden.')
    if data.get('ntfy_enabled')=='1' and not topic:raise ValueError('Für aktiven Versand ein Topic angeben.')
    token=data.get('ntfy_token','').strip() or old['token']
    if data.get('clear_token')=='1':token=''
    if any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('Ungültiger Token.')
    values={'ntfy_url':url,'ntfy_topic':topic,'ntfy_token':token}
    for key,low,high,default in [('disk_warn_percent',1,100,90),('temp_warn_c',1,120,55),('alarms_interval_minutes',1,1440,5)]:
        try:value=int(data.get(key,default))
        except ValueError:raise ValueError('Schwellwerte müssen ganze Zahlen sein.')
        if not low<=value<=high:raise ValueError('Schwellwert außerhalb des erlaubten Bereichs.')
        values[key]=str(value)
    daily_time=data.get('alarms_daily_time','09:00')
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',daily_time):raise ValueError('Erinnerungszeit als HH:MM angeben.')
    values['alarms_daily_time']=daily_time
    for key in ['alarms_daily_enabled','ntfy_enabled','alarms_automatic','alarms_details']+['alarms_source_'+k for k in sources.LABELS]+['alarms_service_'+k for k in sources.SERVICES]:values[key]='1' if data.get(key)=='1' else '0'
    return values

def save(ctx,data):
    values=validate(data,config(ctx));con=ctx.db()
    try:
        con.executemany("INSERT INTO sleep_engine_settings(key,value,updated_at) VALUES(?,?,datetime('now','localtime')) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",values.items());con.commit()
    finally:con.close()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def publish(cfg,title,message):
    if not cfg['enabled'] or not cfg['topic']:return False
    headers={'Content-Type':'application/json'}
    if cfg['token']:headers['Authorization']='Bearer '+cfg['token']
    payload=json.dumps(dict(topic=cfg['topic'],title=title,message=message,tags=['warning']),ensure_ascii=False).encode()
    try:
        parsed=urlsplit(cfg['url'])
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:return False
        req=Request(cfg['url'],data=payload,headers=headers,method='POST')
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=10) as response:
            return 200<=response.status<300
    except Exception:return False

def status(ctx):
    con=ctx.db()
    try:
        return [dict(r) for r in con.execute('SELECT * FROM alarm_items WHERE active=1 ORDER BY source,key')],dict(con.execute('SELECT key,value FROM alarm_status').fetchall())
    finally:con.close()

def check(ctx,send=False):
    if not _lock.acquire(blocking=False):return 'Eine Alarmprüfung läuft bereits.'
    try:
        cfg=config(ctx);now=time.time();sent=failed=0
        for source in cfg['sources']:
            complete=True
            try:items=sources.collect(source,ctx,cfg)
            except Exception:items=[sources.item('collector','Alarmquelle derzeit nicht prüfbar.')];complete=False
            con=ctx.db()
            try:
                prior={r['key']:dict(r) for r in con.execute('SELECT * FROM alarm_items WHERE source=?',(source,))}
                if complete:con.execute('UPDATE alarm_items SET active=0 WHERE source=?',(source,))
                for row in items:
                    previous=prior.get(row['key'],{});last=previous.get('last_sent',0)
                    if not previous.get('active') or (row['level']=='critical' and previous.get('level')!='critical'):last=0
                    attempt=previous.get('last_attempt',0)
                    due=not last or daily_due(cfg,now,last)
                    if send and cfg['enabled'] and due and now-attempt>=300:
                        attempt=now
                        message=row['text'] if cfg['details'] else row.get('notification', 'Im Modul '+sources.LABELS[source]+' liegt eine Warnung vor. Details im Heimserver Manager unter Alarme.')
                        if publish(cfg,'Heimserver Manager · '+sources.LABELS[source],message):last=now;sent+=1
                        else:failed+=1
                    con.execute('INSERT INTO alarm_items VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,key) DO UPDATE SET text=excluded.text,level=excluded.level,active=1,last_seen=excluded.last_seen,last_sent=excluded.last_sent,last_attempt=excluded.last_attempt',(source,row['key'],row['text'],row['level'],1,now,last,attempt))
                con.commit()
            finally:con.close()
        summary=('Vorschau ohne Versand' if not send else 'Versandprüfung')+': '+str(sent)+' gesendet, '+str(failed)+' Versandfehler.'
        con=ctx.db()
        try:
            con.executemany('INSERT INTO alarm_status VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',[('checked',str(now)),('summary',summary)]);con.commit()
        finally:con.close()
        return summary
    finally:_lock.release()

def daily_due(cfg,now,last_sent):
    if not cfg['daily']:return False
    local=datetime.datetime.fromtimestamp(now)
    if local.strftime('%H:%M') < cfg['daily_time']:return False
    return not last_sent or datetime.datetime.fromtimestamp(last_sent).date() < local.date() or datetime.datetime.fromtimestamp(last_sent).strftime('%H:%M') < cfg['daily_time']

def schedule_due(cfg,now,last_check,last_daily):
    day=datetime.datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    daily_slot=cfg['daily'] and datetime.datetime.fromtimestamp(now).strftime('%H:%M')>=cfg['daily_time']
    key=day+' '+cfg['daily_time']
    return now-last_check>=cfg['interval']*60 or (daily_slot and key!=last_daily), key if daily_slot else last_daily

def start(app,ctx):
    if app.testing or app.extensions.get('alarm_worker'):return
    app.extensions['alarm_worker']=True
    def loop():
        last_check=time.time();last_daily=''
        while True:
            time.sleep(30)
            try:
                cfg=config(ctx)
                if not cfg['automatic']:continue
                due,daily=schedule_due(cfg,time.time(),last_check,last_daily)
                if due:
                    result=check(ctx,send=True)
                    if result!='Eine Alarmprüfung läuft bereits.':last_check=time.time();last_daily=daily
            except Exception:pass
    threading.Thread(target=loop,name='alarm-monitor',daemon=True).start()
