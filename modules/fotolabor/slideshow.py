"""Portable feh/makeself slideshows sharing Fotolabor's lock and database."""
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
import decimal
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import threading
import time

MAX_FILES=100000
MAX_FOLDERS=100
RESERVE=256*1024**2


def makeself_command():
    installed=shutil.which('makeself')
    if installed:return [installed]
    vendor=Path(__file__).parent/'vendor'/'makeself'
    if not (vendor/'makeself.sh').is_file() or not (vendor/'makeself-header.sh').is_file():
        raise ValueError('Der mitgelieferte makeself-Paketgenerator fehlt.')
    return ['sh',str(vendor/'makeself.sh'),'--header',str(vendor/'makeself-header.sh')]


def relative(value):
    if not isinstance(value,str) or '\x00' in value:
        raise ValueError('Ungültiger Ordnerpfad.')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('Ordner müssen innerhalb des Fotolabors liegen.')
    return '' if str(p)=='.' else str(p)


@contextmanager
def open_dir(root, value):
    """Resolve every component beneath an anchored directory without following symlinks."""
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(relative(value)).parts:
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=new
        yield fd
    finally:os.close(fd)


def validate(root,data):
    folders=data.get('folders',[])
    if not isinstance(folders,list) or not 1<=len(folders)<=MAX_FOLDERS:
        raise ValueError('Bitte 1 bis 100 Quellordner auswählen.')
    folders=list(dict.fromkeys(relative(v) for v in folders))
    for folder in folders:
        with open_dir(root,folder):pass
    try:
        delay=decimal.Decimal(str(data.get('delay','5')))
        if not delay.is_finite() or not decimal.Decimal('0.1')<=delay<=3600 or delay.as_tuple().exponent < -2:
            raise ValueError()
    except (decimal.InvalidOperation,ValueError):
        raise ValueError('Bilddauer: 0,1 bis 3600 Sekunden, höchstens zwei Nachkommastellen (Punkt als Dezimalzeichen).')
    filename=str(data.get('filename','Fotoshow')).strip()
    if filename.lower().endswith('.run'):filename=filename[:-4]
    if not filename or filename.startswith('.') or any(c in filename for c in '/\\') or any(ord(c)<32 or ord(c)==127 for c in filename) or len(filename.encode('utf-8'))>160:
        raise ValueError('Dateiname: 1–160 Byte, ohne Pfad, Steuerzeichen oder führenden Punkt.')
    def flag(key):return data.get(key) in ('1',True)
    return dict(folders=folders,delay=format(delay,'f'),filename=filename+'.run',recursive=flag('recursive'),random=flag('random'),fit=flag('fit'))


def folders(root,value='',offset=0):
    value=relative(value)
    if offset<0:raise ValueError('Ungültige Seitennummer.')
    children=[];jpegs=0
    with open_dir(root,value) as fd:
        for entry in os.scandir(fd):
            if entry.is_dir(follow_symlinks=False):children.append(entry.name)
            elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in ('.jpg','.jpeg'):jpegs+=1
    children.sort(key=lambda v:(v.casefold(),v))
    return dict(path=value,parent=str(PurePosixPath(value).parent) if value and str(PurePosixPath(value).parent)!='.' else '',
        children=[dict(name=n,path=str(PurePosixPath(value)/n)) for n in children[offset:offset+150]],
        next_offset=offset+150 if offset+150<len(children) else None,total=len(children),jpegs=jpegs)


def collect(root,selection,checkpoint=lambda:None,progress=lambda count:None):
    found={}
    def visit(fd,prefix,depth):
        if depth>100:raise ValueError('Ordnerstruktur zu tief. Bitte einen engeren Quellordner wählen.')
        with os.scandir(fd) as entries:
            for entry in entries:
                checkpoint();rel=str(PurePosixPath(prefix)/entry.name)
                if entry.is_dir(follow_symlinks=False) and selection['recursive']:
                    child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    try:visit(child,rel,depth+1)
                    finally:os.close(child)
                elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in ('.jpg','.jpeg'):
                    info=entry.stat(follow_symlinks=False)
                    found[rel]=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
                    if len(found)>MAX_FILES:raise ValueError('Mehr als 100.000 Bilder. Bitte die Ordnerauswahl eingrenzen.')
                    if len(found)%100==0:progress(len(found))
    for folder in selection['folders']:
        with open_dir(root,folder) as fd:visit(fd,folder,0)
    if not found:raise ValueError('In der Auswahl wurden keine JPG-/JPEG-Dateien gefunden.')
    return sorted(found.items(),key=lambda row:(row[0].casefold(),row[0]))


