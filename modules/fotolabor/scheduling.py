"""Manager-style background scheduler using the same serialized job worker."""
import datetime,json,threading,time

_STARTED=False


def next_time(clock,days,after=None):
    after=after or datetime.datetime.now()
    hour,minute=map(int,clock.split(':'))
    if not 0<=hour<24 or not 0<=minute<60 or not days or any(d not in range(7) for d in days):
        raise ValueError('Ungültige Zeit oder Wochentage')
    for i in range(8):
        day=(after+datetime.timedelta(days=i)).replace(hour=hour,minute=minute,second=0,microsecond=0)
        if day>after and day.weekday() in days:return int(day.timestamp())
    raise ValueError('Kein nächster Termin')


def tick(service,now=None):
    now=int(now or time.time())
    rows=service.query('SELECT * FROM fotolabor_schedules WHERE enabled=1 AND next_at<=? ORDER BY next_at',(now,))
    for row in rows:
        selection=json.loads(row['options']);selection['_schedule_id']=row['id']
        try:service.start(row['mode'],selection=selection)
        except ValueError:return  # Busy jobs keep the schedule due until the worker is free.
        except Exception as exc:service.execute('UPDATE fotolabor_schedules SET last_error=? WHERE id=?',(str(exc),row['id']))


def start(service):
    global _STARTED
    if _STARTED:return
    _STARTED=True
    def loop():
        while True:
            try:tick(service)
            except Exception:pass
            time.sleep(30)
    threading.Thread(target=loop,name='fotolabor-scheduler',daemon=True).start()


def get_rtc_candidates(ctx=None):
    from .blocker_provider import _SERVICE
    if _SERVICE is not None:ctx=_SERVICE.ctx
    if ctx is None:return []
    con=ctx.db()
    try:rows=con.execute('SELECT name,next_at FROM fotolabor_schedules WHERE enabled=1').fetchall()
    finally:con.close()
    now=int(time.time())
    return [{'source':'fotolabor','title':r['name'],'ts':max(r['next_at']-120,now+1),
             'target_time':datetime.datetime.fromtimestamp(r['next_at']).strftime('%Y-%m-%d %H:%M:%S'),'priority':60}
            for r in rows if r['next_at']>now]
