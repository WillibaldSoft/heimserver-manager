"""Reviewable configuration edits; preserve unrelated text and rollback failed reloads."""
from pathlib import Path
from contextlib import contextmanager
import difflib, fcntl, hashlib, ipaddress, json, os, re, shlex, stat, tempfile, time, uuid, threading

_ACTIVE=threading.Event()
_MUTEX=threading.Lock()
from . import helpers as h

SMB_INDEX=Path('/etc/samba/shares.includes.conf')
NFS_DIR=Path('/etc/exports.d')
PROTECTED=('/root','/var','/opt','/tmp')
SPECIAL={'global','homes','printers','print$','ipc$'}

def single(value,label):
    value=str(value).strip()
    if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError(label+': keine Zeilenumbrüche oder Steuerzeichen erlaubt.')
    return value

def share_name(value):
    value=single(value,'Freigabename')
    if not re.fullmatch(r'[A-Za-z0-9ÄÖÜäöüß][A-Za-z0-9ÄÖÜäöüß _.-]{0,63}',value) or value.lower() in SPECIAL:
        raise ValueError('Freigabename: 1–64 Buchstaben, Ziffern, Leerzeichen, Punkt, _ oder -. Keine reservierten Namen.')
    return value

def folder(value,create=False):
    value=single(value,'Ordner')
    p=Path(value)
    if not p.is_absolute() or '..' in p.parts or len(p.parts)<3 or not h.is_path_safe(value) or any(p==Path(v) or p.is_relative_to(v) for v in PROTECTED):
        raise ValueError('Bitte einen Daten-Unterordner mit vollständigem Pfad wählen, z. B. /srv/freigaben/familie.')
    if any(c in value for c in ['"','\\','%','#',';']):raise ValueError('Dieser Ordnername enthält für Freigaben ungeeignete Sonderzeichen.')
    for part in [p,*p.parents]:
        if part.is_symlink():raise ValueError('Bitte den tatsächlichen Ordner statt eines symbolischen Links auswählen.')
    if p.exists() and not p.is_dir():raise ValueError('Der Pfad ist kein Ordner.')
    if not p.exists() and not create:raise ValueError('Ordner existiert nicht. „Ordner neu anlegen“ auswählen oder Pfad korrigieren.')
    if not p.exists() and not p.parent.is_dir():raise ValueError('Der übergeordnete Ordner muss bereits vorhanden sein.')
    return str(p)

def read(path):
    p=Path(path)
    if p.is_symlink():raise ValueError('Konfigurationsdatei ist ein symbolischer Link: '+str(p))
    return p.read_text() if p.exists() else None

def digest(text):return hashlib.sha256(text.encode()).hexdigest() if text is not None else None

def sections(text):
    matches=list(re.finditer(r'^\s*\[([^]\n]+)\][ \t]*(?:[#;].*)?$',text or '',re.M))
    return [(m.group(1).strip(),m.start(),matches[i+1].start() if i+1<len(matches) else len(text)) for i,m in enumerate(matches)]

def config(text):
    result={}
    for line in text.splitlines():
        s=line.strip()
        if s and not s.startswith(('#',';','[')) and '=' in s:
            key,value=s.split('=',1);result[key.strip().lower()]=value.strip()
    return result

def smb_files():
    # Read known configuration and recursively follow literal include files only.
    paths=[];seen=set()
    def visit(p,depth=0):
        p=Path(p)
        if p in seen or depth>12:return
        seen.add(p)
        if not p.exists():return
        if p.is_symlink():return
        paths.append(p)
        for value in re.findall(r'^\s*include\s*=\s*(.+?)\s*$',p.read_text(),re.M|re.I):
            if any(c in value for c in '*?%'):continue
            target=Path(value)
            if not target.is_absolute():target=p.parent/target
            # Editable system configuration is limited to Samba's own directory.
            if target.is_relative_to(h.SMB_CONF.parent) and '..' not in target.parts:visit(target,depth+1)
    visit(h.SMB_CONF)
    for p in sorted(h.SMB_SHARES_DIR.glob('*.conf')):visit(p)
    return paths

