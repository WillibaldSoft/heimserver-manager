#!/usr/bin/env python3
"""Plan an offline UID/GID migration. Only explicitly selected local user/group."""
import argparse,base64,json,os,pwd,re,shutil,stat,subprocess,sys,tempfile,time
from pathlib import Path
from backup_client import direct,identifier,mounted_below

def offline_root(root):
    root=direct(root)
    if not root.is_dir() or os.path.samefile(root,'/'):raise ValueError('Nur ein offline eingebundenes Linux-System ist zulässig, nicht das laufende System.')
    if not os.path.ismount(root) or root.stat().st_dev==Path('/').stat().st_dev:raise ValueError('Ziel muss ein separat eingebundenes Offline-Dateisystem sein.')
    kind=subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target',str(root)],text=True).strip()
    if kind not in ('ext2','ext3','ext4','xfs','btrfs','f2fs'):raise ValueError('Nur lokale Linux-Dateisysteme zulässig.')
    return root

def plan(root,user,identity):
    root=offline_root(root)
    passwd=direct(root/'etc/passwd');group=direct(root/'etc/group')
    users=[x.split(':') for x in passwd.read_text().splitlines() if x];groups=[x.split(':') for x in group.read_text().splitlines() if x]
    row=next((x for x in users if x[0]==user),None)
    if row is None or len(row)!=7:raise ValueError('Clientbenutzer nicht gefunden.')
    uid,gid=int(row[2]),int(row[3]);new_uid,new_gid=int(identity['uid']),int(identity['gid'])
    if not all(1000<=n<60000 for n in (uid,gid,new_uid,new_gid)):raise ValueError('Nur normale Benutzer und private Gruppen (IDs 1000–59999).')
    if any(x[0]!=user and int(x[2]) in (uid,new_uid) for x in users):raise ValueError('Alte oder neue UID ist einem weiteren Benutzer zugeordnet.')
    primary=next((x for x in groups if int(x[2])==gid),None)
    if primary is None:raise ValueError('Primäre Clientgruppe fehlt.')
    if gid!=new_gid:
        if any(int(x[2])==new_gid for x in groups):raise ValueError('Ziel-GID ist bereits belegt.')
        if any(x[0]!=user and int(x[3])==gid for x in users) or any(n and n!=user for n in primary[3].split(',')):raise ValueError('Primäre Clientgruppe wird gemeinsam genutzt; keine automatische Änderung.')
    home=Path(row[5])
    if not home.is_absolute() or '..' in home.parts or home==Path('/'):raise ValueError('Ungültiges Client-Home.')
    home=direct(root/str(home).lstrip('/'))
    if not home.is_dir():raise ValueError('Client-Home fehlt. Separate Home-Partition zuerst einbinden.')
    # Mounted subtrees need a separate audit; do not silently leave old owners there.
    mounts=mounted_below(root)
    if mounts:raise ValueError('Weitere Dateisysteme unter dem Ziel erkannt. Für diese Ausbaustufe Root und Home auf einem Dateisystem verwenden; sonst manuelle Migration: '+', '.join(mounts[:6]))
    files=[];acls=[];seen=set()
    for directory,dirs,names in os.walk(root,followlinks=False):
        links=[n for n in dirs if Path(directory,n).is_symlink()]
        dirs[:]=[n for n in dirs if n not in links]
        for p in [Path(directory)]+[Path(directory,n) for n in names+links]:
            info=p.lstat()
            inode=(info.st_dev,info.st_ino)
            if inode in seen:continue
            seen.add(inode)
            if info.st_uid==uid or info.st_gid==gid:
                cap=None
                if not stat.S_ISLNK(info.st_mode):
                    try:cap=base64.b64encode(os.getxattr(p,'security.capability',follow_symlinks=False)).decode()
                    except OSError:pass
                files.append(dict(path=str(p.relative_to(root)),uid=info.st_uid,gid=info.st_gid,mode=stat.S_IMODE(info.st_mode),symlink=stat.S_ISLNK(info.st_mode),cap=cap))
            if not stat.S_ISLNK(info.st_mode):
                attrs=os.listxattr(p,follow_symlinks=False)
                if 'system.posix_acl_access' in attrs or 'system.posix_acl_default' in attrs:acls.append(str(p))
    return dict(root=str(root),user=user,group=primary[0],old_uid=uid,old_gid=gid,new_uid=new_uid,new_gid=new_gid,files=files,acl_paths=acls,passwd=passwd.read_text(),groups=group.read_text())

