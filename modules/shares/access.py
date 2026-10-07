"""Explain Samba rules and bounded POSIX directory ACLs without guessing file access."""
import copy,grp,os,pwd,re,shlex
from pathlib import Path
from . import configuration as c,helpers as h,accounts

LISTS=('valid users','invalid users','read list','write list','admin users')
LABEL={'none':'Kein Zugriff','read':'Lesen','write':'Lesen / Schreiben','admin':'SMB-Admin','unknown':'Nicht eindeutig','inherit':'Gruppen / Standard','unassigned':'Keine Gruppenfreigabe','traverse':'Nur Betreten','write_only':'Schreiben ohne Auflisten'}

def tokens(value):
    lexer=shlex.shlex(value or '',posix=True);lexer.whitespace_split=True;lexer.whitespace+=',';lexer.escape='';lexer.commenters=''
    return list(lexer)

def encoded(parts):return ' '.join('"'+p+'"' if any(char.isspace() for char in p) else p for p in parts)

def effective_configs():
    result=h.run(['testparm','-s',str(h.SMB_CONF)],timeout=15)
    if not result.get('ok'):raise ValueError('Samba-Konfiguration konnte nicht ausgewertet werden: '+result.get('err',''))
    text=result.get('out','');rows={name.casefold():c.config(text[a:b]) for name,a,b in c.sections(text)}
    base=rows.get('global',{})
    return {key:dict(base,**cfg) for key,cfg in rows.items() if key not in c.SPECIAL}

def subject(name):
    result=dict(name=name,group=name.startswith(('@','+')),resolved=False,gids=[],groups=[])
    if result['group']:
        try:
            g=grp.getgrnam(name[1:]);result.update(resolved=True,gid=g.gr_gid,members=list(g.gr_mem))
        except KeyError:pass
    else:
        try:
            u=pwd.getpwnam(name);gids=os.getgrouplist(u.pw_name,u.pw_gid);groups=[]
            for gid in gids:
                try:groups.append(grp.getgrgid(gid).gr_name)
                except KeyError:pass
            result.update(resolved=True,uid=u.pw_uid,gid=u.pw_gid,gids=gids,groups=groups)
        except KeyError:pass
    return result

def matches(token,who):
    if token.casefold()==who['name'].casefold():return True
    if token.startswith(('@','+')):
        if who['group']:return False
        return token[1:].casefold() in {g.casefold() for g in who.get('groups',[])}
    return False

def unsupported(cfg):
    for key in LISTS:
        for t in tokens(cfg.get(key,'')):
            if any(char in t for char in ('%','*','?','&')):return True
    return False

def yes(value):return str(value).lower() in ('yes','true','1')

def samba_right(cfg,who):
    if unsupported(cfg):return dict(level='unknown',reason='Dynamische Namen oder Netgroups erfordern manuelle Prüfung.',admin=False)
    lists={key:[t for t in tokens(cfg.get(key,'')) if matches(t,who)] for key in LISTS}
    if lists['invalid users']:return dict(level='none',reason='Gesperrt durch '+', '.join(lists['invalid users']),admin=False)
    if tokens(cfg.get('valid users','')) and not lists['valid users']:
        if not who['resolved'] and not who['group']:return dict(level='unknown',reason='Gruppenzugehörigkeit des Kontos nicht auflösbar.',admin=False)
        return dict(level='none',reason='Nicht in den erlaubten Benutzern/Gruppen enthalten.',admin=False)
    if not who['resolved'] and not who['group'] and any(t.startswith(('@','+')) for key in LISTS for t in tokens(cfg.get(key,''))):
        return dict(level='unknown',reason='Gruppen des Kontos nicht auflösbar.',admin=False)
    read_only=yes(cfg.get('read only','no' if yes(cfg.get('writable',cfg.get('writeable','no'))) else 'yes'))
    write=bool(lists['write list']) or (not read_only and not lists['read list'])
    admin=bool(lists['admin users'])
    reason=('Schreibregel: '+', '.join(lists['write list']) if lists['write list'] else 'Leseregel: '+', '.join(lists['read list']) if lists['read list'] else 'Standard der Freigabe')
    if lists['valid users']:reason+='; erlaubt über '+', '.join(lists['valid users'])
    if admin:reason+='; Dateivorgänge als root über '+', '.join(lists['admin users'])
    return dict(level='admin' if admin and write else 'write' if write else 'read',reason=reason,admin=admin)

