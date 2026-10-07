"""Explicit Manager grants, bound to local account name and UID."""
import fcntl,json,os,secrets,tempfile
from pathlib import Path
from . import system,policy
ROLES={'admin':'Administrator','user':'Benutzer','viewer':'Nur Lesen'}
class Users:
    def __init__(self,path):self.path=Path(path)
    def read(self):
        try:data=json.loads(self.path.read_text())
        except FileNotFoundError:return dict(version=1,revision='initial',users={})
        if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('revision'),str) or not isinstance(data.get('users'),dict):raise ValueError('Ungültige Manager-Benutzerkonfiguration. Notfallzugang bleibt erhalten.')
        for name,row in data['users'].items():
            if not isinstance(row,dict) or type(row.get('uid')) is not int or row['uid']<1000 or not isinstance(row.get('role'),str) or row.get('role') not in ROLES or type(row.get('enabled')) is not bool or not isinstance(row.get('revision'),str) or not isinstance(row.get('modules'),list) or any(not isinstance(m,str) or m not in policy.SCOPES for m in row['modules']):raise ValueError('Ungültige Manager-Benutzerrechte.')
        return data
    def change(self,name,role,modules,enabled,expected,reserved,remove=False):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
            data=self.read()
            if expected!=data['revision']:raise ValueError('Die Rechte wurden inzwischen geändert. Seite neu laden.')
            if name==reserved:raise ValueError('Der eigenständige Notfallzugang wird hier nicht verändert.')
            if remove:
                if name not in data['users']:raise ValueError('Manager-Zugang nicht gefunden.')
                del data['users'][name]
            else:
                candidate=next((x for x in system.candidates() if x['name']==name),None)
                if not candidate:raise ValueError('Kein lokales interaktives Benutzerkonto.')
                if role not in ROLES or any(x not in policy.SCOPES for x in modules):raise ValueError('Ungültige Rolle oder Modulauswahl.')
                data['users'][name]=dict(uid=candidate['uid'],role=role,modules=sorted(set(modules)) if role!='admin' else [],enabled=bool(enabled),revision=secrets.token_hex(16))
            data['revision']=secrets.token_hex(16)
            fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.users-')
            try:
                with os.fdopen(fd,'w') as f:os.fchmod(f.fileno(),0o600);json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
                os.replace(tmp,self.path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
            return data
    def principal(self,name,secret):
        try:
            row=self.read()['users'].get(name)
            if not row or not row['enabled']:return None
            identity=system.identity(name,secret)
            if not identity or identity['uid']!=row['uid']:return None
            return dict(kind='system',name=name,uid=row['uid'],role=row['role'],modules=row['modules'],revision=row['revision'],stamp=identity['stamp'])
        except (OSError,ValueError):return None
    def verify(self,name,password,secret):
        before=self.principal(name,secret)
        if not before or not system.verify(name,password):return None
        after=self.principal(name,secret)
        return after if after==before else None