def smb_shares():
    rows=[]
    for p in smb_files():
        text=read(p) or ''
        for name,start,end in sections(text):
            if name.lower() in SPECIAL:continue
            raw=text[start:end];cfg=config(raw)
            rows.append(dict(name=name,path=cfg.get('path',''),comment=cfg.get('comment',''),config=cfg,file=str(p),raw=raw))
    return sorted(rows,key=lambda r:r['name'].casefold())

def smb_one(name):
    matches=[r for r in smb_shares() if r['name'].casefold()==name.casefold()]
    if len(matches)!=1:raise ValueError('Freigabe nicht eindeutig gefunden; doppelte Definitionen zuerst bereinigen.')
    return matches[0]

def nfs_exports():
    rows=[]
    for p in [h.NFS_EXPORTS,*sorted(NFS_DIR.glob('*.exports'))]:
        text=read(p)
        if text is None:continue
        lines=text.splitlines(keepends=True);idx=0
        while idx<len(lines):
            start=idx;raw=lines[idx];idx+=1
            while raw.rstrip().endswith('\\') and idx<len(lines):raw+=lines[idx];idx+=1
            content=re.sub(r'\\\n',' ',raw).strip()
            if not content or content.startswith('#'):continue
            try:
                lexer=shlex.shlex(content,posix=True);lexer.whitespace_split=True;lexer.escape='';parts=list(lexer);path=parts[0];clients=' '.join(parts[1:])
                path=path.replace('\\040',' ').replace('\\011','\t')
            except (ValueError,IndexError):path='';clients=content
            rows.append(dict(id=hashlib.sha256((str(p)+':'+str(start)).encode()).hexdigest()[:24],path=path,clients=clients,raw=raw,file=str(p),start=start,end=idx))
    return rows

def nfs_one(key):
    for row in nfs_exports():
        if row['id']==key:return row
    raise ValueError('NFS-Freigabe nicht mehr gefunden. Übersicht neu laden.')

def principals(value):
    lexer=shlex.shlex(value,posix=True);lexer.whitespace_split=True;lexer.commenters='';lexer.escape=''
    return list(lexer)

def principal_list(value):
    value=single(value,'Benutzer und Gruppen')
    try:parts=principals(value)
    except ValueError:raise ValueError('Benutzer/Gruppen: Anführungszeichen nicht vollständig.')
    for part in parts:
        if not re.fullmatch(r'@?[\w .\\@-]{1,128}',part):raise ValueError('Ungültiger Benutzer-/Gruppenname: '+part)
    return ' '.join('"'+p+'"' if ' ' in p else p for p in parts)

def patch_section(raw,changes):
    aliases={'writable':'read only','writeable':'read only','public':'guest ok','browsable':'browseable'}
    result=[];done=set()
    for line in raw.splitlines():
        key=line.split('=',1)[0].strip().lower() if '=' in line and not line.lstrip().startswith(('#',';')) else ''
        canonical=aliases.get(key,key)
        if canonical in changes:
            if canonical not in done and changes[canonical] is not None:result.append('   '+canonical+' = '+changes[canonical])
            done.add(canonical)
        else:result.append(line)
    additions=['   '+key+' = '+value for key,value in changes.items() if key not in done and value is not None]
    at=next((i for i,line in enumerate(result) if re.match(r'^\s*include\s*=',line,re.I)),len(result))
    result[at:at]=additions
    return '\n'.join(result).rstrip()+'\n\n'

def change(files,path,text):
    path=str(path)
    if path not in files:files[path]={'before':read(path),'after':text}
    else:files[path]['after']=text

