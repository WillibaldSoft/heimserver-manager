"""Immutable first hashes, latest findings, and explicit incremental reuse."""
import json,os
from pathlib import Path
from . import checks


def inspect(service,job,row,mode):
    from .service import unpack
    path=Path(unpack(row['path']))
    old=service.query('SELECT * FROM fotolabor_archive WHERE path=?',(row['path'],))
    old=old[0] if old else None
    with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:
        before=checks.signature(os.fstat(fd));sig=json.dumps(before)
        # DNG pairing depends on neighboring JPEGs and must never be reused.
        if mode=='incremental' and old and old['signature']==sig and path.suffix.lower()!='.dng':
            result=json.loads(old['result'])
            if result['status']=='ok':
                result['_reused']=True
                result['reason']='Unverändert laut Dateimerkmalen; Befund aus Prüfung #'+str(old['checked_job'])
                service.execute('INSERT OR REPLACE INTO fotolabor_observations VALUES(?,?,?,?,?)',(job,row['path'],old['latest_digest'],'unchanged',1))
                return result
        digest=checks.digest(fd).hex()
        if mode=='checksum':
            result=dict(status='hashed',reason='SHA-256 gelesen; keine neue Bildintegritätsprüfung',category=None,jpeg=None,safe=False)
        else:
            result=checks.inspect(service.root,str(path))
        if checks.signature(os.fstat(fd))!=before or checks.signature(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=before:
            raise checks.Uncheckable('Datei während Prüfsummenprüfung verändert')
    change='new' if not old else ('unchanged' if old['latest_digest']==digest else 'changed')
    con=service.ctx.db()
    try:
        con.execute('INSERT OR REPLACE INTO fotolabor_observations VALUES(?,?,?,?,?)',(job,row['path'],digest,change,0))
        # Hash-only jobs cannot replace a decoded result with a fictitious OK.
        cached=result
        if mode=='checksum' and old and old['latest_digest']==digest:
            cached=json.loads(old['result'])
        con.execute('''INSERT INTO fotolabor_archive VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET latest_digest=excluded.latest_digest,signature=excluded.signature,
            result=excluded.result,checked_job=excluded.checked_job,updated=excluded.updated''',
            (row['path'],digest,digest,sig,json.dumps(cached),old['checked_job'] if mode=='checksum' and old and old['latest_digest']==digest else job,service.ctx.now()))
        con.commit()
    finally:con.close()
    if change=='changed':result['reason']+='; SHA-256 gegenüber letztem Stand verändert'
    return result
