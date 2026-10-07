"""Wake for existing enabled app-backup timers and stay awake around their start."""
import datetime,json,re,subprocess,time
PATTERN=re.compile(r'^server-manager-appbackup-[a-z0-9_-]+\.timer$')

def upcoming():
    result=subprocess.run(['systemctl','list-timers','--no-pager','--output=json','server-manager-appbackup-*.timer'],capture_output=True,text=True,timeout=10)
    if result.returncode:raise RuntimeError('App-Backup-Zeitpläne nicht prüfbar.')
    rows=json.loads(result.stdout);out=[]
    for row in rows:
        unit=row.get('unit','')
        if not PATTERN.fullmatch(unit):continue
        stamp=int(row.get('next') or 0)//1000000
        if stamp:out.append((unit,stamp))
    return out

def get_rtc_candidates(ctx=None):
    now=int(time.time())
    return [dict(source='app_backup',title='App-Sicherung: '+unit.removeprefix('server-manager-appbackup-').removesuffix('.timer'),ts=max(now+1,stamp-120),target_time=datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M:%S'),priority=60)
            for unit,stamp in upcoming() if stamp>now]

def get_blockers(ctx=None):
    now=int(time.time())
    return [dict(source='App Manager',type='backup-prewake',title='Geplante App-Sicherung',reason=unit.removeprefix('server-manager-appbackup-').removesuffix('.timer')+' startet in Kürze.',priority=80)
            for unit,stamp in upcoming() if -60<=stamp-now<=180]
