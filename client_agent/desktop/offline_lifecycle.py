"""Bounded login/shutdown synchronization; no server wake during shutdown."""
import contextlib,json,os,signal,socket,subprocess,sys,threading,time,urllib.parse
from pathlib import Path
import core,offline
from client_i18n import tr
STATUS=offline.ROOT/'lifecycle-status.json'

def record(event,status,detail=''):
    core.atomic(STATUS,json.dumps(dict(event=event,status=status,detail=detail,time=time.strftime('%Y-%m-%d %H:%M:%S'))))

def reachable():
    url=urllib.parse.urlsplit(core.validate(core.load())['SERVER_URL'])
    # Numeric addresses are immediate; DNS and connect share the outer process
    # deadline, so even a hung resolver cannot delay shutdown indefinitely.
    try:
        with socket.create_connection((url.hostname,url.port or 443),timeout=1):return True
    except OSError:return False

def run_event(event):
    rows=[dict(r) for r in offline.config() if r.get('sync_'+event)]
    if not rows:return
    if event=='shutdown' and not reachable():record(event,'offline',tr('Server offline: Ausschalten ohne Abgleich.'));return
    failures=[]
    for row in rows:
        if event=='shutdown':row['wake']=False
        try:offline.sync(dict(row,_require_clean=True))
        except Exception as exc:failures.append(row.get('name',row['id'])+': '+str(exc))
    record(event,'pending' if failures else 'ok','\n'.join(failures))

def bounded(event,seconds):
    record(event,'running')
    proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),event],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        code=proc.wait(timeout=max(0.1,seconds))
        if code:record(event,'pending',tr('Automatischer Abgleich fehlgeschlagen; beim nächsten Start erneut versuchen.'))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        record(event,'pending',tr('Zeitlimit erreicht. Lokale Änderungen bleiben erhalten.'))

class Monitor:
    def __init__(self,app):
        from gi.repository import Gio,GLib
        self.app=app;self.Gio=Gio;self.GLib=GLib;self.fd=None;self.shutting=False;self.running=False;self.started=False;self.error='';self.seconds=0
        self.proxy=None
        try:
            self.proxy=Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM,Gio.DBusProxyFlags.NONE,None,'org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager',None)
            self.proxy.connect('g-signal',self.signal)
        except Exception:self.error=tr('Ausschalt-Abgleich nicht verfügbar: systemd-logind fehlt.')
        GLib.timeout_add_seconds(3,self.tick)

    def release(self):
        if self.fd is not None:os.close(self.fd);self.fd=None

    def acquire(self):
        if self.fd is not None or not self.proxy:return
        result,fds=self.proxy.call_with_unix_fd_list_sync('Inhibit',self.GLib.Variant('(ssss)',('shutdown','Heimserver Manager Client','Offline file synchronization','delay')),self.Gio.DBusCallFlags.NONE,2000,None,None)
        self.fd=fds.get(result.unpack()[0])
        value=self.proxy.get_cached_property('InhibitDelayMaxUSec')
        self.seconds=min(60,max(0,float(value.unpack())/1000000 if value else 5))
        self.error=''

    def tick(self):
        if self.shutting:return True
        try:
            rows=offline.config()
            if not self.started:
                self.started=True
                if any(r.get('sync_startup') for r in rows):self.launch('startup',300)
            if any(r.get('sync_shutdown') for r in rows):self.acquire()
            else:self.release()
        except Exception:self.error=tr('Automatischer Abgleich nicht bereit. Einstellungen und Protokoll prüfen.')
        return True

    def launch(self,event,seconds):
        if self.running:return False
        self.running=True
        def task():
            try:bounded(event,seconds)
            finally:
                self.running=False
                if event=='shutdown':self.release()
        threading.Thread(target=task,daemon=True).start();return True

    def signal(self,proxy,sender,name,params):
        if name!='PrepareForShutdown':return
        self.shutting=params.unpack()[0]
        if not self.shutting:self.tick();return
        if self.fd is None:return
        # A delay inhibitor is finite and controlled by logind. Do not imply a
        # full 60-second window when the operating system only allows five.
        if not self.launch('shutdown',max(0.1,self.seconds-0.5)):
            record('shutdown','pending',tr('Ein Abgleich läuft bereits. Ausstehende Änderungen bleiben erhalten.'));self.release()

if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1] not in ('startup','shutdown'):raise SystemExit(2)
    def stop(*args):raise TimeoutError('Shutdown synchronization deadline')
    signal.signal(signal.SIGTERM,stop)
    run_event(sys.argv[1])