def build_smb(data):
    original=data.get('original','');deleting=data.get('operation')=='delete'
    old=smb_one(original) if original else None
    files={};mkdir=None
    if deleting:
        if not old:raise ValueError('Freigabe fehlt.')
        source=Path(old['file']);text=read(source)
        # Includes can follow the last share; preserve their lines when removing a section.
        replacement=''.join(line+'\n' for line in old['raw'].splitlines() if re.match(r'^\s*include\s*=',line,re.I))
        change(files,source,text.replace(old['raw'],replacement,1))
        return make_plan('SMB-Freigabe entfernen: '+old['name'],'smb',files,None)
    name=share_name(data.get('name',''))
    if original and name!=old['name']:raise ValueError('Der Netzwerkname bleibt beim Bearbeiten erhalten. Für einen neuen Namen eine neue Freigabe erstellen.')
    if not old and any(r['name'].casefold()==name.casefold() for r in smb_shares()):raise ValueError('Dieser Freigabename ist bereits vorhanden.')
    path=folder(data.get('path',''),data.get('create_dir')=='1')
    if not Path(path).exists():mkdir=path
    access=data.get('access','read')
    if access not in ('read','write','keep'):raise ValueError('Bitte Lesen oder Lesen und Schreiben wählen.')
    values={'path':path,'comment':single(data.get('comment',''),'Beschreibung'),'browseable':'yes' if data.get('browseable')=='1' else 'no','guest ok':'yes' if data.get('guest')=='1' else 'no'}
    valid=principal_list(data.get('valid_users',''));group=principal_list(data.get('force_group',''))
    if group and (len(principals(group))!=1 or group.startswith('@')):raise ValueError('Gemeinsame Gruppe: genau einen Gruppennamen ohne @ eingeben.')
    values['valid users']=valid or None;values['force group']=group or None
    if access!='keep':
        values['read only']='yes' if access=='read' else 'no'
        values['write list']=None;values['read list']=None;values['admin users']=None
    if not old:
        if not valid and data.get('guest')!='1':raise ValueError('Bitte mindestens einen erlaubten Benutzer oder eine @Gruppe angeben.')
        if access=='keep':raise ValueError('Für eine neue Freigabe bitte ein Zugriffsrecht wählen.')
        raw='['+name+']\n   create mask = 0660\n   directory mask = 2770\n   inherit acls = yes\n'
        source=h.SMB_SHARES_DIR/('server-manager-'+hashlib.sha256(name.encode()).hexdigest()[:20]+'.conf')
        if source.exists():raise ValueError('Zieldatei existiert bereits.')
        change(files,source,patch_section(raw,values))
        index=read(SMB_INDEX) or ''
        include='include = '+str(source)
        change(files,SMB_INDEX,index.rstrip()+'\n'+include+'\n')
        main=read(h.SMB_CONF)
        if main is None:raise ValueError('Samba ist noch nicht eingerichtet; smb.conf fehlt.')
        if not any(line.strip()==('include = '+str(SMB_INDEX)) for line in main.splitlines()):
            change(files,h.SMB_CONF,main.rstrip()+'\n\n# Server Manager Freigaben\ninclude = '+str(SMB_INDEX)+'\n')
    else:
        source=Path(old['file']);text=read(source)
        change(files,source,text.replace(old['raw'],patch_section(old['raw'],values),1))
    plan=make_plan(('SMB-Freigabe ändern: ' if old else 'SMB-Freigabe erstellen: ')+name,'smb',files,mkdir)
    if mkdir:
        # New folders receive access only for explicitly selected local identities.
        import pwd,grp
        entries=[]
        for part in principals(valid):
            if part.startswith('@'):entries.append(('g',grp.getgrnam(part[1:]).gr_gid))
            else:entries.append(('u',pwd.getpwnam(part).pw_uid))
        if group:entries.append(('g',grp.getgrnam(principals(group)[0]).gr_gid))
        plan['acl']=[f'{kind}:{uid}:'+('rwx' if access=='write' else 'r-x') for kind,uid in entries]
        if data.get('guest')=='1':plan['acl'].append('o::'+('rwx' if access=='write' else 'r-x'))
    return plan

def client_hosts(value):
    parts=re.split(r'[\s,]+',single(value,'Erlaubte Geräte'))
    parts=[p for p in parts if p]
    if not parts:raise ValueError('Mindestens eine IP-Adresse oder ein Netzwerk angeben.')
    result=[]
    for part in parts:
        try:result.append(str(ipaddress.ip_network(part,strict=False)) if '/' in part else str(ipaddress.ip_address(part)))
        except ValueError:raise ValueError('Erlaubte Geräte bitte als IP-Adresse oder Netzwerk angeben, z. B. 192.168.1.0/24.')
    return list(dict.fromkeys(result))

