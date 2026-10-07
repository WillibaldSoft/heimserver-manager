"""Repair only invalid MPF thumbnail references; preserve all other bytes."""
import io,json,os,struct,tempfile,shutil
from pathlib import Path
from PIL import Image
from . import checks


def structure(data):
    if data[:2]!=b'\xff\xd8':raise checks.Uncheckable('Kein JPEG')
    pos=2;mpf=[]
    while pos<len(data):
        start=pos
        if data[pos]!=255:raise checks.Uncheckable('Ungültige JPEG-Struktur')
        while pos<len(data) and data[pos]==255:pos+=1
        if pos>=len(data):break
        marker=data[pos];pos+=1
        if marker==0xd9:return mpf,pos
        if marker in (0,0xd8) or 0xd0<=marker<=0xd7:raise checks.Uncheckable('Unerwarteter JPEG-Marker')
        if marker==1:continue
        if pos+2>len(data):break
        length=int.from_bytes(data[pos:pos+2],'big');end=pos+length
        if length<2 or end>len(data):break
        if marker==0xe2 and data[pos+2:pos+6]==b'MPF\0':mpf.append((start,end,pos+6))
        pos=end
        if marker==0xda:
            while pos<len(data):
                found=data.find(b'\xff',pos)
                if found<0:raise checks.Uncheckable('JPEG-Ende fehlt')
                nxt=found+1
                while nxt<len(data) and data[nxt]==255:nxt+=1
                if nxt>=len(data):raise checks.Uncheckable('JPEG-Ende fehlt')
                if data[nxt]==0 or 0xd0<=data[nxt]<=0xd7:pos=nxt+1;continue
                pos=found;break
    raise checks.Uncheckable('JPEG-Struktur unvollständig')


def pixels(im):
    im.load()
    return im.size,im.mode,im.tobytes(),im.info.get('icc_profile',b''),im.getexif().get(274,1)


def transform(data):
    segments,eoi=structure(data)
    if len(segments)!=1:raise checks.Uncheckable('Kein eindeutiger MPF-Eintrag')
    start,end,tiff=segments[0]
    with Image.open(io.BytesIO(data)) as im:
        if im.format!='MPO' or getattr(im,'n_frames',1)!=2:raise checks.Uncheckable('Keine eindeutige Hauptbild/Vorschaubild-Kombination')
        entries=im.mpinfo.get(0xb002,[])
        if len(entries)!=2 or entries[0]['Attribute']['MPType']!='Baseline MP Primary Image' or entries[1]['Attribute']['MPType'] not in ('Large Thumbnail (Full HD Equivalent)','Large Thumbnail (VGA Equivalent)'):
            raise checks.Uncheckable('MPF enthält keine eindeutig ausgewiesene Vorschau')
        before=pixels(im)
        try:im.seek(1);im.load()
        except (ValueError,SyntaxError,OSError):pass
        else:raise checks.Uncheckable('Vorschaubild bereits lesbar; keine Änderung')
    if eoi==len(data):
        result=data[:start]+data[end:];action='Ungültigen MPF-Verweis entfernt; keine nachgestellten Vorschaubilddaten vorhanden'
    else:
        # Correct only one complete, unambiguous thumbnail immediately after EOI.
        tail=data[eoi:];_,tailend=structure(tail)
        if tailend!=len(tail):raise checks.Uncheckable('Zusätzliche Daten nicht eindeutig zuordenbar')
        with Image.open(io.BytesIO(tail)) as thumb:
            if thumb.format!='JPEG':raise checks.Uncheckable('Zusatzbild ist kein einfaches JPEG')
            thumbnail=pixels(thumb)
        if thumbnail[0][0]>before[0][0] or thumbnail[0][1]>before[0][1]:raise checks.Uncheckable('Zusatzbild größer als Hauptbild')
        order={b'II':'<',b'MM':'>'}.get(data[tiff:tiff+2])
        if not order:raise checks.Uncheckable('Ungültige MPF-Byteordnung')
        def val(fmt,offset):
            n=struct.calcsize(fmt)
            if offset<tiff or offset+n>end:raise checks.Uncheckable('MPF-Verweis außerhalb des Segments')
            return struct.unpack_from(order+fmt,data,offset)[0]
        if val('H',tiff+2)!=42:raise checks.Uncheckable('Ungültiger MPF-Header')
        ifd=tiff+val('I',tiff+4);count=val('H',ifd);entry=None
        for n in range(count):
            at=ifd+2+n*12
            if val('H',at)==0xb002:
                if val('H',at+2)!=7 or val('I',at+4)!=32:raise checks.Uncheckable('Unbekanntes MPF-Entry-Format')
                if entry is not None:raise checks.Uncheckable('Doppelter MPF-Index')
                entry=tiff+val('I',at+8)
        if entry is None or entry<tiff or entry+32>end:raise checks.Uncheckable('MPF-Index fehlt')
        result=bytearray(data)
        for offset,value in ((entry+4,eoi),(entry+20,len(tail)),(entry+24,eoi-tiff)):
            struct.pack_into(order+'I',result,offset,value)
        result=bytes(result);action='MPF-Versatz und Längen der vorhandenen Vorschau korrigiert'
    with Image.open(io.BytesIO(result)) as im:
        if pixels(im)!=before:raise checks.Uncheckable('Hauptbild, Farbprofil oder Orientierung verändert')
        if eoi<len(data):
            im.seek(1)
            if pixels(im)!=thumbnail:raise checks.Uncheckable('Vorschaubild verändert')
    return result,action


