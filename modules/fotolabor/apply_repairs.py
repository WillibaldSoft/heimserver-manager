"""Explicit, backed-up adoption; never invoked by scanning or repair attempts."""
import json,os,secrets,shutil,stat,tempfile
from pathlib import Path
from . import checks,repairs


def copy_fd(fd,destination):
    with open(destination,'xb') as out:
        pos=0
        while True:
            data=os.pread(fd,1024*1024,pos)
            if not data:break
            out.write(data);pos+=len(data)
        out.flush();os.fsync(out.fileno())


def repair_allows(service,encoded):
    """Repaired JPEGs remain protected until explicitly adopted and unchanged."""
    from .service import unpack
    if not service.query('SELECT 1 FROM fotolabor_repairs WHERE path=? LIMIT 1',(encoded,)):return True
    rows=service.query("SELECT applied_digest,backup FROM fotolabor_applied WHERE path=? AND status='applied' ORDER BY job_id DESC LIMIT 1",(encoded,))
    if not rows or not Path(rows[0]['backup']).is_file():return False
    p=Path(unpack(encoded))
    try:
        with checks.directory(service.root,str(p.parent)) as parent,checks.opened(parent,p.name) as fd:
            before=checks.signature(os.fstat(fd));digest=checks.digest(fd).hex()
            return digest==rows[0]['applied_digest'] and checks.signature(os.fstat(fd))==before
    except (OSError,checks.Uncheckable):return False


def select(service,job):
    con=service.ctx.db()
    try:
        con.execute("""INSERT OR IGNORE INTO fotolabor_applied(job_id,path,repair_job,output)
            SELECT ?,r.path,r.job_id,r.output FROM fotolabor_repairs r
            WHERE r.status='repaired' AND r.job_id=(SELECT MAX(n.job_id) FROM fotolabor_repairs n WHERE n.path=r.path AND n.status='repaired')
            AND NOT EXISTS(SELECT 1 FROM fotolabor_applied a WHERE a.path=r.path AND a.repair_job=r.job_id AND a.status='applied')""",(job,))
        con.execute("INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,status) SELECT job_id,path,'.jpg','pending' FROM fotolabor_applied WHERE job_id=?",(job,))
        con.commit()
    finally:con.close()
    service.totals(job)