def nfs_simple(row):
    hosts=[];modes=set();root=set()
    for piece in row['clients'].split():
        m=re.fullmatch(r'([^()]+)\(([^()]+)\)',piece)
        if not m:return None
        opts=set(m[2].split(','))
        if opts-{'rw','ro','rwx','sync','no_subtree_check','root_squash','no_root_squash'}:return None
        try:hosts.extend(client_hosts(m[1]))
        except ValueError:return None
        modes.add('write' if opts & {'rw','rwx'} else 'read');root.add('no_root_squash' not in opts)
    if len(modes)!=1 or len(root)!=1:return None
    return dict(hosts=' '.join(hosts),access=modes.pop(),root_squash=root.pop(),invalid='rwx' in row['clients'])

def build_nfs(data):
    old=nfs_one(data['original']) if data.get('original') else None
    files={};mkdir=None
    if data.get('operation')=='delete':
        if not old:raise ValueError('Freigabe fehlt.')
        text=read(old['file']);lines=text.splitlines(keepends=True)
        change(files,old['file'],''.join(lines[:old['start']]+lines[old['end']:]))
        return make_plan('NFS-Freigabe entfernen: '+old['path'],'nfs',files,None)
    if old and nfs_simple(old) is None and data.get('replace_advanced')!='1':raise ValueError('Diese Freigabe hat erweiterte NFS-Optionen. Das Ersetzen muss ausdrücklich ausgewählt werden.')
    path=folder(data.get('path',''),data.get('create_dir')=='1')
    if not Path(path).exists():mkdir=path
    if any(r['path']==path and (not old or r['id']!=old['id']) for r in nfs_exports()):raise ValueError('Für diesen Ordner existiert bereits ein NFS-Eintrag. Diesen bitte bearbeiten.')
    if data.get('access') not in ('read','write'):raise ValueError('Ungültige Zugriffsart.')
    hosts=client_hosts(data.get('hosts',''))
    opts=['rw' if data['access']=='write' else 'ro','sync','no_subtree_check','root_squash' if data.get('root_squash')=='1' else 'no_root_squash']
    line='"'+path+'" '+ ' '.join(host+'('+','.join(opts)+')' for host in hosts)+'\n'
    if old:
        lines=read(old['file']).splitlines(keepends=True)
        change(files,old['file'],''.join(lines[:old['start']])+line+''.join(lines[old['end']:]))
    else:
        text=read(h.NFS_EXPORTS) or ''
        change(files,h.NFS_EXPORTS,text.rstrip()+'\n'+line)
    plan=make_plan(('NFS-Freigabe ändern: ' if old else 'NFS-Freigabe erstellen: ')+path,'nfs',files,mkdir)
    if mkdir:
        import grp
        group=single(data.get('folder_group',''),'Ordnergruppe')
        if not group:raise ValueError('Für einen neuen NFS-Ordner bitte eine gemeinsame Linux-Gruppe wählen. Deren GID muss zu den Clients passen.')
        gid=grp.getgrnam(group).gr_gid
        plan['acl']=['g:'+str(gid)+':'+('rwx' if data['access']=='write' else 'r-x')]
    return plan

def make_plan(title,kind,files,mkdir):
    return dict(title=title,kind=kind,files=files,mkdir=mkdir,created=time.time())

def preview(plan):
    return '\n'.join(''.join(difflib.unified_diff((v['before'] or '').splitlines(True),(v['after'] or '').splitlines(True),fromfile=p+' (bisher)',tofile=p+' (neu)')) for p,v in plan['files'].items())

def atomic(path,text):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    previous=p.stat() if p.exists() else None
    fd,tmp=tempfile.mkstemp(prefix='.'+p.name+'.',dir=p.parent)
    try:
        with os.fdopen(fd,'w') as out:out.write(text);out.flush();os.fsync(out.fileno())
        os.chmod(tmp,stat.S_IMODE(previous.st_mode) if previous else 0o644)
        if previous and os.geteuid()==0:os.chown(tmp,previous.st_uid,previous.st_gid)
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def checked(result,message):
    if not result.get('ok'):raise ValueError(message+': '+(result.get('err') or result.get('out') or str(result.get('rc',''))))

