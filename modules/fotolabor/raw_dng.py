"""RAW to DNG copies using DNGLab, serialized by the Fotolabor lock."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json,os,shutil,subprocess,tempfile,zipfile
from pathlib import Path
from flask import request,redirect,send_file
from . import checks
from .service import pack,unpack
FORMATS={'.cr2','.cr3','.crw','.nef','.nrw','.arw','.srf','.sr2','.raf','.orf','.rw2','.pef','.srw','.3fr','.iiq','.mos','.mrw','.kdc','.dcr'}

def output(base,job):return Path(base.ctx.state_dir)/'fotolabor-dng'/str(job)

def command(args):
    with tempfile.TemporaryFile() as log:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=600,env=dict(os.environ,RAYON_NUM_THREADS='1'))
        if result.returncode:
            log.seek(0,2);log.seek(max(0,log.tell()-4000))
            raise ValueError(log.read().decode('utf-8','replace'))

def convert(source,dest):
    command([shutil.which('dnglab'),'convert','--compression','lossless','--embed-raw','false',str(source),str(dest)])
    if not dest.is_file() or dest.is_symlink() or dest.stat().st_size<16:raise ValueError('Keine DNG-Ausgabe erzeugt.')
    command([shutil.which('dnglab'),'analyze','--raw-checksum',str(dest)])

def run(base,job,selection):
    if not shutil.which('dnglab'):raise ValueError('DNGLab fehlt. Installation auf der RAW-zu-DNG-Seite beschrieben.')
    # Reuse the no-symlink inventory and source folder validation.
    with checks.directory(base.root,selection.get('folder','')) as parent:base.inventory(job,parent,selection.get('folder',''))
    rows=base.query('SELECT * FROM fotolabor_files WHERE job_id=?',(job,))
    for row in rows:
        if row['kind'] not in FORMATS:
            base.execute('DELETE FROM fotolabor_file_details WHERE job_id=? AND path=?',(job,row['path']))
            base.execute('DELETE FROM fotolabor_files WHERE job_id=? AND path=?',(job,row['path']))
    rows=base.query('SELECT * FROM fotolabor_files WHERE job_id=?',(job,));base.totals(job)
    if not rows:raise ValueError('Keine unterstützten RAW-Dateiendungen im gewählten Ordner gefunden.')
    target=output(base,job);target.mkdir(parents=True,mode=0o700,exist_ok=False)
    failures=0;results=[]
    for row in rows:
        if base.cancelled(job):raise InterruptedError('Umwandlung abgebrochen. Originale bleiben unverändert; neuen Auftrag starten.')
        relative=unpack(row['path']);base.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?',(relative,job))
        try:
            if row['status']!='pending':raise ValueError(row['reason'] or 'Quelldatei nicht regulär.')
            if shutil.disk_usage(target).free < row['bytes']*6+256*1024**2:raise ValueError('Nicht genügend freier Speicher für Umwandlung und Download.')
            with checks.directory(base.root,str(Path(relative).parent)) as parent,checks.opened(parent,Path(relative).name) as fd,tempfile.TemporaryDirectory(dir=target) as scratch:
                before=os.fstat(fd);src=Path(scratch)/('source'+row['kind']);dest=Path(scratch)/'converted.dng'
                with os.fdopen(os.dup(fd),'rb') as stream,src.open('xb') as copied:shutil.copyfileobj(stream,copied)
                after=os.fstat(fd)
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Quelle wurde beim Lesen verändert.')
                convert(src,dest)
                # Preserve extension in the name to avoid collisions between e.g. NEF and CR2.
                name=relative+'.dng';final=target/'files'/name;final.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with dest.open('rb') as converted,final.open('xb') as saved:shutil.copyfileobj(converted,saved)
                os.chmod(final,0o600)
            status,reason='derived','DNG erstellt und durch DNGLab dekodiert; Original unverändert.'
            results.append({'source':relative,'output':name,'status':'ok'})
        except Exception as exc:
            failures+=1;status,reason='uncheckable',str(exc);results.append({'source':relative,'status':'failed','reason':reason})
        base.execute('UPDATE fotolabor_files SET status=?,reason=? WHERE job_id=? AND path=?',(status,reason,job,row['path']));base.totals(job)
    (target/'report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));os.chmod(target/'report.json',0o600)
    with zipfile.ZipFile(target/'result.zip','x',compression=zipfile.ZIP_STORED) as archive:
        archive.write(target/'report.json','report.json')
        for item in results:
            if item['status']=='ok':archive.write(target/'files'/item['output'],item['output'])
    os.chmod(target/'result.zip',0o600)
    if failures:raise ValueError(f'{failures} von {len(rows)} Dateien nicht umgewandelt. Einzelgründe im Ergebnis; erfolgreiche DNGs sind im Download enthalten.')

def register(app,ctx,base,token,protected):
    e=lambda value:ctx.esc(str(value))
    @app.route('/fotolabor/raw-dng',methods=['GET','POST'])
    def page():
        error=''
        if request.method=='POST':
            if not protected():return 'Formular abgelaufen.',403
            try:
                if not shutil.which('dnglab'):raise ValueError('DNGLab ist noch nicht installiert.')
                jid=base.start('raw_dng',selection={'folder':request.form.get('folder',''),'gentle':True})
                return redirect('/fotolabor/raw-dng?job='+str(jid),303)
            except (OSError,ValueError) as exc:error=str(exc)
        body=_ui_html("<div class='card'><h2>RAW nach DNG</h2><a class='btn' href='/fotolabor'>Fotolabor</a><p>Kamera-RAWs als zusätzliche DNG-Dateien speichern. Originale und XMP-Begleitdateien werden nicht verändert. Enthaltene Unterordner werden mit verarbeitet. Vorhandene DNGs und JPEGs werden ausgelassen.</p><p>Formate: ")+e(', '.join(sorted(FORMATS)))+_ui_html(". Das konkrete Kameramodell und die RAW-Variante müssen von DNGLab unterstützt werden.</p><p>Verlustfreie Kompression; das Original wird nicht zusätzlich im DNG eingebettet. Externe XMP-Bearbeitungen werden nicht übernommen. RAW-Bursts: nur das erste Bild. Ergebnisse vor einer weiteren Verwendung in deiner Fotosoftware prüfen.</p>")
        if error:body+=_ui_html("<p class='err'>")+e(_ui_text(error))+_ui_html('</p>')
        available=bool(shutil.which('dnglab'))
        body+=_ui_html('<p>Konverter: ')+(_ui_text('DNGLab vorhanden') if available else _ui_text('DNGLab fehlt'))+_ui_html('</p>')
        if not available:body+=_ui_html("<p>Das zur Serverarchitektur passende Debian-Paket aus den <a href='https://github.com/dnglab/dnglab/releases'>offiziellen DNGLab-Releases</a> herunterladen und auf dem Server mit <code>sudo apt install ./dnglab_VERSION_ARCH.deb</code> installieren. Danach diese Seite neu laden.</p>")
        body+=f'{_ui_html("<form method='post'><input type='hidden' name='csrf' value='")}{e(token())}{_ui_html("'><label>Quellordner relativ zum Fotolabor (leer = gesamter Bildordner)<input name='folder' placeholder='z. B. Urlaub/RAW' style='width:100%'></label><p><button class='btn' ")}{('disabled' if not available else '')}{_ui_html('>Umwandlung starten</button></p></form><p>Ausgabe: geschützter separater Ordner je Auftrag unter <code>')}{e(Path(base.ctx.state_dir) / 'fotolabor-dng')}{_ui_html('</code>. Download als ZIP mit Ordnerstruktur und Ergebnisprotokoll. Der Server bleibt während des Auftrags wach.</p></div>')}'
        jobs=base.query("SELECT * FROM fotolabor_jobs WHERE mode='raw_dng' ORDER BY id DESC LIMIT 20")
        from .plugin import STATES
        for row in jobs:
            jid=row['id'];body+=f'{_ui_html("<div class='card'><h3>Auftrag #")}{jid}{_ui_html(' · ')}{e(_ui_text(STATES.get(row['state'], _ui_text(row['state']))))}{_ui_html('</h3><p>')}{row['checked']}{' / '}{row['total']}{_ui_html(' Dateien · ')}{e(row['current'])}{_ui_html('</p><p>')}{e(_ui_text(row['error']))}{_ui_html('</p>')}'
            if row['state'] in ('queued','running'):
                body+=f'{_ui_html("<form method='post' action='/fotolabor/cancel'><input type='hidden' name='csrf' value='")}{e(token())}{_ui_html("'><button class='btn'>Nach aktueller Datei abbrechen</button></form><script>setTimeout(()=>location.reload(),4000)</script>")}'
            elif (output(base,jid)/'result.zip').is_file():body+=f'{_ui_html("<a class='btn' href='/fotolabor/raw-dng/")}{jid}{_ui_html("/download'>DNGs und Protokoll herunterladen</a>")}'
            body+=_ui_html('</div>')
        return ctx.page(_ui_text('RAW nach DNG'),body,'Fotolabor')
    @app.route('/fotolabor/raw-dng/<int:jid>/download')
    def download(jid):
        rows=base.query("SELECT state FROM fotolabor_jobs WHERE id=? AND mode='raw_dng'",(jid,))
        path=output(base,jid)/'result.zip'
        if not rows or rows[0]['state'] not in ('completed','failed') or not path.is_file():return 'Kein fertiger Download.',404
        return send_file(path,as_attachment=True,download_name=f'RAW-DNG-{jid}.zip')