def copy_image(root,rel,expected,dest,checkpoint):
    """Copy an unchanged regular file from a no-symlink anchored path."""
    with open_dir(root,str(PurePosixPath(rel).parent)) as parent:
        fd=os.open(PurePosixPath(rel).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    try:
        info=os.fstat(fd)
        signature=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns)
        if not stat.S_ISREG(info.st_mode) or signature(info)!=tuple(expected):
            raise ValueError('Quelldatei wurde während der Erstellung geändert: '+rel)
        with os.fdopen(fd,'rb',closefd=False) as source,open(dest,'xb') as target:
            header=source.read(3)
            if header!=b'\xff\xd8\xff':raise ValueError('Kein gültiger JPEG-Dateianfang: '+rel)
            target.write(header)
            while True:
                checkpoint();chunk=source.read(1024*1024)
                if not chunk:break
                target.write(chunk)
        if signature(os.fstat(fd))!=tuple(expected):raise ValueError('Quelldatei hat sich beim Kopieren geändert: '+rel)
    finally:os.close(fd)


def launcher(selection):
    # Only validated numeric and fixed flag values enter the generated script.
    options=['--fullscreen','--auto-rotate','--slideshow-delay',selection['delay']]
    options+=['--randomize'] if selection['random'] else ['--sort','filename']
    if selection['fit']:options+=['--auto-zoom','--scale-down']
    import shlex
    return '''#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if ! command -v feh >/dev/null 2>&1; then
  echo "feh fehlt auf diesem Linux-Rechner. Bitte über die Paketverwaltung installieren (Debian/Mint/Ubuntu: sudo apt install feh)." >&2
  exit 1
fi
if [ -z "${DISPLAY:-}" ]; then
  echo "Bitte in einer grafischen Linux-Sitzung mit X11 oder XWayland starten." >&2
  exit 1
fi
# Makeself entfernt den temporär entpackten Inhalt nach Programmende.
feh '''+shlex.join(options)+''' ./Bilder
'''