def apply(plan,password=''):
    if not _MUTEX.acquire(blocking=False):raise ValueError('Eine Freigabenänderung läuft bereits. Bitte kurz warten.')
    _ACTIVE.set()
    try:return _apply(plan,password)
    finally:_ACTIVE.clear();_MUTEX.release()

def _apply(plan,password=''):
    if time.time()-plan['created']>900:raise ValueError('Vorschau ist abgelaufen. Bitte erneut prüfen.')
    if plan['kind'] in ('smb','nfs'):
        probe=['testparm','--version'] if plan['kind']=='smb' else ['exportfs','-v']
        checked(h.run(probe,timeout=15),'Serverwerkzeug fehlt oder ist nicht ausführbar. Unter Apps → SMB/NFS installieren / prüfen ausführen')
    h.BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    with open(h.BACKUP_DIR/'change.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for path,v in plan['files'].items():
            if read(path)!=v['before']:raise ValueError('Konfiguration wurde inzwischen geändert. Neue Vorschau erforderlich.')
        for path,before in plan.get('dependencies',{}).items():
            if read(path)!=before:raise ValueError('Eine abhängige Samba-Konfiguration wurde inzwischen geändert.')
        if plan.get('rights_guard'):
            from .access import validate_rights
            validate_rights(plan)
        if plan.get('acl_change'):
            from .access import validate_acl,write_acl
            validate_acl(plan['acl_change'])
        if plan['mkdir']:folder(plan['mkdir'],True)
        backup=h.BACKUP_DIR/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);backup.mkdir(mode=0o700)
        (backup/'restore.json').write_text(json.dumps({p:v['before'] for p,v in plan['files'].items()},ensure_ascii=False,indent=2));os.chmod(backup/'restore.json',0o600)
        if plan.get('acl_change'):
            (backup/'acl-before.json').write_text(json.dumps(plan['acl_change'],ensure_ascii=False,indent=2));os.chmod(backup/'acl-before.json',0o600)
        changed=[];created=False;acl_changed=False
        def reload():
            if plan['kind']=='smb':return h.sudo_run(['systemctl','reload','smbd.service'],password=password,timeout=20)
            if plan['kind']=='acl':return {'ok':True}
            return h.sudo_run(['exportfs','-ra'],password=password,timeout=30)
        try:
            if plan['mkdir']:
                Path(plan['mkdir']).mkdir(mode=0o770);created=True
                if plan.get('acl'):
                    for flags in ([],['-d']):checked(h.sudo_run(['setfacl',*flags,'-m',','.join(plan['acl']),'--',plan['mkdir']],password=password,timeout=15),'Ordnerrechte konnten nicht gesetzt werden')
            for path,v in plan['files'].items():
                if v['before']!=v['after']:atomic(path,v['after']);changed.append(path)
            if plan['kind']=='smb':checked(h.run(['testparm','-s',str(h.SMB_CONF)],timeout=15),'Samba-Prüfung fehlgeschlagen')
            if plan.get('acl_change'):
                acl_changed=True;write_acl(plan['acl_change'])
            checked(reload(),'Freigaben konnten nicht aktiviert werden')
            return {'ok':True,'backup':str(backup)}
        except Exception as exc:
            errors=[]
            if acl_changed:
                try:write_acl(plan['acl_change'],restore=True)
                except Exception as restore:errors.append('Ordnerrechte: '+str(restore))
            for path in reversed(changed):
                try:
                    before=plan['files'][path]['before']
                    if before is None:Path(path).unlink(missing_ok=True)
                    else:atomic(path,before)
                except Exception as restore:errors.append(str(restore))
            if changed:
                result=reload()
                if not result.get('ok'):errors.append('Vorherige Konfiguration konnte nicht erneut geladen werden: '+str(result.get('err','')))
            if created:
                try:Path(plan['mkdir']).rmdir()
                except OSError:errors.append('Neu angelegter Ordner bleibt erhalten: '+plan['mkdir'])
            suffix=' Vorherige Konfiguration wiederhergestellt.' if not errors else ' Wiederherstellung prüfen: '+'; '.join(errors)
            raise ValueError(str(exc)+suffix+' Sicherung: '+str(backup)) from exc