def filesystem_subject(cfg,who):
    """Resolve the identity Samba uses for filesystem operations."""
    effective=copy.deepcopy(who);notes=[]
    forced=cfg.get('force user','').strip()
    if forced:
        if any(char in forced for char in '%*?'):raise ValueError('Dynamischer force user nicht auflösbar.')
        effective=subject(forced)
        if not effective['resolved'] or effective['group']:raise ValueError('Erzwungener Dateibenutzer nicht auflösbar.')
        notes.append('Dateibenutzer: '+forced)
    forced=cfg.get('force group','').strip()
    if forced:
        conditional=forced.startswith('+');name=forced.lstrip('+')
        if any(char in name for char in '%*?'):raise ValueError('Dynamische force group nicht auflösbar.')
        group=subject('@'+name)
        if not group['resolved']:raise ValueError('Erzwungene Dateigruppe nicht auflösbar.')
        if not conditional or group['gid'] in effective.get('gids',[]):
            effective['gid']=group['gid']
            effective['gids']=list(set(effective.get('gids',[])+[group['gid']]))
            notes.append('Dateigruppe: '+name)
    return effective,'; '.join(notes)

def smb_folder_right(cfg,snap,who):
    if who['group']:return folder_right(snap,who)
    try:
        effective,note=filesystem_subject(cfg,who)
        return folder_right(snap,effective)+(' ('+note+')' if note else '')
    except ValueError as exc:return str(exc)

def displayed_right(cfg,who,path,get_snapshot):
    """Separate a group's rule from a user's bounded filesystem access."""
    def result(level,reason):return dict(level=level,reason=reason,admin=False)
    if cfg is None:return result('unknown','Freigabe nicht geladen oder Konfiguration nicht prüfbar.')
    if who['group']:
        explicit=any(matches(t,who) for key in LISTS for t in tokens(cfg.get(key,'')))
        if not explicit:return result('unassigned','Keine SMB-Regel für diese Gruppe. Der Freigabestandard ist keine Gruppenberechtigung; Mitglieder können über andere Regeln oder allgemeine Ordnerrechte Zugriff haben.')
        rule=samba_right(cfg,who)
        rule['reason']='Gruppenregel (kein Nachweis für jedes Mitglied): '+rule['reason']
        return rule
    rule=samba_right(cfg,who)
    if rule['level'] in ('none','unknown'):return rule
    if not who['resolved']:return result('unknown','Benutzeridentität nicht auflösbar.')
    try:effective,identity_note=filesystem_subject(cfg,who)
    except ValueError as exc:return result('unknown',str(exc))
    modules=set(tokens(cfg.get('vfs objects','')))
    if modules-{'acl_xattr','recycle','full_audit','audit','streams_xattr','catia','fruit','shadow_copy2'}:
        return result('unknown','Nicht unterstützte VFS-Rechteauswertung: '+', '.join(sorted(modules)))
    if 'acl_xattr' in modules and yes(cfg.get('acl_xattr:ignore system acls','no')):
        return result('unknown','Windows-ACLs ersetzen die POSIX-Rechte (ignore system acls = yes).')
    # Do not bypass filesystem checks for an admin: root semantics and remote
    # filesystems can differ. Show the configured role without claiming access.
    if rule.get('admin'):return result('unknown','SMB-Admin konfiguriert; Dateizugriff als root muss separat geprüft werden.')
    for parent in reversed(Path(path).parents):
        snap=get_snapshot(str(parent))
        if snap is None:return result('unknown','Übergeordnete Ordnerrechte nicht prüfbar: '+str(parent))
        value=acl_bits(snap,effective)
        if value is None:return result('unknown','Ordneridentität nicht auflösbar.')
        if not value&1:return result('none','Übergeordneter Ordner nicht betretbar: '+str(parent))
    snap=get_snapshot(path)
    if snap is None:return result('unknown','Hauptordnerrechte nicht prüfbar.')
    value=acl_bits(snap,effective)
    if value is None:return result('unknown','Ordneridentität nicht auflösbar.')
    if not value&1:return result('none','Hauptordner nicht betretbar: '+perms(value)+'. SMB-Regel allein gewährt keinen Dateizugriff.')
    if 'acl_xattr' in modules and snap.get('ntacl','unknown')!='absent':
        return result('unknown','POSIX: '+folder_right(snap,effective)+'. '+identity_note+'; zusätzliche Windows-ACL vorhanden oder nicht lesbar. Diese muss zusätzlich ausgewertet werden.')
    can_write=rule['level']=='write' and bool(value&2)
    level=('write' if can_write else 'read') if value&4 else ('write_only' if can_write else 'traverse')
    return result(level,rule['reason']+('; '+identity_note if identity_note else '')+'; wirksame POSIX-Rechte: '+perms(value)+'. Gilt für den Hauptordner nach erfolgreicher SMB-Anmeldung; einzelne Inhalte können abweichen.')