class Service:
    def __init__(self,base):
        self.base=base;self.root=base.root
        self.output=Path(base.ctx.state_dir)/'fotoshows'
        self.output.mkdir(mode=0o700,parents=True,exist_ok=True)
        base.execute('''CREATE TABLE IF NOT EXISTS fotolabor_slideshows (
            id INTEGER PRIMARY KEY, state TEXT NOT NULL, options TEXT NOT NULL,
            started TEXT NOT NULL, finished TEXT, phase TEXT NOT NULL DEFAULT 'inventory',
            total INTEGER NOT NULL DEFAULT 0, copied INTEGER NOT NULL DEFAULT 0,
            bytes INTEGER NOT NULL DEFAULT 0, current TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', cancel INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '', output_bytes INTEGER NOT NULL DEFAULT 0)''')
        self.recover()
    def recover(self):
        lock=self.base.acquire()
        if lock:
            try:
                rows=self.base.query("SELECT id FROM fotolabor_slideshows WHERE state IN ('queued','running')")
                for row in rows:
                    jobdir=self.output/str(row['id'])
                    if jobdir.is_dir() and not jobdir.is_symlink():
                        for path in (jobdir/'work',jobdir/'result.partial'):
                            if path.is_symlink():path.unlink()
                            elif path.is_dir():shutil.rmtree(path)
                            elif path.exists():path.unlink()
                    self.base.execute("UPDATE fotolabor_slideshows SET state='interrupted',finished=?,error='Dienst unterbrochen. Bitte Fotoshow erneut erstellen.' WHERE id=?",(self.base.ctx.now(),row['id']))
            finally:lock.close()
    def jobs(self):
        return self.base.query('SELECT * FROM fotolabor_slideshows ORDER BY id DESC LIMIT 30')
    def get(self,jid):
        rows=self.base.query('SELECT * FROM fotolabor_slideshows WHERE id=?',(jid,))
        if not rows:raise ValueError('Fotoshow-Auftrag nicht gefunden.')
        return rows[0]
    def active(self):return self.base.query("SELECT id,total,copied,phase FROM fotolabor_slideshows WHERE state IN ('queued','running')")
    def checkpoint(self,jid):
        if self.get(jid)['cancel']:raise InterruptedError('Erstellung abgebrochen.')
    def start(self,data):
        selection=validate(self.root,data)
        makeself_command()
        lock=self.base.acquire()
        if not lock:raise ValueError('Im Fotolabor läuft bereits ein Auftrag. Bitte Abschluss abwarten oder den laufenden Auftrag anhalten.')
        jid=None
        try:
            jid=self.base.execute('INSERT INTO fotolabor_slideshows(state,options,started) VALUES(?,?,?)',('queued',json.dumps(selection),self.base.ctx.now()))
            threading.Thread(target=self.worker,args=(jid,selection,lock),daemon=True,name=f'fotoshow-{jid}').start()
            return jid
        except Exception:
            if jid:self.base.execute("UPDATE fotolabor_slideshows SET state='failed',error='Worker konnte nicht gestartet werden',finished=? WHERE id=?",(self.base.ctx.now(),jid))
            lock.close();raise
    def cancel(self,jid):
        self.base.execute("UPDATE fotolabor_slideshows SET cancel=1 WHERE id=? AND state IN ('queued','running')",(jid,))
    def run_command(self,jid,args,cwd,logfile,timeout=21600):
        with open(logfile,'wb') as output:
            proc=subprocess.Popen(args,cwd=cwd,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
            deadline=time.monotonic()+timeout
            try:
                while proc.poll() is None:
                    self.checkpoint(jid)
                    if time.monotonic()>deadline:raise ValueError('Zeitlimit bei der Paketerstellung überschritten.')
                    time.sleep(.25)
                if proc.returncode:
                    raise ValueError('Paketerstellung fehlgeschlagen: '+Path(logfile).read_text(errors='replace')[-3000:])
            except BaseException:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                raise
    def worker(self,jid,selection,lock):
        jobdir=self.output/str(jid);work=jobdir/'work';partial=jobdir/'result.partial'
        try:
            self.base.execute("UPDATE fotolabor_slideshows SET state='running' WHERE id=?",(jid,))
            check=lambda:self.checkpoint(jid)
            def counted(n):self.base.execute('UPDATE fotolabor_slideshows SET total=? WHERE id=?',(n,jid))
            files=collect(self.root,selection,check,counted)
            size=sum(info[2] for _,info in files)
            if shutil.disk_usage(self.output).free<2*size+RESERVE:raise ValueError('Nicht genügend freier Speicher: Bilddaten werden temporär kopiert und zusätzlich als Paket gespeichert.')
            self.base.execute("UPDATE fotolabor_slideshows SET total=?,bytes=?,phase='copy' WHERE id=?",(len(files),size,jid))
            jobdir.mkdir(mode=0o700);(work/'Bilder').mkdir(parents=True)
            manifest=[]
            for i,(rel,info) in enumerate(files,1):
                check();target=f'{i:08}.jpg';copy_image(self.root,rel,info,work/'Bilder'/target,check)
                manifest.append(dict(file='Bilder/'+target,source=rel))
                self.base.execute('UPDATE fotolabor_slideshows SET copied=?,current=? WHERE id=?',(i,rel,jid))
            (work/'start-diashow.sh').write_text(launcher(selection));(work/'start-diashow.sh').chmod(0o755)
            (work/'Bildliste.json').write_text(json.dumps(manifest,ensure_ascii=True,indent=2))
            (work/'LIESMICH.txt').write_text('Fotoshow aus dem Server-Manager-Fotolabor\n\nStart: bash Fotoshow.run (oder den gewählten Dateinamen verwenden)\nVoraussetzung auf dem Wiedergaberechner: Linux, grafische Sitzung (X11/XWayland), feh.\nDebian/Mint/Ubuntu: sudo apt install feh\nPfeiltasten: Bildwechsel; Escape: Beenden.\nDie Originaldateien wurden nur gelesen. Die Kopien werden bei normalem Ende aus dem temporären Entpackverzeichnis entfernt.\nBildliste.json ordnet die nummerierten Bilder ihren ursprünglichen relativen Pfaden zu.\n')
            self.base.execute("UPDATE fotolabor_slideshows SET phase='package',current='' WHERE id=?",(jid,))
            check()
            self.run_command(jid,makeself_command()+['--quiet','--nox11','--complevel','1','--sha256','--tar-format','posix',str(work),str(partial),'Fotolabor Fotoshow','./start-diashow.sh'],jobdir,jobdir/'build.log')
            self.base.execute("UPDATE fotolabor_slideshows SET phase='verify' WHERE id=?",(jid,))
            self.run_command(jid,['sh',str(partial),'--check'],jobdir,jobdir/'verify.log')
            digest=hashlib.sha256()
            with partial.open('rb') as stream:
                while chunk:=stream.read(1024*1024):check();digest.update(chunk)
            check();dest=jobdir/'fotoshow.run';os.replace(partial,dest);dest.chmod(0o600)
            self.base.execute("UPDATE fotolabor_slideshows SET state='completed',phase='finished',finished=?,sha256=?,output_bytes=? WHERE id=?",(self.base.ctx.now(),digest.hexdigest(),dest.stat().st_size,jid))
        except Exception as exc:
            self.base.execute('UPDATE fotolabor_slideshows SET state=?,error=?,finished=? WHERE id=?',('cancelled' if isinstance(exc,InterruptedError) else 'failed',str(exc),self.base.ctx.now(),jid))
        finally:
            try:
                if work.is_dir():shutil.rmtree(work)
                if partial.exists():partial.unlink()
            finally:lock.close()
    def download(self,jid):
        row=self.get(jid);path=self.output/str(jid)/'fotoshow.run'
        if row['state']!='completed' or not path.is_file() or path.is_symlink():raise ValueError('Fotoshow ist noch nicht zum Download bereit.')
        return row,path
