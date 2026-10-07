"""Persistent, serialized jobs using the existing Server Manager database."""
from pathlib import Path
import json
import threading
import time
from . import backup
from . import backend

ACTIONS={'rescue-export','rescue-detach','schedule-shutdown-all','schedule-shutdown','start','shutdown','reboot','suspend','resume','destroy','autostart-on','autostart-off','resources','eject','undefine','clone','export','backup'}

class Service:
    def __init__(self,ctx):
        self.ctx=ctx
        self.backups=Path(ctx.state_dir)/'kvm-xml-backups'
        self.mutex=threading.Lock()
        self.transfer_lock=threading.Lock();self.transfers=0
        with self.db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS kvm_shutdown_requests (vm TEXT PRIMARY KEY, requested REAL NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS kvm_sleep_policy (vm TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('block','managed','ignore')))")
            con.execute('''CREATE TABLE IF NOT EXISTS kvm_jobs (
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, vm TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL, state TEXT NOT NULL, created TEXT DEFAULT (datetime('now','localtime')),
                finished TEXT, log TEXT NOT NULL DEFAULT '', result_vm TEXT NOT NULL DEFAULT '')''')
            con.execute("UPDATE kvm_jobs SET state='interrupted', finished=datetime('now','localtime'), log=log || '\nServer Manager neu gestartet. Zustand und mögliche Teilergebnisse vor erneutem Auftrag prüfen.' WHERE state IN ('queued','running','uploading')")
        with self.db() as con:
            stale=con.execute("SELECT id FROM kvm_jobs WHERE action='restore-backup' AND state='interrupted'").fetchall()
        for row in stale:
            try:backup.upload(row['id']).unlink(missing_ok=True)
            except (OSError,backend.Error):pass # unavailable backup mount must not disable KVM
    def db(self):
        from contextlib import closing
        # Return a manager that commits/rolls back AND closes the connection.
        from contextlib import contextmanager
        @contextmanager
        def opened():
            with closing(self.ctx.db()) as con:
                with con:yield con
        return opened()
    def mark_shutdown(self,uid):
        with self.db() as con:con.execute('INSERT OR IGNORE INTO kvm_shutdown_requests(vm,requested) VALUES(?,?)',(uid,time.time()))
    def clear_finished_shutdowns(self,active_managed):
        with self.db() as con:
            for row in con.execute('SELECT vm FROM kvm_shutdown_requests').fetchall():
                if row['vm'] not in active_managed:con.execute('DELETE FROM kvm_shutdown_requests WHERE vm=?',(row['vm'],))
    def sleep_mode(self,uid):
        uid=backend.domain_id(uid)
        with self.db() as con:
            row=con.execute('SELECT mode FROM kvm_sleep_policy WHERE vm=?',(uid,)).fetchone()
        return row['mode'] if row else 'block'
    def set_sleep_mode(self,uid,mode):
        from .sleep_control import MODES
        uid=backend.domain_id(uid)
        if mode not in MODES:raise backend.Error('Ungültige Schlafsteuerung.')
        backend.detail(uid)
        with self.db() as con:
            con.execute('INSERT INTO kvm_sleep_policy(vm,mode) VALUES(?,?) ON CONFLICT(vm) DO UPDATE SET mode=excluded.mode',(uid,mode))
    def expire_uploads(self):
        with self.db() as con:
            rows=con.execute("SELECT id,payload FROM kvm_jobs WHERE state='uploading'").fetchall()
            for row in rows:
                if time.time()-json.loads(row["payload"]).get("touched",0)>1800:
                    con.execute("UPDATE kvm_jobs SET state='interrupted',finished=datetime('now','localtime'),log='Upload nach 30 Minuten ohne Aktivität verworfen.' WHERE id=? AND state='uploading'",(row["id"],))
                    try:backup.upload(row["id"]).unlink(missing_ok=True)
                    except (OSError,backend.Error):pass
    def jobs(self,limit=30):
        self.expire_uploads()
        with self.db() as con:
            return [dict(r) for r in con.execute('SELECT id,action,vm,state,created,finished,log,result_vm FROM kvm_jobs ORDER BY id DESC LIMIT ?', (limit,))]
    def active(self):
        self.expire_uploads()
        with self.db() as con:
            rows=[dict(r) for r in con.execute("SELECT id,action,vm FROM kvm_jobs WHERE state IN ('queued','running','uploading')")]
        with self.transfer_lock:
            if self.transfers:rows.append(dict(id='download',action='Backup-Download',vm=''))
        return rows
    def log(self,jid,message):
        with self.db() as con:
            con.execute('UPDATE kvm_jobs SET log=substr(log || ?, -40000) WHERE id=?', ('\n'+str(message),jid))
    def submit(self,action,uid,data):
        self.expire_uploads()
        if action=='create':data=backend.prepare_create(data)
        elif action not in ACTIONS:raise backend.Error('Unbekannte Aktion.')
        else:
            uid=backend.domain_id(uid)
            if action in ('destroy','undefine'):
                row=backend.detail(uid)
                if data.get('confirm')!=row['name']:raise backend.Error('Exakten VM-Namen zur Bestätigung eingeben.')
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute("SELECT 1 FROM kvm_jobs WHERE state IN ('queued','running','uploading')").fetchone():
                raise backend.Error('Ein KVM-Auftrag läuft bereits. Bitte dessen Abschluss abwarten.')
            jid=con.execute('INSERT INTO kvm_jobs(action,vm,payload,state) VALUES(?,?,?,?)',(action,uid,json.dumps(data),'queued')).lastrowid
        try:threading.Thread(target=self.run,args=(jid,),daemon=True,name=f'kvm-job-{jid}').start()
        except Exception:
            with self.db() as con:con.execute("UPDATE kvm_jobs SET state='failed',log='Worker konnte nicht gestartet werden' WHERE id=?",(jid,))
            raise
        return jid
    def run(self,jid):
        with self.mutex:
            with self.db() as con:
                row=dict(con.execute('SELECT * FROM kvm_jobs WHERE id=?',(jid,)).fetchone())
                con.execute("UPDATE kvm_jobs SET state='running' WHERE id=?",(jid,))
            try:
                data=json.loads(row['payload']);log=lambda msg:self.log(jid,msg)
                if row['action']=='schedule-shutdown-all':
                    errors=[]
                    for uid in data.get('vms',[]):
                        try:
                            if self.sleep_mode(uid)!='managed':
                                log('VM '+uid+': Schlafsteuerung geändert; übersprungen.');continue
                            log('VM '+uid+': reguläres Herunterfahren anfordern.')
                            backend.vm_action(uid,'shutdown',{},log,self.backups)
                            self.mark_shutdown(uid)
                        except Exception as exc:errors.append(uid+': '+str(exc));log(errors[-1])
                    if errors:raise backend.Error('; '.join(errors))
                    result=''
                elif row['action']=='schedule-shutdown':
                    if self.sleep_mode(row['vm'])!='managed':raise backend.Error('Zeitplansteuerung für diese VM ist nicht mehr freigegeben.')
                    log('Schlaf & Wake: reguläres Herunterfahren angefordert. Der Server wartet auf den ausgeschalteten Zustand; kein hartes Ausschalten.')
                    result=backend.vm_action(row['vm'],'shutdown',data,log,self.backups)
                    self.mark_shutdown(row['vm'])
                elif row['action']=='create':result=backend.create_vm(data,log)
                elif row['action']=='rescue-export':result=backup.export_rescuezilla(row['vm'],jid,data,log)
                elif row['action']=='backup':result=backup.create(row['vm'],jid,log)
                elif row['action']=='restore-backup':result=backup.restore(data,jid,log)
                else:result=backend.vm_action(row['vm'],row['action'],data,log,self.backups)
                with self.db() as con:
                    con.execute("UPDATE kvm_jobs SET state='completed',result_vm=?,finished=datetime('now','localtime') WHERE id=?",(result or '',jid))
            except Exception as exc:
                self.log(jid,'Fehler: '+str(exc)+'\nVor erneutem Auftrag mögliche Teilergebnisse prüfen. Quelldateien werden nicht automatisch gelöscht.')
                with self.db() as con:con.execute("UPDATE kvm_jobs SET state='failed',finished=datetime('now','localtime') WHERE id=?",(jid,))

            finally:
                if row['action']=='restore-backup':
                    try:backup.upload(jid).unlink(missing_ok=True)
                    except (OSError,backend.Error):self.log(jid,'Temporären Upload im Backup-Ordner manuell prüfen; Bereinigung nicht möglich.')