def direct_rule(cfg,name):
    present=lambda key:any(t.casefold()==name.casefold() for t in tokens(cfg.get(key,'')))
    if present('invalid users'):return 'none'
    if present('admin users'):return 'admin'
    if present('write list'):return 'write'
    if present('read list'):return 'read'
    # valid users alone inherits read-only/writeable, not a read permission.
    return 'inherit'

def all_subjects(shares,configs):
    names={u['name'] for u in accounts.users()}
    names.update('@'+g['name'] for g in accounts.groups())
    for row in shares:
        cfg=configs.get(row['name'].casefold(),row['config'])
        for key in LISTS:
            names.update(t for t in tokens(cfg.get(key,'')) if not any(char in t for char in ('%','&','*','?')))
    return [subject(n) for n in sorted(names,key=lambda n:(n.startswith(('@','+')),n.casefold()))]

def snapshot(path):
    path=str(Path(path));st=os.stat(path,follow_symlinks=False)
    if not __import__('stat').S_ISDIR(st.st_mode):raise ValueError('Kein regulärer Ordner oder symbolischer Link.')
    result=h.run(['getfacl','-c','-p','-n','--',path],timeout=10);c.checked(result,'Ordnerrechte nicht lesbar')
    ntacl='unknown'
    # security.* attributes may appear absent to unprivileged readers.
    if os.geteuid()==0:
        import errno
        try:os.getxattr(path,'security.NTACL');ntacl='present'
        except OSError as exc:
            if exc.errno==errno.ENODATA:ntacl='absent'
    return dict(ntacl=ntacl,path=path,dev=st.st_dev,ino=st.st_ino,uid=st.st_uid,gid=st.st_gid,mode=st.st_mode,before=result['out'])

def acl_entries(text):
    result={}
    for line in text.splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        parts=line.split(':');perm=parts[-1];key=':'.join(parts[:-1])
        if re.fullmatch(r'[r-][w-][x-]',perm):result[key]=perm
    return result

def bits(perm):return (4 if 'r' in perm else 0)|(2 if 'w' in perm else 0)|(1 if 'x' in perm else 0)
def perms(value):return ('r' if value&4 else '-')+('w' if value&2 else '-')+('x' if value&1 else '-')

def acl_bits(snap,who):
    entries=acl_entries(snap['before']);mask=bits(entries.get('mask:','rwx'))
    if not who['resolved']:return None
    if who['group']:
        key='group:' if who['gid']==snap['gid'] else 'group:'+str(who['gid'])
        return bits(entries.get(key,'---'))&mask
    if who['uid']==0:return 7
    if who['uid']==snap['uid']:return bits(entries.get('user:','---'))
    named='user:'+str(who['uid'])
    if named in entries:return bits(entries[named])&mask
    matched=[]
    if snap['gid'] in who['gids']:matched.append(bits(entries.get('group:','---')))
    for gid in who['gids']:
        if 'group:'+str(gid) in entries:matched.append(bits(entries['group:'+str(gid)]))
    if matched:
        value=0
        for permission in matched:value|=permission
        return value&mask
    return bits(entries.get('other:','---'))

def folder_right(snap,who):
    value=acl_bits(snap,who)
    if value is None:return 'Nicht auflösbar'
    if not value&1:return 'Kein Betreten ('+perms(value)+')'
    if value&6==6:return 'Lesen / Schreiben'
    if value&4:return 'Lesen'
    if value&2:return 'Schreiben ohne Auflisten'
    return 'Nur Betreten'

