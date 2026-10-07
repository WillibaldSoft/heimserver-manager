"""Optional AD setup profiles and interactive server/client setup downloads."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import ipaddress,json,re,shlex,shutil,socket
from contextlib import closing
from flask import request,redirect,Response
from . import helpers as h
from .downloads import ps
from .workflow import page,field,select,check,token

DEFAULT=dict(enabled=False,mode='member',realm='',netbios='',controller='',address='',forwarder='',admin='Administrator')

def validate(data):
    result={key:str(data.get(key,'')).strip() for key in DEFAULT if key!='enabled'}
    result['enabled']=data.get('enabled') in ('1',True)
    if result['mode'] not in ('member','controller'):raise ValueError('Bitte Beitritt oder neue Domäne wählen.')
    if not result['realm'] and not result['enabled']:return dict(DEFAULT,**result)
    realm=result['realm'].lower().rstrip('.')
    if len(realm)>253 or '.' not in realm or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in realm.split('.')):raise ValueError('Domäne als vollständigen DNS-Namen angeben, z. B. ad.beispiel.de.')
    result['realm']=realm
    netbios=result['netbios'].upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}',netbios):raise ValueError('Kurzname: 1–15 Zeichen, beginnend mit einem Buchstaben, z. B. FAMILIE.')
    result['netbios']=netbios
    if not re.fullmatch(r'[A-Za-z0-9_.@\\-]{1,128}',result['admin']) or result['admin'].startswith('-'):raise ValueError('Ungültiger Beitritts-Benutzer.')
    if result['controller'] and not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,14}',result['controller']):raise ValueError('DC-Rechnername: 1–15 Buchstaben/Ziffern oder Bindestriche.')
    for key in ('address','forwarder'):
        if result[key]:
            try:ipaddress.IPv4Address(result[key])
            except ValueError:raise ValueError('Für DC-Adresse und DNS-Weiterleitung bitte gültige IPv4-Adressen angeben.')
    if result['mode']=='controller' and not all(result[k] for k in ('controller','address','forwarder')):raise ValueError('Für eine neue Domäne sind DC-Rechnername, feste IP und DNS-Weiterleitung erforderlich.')
    if result['mode']=='controller' and result['address']==result['forwarder']:raise ValueError('Die DNS-Weiterleitung darf nicht auf den neuen DC selbst zeigen.')
    return result

def script(profile,kind):
    p=validate(profile)
    if not p['enabled']:raise ValueError('Domänenprofil zuerst aktivieren und speichern.')
    realm=shlex.quote(p['realm']);admin=shlex.quote(p['admin'])
    intro='''#!/usr/bin/env bash
set -euo pipefail
umask 077
# Ausführung verändert die Domänenmitgliedschaft auf diesem Zielrechner.
# Keine Passwörter in dieser Datei; das Werkzeug fragt sie interaktiv ab.
'''
    variables='realm='+realm+'\nadmin='+admin+'\n'
    checks='''command -v realm >/dev/null || { echo 'realmd fehlt. Bitte die in der Anleitung genannten Pakete installieren.' >&2; exit 1; }
existing=$(realm list --name-only)
if [ -n "$existing" ]; then echo "Dieser Rechner ist bereits Mitglied: $existing. Kein automatischer Wechsel." >&2; exit 1; fi
realm discover "$realm"
printf 'Zieldomäne: %s\n' "$realm"
echo 'DNS muss den AD-DNS-Server verwenden; die Uhrzeit muss synchron sein.'
read -r -p 'Diesem Rechner den Domänenbeitritt erlauben? [ja/NEIN] ' answer
[[ "${answer,,}" == ja ]] || exit 0
'''
    if kind=='linux':
        return 'AD-Client-Linux.sh',intro+variables+checks+'''sudo realm join --client-software=sssd --membership-software=adcli --user="$admin" "$realm"
realm list
echo 'Beitritt abgeschlossen. Erlaubte Anmeldungen mit realm permit gezielt festlegen.'
echo 'Für automatische Homeverzeichnisse bei Debian/Mint bei Bedarf sudo pam-auth-update ausführen.'
'''
    if kind=='windows':
        return 'AD-Client-Windows.ps1','\ufeff'+'''# In Windows PowerShell als Administrator ausführen; Windows Pro/Enterprise/Education.
# Passwort wird ausschließlich durch Get-Credential abgefragt.
# DNS vorher auf den AD-DNS-Server einstellen. Kein automatischer Neustart.
#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$Domain = '''+ps(p['realm'])+'''
$Current = Get-CimInstance Win32_ComputerSystem
if ($Current.PartOfDomain) { throw "Bereits Mitglied von $($Current.Domain). Kein automatischer Wechsel." }
Resolve-DnsName -Type SRV "_ldap._tcp.dc._msdcs.$Domain" -ErrorAction Stop | Out-Host
$Credential = Get-Credential -UserName '''+ps(p['admin']+'@'+p['realm'] if '@' not in p['admin'] and '\\' not in p['admin'] else p['admin'])+''' -Message 'Konto mit Berechtigung zum Domänenbeitritt'
if ($null -eq $Credential) { throw 'Abgebrochen.' }
Add-Computer -DomainName $Domain -Credential $Credential -PassThru -Confirm
Write-Host 'Nach erfolgreichem Beitritt Windows selbst neu starten.'
'''
    if kind=='server' and p['mode']=='member':
        return 'AD-Server-Beitritt.sh',intro+variables+'''# Debian 13 Samba-Dateiserver: realmd, winbind, libnss-winbind,
# libpam-winbind, samba-common-bin und krb5-user müssen installiert sein.
''' +checks+'''command -v testparm >/dev/null || { echo 'testparm fehlt.' >&2; exit 1; }
command -v net >/dev/null || { echo 'Samba-Werkzeuge fehlen.' >&2; exit 1; }
backup="/var/backups/server-manager-domain-$(date +%Y%m%d-%H%M%S)"
sudo mkdir -m 700 -- "$backup"
for file in /etc/samba/smb.conf /etc/krb5.conf /etc/nsswitch.conf; do
  if [ -f "$file" ]; then sudo cp -a -- "$file" "$backup/"; fi
done
echo "Konfigurationssicherung: $backup"
sudo realm join --client-software=winbind --membership-software=samba --user="$admin" "$realm"
sudo testparm -s
sudo net ads testjoin
sudo systemctl restart winbind.service
sudo systemctl reload smbd.service
realm list
echo 'Beitritt abgeschlossen. Freigaben und Auflösung von DOMAENE\\Benutzer mit getent prüfen.'
echo 'Ordnerrechte und bestehende lokale UID/GID werden von dieser Datei nicht pauschal geändert.'
'''
    if kind=='server' and p['mode']=='controller':
        return 'AD-Domaenencontroller-einrichten.sh',intro+'''# Nur auf einem frischen Debian-13-System / einer eigenen VM ausführen.
# Dieser Assistent konvertiert keinen vorhandenen produktiven Dateiserver.
# Pakete: samba-ad-dc krb5-user bind9-dnsutils python3
# Feste IP und passende Uhrzeitsynchronisierung müssen vorher eingerichtet sein.
[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo 'Mit sudo bash starten.' >&2; exit 1; }
command -v samba-tool >/dev/null || { echo 'Paket samba-ad-dc fehlt.' >&2; exit 1; }
command -v testparm >/dev/null || exit 1
command -v python3 >/dev/null || exit 1
'''+variables+'dc='+shlex.quote(p['controller'])+'\nip='+shlex.quote(p['address'])+'\nnetbios='+shlex.quote(p['netbios'])+'\nforwarder='+shlex.quote(p['forwarder'])+r'''
[[ "$(hostname -s | tr '[:upper:]' '[:lower:]')" == "${dc,,}" ]] || { echo "Hostname muss zuerst auf $dc gesetzt werden." >&2; exit 1; }
ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fx -- "$ip" >/dev/null || { echo "Feste Adresse $ip ist nicht vorhanden." >&2; exit 1; }
[[ ! -e /var/lib/samba/private/sam.ldb ]] || { echo 'AD-Datenbank existiert bereits. Abbruch.' >&2; exit 1; }
if [ -f /etc/samba/smb.conf ]; then
  config=$(testparm -s /etc/samba/smb.conf 2>/dev/null) || exit 1
  shares=$(printf '%s\n' "$config" | sed -n 's/^\[\(.*\)\]$/\1/p' | grep -Eiv '^(global|homes|printers|print\$)$' || true)
  [[ -z "$shares" ]] || { printf 'Vorhandene Dateifreigaben – keine Umstellung:\n%s\n' "$shares" >&2; exit 1; }
fi
for file in /etc/exports /etc/exports.d/*.exports; do
  if [ -f "$file" ] && grep -Eq '^[[:space:]]*[^#[:space:]]' "$file"; then echo 'Vorhandene NFS-Freigaben. Bitte eigene VM verwenden.' >&2; exit 1; fi
done
echo "Neue AD-Domäne: $realm ($netbios), DC $dc, IP $ip, DNS-Weiterleitung $forwarder"
echo 'Im folgenden Dialog die Vorgaben prüfen und das neue Administratorpasswort eingeben.'
read -r -p 'Auf diesem frischen System einrichten? NEUE-DOMAENE eingeben: ' answer
[[ "$answer" == NEUE-DOMAENE ]] || exit 0
backup="/var/backups/server-manager-ad-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 -- "$backup"
if [ -f /etc/samba/smb.conf ]; then cp -a /etc/samba/smb.conf "$backup/"; fi
if [ -f /etc/krb5.conf ]; then cp -a /etc/krb5.conf "$backup/"; fi
trap 'echo "Einrichtung unterbrochen. Teilergebnisse und Dienste prüfen. Sicherung: $backup. Nicht blind erneut starten." >&2' ERR
systemctl stop smbd.service nmbd.service winbind.service
if [ -f /etc/samba/smb.conf ]; then mv /etc/samba/smb.conf "$backup/smb.conf.before-provision"; fi
samba-tool domain provision --interactive --realm="${realm^^}" --domain="$netbios" --server-role=dc --dns-backend=SAMBA_INTERNAL --host-name="$dc" --host-ip="$ip" --use-rfc2307 --option="dns forwarder = $forwarder"
install -m 644 /var/lib/samba/private/krb5.conf /etc/krb5.conf
systemctl disable smbd.service nmbd.service winbind.service
systemctl unmask samba-ad-dc.service
systemctl enable --now samba-ad-dc.service
samba-tool domain level show
echo "Domäne eingerichtet. DNS auf diesem DC und allen Clients auf $ip einstellen. DNS-SRV und Kerberos vor Client-Beitritten prüfen."
echo 'Zeitdienst für AD/NTP und Sicherung der AD-Datenbank separat einrichten.'
'''
    if kind=='admin':
        return 'AD-Verwaltung.sh',intro+'''# Auf dem eingerichteten Samba-AD-Domänencontroller ausführen.
[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo 'Mit sudo bash starten.' >&2; exit 1; }
[[ -f /var/lib/samba/private/sam.ldb ]] || { echo 'Keine lokale AD-Datenbank gefunden.' >&2; exit 1; }
valid_name(){ [[ "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]]; }
while true; do
 echo '1 Benutzer anzeigen | 2 Gruppe anzeigen | 3 Benutzer anlegen | 4 Gruppe anlegen | 5 Gruppenmitglied hinzufügen | 6 Passwort setzen | 0 Ende'
 read -r -p 'Auswahl: ' action
 case "$action" in
  1) samba-tool user list ;;
  2) samba-tool group list ;;
  3|4|6)
   read -r -p 'Name: ' name; valid_name "$name" || { echo 'Ungültiger Name.'; continue; }
   case "$action" in
    3) samba-tool user create "$name" ;;
    4) samba-tool group add "$name" ;;
    6) samba-tool user setpassword "$name" ;;
   esac ;;
  5)
   read -r -p 'Gruppe: ' group; read -r -p 'Benutzer: ' name
   valid_name "$group" && valid_name "$name" || { echo 'Ungültiger Name.'; continue; }
   samba-tool group addmembers "$group" "$name" ;;
  0) exit 0 ;;
  *) echo 'Bitte eine der angezeigten Zahlen wählen.' ;;
 esac
done
'''
    raise ValueError('Unbekannter Download.')

def register(app,ctx):
    with closing(ctx.db()) as con:con.execute('CREATE TABLE IF NOT EXISTS shares_domain (id INTEGER PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL)');con.commit()
    def get():
        with closing(ctx.db()) as con:row=con.execute('SELECT profile FROM shares_domain WHERE id=1').fetchone()
        return dict(DEFAULT,**json.loads(row['profile'])) if row else dict(DEFAULT)
    @app.route('/freigaben/domain',methods=['GET','POST'])
    def domain_page():
        profile=get();message=''
        if request.method=='POST':
            try:
                profile=validate(request.form)
                with closing(ctx.db()) as con:con.execute('INSERT INTO shares_domain(id,profile) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET profile=excluded.profile',(json.dumps(profile),));con.commit()
                message=_ui_html("<p class='share-ok'>Profil gespeichert. Serverrolle und Domänenmitgliedschaft werden erst durch Ausführung der heruntergeladenen Datei geändert.</p>")
            except Exception as exc:
                profile={key:request.form.get(key,DEFAULT[key]) for key in DEFAULT};profile['enabled']=request.form.get('enabled')=='1'
                message=_ui_html("<p class='share-error'>")+h.esc(_ui_text(exc))+_ui_html('</p>')
        role=h.run(['testparm','-s','--parameter-name=server role'],timeout=8)
        realm=h.run(['realm','list'],timeout=8) if shutil.which('realm') else {'out':'realmd ist auf diesem Server noch nicht installiert.'}
        body=_ui_html("<div class='card'><h2>Domäne · optional</h2><p>Eine Domäne stellt gemeinsame Konten für Server und Clients bereit. Normale SMB-/NFS-Freigaben funktionieren auch ohne Domäne.</p>")+_ui_text(message)+_ui_html("<form method='post' class='share-form'>")+token()
        body+=check('enabled','Domänenprofil und Downloads aktivieren',profile['enabled'])
        body+=select('mode','Was soll eingerichtet werden?',[('member','Server einer vorhandenen AD-Domäne beitreten lassen'),('controller','Neue AD-Domäne auf eigenem Server / eigener VM einrichten')],profile['mode'])
        body+=field('realm','DNS-Name der Domäne',profile['realm'],'Zum Beispiel ad.beispiel.de. Keine bestehende öffentliche Domäne verwenden, die dir nicht gehört.')
        body+=field('netbios','Domänen-Kurzname',profile['netbios'],'Zum Beispiel FAMILIE; maximal 15 Zeichen.')
        body+=field('admin','Konto für Beitritte',profile['admin'],'Das Passwort wird erst am Zielgerät abgefragt.')
        body+=_ui_html("<details><summary>Domänencontroller / DNS (für neue Domäne erforderlich)</summary>")
        body+=field('controller','Name des Domänencontrollers',profile['controller'],'Für neue Domänen erforderlich, z. B. dc01. Der Zielrechner muss bereits so heißen.')
        body+=field('address','Feste IPv4-Adresse des Domänencontrollers',profile['address'],'Die Clients müssen den AD-DNS-Server verwenden.')
        body+=field('forwarder','DNS-Weiterleitung für neue Domänen',profile['forwarder'],'Zum Beispiel die IP-Adresse des vorhandenen DNS-Resolvers/Routers.')
        body+=_ui_html("</details><button class='btn'>Profil speichern</button></form></div>")
        if profile['enabled']:
            body+=_ui_html("<div class='card'><h3>1. Server einrichten</h3><p>")+(_ui_text('Auf dem Samba-Dateiserver: benötigte Pakete installieren, DNS/Uhrzeit prüfen und dann die Beitrittsdatei im Terminal ausführen.') if profile['mode']=='member' else _ui_text('Auf einer frischen Debian-13-VM mit fester IP ausführen. Die Datei verweigert die Umwandlung eines Servers mit vorhandenen SMB-/NFS-Freigaben oder AD-Datenbank.'))+_ui_html("</p><a class='btn' href='/freigaben/domain/download/server'>Server-Datei herunterladen</a> <a class='btn' href='/freigaben/domain/download/admin'>AD-Verwaltungsmenü herunterladen</a>")
            body+=_ui_html("<p>Server-Beitritt: <code>bash AD-Server-Beitritt.sh</code>. Neue Domäne: <code>sudo bash AD-Domaenencontroller-einrichten.sh</code>. AD-Verwaltung auf dem DC: <code>sudo bash AD-Verwaltung.sh</code>.</p><h3>2. Clients beitreten lassen</h3><a class='btn' href='/freigaben/domain/download/windows'>Windows-Datei (.ps1)</a> <a class='btn' href='/freigaben/domain/download/linux'>Linux-Datei (.sh)</a><p>Windows Pro/Enterprise/Education: PowerShell als Administrator. Linux: Terminal, realmd und SSSD/adcli. DNS und Uhrzeit zuerst prüfen. Kein automatischer Neustart.</p><h3>3. Freigaben erlauben</h3><p>Nach erfolgreichem Server-Beitritt Domänenbenutzer/-gruppen bei der SMB-Freigabe eintragen und passende Ordnerrechte vergeben. Ein Beitritt allein vergibt keinen Zugriff auf vorhandene Daten. NFS mit sec=sys bleibt UID/GID-basiert und wird dadurch nicht Kerberos-geschützt.</p></div>")
        body+=_ui_html("<div class='card'><h3>Aktueller Serverstatus</h3><p>Samba-Rolle: <code>")+h.esc(role.get('out') or role.get('err'))+_ui_html("</code></p><pre>")+h.esc(realm.get('out') or realm.get('err'))+_ui_html("</pre><p>Pakete für Samba-Mitglied: realmd, winbind, libnss-winbind, libpam-winbind, samba-common-bin, krb5-user. Linux-Client: realmd, sssd, sssd-tools, adcli, libnss-sss, libpam-sss, samba-common-bin. Neuer DC: samba-ad-dc, krb5-user, bind9-dnsutils, python3.</p><p>Die Downloads enthalten keine Passwörter. Das Speichern eines Profils installiert keine Pakete und verändert keine Netzwerk-, DNS- oder Samba-Rolle.</p><p><a href='https://manpages.debian.org/trixie/realmd/realm.8.en.html'>Debian: Domänenbeitritt</a> · <a href='https://www.samba.org/samba/docs/current/man-html/samba-tool.8.html'>Samba: Domänenverwaltung</a> · <a href='https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/add-computer'>Microsoft: Windows-Beitritt</a></p></div>")
        return page(ctx,_ui_html('Domäne'),body)
    @app.route('/freigaben/domain/download/<kind>')
    def domain_download(kind):
        try:
            name,text=script(get(),kind)
            return Response(text,mimetype='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+name+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        except Exception as exc:return page(ctx,_ui_html('Domäne'),_ui_html("<div class='card share-error'>")+h.esc(_ui_text(exc))+_ui_html('</div>')),400
