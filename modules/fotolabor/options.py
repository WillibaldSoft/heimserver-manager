"""Validated, persisted scan scope and per-worker load controls."""
import os,time
from pathlib import PurePosixPath


def relative(value):
    value=str(value).strip().strip('/') if not str(value).startswith('/') else str(value)
    if not value or value=='.':return ''
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or '\x00' in value:
        raise ValueError('Nur relative Ordner innerhalb des Fotolabors verwenden')
    return str(p)


def validate(selection):
    value=dict(selection)
    value['folder']=relative(value.get('folder',''))
    excludes=value.get('exclude',[])
    if isinstance(excludes,str):excludes=excludes.splitlines()
    if not isinstance(excludes,list) or len(excludes)>100:raise ValueError('Ungültige Ausschlussliste')
    value['exclude']=sorted(set(relative(x) for x in excludes if str(x).strip()))
    if '' in value['exclude']:raise ValueError('Nicht den gesamten Bestand ausschließen')
    value['gentle']=bool(value.get('gentle',False))
    value['max_load']=float(value.get('max_load',0) or 0)
    if not 0<=value['max_load']<=128:raise ValueError('Lastgrenze muss zwischen 0 und 128 liegen')
    return value


def includes(selection,path):
    folder=selection.get('folder','')
    if folder and path!=folder and not path.startswith(folder+'/'):return False
    return not any(path==e or path.startswith(e+'/') for e in selection.get('exclude',[]))


def throttle(service,job,selection):
    if selection.get('gentle'):time.sleep(.1)
    maximum=selection.get('max_load',0)
    while maximum and os.getloadavg()[0]>maximum:
        if service.cancelled(job):raise InterruptedError('Prüfung während Lastpause angehalten')
        time.sleep(2)


def scope(selection):
    return (selection.get('folder',''),tuple(selection.get('exclude',[])),selection.get('kind',''),selection.get('status',''),selection.get('reason',''))
