"""Explicit SMB writes using the user's keyring credentials and Samba permissions.

HTTPS remains authoritative for the assigned folder and revisions. Existing
files are updated in place to retain their full Windows ACL and owner. A verified
SMB revision is retained before changing data; interrupted writes are conflicts,
never silently accepted as a successful checkpoint.
"""
import contextlib,errno,hashlib,json,os,stat,subprocess,time,urllib.parse,uuid
from pathlib import Path
import core
from client_i18n import tr


def attributes(meta):
    host=urllib.parse.urlsplit(core.validate(core.load())['SERVER_URL']).hostname
    if not host or not meta.get('share') or not meta.get('user'):raise core.Error(tr('SMB-Zuordnung fehlt. Freigaben neu laden.'))
    return host,['application','heimserver-manager-client','server',host,'share',meta['share'],'username',meta['user']]


def password(meta,value=None,forget=False):
    _,attrs=attributes(meta)
    args=['secret-tool']+(['clear'] if forget else ['store','--label=Heimserver Manager · SMB'] if value is not None else ['lookup'])+attrs
    try:r=subprocess.run(args,input=value,text=True,capture_output=True,timeout=25)
    except (OSError,subprocess.TimeoutExpired):raise core.Error(tr('Lokaler Schlüsselbund nicht verfügbar.')) from None
    if r.returncode:raise core.Error(tr('SMB-Passwort fehlt oder der Schlüsselbund ist gesperrt.'))
    return r.stdout.rstrip('\n') if value is None and not forget else None


def components(path):
    if not path:return []
    bits=path.split('/')
    if any(not p or p in ('.','..') or '\\' in p or '\x00' in p for p in bits):raise core.Error('Invalid SMB path')
    return bits


class Writer:
    def __init__(self,meta,sub='',secret=None):
        import smbc
        self.host,_=attributes(meta);self.meta=meta
        self.prefix=components(meta.get('path',''))+components(sub)
        secret=password(meta) if secret is None else secret
        if not secret:raise core.Error(tr('SMB-Passwort fehlt oder der Schlüsselbund ist gesperrt.'))
        def auth(server,share,workgroup,user,unused):
            if server.casefold()!=self.host.casefold() or (share and share.casefold()!=meta['share'].casefold()):return ('','','')
            return ('WORKGROUP',meta['user'],secret)
        self.ctx=smbc.Context(auth_fn=auth,proto='SMB3')
        self.ctx.optionNoAutoAnonymousLogin=True
        self.ctx.timeout=5000
        directory=self.ctx.opendir(self.url());del directory

    def url(self,path=''):
        host='['+self.host+']' if ':' in self.host else self.host
        return 'smb://'+host+'/'+ '/'.join(urllib.parse.quote(x,safe='') for x in [self.meta['share']]+self.prefix+components(path))

    def revision(self,path):
        try:f=self.ctx.open(self.url(path),os.O_RDONLY)
        except OSError as e:
            if e.errno==errno.ENOENT:return None
            raise
        try:
            before=f.fstat()
            if not stat.S_ISREG(before[0]) or before[3]!=1:raise core.Error('Unsupported SMB file')
            h=hashlib.sha256()
            while True:
                data=f.read(1024*1024)
                if not data:break
                h.update(data)
            if before[:7]+before[8:] != (after:=f.fstat())[:7]+after[8:]:raise core.Error('SMB file changed during check')
            return h.hexdigest()
        finally:f.close()

    def parents(self,path):
        bits=components(path)
        for n in range(1,len(bits)):
            url=self.url('/'.join(bits[:n]))
            try:self.ctx.mkdir(url,0o750)
            except OSError as e:
                if e.errno!=errno.EEXIST:raise
            if not stat.S_ISDIR(self.ctx.stat(url)[0]):raise core.Error('Unsafe SMB parent')

    def copy(self,source,target):
        src=self.ctx.open(self.url(source),os.O_RDONLY)
        try:
            dst=self.ctx.open(self.url(target),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                acl=self.ctx.getxattr(self.url(source),'system.nt_sec_desc.*')
                self.ctx.setxattr(self.url(target),'system.nt_sec_desc.*',acl,0)
                if self.ctx.getxattr(self.url(target),'system.nt_sec_desc.*')!=acl:raise core.Error('Cannot preserve backup permissions')
                while True:
                    data=src.read(1024*1024)
                    if not data:break
                    self.write_all(dst,data)
            finally:dst.close()
        finally:src.close()

    @staticmethod
    def write_all(dst,data):
        while data:
            n=dst.write(data)
            if not n:raise core.Error('Incomplete SMB write')
            data=data[n:]

    def mutate(self,path,expected,source=None,sha=None,delete=False):
        if self.revision(path)!=(expected or None):raise core.Error('Conflict: SMB file changed')
        self.parents(path)
        history=None
        if expected:
            # Require write access on the file itself, not merely permission to
            # create a replacement in its parent. Do not truncate in this check.
            if not delete:self.ctx.open(self.url(path),os.O_WRONLY).close()
            bits=components(path);history='/'.join(bits[:-1]+['.hsm-history-'+str(time.time_ns())+'-'+uuid.uuid4().hex])
            self.copy(path,history)
            if self.revision(history)!=expected or self.revision(path)!=expected:raise core.Error('Conflict while retaining SMB revision')
        journal=Path.home()/'.config/server-manager-client/offline'/('smb-recovery-'+hashlib.sha256(self.url(path).encode()).hexdigest()+'.json')
        core.atomic(journal,json.dumps(dict(path=path,history=history,before=expected,after=sha)))
        try:
            if delete:self.ctx.unlink(self.url(path));journal.unlink();return {'sha':None}
            flags=os.O_WRONLY|os.O_TRUNC if expected else os.O_WRONLY|os.O_CREAT|os.O_EXCL
            dst=self.ctx.open(self.url(path),flags,0o660)
            try:
                h=hashlib.sha256()
                while True:
                    chunk=source.read(1024*1024)
                    if not chunk:break
                    h.update(chunk);self.write_all(dst,chunk)
            finally:dst.close()
            if h.hexdigest()!=sha or self.revision(path)!=sha:raise core.Error('SMB upload verification failed')
            journal.unlink();return {'sha':sha}
        except Exception as exc:
            # Never overwrite a concurrently changed server file as a rollback.
            # Both local content and the verified previous SMB revision survive.
            if history:raise core.Error(tr('SMB-Übertragung nicht abgeschlossen. Lokale Datei behalten; vorheriger Serverstand: ')+history) from exc
            raise
