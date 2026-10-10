import json,os,subprocess,sys,tempfile,contextlib,fcntl
import server_settings
from pathlib import Path
def reserve(fd, size):
    space=os.fstatvfs(fd)
    if space.f_bavail*space.f_frsize < size+512*1024**2:
        raise ValueError('Insufficient temporary storage; 512 MiB reserve required')


def invoke(spec,user,stream=None):
    output=tempfile.TemporaryFile()
    try:
        with contextlib.ExitStack() as cleanup:
            lock_fd=None
            if spec['action'] in ('put','delete'):
                folder=server_settings.STATE_DIR/'offline-locks';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
                lock_fd=os.open(folder/(spec['row']['id']+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
                cleanup.callback(os.close,lock_fd)
                fcntl.flock(lock_fd,fcntl.LOCK_EX)
            from . import rights,samba_acl
            acl_fd=cleanup.enter_context(samba_acl.broker(user)) if rights.uses_samba(spec.get('row',{}).get('path','')) else None
            inherited=tuple(fd for fd in (lock_fd,acl_fd) if fd is not None)
            incoming=cleanup.enter_context(tempfile.TemporaryFile())
            incoming.write(json.dumps(spec).encode()+b'\n')
            if stream is not None:
                count=0
                reserve(incoming.fileno(),spec['size'])
                while True:
                    chunk=stream.read(min(1024*1024,spec['size']-count+1))
                    if not chunk:break
                    count+=len(chunk)
                    if count>spec['size']:raise ValueError('Upload too large')
                    reserve(incoming.fileno(),len(chunk))
                    incoming.write(chunk)
                if count!=spec['size']:raise ValueError('Incomplete upload')
            incoming.seek(0)
            result=subprocess.run([sys.executable,'-m','modules.offline_files.worker'],cwd=Path(__file__).resolve().parents[2],stdin=incoming,stdout=output,stderr=subprocess.PIPE,timeout=300,pass_fds=inherited,umask=0o027,user=user.pw_uid,group=user.pw_gid,extra_groups=os.getgrouplist(user.pw_name,user.pw_gid),env={'HSM_OFFLINE_ACL_FD':str(acl_fd) if acl_fd is not None else '', 'HSM_OFFLINE_LOCK_FD':str(lock_fd) if lock_fd is not None else '', 'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','SERVER_MANAGER_CONFIG':'/proc/self/hsm-offline-config','SERVER_MANAGER_STATE':'/proc/self/hsm-offline-state','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'})
        output.seek(0)
        if result.returncode:
            try:error=json.loads(result.stderr[:8192])
            except Exception:error=dict(error='File access denied or worker failed')
            if error.get('conflict'):raise FileExistsError(error['error'])
            raise ValueError(error['error'])
        if spec['action']=='get':return output
        data=json.load(output);output.close();return data
    except Exception:output.close();raise