def acl_plan(path,who,level,defaults=False):
    if not who['resolved']:raise ValueError('Konto/Gruppe muss auf dem Server auflösbar sein, um Ordnerrechte zu ändern.')
    if not who['group'] and who['uid']==0:raise ValueError('Root-Zugriff kann durch diese Ordnerrechte nicht eingeschränkt werden.')
    snap=snapshot(c.folder(path));entries=acl_entries(snap['before']);wanted={'none':'---','read':'r-x','write':'rwx','admin':'rwx'}[level]
    for prefix in ('','default:') if defaults else ('',):
        if prefix and 'default:user:' not in entries:
            for key in ('user:','group:','other:'):entries[prefix+key]=entries.get(key,'---')
        mask=bits(entries.get(prefix+'mask:','rwx'))
        key=('group:' if who['group'] and who['gid']==snap['gid'] else 'group:'+str(who['gid']) if who['group'] else 'user:' if who['uid']==snap['uid'] else 'user:'+str(who['uid']))
        target=prefix+key
        # Preserve effective permissions of other mask-class entries before widening the mask.
        for entry,value in list(entries.items()):
            if prefix:
                if not entry.startswith(prefix):continue
                simple=entry[len(prefix):]
            else:
                if entry.startswith('default:'):continue
                simple=entry
            if entry!=target and (simple.startswith('group:') or (simple.startswith('user:') and simple!='user:')):
                entries[entry]=perms(bits(value)&mask)
        entries[target]=wanted
        combined=0
        for entry,value in entries.items():
            if prefix:
                if not entry.startswith(prefix):continue
                simple=entry[len(prefix):]
            else:
                if entry.startswith('default:'):continue
                simple=entry
            if simple.startswith('group:') or (simple.startswith('user:') and simple!='user:'):combined|=bits(value)
        entries[prefix+'mask:']=perms(combined)
    snap['after']='\n'.join(key+':'+value for key,value in entries.items())+'\n'
    snap['subject']=who['name'];snap['level']=level;snap['defaults']=defaults
    return snap

def validate_acl(change):
    now=snapshot(change['path'])
    for key in ('dev','ino','uid','gid','mode','before'):
        if now[key]!=change[key]:raise ValueError('Ordner oder Ordnerrechte wurden inzwischen geändert. Neue Vorschau erforderlich.')

def write_acl(change,restore=False):
    # Use a pinned fd so a path swap cannot redirect permission changes.
    from .slim_fd import directory_fd
    with directory_fd(change['path']) as fd:
        st=os.fstat(fd)
        if (st.st_dev,st.st_ino,st.st_uid,st.st_gid)!=(change['dev'],change['ino'],change['uid'],change['gid']):raise ValueError('Ordner wurde ausgetauscht.')
        import subprocess
        text=change['before'] if restore else change['after']
        # --set-file does not remove an absent default ACL; remove it explicitly when required.
        commands=[]
        if not any(line.startswith('default:') for line in text.splitlines()):commands.append((['setfacl','-k','--','/proc/self/fd/'+str(fd)],None))
        commands.append((['setfacl','--set-file=-','--','/proc/self/fd/'+str(fd)],text))
        for args,input_text in commands:
            result=subprocess.run(args,input=input_text,text=True,capture_output=True,timeout=15,pass_fds=(fd,))
            if result.returncode:raise ValueError('Ordnerrechte konnten nicht gesetzt werden: '+result.stderr)

def validate_rights(plan):
    guard=plan.get('rights_guard')
    if not guard:return
    who=subject(guard['subject']);result=samba_right(guard['config'],who)
    if result['level']!=guard['level'] or (guard['level']=='read' and result['admin']):
        raise ValueError('Gruppenmitgliedschaft oder Kontozuordnung hat sich geändert. Neue Rechtevorschau erforderlich.')

