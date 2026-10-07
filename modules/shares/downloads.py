"""Per-share client setup files. Passwords are requested on the client only."""
import re,shlex,socket
from urllib.parse import quote

def host(value):
    value=str(value or socket.gethostname()).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',value):raise ValueError('Serveradresse bitte als IPv4-Adresse oder DNS-Namen ohne Protokoll/Pfad angeben.')
    return value

def ps(value):return "'"+str(value).replace("'","''")+"'"

def client_file(protocol,row,platform,server):
    server=host(server)
    if protocol=='smb':
        name=row['name']
        if platform=='windows':
            return 'Freigabe-verbinden.ps1', '\ufeff'+'''# In Windows PowerShell als normaler Benutzer starten.
$ErrorActionPreference = 'Stop'
$Remote = '''+ps('\\\\'+server+'\\'+name)+'''
$Letter = (Read-Host 'Freier Laufwerksbuchstabe, z.B. Z').Trim().TrimEnd(':').ToUpperInvariant()
if ($Letter -notmatch '^[D-Z]$') { throw 'Bitte einen Buchstaben von D bis Z eingeben.' }
if (Get-PSDrive -Name $Letter -ErrorAction SilentlyContinue) { throw 'Dieser Laufwerksbuchstabe ist bereits belegt.' }
$Credential = Get-Credential -Message 'SMB-Benutzer und Passwort (bei AD: DOMAENE\\Benutzer)'
if ($null -eq $Credential) { throw 'Abgebrochen.' }
New-PSDrive -Name $Letter -PSProvider FileSystem -Root $Remote -Credential $Credential -Persist -Scope Global | Out-Null
Write-Host "Freigabe verbunden: ${Letter}:"
'''
        if platform=='linux':
            uri='smb://'+server+'/'+quote(name,safe='')
            return 'Freigabe-verbinden.sh','''#!/usr/bin/env bash
set -euo pipefail
if [ "${EUID:-$(id -u)}" -eq 0 ]; then echo 'Bitte ohne sudo in der Desktop-Sitzung starten.' >&2; exit 1; fi
command -v gio >/dev/null || { echo 'Benötigt: gio / gvfs-backends (Debian/Mint).' >&2; exit 1; }
uri='''+shlex.quote(uri)+'''
echo 'Zugangsdaten im folgenden Dialog eingeben. Dieses Skript enthält kein Passwort.'
gio mount "$uri"
gio open "$uri"
'''
    if protocol=='nfs' and platform=='linux':
        remote=server+':'+row['path']
        return 'NFS-verbinden.sh','''#!/usr/bin/env bash
set -euo pipefail
command -v mount.nfs >/dev/null || { echo 'Bitte zuerst das Paket nfs-common installieren.' >&2; exit 1; }
read -r -p 'Lokaler leerer Mount-Ordner (vollständiger Pfad): ' target
[[ "$target" == /* && "$target" != / ]] || { echo 'Ungültiger Pfad.' >&2; exit 1; }
if mountpoint -q -- "$target"; then echo 'Hier ist bereits ein Dateisystem eingehängt.' >&2; exit 1; fi
if [ -d "$target" ] && [ -n "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]; then echo 'Ordner ist nicht leer.' >&2; exit 1; fi
sudo mkdir -p -- "$target"
sudo mount -t nfs -o nosuid,nodev '''+shlex.quote(remote)+''' "$target"
echo 'Verbunden. Dieser Mount gilt bis zum Aushängen/Neustart; /etc/fstab bleibt unverändert.'
'''
    raise ValueError('Dieser Download wird für das gewählte Protokoll nicht angeboten.')
