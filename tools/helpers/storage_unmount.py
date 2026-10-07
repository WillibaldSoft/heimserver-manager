"""Unmount one verified data mount without force, recursion or fstab changes."""
import json,os,stat,subprocess,sys
PROTECTED=('/', '/boot','/etc','/usr','/var','/run','/proc','/sys','/dev','/opt','/home')
def validate(device,mount):
    if not mount.startswith('/') or os.path.realpath(mount)!=mount or any(mount==p or mount.startswith(p+'/') for p in PROTECTED if p!='/') or mount=='/':
        raise ValueError('System- oder nicht eindeutiger Mountpunkt: Aushängen gesperrt.')
    if not device.startswith('/dev/') or not stat.S_ISBLK(os.stat(device).st_mode):
        raise ValueError('Kein gültiges Blockgerät.')
    result=subprocess.run(['findmnt','--json','--mountpoint',mount,'--output','TARGET,MAJ:MIN'],capture_output=True,text=True,check=True,timeout=10)
    rows=json.loads(result.stdout).get('filesystems',[])
    number=os.stat(device).st_rdev
    if len(rows)!=1 or rows[0]['target']!=mount or rows[0]['maj:min']!=f'{os.major(number)}:{os.minor(number)}':
        raise ValueError('Mount-Zuordnung hat sich geändert. Seite neu laden.')
def unmount(device,mount):
    validate(device,mount)
    subprocess.run(['umount','--',mount],check=True,timeout=60)
if __name__=='__main__':
    try:
        unmount(*sys.argv[1:]);print('Erfolgreich ausgehängt. Einträge in fstab bleiben erhalten.')
    except Exception as exc:
        print('Aushängen fehlgeschlagen: '+str(exc),file=sys.stderr);sys.exit(1)
