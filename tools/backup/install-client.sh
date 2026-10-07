#!/bin/sh
set -eu
[ "$(id -u)" -ne 0 ] || { echo 'Als normaler Client-Benutzer starten, ohne sudo.'; exit 1; }
command -v python3 >/dev/null
command -v tar >/dev/null
command -v gio >/dev/null || { echo 'gio fehlt; Paket libglib2.0-bin und gvfs-backends installieren.'; exit 1; }
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dest="$HOME/.local/share/server-manager-backup"
mkdir -p "$dest" "$HOME/.local/share/applications"
cp "$base/backup_client.py" "$base/identity_sync.py" "$base/client.json" "$base/README.md" "$dest/"
chmod 700 "$dest"
# Desktop Exec fields need quoting independent of the shell.
python3 - "$dest" "$HOME/.local/share/applications/server-manager-backup.desktop" <<'PY'
import sys
from pathlib import Path
launcher=Path(sys.argv[1])/'start-backup.sh'
launcher.write_text("#!/bin/sh\ncd -- \"$(dirname -- \"$0\")\" || exit 1\npython3 backup_client.py backup\nresult=$?\nprintf '\\nZum Schließen Eingabetaste drücken.'\nread -r answer\nexit \"$result\"\n")
path=str(launcher)
if any(c in path for c in '\n\r'):raise SystemExit('Unzulässiger Home-Pfad')
quoted='"'+path.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
Path(sys.argv[2]).write_text('[Desktop Entry]\nType=Application\nName=Server-Backup – Jetzt sichern\nComment=Benutzerdateien auf dem Server sichern\nExec=sh '+quoted+'\nTerminal=true\nIcon=drive-harddisk\nCategories=Utility;Archiving;\n')
PY
echo 'Installiert: Im Anwendungsmenü „Server-Backup – Jetzt sichern“. Kein dauerhaft privilegierter Dienst.'