def build(data):
    proto=data.get('protocol','smb');key=data.get('key','');name=c.single(data.get('subject',''),'Benutzer/Gruppe')
    if not re.fullmatch(r'[@+]?[\w .\\@-]{1,128}',name):raise ValueError('Bitte genau einen Benutzer oder eine @Gruppe auswählen.')
    who=subject(name);level=data.get('level')
    if level not in ('inherit','none','read','write','admin'):raise ValueError('Ungültiges Recht.')
    row=c.smb_one(key) if proto=='smb' else c.nfs_one(key) if proto=='nfs' else None
    if row is None:raise ValueError('Unbekanntes Protokoll.')
    files={};plan=c.make_plan('Rechte ändern: '+name+' · '+row.get('name',row['path']),'smb' if proto=='smb' else 'acl',files,None)
    if proto=='smb':
        if data.get('defaults')=='1' and data.get('folder_acl')!='1':raise ValueError('Vererbung erfordert zusätzlich die Auswahl „Ordnerrechte ebenfalls anpassen“.')
        plan['dependencies']={str(path):c.read(path) for path in c.smb_files()}
        cfg=effective_configs().get(row['name'].casefold())
        if cfg is None:raise ValueError('Freigabe wird von Samba nicht geladen.')
        if unsupported(cfg):raise ValueError('Dynamische Samba-Namen/Netgroups zuerst in der Konfiguration prüfen.')
        lists={k:tokens(cfg.get(k,'')) for k in LISTS}
        for k in ('invalid users','read list','write list','admin users'):
            lists[k]=[t for t in lists[k] if t.casefold()!=name.casefold()]
        if level=='inherit':
            previous=lists['valid users'];lists['valid users']=[t for t in previous if t.casefold()!=name.casefold()]
            if previous and not lists['valid users']:raise ValueError('Die letzte Erlaubnis darf nicht entfernt werden: Eine leere Liste würde alle Konten zulassen. Stattdessen „Kein Zugriff“ auswählen.')
        elif level=='none':lists['invalid users'].append(name)
        else:
            if lists['valid users'] and not any(t.casefold()==name.casefold() for t in lists['valid users']):lists['valid users'].append(name)
            lists['write list' if level in ('write','admin') else 'read list'].append(name)
            if level=='admin':
                if data.get('confirm_admin')!='1':raise ValueError('SMB-Admin arbeitet als root. Bitte die zusätzliche Bestätigung markieren.')
                lists['admin users'].append(name)
        changed={k:encoded(v) for k,v in lists.items()}
        after=dict(cfg,**changed);result=samba_right(after,who)
        if not who['group'] and level!='inherit' and (result['level']!=level or (level=='read' and result['admin'])):
            raise ValueError('Eine Gruppenregel verhindert das gewünschte Recht: '+result['reason']+'. Bitte zuerst die betreffende Gruppe bearbeiten.')
        if not who['group'] and level!='inherit':plan['rights_guard']=dict(subject=name,level=level,config=after)
        source=Path(row['file']);text=c.read(source)
        c.change(files,source,text.replace(row['raw'],c.patch_section(row['raw'],changed),1))
        plan['rights_summary']=[['Benutzer / Gruppe',name],['SMB-Recht',LABEL[level]],['Regelwirkung',result['reason']]]
        if yes(cfg.get('guest ok','no')):plan['rights_summary'].append(['Gastzugriff','Bleibt aktiv: Anonyme Zugriffe sind unabhängig von dieser Benutzerregel.'])
        if data.get('folder_acl')=='1' and level=='inherit':raise ValueError('Beim Entfernen einer Samba-Regel werden keine Ordnerrechte abgeleitet. Ordneränderung bitte abwählen.')
        if data.get('folder_acl')=='1' and level!='inherit':
            forced=cfg.get('force group','').strip('\"').lstrip('+')
            if cfg.get('force user') or (forced and not (who['group'] and who['name'][1:].casefold()==forced.casefold())):raise ValueError('Diese Freigabe erzwingt eine Dateiidentität (force user/group). Ordnerrechte bitte separat unter NFS/Ordnerrechten bzw. für die erzwungene Gruppe ändern; die SMB-Regel kann ohne Ordneränderung gespeichert werden.')
            plan['acl_change']=acl_plan(row['path'],who,level,data.get('defaults')=='1')
    else:
        if level not in ('none','read','write'):raise ValueError('Für NFS sind Ordnerrechte Lesen, Schreiben oder kein zusätzlicher Zugriff wählbar.')
        plan['acl_change']=acl_plan(row['path'],who,level,data.get('defaults')=='1')
        # Bind ACL plan to its export definition without changing the export.
        source=Path(row['file']);c.change(files,source,c.read(source))
        plan['rights_summary']=[['Benutzer / Gruppe',name],['Ordnerrecht',LABEL[level]],['NFS-Export',row['clients']]]
    if plan.get('acl_change'):
        path=row['path'];shared=[r.get('name',r['path']) for r in c.smb_shares()+c.nfs_exports() if r['path']==path]
        plan['rights_summary'].append(['Ordneränderung gilt auch für',', '.join(shared)])
        plan['rights_summary'].append(['Umfang','Nur Hauptordner'+(' und Vererbung für neue Inhalte' if data.get('defaults')=='1' else '; keine Unterordner oder Dateien')])
    return plan
