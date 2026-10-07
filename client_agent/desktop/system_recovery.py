"""Read-only path gates for the interactive Linux system recovery assistant."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,os,subprocess,sys
from pathlib import Path

def direct(value):
 p=Path(value)
 if not p.is_absolute() or '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)):raise ValueError(tr('Absoluten Pfad ohne symbolische Links wählen.'))
 if not p.is_dir():raise ValueError(tr('Ordner fehlt.'))
 return p

def mount_info(path):
 return json.loads(subprocess.check_output(['findmnt','-J','-T',str(path),'-o','TARGET,FSTYPE'],text=True))['filesystems'][0]

def storage(value,source=None):
 p=direct(value);m=mount_info(p)
 if m['target']=='/' or p.stat().st_dev==Path('/').stat().st_dev:raise ValueError(tr('Systemlaufwerk ist als Sicherungsziel gesperrt.'))
 if m['fstype'] not in ('ext2','ext3','ext4','btrfs','xfs','f2fs','nfs','nfs4'):raise ValueError(tr('System-Sicherung benötigt Linux-Dateirechte: ext4/Btrfs/XFS oder passend eingerichtetes NFS. FAT/exFAT/NTFS/SMB bleiben für ZIP-Dateisicherungen verfügbar.'))
 if source:
  source=direct(source)
  if p==source or p.is_relative_to(source) or source.is_relative_to(p):raise ValueError(tr('Quelle und Sicherungsziel dürfen nicht ineinander liegen.'))
 return str(p)

def live():
 cmd=Path('/proc/cmdline').read_text()
 return 'boot=live' in cmd.split() or 'boot=casper' in cmd.split() or Path('/run/live/medium').is_mount() or Path('/cdrom/casper').is_dir()

def restore_target(value,backup):
 if not live():raise ValueError(tr('Systemwiederherstellung ausschließlich vom Live-USB starten.'))
 p=direct(value);b=direct(backup)
 if any((a/'.unvollstaendig').exists() for a in (b,*b.parents)):raise ValueError(tr('Sicherung ist als unvollständig markiert. Erst Protokolle prüfen; keine automatische Systemrücksicherung.'))
 if p==Path('/') or p.stat().st_dev==Path('/').stat().st_dev or not p.is_mount():raise ValueError(tr('Installiertes Zielsystem separat einhängen; Live-System darf nicht Ziel sein.'))
 if not (p/'etc/os-release').is_file() or not (p/'etc/passwd').is_file():raise ValueError(tr('Ziel benötigt eine vorhandene Linux-Grundinstallation. Kein Partitionierungs-/Bootloaderwerkzeug.'))
 if b==p or b.is_relative_to(p) or p.is_relative_to(b):raise ValueError(tr('Sicherung und Zielsystem müssen getrennt sein.'))
 return str(p)

def main():
 action=sys.argv[1]
 if action=='storage':print(storage(*sys.argv[2:]))
 elif action=='restore':print(restore_target(*sys.argv[2:]))
 elif action=='user':
  root=direct(sys.argv[2]);name=sys.argv[3]
  rows=[line.split(':') for line in (root/'etc/passwd').read_text().splitlines()]
  row=next((r for r in rows if len(r)==7 and r[0]==name),None)
  if not row or not row[2].isdigit() or int(row[2])<1000:raise ValueError(tr('Vorhandenen normalen Zielbenutzer angeben.'))
  home=direct(str(root)+row[5]);home.relative_to(root)
  print(str(home));print(row[2]);print(row[3])
 else:raise ValueError(tr('Unbekannte Prüfung.'))
if __name__=='__main__':
 try:main()
 except (OSError,ValueError,subprocess.SubprocessError) as exc:raise SystemExit(str(exc))
