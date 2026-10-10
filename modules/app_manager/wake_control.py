"""Daily wake policy for Nextcloud/DAV requests only; Recovery stays independent."""
import hashlib,json,os,secrets,tempfile,time
from pathlib import Path
from flask import g,request,session,redirect,abort
from ui_translation import html_literal as html,text
from .install_ui import token,esc

# HSM_NEXTCLOUD_CONTROL_V2: applies only to this Nextcloud gateway.
CONTROL = Path('/etc/server-manager-nextcloud-wake-control.json')
def wake_enabled():
    try:
        config = json.loads(CONTROL.read_text())
        mode = config.get('mode')
        if mode in ('active', 'inactive'):return mode == 'active'
        if mode != 'schedule' or type(config.get('default')) is not bool:return False
        now = time.localtime();minute = now.tm_hour * 60 + now.tm_min
        result = config['default']
        for entry in config['periods']:
            start,end = entry['start'],entry['end']
            if type(start) is not int or type(end) is not int or not 0 <= start < 1440 or not 0 <= end < 1440 or start == end or type(entry['enabled']) is not bool:return False
            if (start <= minute < end if start < end else minute >= start or minute < end):result = entry['enabled']
        return result
    except FileNotFoundError:return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):return False



def load():
    try:return json.loads(CONTROL.read_text())
    except FileNotFoundError:return dict(mode='active',default=False,periods=[])
    except (OSError,ValueError):return dict(mode='inactive',default=False,periods=[])
def revision():
    try:return hashlib.sha256(CONTROL.read_bytes()).hexdigest()
    except FileNotFoundError:return 'missing'
def supported():
    try:return 'HSM_NEXTCLOUD_WAKE_CONTROL_V2' in Path('/opt/server-manager-nextcloud-wake/gateway.py').read_text()
    except OSError:return False

def parse(form):
    mode=form.get('mode')
    if mode not in ('active','inactive','schedule'):raise ValueError('Ungültiger Modus.')
    default=form.get('default')
    if default not in ('active','inactive'):raise ValueError('Ungültiger Grundzustand.')
    periods=[];occupied=set()
    def minutes(raw):
        if len(raw)!=5 or raw[2]!=':' or not raw[:2].isdigit() or not raw[3:].isdigit():raise ValueError('Uhrzeit als HH:MM angeben.')
        h,m=map(int,raw.split(':'))
        if h>23 or m>59:raise ValueError('Ungültige Uhrzeit.')
        return h*60+m
    for i in range(8):
        a=form.get('start'+str(i),'');b=form.get('end'+str(i),'')
        if not a and not b:continue
        start,end=minutes(a),minutes(b);state=form.get('state'+str(i))
        if start==end:raise ValueError('Von und bis dürfen nicht gleich sein.')
        if state not in ('active','inactive'):raise ValueError('Ungültiger Zeitraum-Zustand.')
        covered=set(range(start,end)) if start<end else set(range(start,1440))|set(range(end))
        if occupied & covered:raise ValueError('Zeiträume dürfen sich nicht überschneiden.')
        occupied|=covered;periods.append(dict(start=start,end=end,enabled=state=='active'))
    return dict(mode=mode,default=default=='active',periods=periods)

def save(value):
    fd,tmp=tempfile.mkstemp(prefix='.nextcloud-wake-',dir=CONTROL.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,CONTROL)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def card():
    body=html("<div class='card'><h3>Nextcloud / DAVx5: Server wecken</h3><p>Nur das Aufwecken durch Nextcloud-/DAVx5-Anfragen steuern. Recovery-API, Home Assistant und Client-Aufweckbefehle bleiben unabhängig. Ein bereits laufender Server bleibt erreichbar; bereits gesendete Aufweckbefehle werden nicht rückgängig gemacht.</p>")
    if not supported():return body+html('<p>Schalter noch nicht verfügbar: den installierten Nextcloud-Wake-Gateway zuerst aktualisieren.</p></div>')
    c=load()
    body+=html('<p>Aufwecken jetzt: <b>')+text('Aktiv' if wake_enabled() else 'Inaktiv')+html('</b> · ')+esc(time.strftime('%H:%M %Z'))+html('</p>')
    if getattr(g,'auth_principal',{}).get('role')!='admin':return body+html('</div>')
    def select(name,selected,schedule=False):
        opts=[('active','Aktiv'),('inactive','Inaktiv')]+([('schedule','Zeitplan')] if schedule else [])
        return "<select name='"+name+"'>"+''.join("<option value='"+v+"'"+(' selected' if selected==v else '')+">"+text(label)+"</option>" for v,label in opts)+"</select>"
    body+=html("<form method='post' action='/apps/nextcloud/wake/control'>")+token()+"<input type='hidden' name='revision' value='"+revision()+"'>"
    body+=html('<p><label>Modus: ')+select('mode',c.get('mode'),True)+html('</label></p><details><summary>Tägliche Zeiträume einstellen</summary><p>Bis zu acht Zeiträume täglich, auch über Mitternacht. Es gilt die lokale Uhrzeit dieses Dauerläufers; die Endzeit gehört nicht mehr zum Zeitraum. Überschneidungen sind nicht erlaubt. Der Zeitplan wirkt nur im Modus Zeitplan.</p><p><label>Außerhalb der Zeiträume: ')+select('default','active' if c.get('default') else 'inactive')+html('</label></p><table><thead><tr><th>Von</th><th>Bis</th><th>Aufwecken</th></tr></thead><tbody>')
    periods=c.get('periods',[])
    for i in range(8):
        p=periods[i] if i<len(periods) else {}
        fmt=lambda value:('%02d:%02d'%(value//60,value%60)) if value is not None else ''
        body+="<tr><td><input type='time' name='start"+str(i)+"' value='"+fmt(p.get('start'))+"'></td><td><input type='time' name='end"+str(i)+"' value='"+fmt(p.get('end'))+"'></td><td>"+select('state'+str(i),'active' if p.get('enabled',True) else 'inactive')+"</td></tr>"
    return body+html('</tbody></table></details><p><button>Übernehmen</button></p></form></div>')

def register(app):
    @app.post('/apps/nextcloud/wake/control')
    def change_wake_control():
        if getattr(g,'auth_principal',{}).get('role')!='admin':abort(403)
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):abort(403)
        if not supported() or request.form.get('revision')!=revision():abort(409)
        try:config=parse(request.form)
        except ValueError as exc:return esc(text(str(exc))),400
        save(config)
        return redirect('/apps/nextcloud/wake',303)
