"""Read-only exact-content search using the shared Fotolabor worker and lock."""
import hashlib
import json
import os
from pathlib import Path
from . import checks, options


def scan(service, job):
    from .service import unpack
    selection = json.loads(service.details(job)['selection'])
    service.execute("UPDATE fotolabor_job_details SET phase='hashing' WHERE job_id=?", (job,))
    # Unique sizes cannot have an exact duplicate. Never label hashing as image OK.
    service.execute("""UPDATE fotolabor_files SET status='hashed',reason='Einmalige Dateigröße'
        WHERE job_id=? AND status='pending' AND bytes IN
        (SELECT bytes FROM fotolabor_files WHERE job_id=? GROUP BY bytes HAVING COUNT(*)=1)""", (job, job))
    service.totals(job)
    while True:
        rows = service.query("SELECT path,bytes FROM fotolabor_files WHERE job_id=? AND status='pending' ORDER BY path LIMIT 100", (job,))
        if not rows:
            return
        for row in rows:
            if service.cancelled(job):
                raise InterruptedError('Duplikatsuche pausiert')
            options.throttle(service, job, selection)
            path = Path(unpack(row['path']))
            service.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?', (row['path'], job))
            status, reason, identity = 'hashed', 'Dateiinhalt gelesen; keine Integritätsprüfung', None
            try:
                with checks.directory(service.root, str(path.parent)) as parent, checks.opened(parent, path.name) as fd:
                    before = os.fstat(fd)
                    if before.st_size != row['bytes']:
                        raise checks.Uncheckable('Dateigröße seit Erfassung verändert')
                    digest = hashlib.sha256()
                    while True:
                        if service.cancelled(job):
                            raise InterruptedError('Duplikatsuche pausiert')
                        block = os.read(fd, 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                    if checks.signature(before) != checks.signature(os.fstat(fd)) or checks.signature(before) != checks.signature(os.stat(path.name, dir_fd=parent, follow_symlinks=False)):
                        raise checks.Uncheckable('Datei während Duplikatsuche verändert')
                    identity = (digest.hexdigest(), before.st_size, before.st_dev, before.st_ino)
            except (OSError, checks.Uncheckable) as exc:
                status, reason = 'uncheckable', str(exc)
            con = service.ctx.db()
            try:
                if identity:
                    con.execute('INSERT OR REPLACE INTO fotolabor_hashes VALUES(?,?,?,?,?,?)', (job, row['path'], *identity))
                con.execute('UPDATE fotolabor_files SET status=?,reason=? WHERE job_id=? AND path=?', (status, reason, job, row['path']))
                con.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?', (job,))
                con.commit()
            finally:
                con.close()


def groups(service, job, offset=0, limit=50):
    return service.query('''SELECT digest,bytes,COUNT(*) AS copies,
        COUNT(DISTINCT CAST(device AS TEXT)||':'||CAST(inode AS TEXT)) AS physical
        FROM fotolabor_hashes WHERE job_id=? GROUP BY digest,bytes
        HAVING COUNT(*)>1 ORDER BY digest LIMIT ? OFFSET ?''', (job, limit, offset))
