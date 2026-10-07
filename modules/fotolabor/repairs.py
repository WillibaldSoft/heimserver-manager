"""Automatic conservative metadata repair, exclusively into separate copies."""
import json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from . import checks


def fingerprint(path):
    proc=subprocess.run([sys.executable,str(Path(__file__).with_name('repair_pixels.py')),str(path)],capture_output=True,timeout=180)
    if proc.returncode:
        raise checks.Uncheckable('Bildvergleich nicht möglich: '+proc.stderr.decode('utf8','replace')[-1000:])
    return json.loads(proc.stdout)


def consider(service,job,relative,result):
    from .service import pack
    if Path(relative).suffix.lower() not in ('.jpg','.jpeg'):
        return
    # Corrupt pixel streams and uncertain JPEG structure are never auto-repaired.
    if result['status'] != 'ok':
        return
    if service.query("SELECT 1 FROM fotolabor_repairs WHERE job_id=? AND path=? AND status!='selected'",(job,pack(relative))):
        return
    path=Path(relative)
    output='';work=None
    try:
        with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:
            before=checks.signature(os.fstat(fd)); original=checks.digest(fd)
            rc,out,err=checks.run('exiftool',['-json','-Warning','-Error'],fd)
            if rc or err.strip(): return
            data=json.loads(out)[0]
            notice=str(data.get('Warning') or data.get('Error') or '')
            if not notice: return
            status='failed';reason=notice
            service.execute('INSERT INTO fotolabor_repairs(job_id,path,status,reason) VALUES(?,?,?,?) ON CONFLICT(job_id,path) DO UPDATE SET status=excluded.status,reason=excluded.reason',(job,pack(relative),'selected',notice))
            # Random private directory outside the photo root; never replaces a file.
            with checks.directory(Path(service.ctx.state_dir)):
                work=Path(tempfile.mkdtemp(prefix='fotolabor-repair-',dir=service.ctx.state_dir))
            target=work/'repariert.jpg'
            os.lseek(fd,0,os.SEEK_SET)
            with open(target,'xb') as dest:
                while True:
                    block=os.read(fd,1024*1024)
                    if not block: break
                    dest.write(block)
            baseline=fingerprint(target)
            executable=shutil.which('exiftool')
            if not executable: raise checks.Uncheckable('ExifTool fehlt')
            args = ['-MakerNotes=','-XMP=','-IPTC='] if baseline.get('format')=='MPO' else ['-all=','-tagsfromfile','@','-all:all','-unsafe','-icc_profile']
            p=subprocess.run([executable,'-overwrite_original',*args,str(target)],capture_output=True,timeout=180)
            if p.returncode: raise checks.Uncheckable('Metadaten konnten nicht neu aufgebaut werden')
            # Drop unreadable auxiliary metadata only in the separate copy.
            diagnostics=subprocess.run([executable,'-json','-Warning','-Error',str(target)],capture_output=True,timeout=180)
            remaining=json.loads(diagnostics.stdout)[0] if diagnostics.returncode==0 else {'Error':'Metadatenprüfung fehlgeschlagen'}
            if remaining.get('Warning') and not remaining.get('Error'):
                cleaned=subprocess.run([executable,'-overwrite_original','-MakerNotes=','-XMP=','-IPTC=',str(target)],capture_output=True,timeout=180)
                if cleaned.returncode:raise checks.Uncheckable('Nebenmetadaten konnten nicht bereinigt werden')
            with checks.directory(work) as folder,checks.opened(folder,'repariert.jpg') as newfd:
                checks.decode(newfd,'.jpg')
                rc,out,err=checks.run('exiftool',['-json','-Warning','-Error'],newfd)
                data=json.loads(out)[0]
                if rc or err.strip() or data.get('Error') or data.get('Warning'):
                    raise checks.Uncheckable('Reparatur enthält weiterhin Metadatenfehler')
            if fingerprint(target)!=baseline:
                raise checks.Uncheckable('Bildpixel, Farbprofil oder Orientierung verändert')
            if checks.signature(os.fstat(fd))!=before or checks.digest(fd)!=original or checks.signature(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=before:
                raise checks.Uncheckable('Original während Reparatur verändert')
            status='repaired';output=str(target)
            reason='Separate Kopie geprüft; Pixel, Farbprofil und Orientierung unverändert. Metadaten können entfallen. Sichtkontrolle erforderlich. Ursprung: '+notice
    except Exception as exc:
        status='failed';reason=str(exc)
    else:
        if not work: return
    if not output and work:
        shutil.rmtree(work)
    service.execute('INSERT INTO fotolabor_repairs(job_id,path,status,reason,output) VALUES(?,?,?,?,?) ON CONFLICT(job_id,path) DO UPDATE SET status=excluded.status,reason=excluded.reason,output=excluded.output',(job,pack(relative),status,reason,output))