def equivalent(source,candidate):
    try:return transform(Path(source).read_bytes())[0]==Path(candidate).read_bytes()
    except (OSError,ValueError,SyntaxError,checks.Uncheckable):return False


def run(service,job):
    from .service import pack,unpack
    # Only previously failed MPO auxiliary-frame cases; never rescan the archive.
    service.execute("""INSERT OR IGNORE INTO fotolabor_files(job_id,path,kind,status)
        SELECT DISTINCT ?,path,'.jpg','pending' FROM fotolabor_repairs
        WHERE status='failed' AND (reason LIKE '%No data found for frame%' OR (reason LIKE '%MpoImagePlugin%' AND reason LIKE '%not a JPEG file%'))
        AND NOT EXISTS(SELECT 1 FROM fotolabor_repairs r WHERE r.path=fotolabor_repairs.path AND r.status='repaired')""",(job,))
    service.totals(job)
    service.execute("UPDATE fotolabor_job_details SET phase='repairing' WHERE job_id=?",(job,))
    while True:
        rows=service.query("SELECT path FROM fotolabor_files WHERE job_id=? AND status='pending' ORDER BY path LIMIT 100",(job,))
        if not rows:return
        for row in rows:
            if service.cancelled(job):raise InterruptedError('MPF-Reparatur pausiert')
            path=Path(unpack(row['path']));work=None;output='';status='failed'
            service.execute('UPDATE fotolabor_jobs SET current=? WHERE id=?',(row['path'],job))
            try:
                if path.suffix.lower() not in ('.jpg','.jpeg'):raise checks.Uncheckable('Kein JPEG-Pfad')
                with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:
                    stamp=checks.signature(os.fstat(fd));checks.decode(fd,'.jpg')
                    with os.fdopen(os.dup(fd),'rb') as source:source.seek(0);data=source.read()
                    result,reason=transform(data)
                    work=Path(tempfile.mkdtemp(prefix='fotolabor-repair-',dir=service.ctx.state_dir));target=work/'repariert.jpg'
                    with open(target,'xb') as dest:dest.write(result);dest.flush();os.fsync(dest.fileno())
                    with checks.directory(work) as folder,checks.opened(folder,target.name) as repaired:checks.decode(repaired,'.jpg')
                    if checks.signature(os.fstat(fd))!=stamp or checks.signature(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=stamp:raise checks.Uncheckable('Original während Prüfung verändert')
                    output=str(target);status='repaired'
            except Exception as exc:reason=str(exc)
            if work and not output:shutil.rmtree(work)
            service.execute('INSERT OR REPLACE INTO fotolabor_repairs(job_id,path,status,reason,output) VALUES(?,?,?,?,?)',(job,row['path'],status,reason,output))
            service.execute('UPDATE fotolabor_files SET status=?,reason=? WHERE job_id=? AND path=?',('ok' if output else 'uncheckable',reason,job,row['path']))
            service.execute('UPDATE fotolabor_jobs SET checked=checked+1 WHERE id=?',(job,))
