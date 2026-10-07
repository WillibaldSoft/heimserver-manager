"""Explicit DNG recovery job; retains source, writes only private derived files."""
import os,shutil,subprocess,sys,tempfile
from pathlib import Path
from . import checks


def run(service,job,selection):
    from .service import pack
    path=Path(selection['restore_path'])
    service.execute("UPDATE fotolabor_job_details SET phase='restoring' WHERE job_id=?",(job,))
    service.execute("INSERT OR REPLACE INTO fotolabor_restores(job_id,path,status) VALUES(?,?,'running')",(job,pack(path)))
    service.execute("INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,status) VALUES(?,? ,'.dng','pending')",(job,pack(path)))
    service.execute('UPDATE fotolabor_jobs SET total=1,current=? WHERE id=?',(pack(path),job))
    work=None
    try:
        with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:
            signature=checks.signature(os.fstat(fd));digest=checks.digest(fd)
            data=checks.metadata(fd)
            if not data.get('DNGVersion'):raise checks.Uncheckable('Quelle ist kein bestätigtes DNG')
            if not shutil.which('dcraw_emu'):raise checks.Uncheckable('libraw-bin fehlt')
            with checks.directory(service.ctx.state_dir):
                work=Path(tempfile.mkdtemp(prefix='fotolabor-restore-',dir=service.ctx.state_dir))
            tiff=work/'wiederhergestellt.tiff';jpeg=work/'wiederhergestellt.jpg'
            with open(tiff,'xb') as output:
                p=subprocess.run(['dcraw_emu','-T','-6','-w','-q','3','-Z','-',f'/proc/self/fd/{fd}'],pass_fds=(fd,),stdout=output,stderr=subprocess.PIPE,timeout=180)
            if p.returncode or p.stderr.strip():raise checks.Uncheckable('LibRaw: '+p.stderr.decode('utf8','replace')[:1500])
            if service.cancelled(job):raise InterruptedError('Wiederherstellung pausiert')
            with checks.directory(work) as folder,checks.opened(folder,tiff.name) as tfd:checks.decode(tfd,'.tiff')
            p=subprocess.run([sys.executable,str(Path(__file__).with_name('restore_jpeg.py')),str(tiff),str(jpeg)],capture_output=True,timeout=180)
            if p.returncode:raise checks.Uncheckable('JPEG-Ableitung fehlgeschlagen: '+p.stderr.decode('utf8','replace')[-1000:])
            with checks.directory(work) as folder,checks.opened(folder,jpeg.name) as jfd:checks.decode(jfd,'.jpg')
            if checks.signature(os.fstat(fd))!=signature or checks.digest(fd)!=digest or checks.signature(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=signature:
                raise checks.Uncheckable('DNG während Wiederherstellung verändert')
            if service.cancelled(job):raise InterruptedError('Wiederherstellung pausiert')
            service.execute("UPDATE fotolabor_restores SET status='completed',tiff=?,jpeg=?,reason=? WHERE job_id=?",(str(tiff),str(jpeg),'Neu entwickeltes 16-Bit-TIFF und JPEG. Keine originalgetreue JPEG-Rekonstruktion garantiert; Sichtkontrolle erforderlich.',job))
            service.execute("UPDATE fotolabor_files SET status='derived',reason='Separate TIFF-/JPEG-Kopien erstellt' WHERE job_id=?",(job,))
    except Exception as exc:
        if work:shutil.rmtree(work)
        service.execute("UPDATE fotolabor_restores SET status='failed',reason=? WHERE job_id=?",(str(exc),job))
        raise
