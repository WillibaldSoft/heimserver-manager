"""Durable Manager jobs: preview never deletes; execution needs explicit approval."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from . import checks, options, archive, apply_repairs


def pack(path):
    return json.dumps(str(path), ensure_ascii=True)


def unpack(path):
    return json.loads(path)


class Service:
    def __init__(self, ctx, root=checks.ROOT):
        self.ctx, self.root = ctx, Path(root)
        self.lock_path = Path(ctx.state_dir) / 'fotolabor.lock'
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        con = ctx.db()
        try:
            con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (id INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT DEFAULT (datetime('now','localtime')), checksum TEXT)")
            for name in ('0003_fotolabor', '0004_fotolabor_resume', '0005_fotolabor_duplicates', '0006_fotolabor_repairs', '0007_fotolabor_archive', '0008_fotolabor_apply'):
                if not con.execute('SELECT 1 FROM schema_migrations WHERE name=?', (name,)).fetchone():
                    sql = (Path(__file__).resolve().parents[2] / 'migrations' / (name + '.sql')).read_text()
                    con.executescript('BEGIN IMMEDIATE;\n' + sql)
                    con.execute('INSERT INTO schema_migrations(name,checksum) VALUES(?,?)', (name, hashlib.sha256(sql.encode()).hexdigest()))
                    con.commit()
        finally:
            con.close()
        self.recover()

    def query(self, sql, params=()):
        con = self.ctx.db()
        try:
            return [dict(row) for row in con.execute(sql, params).fetchall()]
        finally:
            con.close()

    def execute(self, sql, params=()):
        con = self.ctx.db()
        try:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def acquire(self):
        lock = open(self.lock_path, 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except BlockingIOError:
            lock.close()
            return None

    def recover(self):
        lock = self.acquire()
        if lock:
            try:
                self.execute("UPDATE fotolabor_jobs SET state='interrupted',finished=?,error='Dienst unterbrochen; Prüfung kann fortgesetzt werden' WHERE state IN ('queued','running')", (self.ctx.now(),))
            finally:
                lock.close()

    def details(self, job):
        rows = self.query('SELECT * FROM fotolabor_job_details WHERE job_id=?', (job,))
        return rows[0] if rows else {'job_id': job, 'phase': 'inventory', 'inventory_done': 0, 'selection': '{}', 'source_job': None, 'consumed': 0}

    def start(self, mode, source_job=None, selection=None):
        if mode not in ('scan', 'cleanup', 'recheck', 'delete', 'duplicates', 'incremental', 'checksum', 'restore', 'repair', 'apply_repairs', 'refresh_cleanup', 'repair_mpf', 'raw_dng'):
            raise ValueError('Unbekannte Aktion')
        selection = options.validate(selection or {})
        if mode == 'restore':
            path = options.relative(selection.get('restore_path',''))
            if not path or Path(path).suffix.lower() != '.dng':raise ValueError('Relativen DNG-Pfad angeben')
            selection['restore_path'] = path
        if mode == 'delete':
            selection.update(folder='',exclude=[])

        if selection.get('kind', '') not in checks.IMAGES | {''}:
            raise ValueError('Unbekannter Dateityp')
        if selection.get('status', '') not in ('', 'ok', 'damaged', 'uncheckable', 'pending'):
            raise ValueError('Unbekannter Prüfstatus')
        if selection.get('reason', '') not in set(checks.REASONS) | {''}:
            raise ValueError('Unbekannter Fehlergrund')
        lock = self.acquire()
        if not lock:
            raise ValueError('Im Fotolabor läuft bereits ein Auftrag')
        job = None
        try:
            con = self.ctx.db()
            try:
                con.execute('BEGIN IMMEDIATE')
                source = con.execute('SELECT * FROM fotolabor_jobs WHERE id=?', (source_job,)).fetchone()
                if (mode in ('recheck', 'delete', 'repair', 'refresh_cleanup') or (mode == 'apply_repairs' and selection.get('prepare_after'))) and (not source or source['state'] in ('queued', 'running')):
                    raise ValueError('Abgeschlossene oder pausierte Quellprüfung auswählen')
                if mode == 'delete':
                    detail = con.execute('SELECT * FROM fotolabor_job_details WHERE job_id=?', (source_job,)).fetchone()
                    if source['state'] != 'ready' or not detail or detail['consumed']:
                        raise ValueError('Eine neue, noch nicht verwendete Bereinigungs-Vorschau ist erforderlich')
                    con.execute('UPDATE fotolabor_job_details SET consumed=1 WHERE job_id=?', (source_job,))
                job = con.execute('INSERT INTO fotolabor_jobs(mode,state,started) VALUES(?,?,?)', (mode, 'queued', self.ctx.now())).lastrowid
                if selection.get('_schedule_id'):
                    import time, datetime
                    from .scheduling import next_time
                    schedule = con.execute('SELECT * FROM fotolabor_schedules WHERE id=? AND enabled=1 AND next_at<=?', (selection['_schedule_id'],int(time.time()))).fetchone()
                    if not schedule:raise ValueError('Zeitplan wurde bereits gestartet oder deaktiviert')
                    con.execute('UPDATE fotolabor_schedules SET next_at=?,last_job=?,last_error=? WHERE id=?',(next_time(schedule['clock'],json.loads(schedule['days'])),job,'',schedule['id']))
                con.execute('INSERT INTO fotolabor_job_details(job_id,source_job,selection,phase) VALUES(?,?,?,?)',
                            (job, source_job, json.dumps(selection), 'selection' if mode == 'recheck' else 'inventory'))
                con.commit()
            finally:
                con.close()
            self.launch(job, mode, lock)
            return job
        except Exception:
            if job:
                self.execute("UPDATE fotolabor_jobs SET state='failed',error='Worker konnte nicht starten',finished=? WHERE id=?", (self.ctx.now(), job))
            lock.close()
            raise

    def launch(self, job, mode, lock):
        threading.Thread(target=self.worker, args=(job, mode, lock), name='fotolabor-worker', daemon=True).start()

    def resume(self, job):
        rows = self.query('SELECT mode FROM fotolabor_jobs WHERE id=?', (job,))
        if rows and rows[0]['mode'] == 'raw_dng':
            raise ValueError('RAW-Umwandlung bitte als neuen Auftrag starten; vorhandene Ausgaben werden nicht überschrieben.')
        lock = self.acquire()
        if not lock:
            raise ValueError('Im Fotolabor läuft bereits ein Auftrag')
        try:
            rows = self.query('SELECT * FROM fotolabor_jobs WHERE id=?', (job,))
            if not rows or rows[0]['state'] not in ('cancelled', 'interrupted', 'failed') or rows[0]['mode'] == 'delete':
                raise ValueError('Diese Prüfung kann nicht fortgesetzt werden; bei Löschaufträgen neue Vorschau erstellen')
            self.execute("UPDATE fotolabor_files SET status='pending',reason='' WHERE job_id=? AND kind IN ('.webp','.heic','.heif','.avif','.gif','.bmp') AND status='uncheckable' AND reason LIKE '%kein vollständiger Decoder%'", (job,))
            self.execute("UPDATE fotolabor_jobs SET state='queued',finished=NULL,error='',cancel=0 WHERE id=?", (job,))
            self.launch(job, rows[0]['mode'], lock)
            return job
        except Exception:
            lock.close()
            raise

    def cancelled(self, job):
        return bool(self.query('SELECT cancel FROM fotolabor_jobs WHERE id=?', (job,))[0]['cancel'])

    def audit(self, job, path, action, reason):
        self.execute('INSERT INTO fotolabor_audit(job_id,path,action,reason) VALUES(?,?,?,?)', (job, pack(path), action, reason))

    def totals(self, job):
        self.execute("UPDATE fotolabor_jobs SET total=(SELECT COUNT(*) FROM fotolabor_files WHERE job_id=?), bytes=(SELECT COALESCE(SUM(bytes),0) FROM fotolabor_files WHERE job_id=?), checked=(SELECT COUNT(*) FROM fotolabor_files WHERE job_id=? AND status!='pending') WHERE id=?", (job, job, job, job))

    def inventory(self, job, parent, prefix=''):
        selection = json.loads(self.details(job)['selection'])
        options.throttle(self, job, selection)
        with os.scandir(parent) as entries:
            for entry in entries:
                if self.cancelled(job):
                    raise InterruptedError('Prüfung pausiert; gespeicherte Ergebnisse bleiben erhalten')
                relative = str(Path(prefix) / entry.name)
                if not options.includes(selection, relative):
                    continue
                ext = Path(entry.name).suffix.lower()
                try:
                    st = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(st.st_mode):
                        with checks.directory(self.root, relative) as child:
                            self.inventory(job, child, relative)
                    elif ext in checks.IMAGES or stat.S_ISLNK(st.st_mode):
                        regular = stat.S_ISREG(st.st_mode)
                        con = self.ctx.db()
                        try:
                            added = con.execute('INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,bytes,status,reason) VALUES(?,?,?,?,?,?)',
                                (job, pack(relative), ext or 'link', st.st_size if regular else 0,
                                 'pending' if regular else 'uncheckable', '' if regular else 'Symlink/Spezialdatei wird nicht verfolgt')).rowcount
                            if added:
                                con.execute('INSERT INTO fotolabor_file_details(job_id,path,reason_code) VALUES(?,?,?)', (job, pack(relative), '' if regular else 'symlink'))
                                con.execute('UPDATE fotolabor_jobs SET total=total+1,bytes=bytes+?,current=? WHERE id=?', (st.st_size if regular else 0, pack(relative), job))
                            con.commit()
                        finally:
                            con.close()
                except InterruptedError:
                    raise
                except OSError as exc:
                    raise OSError(f'Bestand nicht vollständig erfassbar: {relative}: {exc}') from exc

    def select_files(self, job, details):
        selection = json.loads(details['selection'])
        clauses, args = ['f.job_id=?', 'f.deleted=0'], [details['source_job']]
        for key, column in [('kind', 'f.kind'), ('status', 'f.status'), ('reason', 'd.reason_code')]:
            if selection.get(key):
                clauses.append(column + '=?')
                args.append(selection[key])
        con = self.ctx.db()
        try:
            con.execute('INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,bytes) SELECT ?,f.path,f.kind,f.bytes FROM fotolabor_files f LEFT JOIN fotolabor_file_details d ON d.job_id=f.job_id AND d.path=f.path WHERE ' + ' AND '.join(clauses), (job, *args))
            con.execute('INSERT OR IGNORE INTO fotolabor_file_details(job_id,path) SELECT job_id,path FROM fotolabor_files WHERE job_id=?', (job,))
            con.commit()
        finally:
            con.close()

    def check_pending(self, job):
        mode = self.query('SELECT mode FROM fotolabor_jobs WHERE id=?',(job,))[0]['mode']
        selection = json.loads(self.details(job)['selection'])
        self.execute("UPDATE fotolabor_job_details SET phase='checking' WHERE job_id=?", (job,))
        while True:
            # Resolve requested DNG/JPEG pairs before large thumbnail collections.
            rows = self.query("SELECT * FROM fotolabor_files WHERE job_id=? AND status='pending' AND kind='.dng' ORDER BY path LIMIT 100", (job,))
            if not rows:
                rows = self.query("SELECT * FROM fotolabor_files WHERE job_id=? AND status='pending' ORDER BY path LIMIT 100", (job,))
            if not rows:
                return
            for row in rows:
                if self.cancelled(job):
                    raise InterruptedError('Prüfung pausiert; gespeicherte Ergebnisse bleiben erhalten')
                self.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?', (row['path'], job))
                options.throttle(self, job, selection)
                try:
                    result = checks.inspect(self.root,unpack(row['path'])) if mode=='repair' else archive.inspect(self, job, row, mode)
                except (OSError, checks.Uncheckable) as exc:
                    result = dict(status='uncheckable',reason=str(exc),category=None,jpeg=None,safe=False)

                mode = self.query('SELECT mode FROM fotolabor_jobs WHERE id=?', (job,))[0]['mode']
                if mode not in ('delete','checksum') and not result.get('_reused'):
                    from .repairs import consider
                    consider(self, job, unpack(row['path']), result)
                if result['safe'] and self.query('SELECT 1 FROM fotolabor_restores WHERE path=? LIMIT 1',(row['path'],)):
                    result['safe'] = False
                    result['reason'] += '; DNG-Wiederherstellungsquelle bleibt geschützt'
                if result['safe'] and result['jpeg']:
                    sibling = str(Path(unpack(row['path'])).parent / result['jpeg'])
                    if not apply_repairs.repair_allows(self, pack(sibling)):
                        result['safe'] = False
                        result['reason'] += '; JPEG-Reparaturfall: DNG bleibt geschützt'
                con = self.ctx.db()
                try:
                    con.execute('UPDATE fotolabor_files SET status=?,reason=?,category=?,jpeg=?,safe=? WHERE job_id=? AND path=?',
                                (result['status'], result['reason'], result['category'], pack(result['jpeg']) if result['jpeg'] else None, int(result['safe']), job, row['path']))
                    code = result.get('reason_code', checks.reason_code(result['reason'], result['status']))
                    con.execute('INSERT INTO fotolabor_file_details(job_id,path,reason_code) VALUES(?,?,?) ON CONFLICT(job_id,path) DO UPDATE SET reason_code=excluded.reason_code', (job, row['path'], code))
                    con.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?', (job,))
                    con.commit()
                finally:
                    con.close()

    def prepare_preview(self, job):
        self.execute("UPDATE fotolabor_job_details SET phase='preview' WHERE job_id=?", (job,))
        last = ''
        while True:
            rows = self.query('SELECT path,jpeg FROM fotolabor_files WHERE job_id=? AND category=2 AND safe=1 AND path>? ORDER BY path LIMIT 100', (job, last))
            if not rows:
                return
            for row in rows:
                if self.cancelled(job):
                    raise InterruptedError('Vorschau pausiert')
                last = row['path']
                try:
                    if self.query('SELECT 1 FROM fotolabor_restores WHERE path=? LIMIT 1',(last,)):
                        raise checks.Uncheckable('DNG-Wiederherstellungsquelle bleibt geschützt')
                    sibling = str(Path(unpack(last)).parent / unpack(row['jpeg']))
                    if not apply_repairs.repair_allows(self, pack(sibling)):
                        raise checks.Uncheckable('JPEG-Reparaturfall: DNG bleibt geschützt')
                    snapshot = checks.package_snapshot(self.root, unpack(last), unpack(row['jpeg']))
                    self.execute('UPDATE fotolabor_file_details SET fingerprint=?,preview_bytes=?,preview_xmp=? WHERE job_id=? AND path=?',
                                 (json.dumps(snapshot), snapshot['bytes'], snapshot['xmp'], job, last))
                except (OSError, checks.Uncheckable) as exc:
                    self.execute('UPDATE fotolabor_files SET safe=0,reason=reason||? WHERE job_id=? AND path=?', ('; Vorschau: '+str(exc), job, last))

    def select_repairs(self, job, source):
        last = ''
        while True:
            rows = self.query("SELECT path,jpeg FROM fotolabor_files WHERE job_id=? AND category=2 AND safe=0 AND reason LIKE '%JPEG-Reparaturfall%' AND path>? ORDER BY path LIMIT 100",(source,last))
            if not rows:return
            for row in rows:
                if self.cancelled(job):raise InterruptedError('Reparatur pausiert')
                last=row['path']
                relative=Path(unpack(last)).parent/unpack(row['jpeg'])
                previous=self.query("SELECT output FROM fotolabor_repairs WHERE path=? AND status='repaired'",(pack(relative),))
                if any(Path(r['output']).is_file() for r in previous):continue
                self.execute("INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,status) VALUES(?,?,?,'pending')",(job,pack(relative),relative.suffix.lower()))
                self.execute('INSERT OR IGNORE INTO fotolabor_file_details(job_id,path) VALUES(?,?)',(job,pack(relative)))

    def select_approved(self, job, source):
        con = self.ctx.db()
        try:
            con.execute("""INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,bytes,status,category,jpeg,safe)
                SELECT ?,f.path,f.kind,f.bytes,'pending',2,f.jpeg,1 FROM fotolabor_files f
                JOIN fotolabor_file_details d ON d.job_id=f.job_id AND d.path=f.path
                WHERE f.job_id=? AND f.category=2 AND f.safe=1 AND f.deleted=0 AND d.fingerprint!=''""", (job,source))
            con.execute('INSERT OR IGNORE INTO fotolabor_file_details(job_id,path) SELECT job_id,path FROM fotolabor_files WHERE job_id=?',(job,))
            con.commit()
        finally:
            con.close()

    def delete_approved(self, job, source):
        self.execute("UPDATE fotolabor_job_details SET phase='deleting' WHERE job_id=?", (job,))
        last = ''
        while True:
            rows = self.query("SELECT f.path,d.fingerprint FROM fotolabor_files f JOIN fotolabor_files p ON p.path=f.path AND p.job_id=? JOIN fotolabor_file_details d ON d.path=p.path AND d.job_id=p.job_id WHERE f.job_id=? AND f.category=2 AND f.safe=1 AND p.safe=1 AND d.fingerprint!='' AND f.path>? ORDER BY f.path LIMIT 100", (source, job, last))
            if not rows:
                return
            for row in rows:
                if self.cancelled(job):
                    raise InterruptedError('Löschung abgebrochen; für weitere Löschungen neue Vorschau erstellen')
                last = row['path']
                self.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?', (last, job))
                try:
                    expected = json.loads(row['fingerprint'])
                    jpeg_path = pack(Path(unpack(last)).parent / expected['jpeg'])
                    if self.query('SELECT 1 FROM fotolabor_restores WHERE path=? LIMIT 1',(last,)) or not apply_repairs.repair_allows(self, jpeg_path):
                        raise checks.Uncheckable('Reparatur-/Wiederherstellungsquelle bleibt geschützt')
                    checks.delete_safe(self.root, unpack(last), lambda p, a, r: self.audit(job, p, a, r), expected=expected)
                    self.execute("UPDATE fotolabor_files SET deleted=1,status='ok',reason='Bestätigtes Paket frisch geprüft und gelöscht' WHERE job_id=? AND path=?", (job, last))
                except (OSError, checks.Uncheckable, checks.Damaged) as exc:
                    self.audit(job, unpack(last), 'protected-or-partial', str(exc))
                    self.execute("UPDATE fotolabor_files SET safe=0,status='uncheckable',reason=? WHERE job_id=? AND path=?", ('Geschützt / Teilfehler: '+str(exc), job, last))
                self.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?',(job,))

    def worker(self, job, mode, lock):
        state, error = 'completed', ''
        try:
            self.execute("UPDATE fotolabor_jobs SET state='running' WHERE id=?", (job,))
            details = self.details(job)
            selection = json.loads(details['selection'])
            if selection.get('gentle'):
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
            if mode == 'raw_dng':
                from .raw_dng import run
                run(self, job, selection)
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?",(job,))
                return
            if mode == 'repair_mpf':
                from .mpf_repair import run
                run(self, job)
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?",(job,))
                return
            if mode == 'apply_repairs':
                apply_repairs.run(self, job)
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?",(job,))
                return
            if mode == 'refresh_cleanup':
                apply_repairs.preview(self, job, details['source_job'])
                state = 'ready'
                return
            if mode == 'restore':
                from .restoration import run
                run(self, job, selection)
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?",(job,))
                return
            if not details['inventory_done']:
                if mode == 'repair':
                    self.select_repairs(job, details['source_job'])
                elif mode == 'delete':
                    self.select_approved(job, details['source_job'])
                elif mode == 'recheck':
                    self.select_files(job, details)
                else:
                    folder = selection.get('folder','')
                    with checks.directory(self.root, folder) as parent:
                        self.inventory(job, parent, folder)
                self.execute('UPDATE fotolabor_job_details SET inventory_done=1 WHERE job_id=?', (job,))
            self.totals(job)
            if mode == 'duplicates':
                from .duplicates import scan
                scan(self, job)
            elif mode != 'delete':
                self.check_pending(job)
            if self.cancelled(job):
                raise InterruptedError('Prüfung pausiert')
            if mode == 'cleanup':
                self.prepare_preview(job)
                state = 'ready'
            elif mode == 'delete':
                self.delete_approved(job, details['source_job'])
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?", (job,))
            else:
                self.execute("UPDATE fotolabor_job_details SET phase='finished' WHERE job_id=?", (job,))
        except InterruptedError as exc:
            state, error = 'cancelled', str(exc)
        except Exception as exc:
            state, error = 'failed', str(exc)
        finally:
            try:
                self.totals(job)
                self.execute('UPDATE fotolabor_jobs SET state=?,error=?,finished=?,current=? WHERE id=?', (state, error, self.ctx.now(), '', job))
            finally:
                lock.close()
            if mode == 'repair_mpf' and state == 'completed' and selection.get('apply_after'):
                try:self.start('apply_repairs')
                except Exception as exc:self.audit(job,'','apply-deferred',str(exc))
            if mode == 'apply_repairs' and state == 'completed' and selection.get('prepare_after'):
                try:self.start('refresh_cleanup',source_job=details['source_job'])
                except Exception as exc:self.audit(job,'','prepare-deferred',str(exc))

    def summary(self, job_id=None):
        self.recover()
        jobs = self.query('SELECT * FROM fotolabor_jobs WHERE id=?', (job_id,)) if job_id else self.query("SELECT * FROM fotolabor_jobs ORDER BY (state IN ('queued','running')) DESC,id DESC LIMIT 1")
        if not jobs:
            return {'job': None, 'counts': {}, 'categories': {}, 'kinds': {}, 'reasons': {}, 'deleted': 0, 'preview': {}}
        job = jobs[0]
        job.update(self.details(job['id']))
        if job['current']:
            job['current'] = unpack(job['current'])
        group = lambda col: {str(r[col]): r['n'] for r in self.query(f'SELECT {col},COUNT(*) AS n FROM fotolabor_files WHERE job_id=? GROUP BY {col}', (job['id'],))}
        reasons = {r['reason_code']: r['n'] for r in self.query("SELECT d.reason_code,COUNT(*) n FROM fotolabor_file_details d JOIN fotolabor_files f ON f.job_id=d.job_id AND f.path=d.path WHERE f.job_id=? AND f.status='uncheckable' GROUP BY d.reason_code", (job['id'],))}
        preview = self.query("SELECT COUNT(*) AS dng,COALESCE(SUM(d.preview_bytes),0) AS bytes,COALESCE(SUM(d.preview_xmp),0) AS xmp FROM fotolabor_files f JOIN fotolabor_file_details d ON d.job_id=f.job_id AND d.path=f.path WHERE f.job_id=? AND f.safe=1 AND d.fingerprint!=''", (job['id'],))[0]
        return {'job': job, 'counts': group('status'), 'categories': group('category'), 'kinds': group('kind'), 'reasons': reasons, 'preview': preview,
                'deleted': self.query("SELECT COUNT(*) AS n FROM fotolabor_audit WHERE job_id=? AND action='deleted'", (job['id'],))[0]['n']}