def adopt(service,job,row):
    from .service import unpack
    path=Path(unpack(row['path']));output=Path(row['output'])
    if path.suffix.lower() not in ('.jpg','.jpeg'):raise checks.Uncheckable('Nur JPEG-Originale übernehmen')
    if output.parent.parent!=Path(service.ctx.state_dir) or not output.parent.name.startswith('fotolabor-repair-') or output.name!='repariert.jpg':
        raise checks.Uncheckable('Ungültiger Reparaturpfad')
    with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as src:
        before=os.fstat(src);signature=checks.signature(before);source_hash=checks.digest(src).hex()
        # Recover a completed atomic rename after a service interruption.
        if row['status']=='prepared' and source_hash==row['applied_digest'] and Path(row['backup']).is_file():
            with open(row['backup'],'rb') as backup:
                if checks.digest(backup.fileno()).hex()!=row['source_digest']:raise checks.Uncheckable('Sicherung verändert')
            service.execute("UPDATE fotolabor_applied SET status='applied',reason='Übernahme nach Unterbrechung bestätigt' WHERE job_id=? AND path=?",(job,row['path']))
            return
        if before.st_nlink!=1:raise checks.Uncheckable('Original hat Hardlinks; manuelle Übernahme erforderlich')
        if shutil.disk_usage(service.ctx.state_dir).free < before.st_size*3+100*1024*1024:raise checks.Uncheckable('Nicht genug Platz für Originalsicherung')
        with checks.directory(output.parent) as folder,checks.opened(folder,output.name) as repaired:
            stamp=checks.signature(os.fstat(repaired))
            work=Path(tempfile.mkdtemp(prefix='fotolabor-original-',dir=service.ctx.state_dir))
            backup=work/'original.jpg';candidate=work/'replacement.jpg'
            copy_fd(src,backup);copy_fd(repaired,candidate)
            with open(backup,'rb') as handle:
                if checks.digest(handle.fileno()).hex()!=source_hash:raise checks.Uncheckable('Sicherungsvergleich fehlgeschlagen')
            from .mpf_repair import equivalent
            mpf_only=equivalent(backup,candidate)
            if not mpf_only and repairs.fingerprint(backup)!=repairs.fingerprint(candidate):raise checks.Uncheckable('Original und Reparatur unterscheiden sich in Bildinhalt/Farben/Orientierung')
            with checks.directory(work) as wd,checks.opened(wd,candidate.name) as newfd:
                checks.decode(newfd,'.jpg')
                rc,out,err=checks.run('exiftool',['-json','-Warning','-Error'],newfd)
                data=json.loads(out)[0]
                if rc or err.strip() or (data.get('Warning') and not mpf_only) or data.get('Error'):raise checks.Uncheckable('Reparatur nicht fehlerfrei')
                digest=checks.digest(newfd).hex()
                tmp='.fotolabor-adopt-'+secrets.token_hex(16)
                target=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=parent)
                try:
                    pos=0
                    while True:
                        block=os.pread(newfd,1024*1024,pos)
                        if not block:break
                        view=memoryview(block)
                        while view:view=view[os.write(target,view):]
                        pos+=len(block)
                    os.fchown(target,before.st_uid,before.st_gid)
                    os.fchmod(target,stat.S_IMODE(before.st_mode))
                    for attr in os.listxattr(src):os.setxattr(target,attr,os.getxattr(src,attr))
                    os.utime(target,ns=(before.st_atime_ns,before.st_mtime_ns));os.fsync(target)
                finally:os.close(target)
                try:
                    if service.cancelled(job):raise InterruptedError('Übernahme angehalten')
                    if checks.signature(os.fstat(src))!=signature or checks.signature(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=signature or checks.digest(src).hex()!=source_hash:
                        raise checks.Uncheckable('Original während Übernahme verändert')
                    if checks.signature(os.fstat(repaired))!=stamp:raise checks.Uncheckable('Reparaturkopie verändert')
                    with checks.directory(service.root,str(path.parent)) as current:
                        if os.fstat(current).st_ino!=os.fstat(parent).st_ino or os.fstat(current).st_dev!=os.fstat(parent).st_dev:raise checks.Uncheckable('Zielordner verändert')
                    service.execute("UPDATE fotolabor_applied SET status='prepared',backup=?,source_digest=?,applied_digest=?,reason='Original gesichert; atomarer Austausch vorbereitet' WHERE job_id=? AND path=?",(str(backup),source_hash,digest,job,row['path']))
                    os.replace(tmp,path.name,src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
                    service.execute("UPDATE fotolabor_applied SET status='applied',reason='Original gesichert; geprüfte Reparatur übernommen' WHERE job_id=? AND path=?",(job,row['path']))
                finally:
                    try:os.unlink(tmp,dir_fd=parent)
                    except FileNotFoundError:pass
            candidate.unlink()


def run(service,job):
    select(service,job)
    service.execute("UPDATE fotolabor_job_details SET phase='applying' WHERE job_id=?",(job,))
    while True:
        rows=service.query("SELECT a.* FROM fotolabor_applied a JOIN fotolabor_files f ON f.job_id=a.job_id AND f.path=a.path WHERE a.job_id=? AND f.status='pending' ORDER BY a.path LIMIT 100",(job,))
        if not rows:return
        for row in rows:
            if service.cancelled(job):raise InterruptedError('Übernahme pausiert')
            service.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?',(row['path'],job))
            try:
                adopt(service,job,row);status='ok';reason='Reparatur übernommen; Original gesichert'
            except InterruptedError:raise
            except Exception as exc:
                status='uncheckable';reason=str(exc)
                # Never overwrite a prepared journal; it may need crash recovery.
                service.execute("UPDATE fotolabor_applied SET status=CASE WHEN status='prepared' THEN status ELSE 'failed' END,reason=? WHERE job_id=? AND path=?",(reason,job,row['path']))
            service.execute('UPDATE fotolabor_files SET status=?,reason=? WHERE job_id=? AND path=?',(status,reason,job,row['path']))
            service.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?',(job,))


def preview(service,job,source):
    """Re-evaluate only previously proven JPEG-origin pairs, never the collection."""
    from .service import unpack,pack
    service.execute("INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,bytes,status) SELECT ?,path,kind,bytes,'pending' FROM fotolabor_files WHERE job_id=? AND category=2 AND deleted=0",(job,source))
    service.execute('INSERT OR IGNORE INTO fotolabor_file_details(job_id,path) SELECT job_id,path FROM fotolabor_files WHERE job_id=?',(job,))
    service.totals(job)
    service.execute("UPDATE fotolabor_job_details SET phase='preview' WHERE job_id=?",(job,))
    while True:
        rows=service.query("SELECT path FROM fotolabor_files WHERE job_id=? AND status='pending' ORDER BY path LIMIT 100",(job,))
        if not rows:return
        for row in rows:
            if service.cancelled(job):raise InterruptedError('Vorbereitung pausiert')
            service.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?',(row['path'],job))
            path=Path(unpack(row['path']));safe=False;jpeg=None;cat=5;reason='';status='uncheckable'
            try:
                with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:
                    stamp=checks.signature(os.fstat(fd))
                    cat,jpeg,safe,reason=checks.pairing(parent,path.name,checks.metadata(fd))
                    if not safe:raise checks.Uncheckable(reason)
                    if service.query('SELECT 1 FROM fotolabor_restores WHERE path=? LIMIT 1',(row['path'],)):raise checks.Uncheckable('Wiederherstellungsquelle geschützt')
                    if not repair_allows(service,pack(path.parent/jpeg)):raise checks.Uncheckable('Reparatur nicht übernommen oder JPEG verändert')
                    snapshot=checks.package_snapshot(service.root,str(path),jpeg)
                    if checks.signature(os.fstat(fd))!=stamp:raise checks.Uncheckable('DNG verändert')
                    service.execute('UPDATE fotolabor_file_details SET fingerprint=?,preview_bytes=?,preview_xmp=? WHERE job_id=? AND path=?',(json.dumps(snapshot),snapshot['bytes'],snapshot['xmp'],job,row['path']))
                    status='ok'
            except (OSError,checks.Uncheckable,checks.Damaged) as exc:safe=False;reason=str(exc)
            service.execute('UPDATE fotolabor_files SET status=?,category=?,safe=?,jpeg=?,reason=? WHERE job_id=? AND path=?',(status,cat,int(safe),pack(jpeg) if jpeg else None,reason,job,row['path']))
            service.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?',(job,))