def mapped_acl(text,p):
    text=re.sub(r'(?m)^((?:default:)?user:)'+str(p['old_uid'])+':',lambda m:m[1]+str(p['new_uid'])+':',text)
    text=re.sub(r'(?m)^((?:default:)?group:)'+str(p['old_gid'])+':',lambda m:m[1]+str(p['new_gid'])+':',text)
    text=re.sub(r'(?m)^(# owner: )'+str(p['old_uid'])+'$',lambda m:m[1]+str(p['new_uid']),text)
    return re.sub(r'(?m)^(# group: )'+str(p['old_gid'])+'$',lambda m:m[1]+str(p['new_gid']),text)

def apply(p):
    if os.geteuid()!=0:raise ValueError('Die Anwendung benötigt sudo im Live-System.')
    if not shutil.which('getfacl') or not shutil.which('setfacl'):raise ValueError('Paket acl im Live-System installieren.')
    root=Path(p['root']);backup=root/'var/lib'/('server-manager-id-before-'+time.strftime('%Y%m%d-%H%M%S'))
    direct(backup);backup.mkdir(mode=0o700,parents=True,exist_ok=False)
    (backup/'plan.json').write_text(json.dumps(p,indent=2));(backup/'plan.json').chmod(0o600)
    shutil.copy2(root/'etc/passwd',backup/'passwd');shutil.copy2(root/'etc/group',backup/'group')
    acl=''
    for path in p['acl_paths']:
        acl+=subprocess.check_output(['getfacl','-p','-n','--',path],text=True)
    (backup/'acls.before').write_text(acl);(backup/'acls.after').write_text(mapped_acl(acl,p))
    changed=[]
    def accounts():
        users=[]
        for line in p['passwd'].splitlines():
            fields=line.split(':')
            if fields[0]==p['user']:fields[2:4]=[str(p['new_uid']),str(p['new_gid'])]
            users.append(':'.join(fields))
        groups=[]
        for line in p['groups'].splitlines():
            fields=line.split(':')
            if fields[0]==p['group']:fields[2]=str(p['new_gid'])
            groups.append(':'.join(fields))
        (root/'etc/passwd').write_text('\n'.join(users)+'\n');(root/'etc/group').write_text('\n'.join(groups)+'\n')
    def owner(item,uid,gid):
        path=direct(root/item['path']) if not item['symlink'] else root/item['path']
        os.chown(path,uid,gid,follow_symlinks=False)
        if not item['symlink']:
            os.chmod(path,item['mode'],follow_symlinks=False)
            if item['cap']:os.setxattr(path,'security.capability',base64.b64decode(item['cap']),follow_symlinks=False)
    try:
        for item in p['files']:
            changed.append(item)
            owner(item,p['new_uid'] if item['uid']==p['old_uid'] else item['uid'],p['new_gid'] if item['gid']==p['old_gid'] else item['gid'])
        if acl:subprocess.run(['setfacl','--restore='+str(backup/'acls.after')],check=True)
        accounts()
    except BaseException:
        failures=[]
        for item in reversed(changed):
            try:owner(item,item['uid'],item['gid'])
            except OSError as e:failures.append(str(e))
        try:
            if acl:subprocess.run(['setfacl','--restore='+str(backup/'acls.before')],check=True)
            shutil.copy2(backup/'passwd',root/'etc/passwd');shutil.copy2(backup/'group',root/'etc/group')
        except Exception as e:failures.append(str(e))
        if failures:raise RuntimeError('Rücksetzung unvollständig! Nicht starten; Sicherung: '+str(backup)+'; '+str(failures))
        raise
    print('IDs angeglichen. Sicherung und Dateiliste:',backup)
    print('Passwörter, Benutzernamen und zusätzliche Gruppenmitgliedschaften bleiben unverändert.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-root',required=True,type=Path);parser.add_argument('--local-user',required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('client.json'));parser.add_argument('--apply',action='store_true')
    a=parser.parse_args();config=json.loads(a.config.read_text());identifier(a.local_user)
    p=plan(a.target_root,a.local_user,config['server_identity'])
    print('Client:',p['user'],'UID/GID',p['old_uid'],p['old_gid'],'→ Server:',config['server_identity']['user'],p['new_uid'],p['new_gid'])
    print('Dateien/Ordner:',len(p['files']),' · ACL-Objekte:',len(p['acl_paths']))
    if not a.apply:print('Nur Vorschau. Für die geprüfte Änderung mit --apply erneut ausführen.');return
    if p['old_uid']==p['new_uid'] and p['old_gid']==p['new_gid']:print('IDs bereits gleich.');return
    if input('Offline-System gesichert? Zum Angleichen ANGLEICHEN eingeben: ')!='ANGLEICHEN':return
    apply(p)
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError,KeyError,RuntimeError) as e:print('Abbruch:',e,file=sys.stderr);sys.exit(1)
