"""Local interactive accounts only; no NSS imports and no password persistence."""
import hashlib,hmac,json,os,pwd,re,subprocess,threading,time
from pathlib import Path
PASSWD=Path('/etc/passwd');SHADOW=Path('/etc/shadow');LOGIN_DEFS=Path('/etc/login.defs')
PAM=Path('/etc/pam.d/server-manager')
POLICY='# Heimserver Manager: local account authentication\nauth requisite pam_localuser.so\n@include common-auth\n@include common-account\n'
SLOTS=threading.BoundedSemaphore(4)
def ensure_policy():
    if PAM.exists() or PAM.is_symlink():return
    if os.geteuid()!=0:return
    fd=os.open(PAM,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    with os.fdopen(fd,'w') as f:f.write(POLICY)
def ready():
    try:
        st=PAM.lstat()
        return not PAM.is_symlink() and PAM.is_file() and st.st_uid==0 and not st.st_mode & 0o022
    except OSError:return False
def candidates():
    low,high=1000,60000
    try:
        for line in LOGIN_DEFS.read_text().splitlines():
            parts=line.split()
            if len(parts)>=2 and parts[0] in ('UID_MIN','UID_MAX'):
                if parts[0]=='UID_MIN':low=max(1000,int(parts[1]))
                else:high=min(60000,int(parts[1]))
    except (OSError,ValueError):pass
    rows=[]
    for line in PASSWD.read_text().splitlines():
        fields=line.split(':')
        if len(fields)!=7:continue
        name,_,uid,gid,comment,home,shell=fields
        if not uid.isdigit() or not low<=int(uid)<=high or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}\$?',name):continue
        if not shell or Path(shell).name in ('false','nologin','sync','shutdown','halt'):continue
        rows.append(dict(name=name,uid=int(uid),label=comment.split(',')[0],home=home))
    return sorted(rows,key=lambda x:x['name'].casefold())
def identity(name,secret):
    user=next((u for u in candidates() if u['name']==name),None)
    if not user:return None
    try:
        if pwd.getpwnam(name).pw_uid!=user['uid']:return None
        fields=next((line.split(':') for line in SHADOW.read_text().splitlines() if line.split(':',1)[0]==name),None)
        if not fields or len(fields)<8 or not fields[1] or fields[1].startswith(('!','*')):return None
        days=int(time.time()//86400)
        if fields[7] and int(fields[7])>=0 and days>=int(fields[7]):return None
        if fields[2]=='0':return None
        if fields[2] and fields[4] and int(fields[4])>=0 and days>int(fields[2])+int(fields[4]):return None
        # Only a keyed change marker enters the session, never shadow hashes.
        stamp=hmac.new(secret.encode(),(':'.join(fields)+':'+str(user['uid'])).encode(),hashlib.sha256).hexdigest()
        return dict(user,stamp=stamp)
    except (OSError,KeyError,ValueError):return None

def verify(name,password):
    if not ready() or not isinstance(password,str) or not password or len(password)>256 or '\0' in password:return False
    if not SLOTS.acquire(blocking=False):return False
    try:
        result=subprocess.run(['/usr/bin/python3','-I',str(Path(__file__).with_name('pam_worker.py'))],input=json.dumps(dict(username=name,password=password)),text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'})
        return result.returncode==0 and result.stdout.strip()=='OK'
    except (OSError,subprocess.SubprocessError):return False
    finally:SLOTS.release()
