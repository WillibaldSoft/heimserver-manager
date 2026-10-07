"""Selected recovery into a new directory; existing data is never overwritten."""
import hashlib,json,os,re,shutil,sys,time,uuid
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from modules.backup import external as e

def repository(conf):
    d=e.select_device(conf.get('uuid',''))
    if len(d['mounts'])!=1:raise ValueError('Externe Platte zuerst unter Speicher einhängen.')
    mount=e.safe_source(d['mounts'][0])
    if e.filesystem(mount)['uuid']!=conf['uuid']:raise ValueError('UUID der externen Platte stimmt nicht.')
    root=e.safe_source(str(mount/'Heimserver-Manager-Vollbackups'))
    return root

def snapshot(root,name):
    if not name or Path(name).name!=name or name.startswith('.'):raise ValueError('Ungültiger Sicherungsstand.')
    folder=e.safe_source(str(root/name));mf=folder/'manifest.json'
    if mf.is_symlink() or not mf.is_file() or mf.stat().st_size>16*1024*1024:raise ValueError('Ungültiges Sicherungsmanifest.')
    data=mf.read_bytes();manifest=json.loads(data)
    if manifest.get('format')!='heimserver-external-backup' or not manifest.get('completed'):raise ValueError('Kein abgeschlossener Sicherungsstand.')
    rows=[];seen=set()
    for row in manifest.get('sources',[]):
        directory=row.get('directory','')
        if not directory or directory.startswith('.') or Path(directory).name!=directory or directory in seen:raise ValueError('Ungültiger Quellordner im Manifest.')
        seen.add(directory);e.safe_source(str(folder/directory))
        rows.append({'directory':directory,'path':str(row.get('path',''))})
    if not rows:raise ValueError('Sicherungsstand enthält keine Quellen.')
    return folder,rows,hashlib.sha256(data).hexdigest()

def snapshots(conf):
    root=repository(conf);result=[]
    for p in sorted(root.iterdir(),reverse=True):
        if p.name.startswith('.') or p.is_symlink() or not p.is_dir():continue
        try:_,rows,_=snapshot(root,p.name);result.append((p.name,len(rows)))
        except (ValueError,OSError):continue
    return result

def prepare(conf,name,selected,target):
    root=repository(conf);folder,rows,digest=snapshot(root,name)
    selected=set(selected);known={r['directory'] for r in rows}
    if not selected or selected-known:raise ValueError('Mindestens einen gültigen Quellordner auswählen.')
    target=e.safe_source(target);e.disjoint([target],root);e.disjoint([target],e.ROOT.resolve())
    binding=e.validate_sources([target],conf['uuid'])
    return dict(config=conf,snapshot=name,digest=digest,selected=[r for r in rows if r['directory'] in selected],target=str(target),binding=binding)

def start(ctx,plan):
    with e.locked():
        if e.active():raise ValueError('Externer Auftrag läuft bereits.')
        e.busy(ctx)
        fresh=prepare(plan['config'],plan['snapshot'],[r['directory'] for r in plan['selected']],plan['target'])
        if fresh!=plan:raise ValueError('Quelle oder Ziel geändert. Rücksicherung erneut prüfen.')
        key=uuid.uuid4().hex
        info=dict(plan,id=key,created=time.time(),state='queued',operation='restore',message='Rücksicherung wird gestartet.')
        e.cfg.atomic(e.ROOT/'status.json',info)
        for name in ('copy.log','verify.log'):(e.ROOT/name).write_text('')
        args=['systemd-run','--quiet','--collect','--unit=server-manager-external-backup-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=7d']
        args+=['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE') if k in os.environ]
        try:e.command(args+['/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key])
        except Exception:
            e.cfg.atomic(e.ROOT/'status.json',{**info,'state':'failed','message':'Rücksicherungsdienst konnte nicht starten.'});raise

def worker(key):
    info=e.cfg.read(e.ROOT/'status.json')
    if info.get('id')!=key or info.get('state')!='queued' or info.get('operation')!='restore':return 1
    original=Path.cwd()
    def update(**values):info.update(values);e.cfg.atomic(e.ROOT/'status.json',info)
    try:
        update(state='running',message='Rücksicherung: Quellen und Ziel prüfen …')
        root=repository(info['config']);folder,rows,digest=snapshot(root,info['snapshot'])
        if digest!=info['digest']:raise ValueError('Sicherungsmanifest verändert.')
        selected={r['directory'] for r in info['selected']}
        if not selected or selected-{r['directory'] for r in rows}:raise ValueError('Ungültige Auswahl.')
        e.check_sources(info['binding']);target=e.safe_source(info['target'])
        e.disjoint([target],root);e.disjoint([target],e.ROOT.resolve())
        os.chdir(target) # pin destination filesystem, never fall through to host after unmount
        name='Ruecksicherung-'+time.strftime('%Y-%m-%d_%H-%M-%S')+'-'+key[:8]
        stage=Path('.partial-'+name);stage.mkdir(mode=0o700)
        update(destination=str(target/stage))
        total=sum(e.source_bytes(folder/r['directory']) for r in info['selected'])
        if shutil.disk_usage('.').free<total+max(256*1024**2,total//20):raise ValueError('Zu wenig freier Platz für Rücksicherung mit Reserve.')
        update(total_bytes=total)
        for i,row in enumerate(info['selected'],1):
            e.check_sources(info['binding']);repository(info['config'])
            source=e.safe_source(str(folder/row['directory']));dest=stage/row['directory'];dest.mkdir(mode=0o700)
            update(message='Rücksicherung '+str(i)+'/'+str(len(selected))+': '+row['path'],current=i,total=len(selected))
            e.rsync(source,dest,e.ROOT/'copy.log')
            log=e.ROOT/'verify.log';log.write_text('');e.rsync(source,dest,log,True)
            if log.stat().st_size:raise ValueError('Kopie weicht ab oder Quelle verändert; Teilordner prüfen.')
        e.check_sources(info['binding']);repository(info['config'])
        if snapshot(root,info['snapshot'])[2]!=digest:raise ValueError('Sicherungsmanifest während Rücksicherung geändert.')
        e.cfg.atomic(stage/'ZUORDNUNG.json',{'snapshot':info['snapshot'],'sources':info['selected']})
        e.command(['sync','-f',str(stage)],timeout=3600);stage.rename(name);e.command(['sync','-f','.'],timeout=3600)
        update(state='completed',destination=str(target/name),message='Ausgewählte Ordner zurückkopiert und geprüft. Anwendungsbackups anschließend im jeweiligen Modul wiederherstellen.',finished=time.time())
    except Exception as exc:update(state='failed',message=str(exc),finished=time.time())
    finally:os.chdir(original)
    return 0 if info['state']=='completed' else 1

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker' or not re.fullmatch('[a-f0-9]{32}',sys.argv[2]):raise SystemExit('Nur interner Rücksicherungsauftrag.')
    raise SystemExit(worker(sys.argv[2]))
