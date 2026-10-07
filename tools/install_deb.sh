#!/bin/sh
# Debian 13 preparation and Heimserver Manager installation; no embedded credentials.
set -eu
PATH=$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# PLATFORM_GUARD
if ! command -v heimserver_check_platform >/dev/null 2>&1; then
    . "$(dirname -- "$0")/../packaging/platform-check.sh"
fi
check_deb_platform() {
    hs_package=$(dpkg-deb -f "$1" Package) || return 1
    [ "$hs_package" = server-manager ] || { echo "Kein Heimserver-Manager-Paket." >&2; return 1; }
    hs_package_target=$(dpkg-deb -f "$1" X-Heimserver-Target) || return 1
    heimserver_check_platform "$hs_package_target" /etc/os-release
}

say() { printf '\n%s\n' "$*"; }
ask() {
    printf '%s [j/N]: ' "$1"
    read -r answer || return 1
    case "$answer" in j|J|ja|Ja|JA|y|Y|yes) return 0;; *) return 1;; esac
}
prepare_debian() {
    [ -r /etc/os-release ] || { echo '/etc/os-release fehlt.' >&2; exit 1; }
    . /etc/os-release
    [ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ] || {
        echo 'Diese Ersteinrichtung mit Heimserver Manager ist für Debian 13 vorgesehen.' >&2; exit 1;
    }
    say "Debian-Ersteinrichtung: ${PRETTY_NAME:-Debian 13}"
    getent hosts deb.debian.org >/dev/null || {
        echo 'DNS nicht verfügbar. Zuerst LAN/WLAN und Namensauflösung einrichten.' >&2; exit 1;
    }
    # APT itself checks connectivity. ICMP/ping can be blocked on working networks.
    say '1: Vorhandene Paketquellen beibehalten (bestehende Installation)'
    echo '2: Debian-13-Onlinequellen einrichten (nach Offline-Installation)'
    printf 'Paketquellen [1/2, Standard 1]: '
    read -r sources_choice
    case "${sources_choice:-1}" in
      1) ;;
      2)
        backup=$(mktemp -d /root/heimserver-apt-before-XXXXXXXX)
        chmod 700 "$backup"
        [ ! -e /etc/apt/sources.list ] || cp -a /etc/apt/sources.list "$backup/"
        [ ! -d /etc/apt/sources.list.d ] || cp -a /etc/apt/sources.list.d "$backup/"
        printf 'APT-Rücksicherung: %s\n' "$backup"
        # Stage every file before changing any active source. Third-party sources stay intact.
        stage=$(mktemp -d /root/heimserver-apt-stage-XXXXXXXX)
        mkdir -p /etc/apt/sources.list.d
        for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
            [ -f "$file" ] || continue
            [ ! -L "$file" ] || { echo "Symlink zuerst prüfen: $file" >&2; exit 1; }
            mkdir -p "$stage$(dirname "$file")"
            awk '!($0 ~ /^[ \t]*deb(-src)?[ \t]/ && ($0 ~ /cdrom:/ || $0 ~ /https?:\/\/(deb\.debian\.org|security\.debian\.org|ftp\.[A-Za-z0-9.-]*debian\.org)\//))' "$file" > "$stage$file"
        done
        for file in /etc/apt/sources.list.d/*.sources; do
            [ -f "$file" ] || continue
            [ ! -L "$file" ] || { echo "Symlink zuerst prüfen: $file" >&2; exit 1; }
            mkdir -p "$stage$(dirname "$file")"
            if ! grep -Eq '(https?://(deb\.debian\.org|security\.debian\.org|ftp\.[A-Za-z0-9.-]*debian\.org)/|cdrom:)' "$file"; then
                cp "$file" "$stage$file"
                continue
            fi
            awk 'BEGIN {RS=""; ORS="\n\n"}
              {official=0;other=0;uri=0;n=split($0,lines,"\n");
               for(i=1;i<=n;i++) {
                 line=lines[i];
                 if(line ~ /^URIs:/) {sub(/^URIs:[ \t]*/,"",line);uri=1}
                 else if(line !~ /^[ \t]/) uri=0;
                 if(uri) {m=split(line,a,/[ \t]+/);for(j=1;j<=m;j++) if(a[j]!="") {
                    if(a[j] ~ /^(https?:\/\/(deb\.debian\.org|security\.debian\.org|ftp\.[A-Za-z0-9.-]*debian\.org)\/|cdrom:)/) official=1;else other=1;
                 }}
               }
               if(official && other) {print "Gemischte Debian-/Fremdquellen bitte manuell trennen." > "/dev/stderr";exit 2}
               if(!official) print $0;
              }' "$file" > "$stage$file" || {
                echo "Keine Paketquelle geändert. Bitte $file prüfen. Sicherung: $backup" >&2; exit 1;
            }
        done
        # HTTP works before ca-certificates exists; APT verifies Debian signatures.
        [ -f /usr/share/keyrings/debian-archive-keyring.gpg ] || { echo 'Debian-Archivschlüssel fehlen.' >&2; exit 1; }
        [ ! -e /etc/apt/sources.list.d/heimserver-debian.sources ] || {
            echo 'Heimserver-Quellen bereits vorhanden: bitte Option 1 verwenden.' >&2; exit 1;
        }
        for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
            [ -f "$file" ] || continue
            cat "$stage$file" > "$file"
        done
        cat > /etc/apt/sources.list.d/heimserver-debian.sources <<'SOURCES'
Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
SOURCES
        chmod 644 /etc/apt/sources.list.d/heimserver-debian.sources
        say "Quellen eingerichtet. Bisherige Dateien gesichert unter $backup."
        ;;
      *) echo 'Ungültige Auswahl; abgebrochen.' >&2; exit 2;;
    esac
    apt-get -o APT::Update::Error-Mode=any update
    say 'Basispakete installieren'
    apt-get install -y sudo ca-certificates curl wget gnupg rsync openssh-client less nano unzip zip 7zip iproute2 iputils-ping dnsutils pciutils usbutils
    additional_packages

}
additional_packages() {
    say 'Verwaltungswerkzeuge: Git, Editoren und Diagnoseprogramme; SMART prüft Festplatten, htop/ncdu helfen bei CPU- und Speicheranalyse.'
    if ask 'Zusätzliche Verwaltungswerkzeuge installieren (git, Editoren, Diagnose, SMART)?'; then
        apt-get install -y git vim lsb-release lshw dmidecode smartmontools htop ncdu tree bash-completion command-not-found traceroute ethtool gdebi
    fi
    say 'Firmware: zusätzliche Hardware-Unterstützung und fwupd für Hersteller-Firmware. Hier werden nur Pakete und Metadaten installiert, keine Geräte-Firmware geflasht.'
    if ask 'Firmwarepakete und fwupd installieren?'; then
        apt-get install -y firmware-linux firmware-linux-free firmware-linux-nonfree firmware-misc-nonfree fwupd
        fwupdmgr refresh --force || echo 'Firmware-Metadaten konnten nicht geladen werden; später erneut versuchen.' >&2
    fi
    say 'CPU-Microcode: Korrekturen für Intel-/AMD-Prozessoren. Die Wirkung erfordert normalerweise einen Neustart; in virtuellen Maschinen meist nicht nötig.'
    if ask 'Passenden CPU-Microcode installieren?'; then
        vendor=$(LC_ALL=C lscpu | awk -F: '/Vendor ID/ {gsub(/^[ \t]+/,"",$2);print $2}')
        case "$vendor" in
          GenuineIntel) apt-get install -y intel-microcode;;
          AuthenticAMD) apt-get install -y amd64-microcode;;
          *) echo 'Kein unterstützter Intel-/AMD-Prozessor erkannt; Microcode übersprungen.';;
        esac
    fi
    say 'NetworkManager: LAN/WLAN-Verwaltung mit iw und rfkill. Kann bestehende Netzwerkverwaltung beeinflussen; nur bei Bedarf wählen, besonders vorsichtig bei Fernzugriff.'
    if ask 'NetworkManager und WLAN-Werkzeuge installieren (kann Netzwerkdienste starten)?'; then
        apt-get install -y network-manager iw rfkill
        if ask 'NetworkManager für den Systemstart aktivieren und jetzt starten?'; then
            systemctl enable --now NetworkManager.service
        fi
    fi
    say 'Systempflege: verfügbare Updates anzeigen; Vollupgrade und Entfernen ungenutzter Pakete werden separat bestätigt. APT zeigt die Änderungen vorher an.'
    apt list --upgradable
    if ask 'Vollständiges Systemupgrade ausführen (APT fragt vor Änderungen erneut)?'; then apt full-upgrade; fi
    if ask 'Nicht mehr benötigte Pakete entfernen (APT zeigt die Liste vorab)?'; then apt autoremove; fi
}
setup_ssh() {
    apt-get -o APT::Update::Error-Mode=any update
    apt-get install -y openssh-server
    /usr/sbin/sshd -t
    systemctl enable --now ssh.service
    systemctl is-active --quiet ssh.service
    say 'SSH ist eingerichtet. Bestehende SSH-Konfiguration und Schlüssel bleiben erhalten.'
    echo 'Verbindung: ssh BENUTZER@SERVER-IP (Port laut bestehender SSH-Konfiguration, standardmäßig 22).'
    /usr/sbin/sshd -T | awk '$1=="port" || $1=="passwordauthentication" || $1=="pubkeyauthentication" {print}'
}
setup_xrdp() {
    say 'XRDP richtet eine eigene XFCE-Desktop-Sitzung ein.'
    echo 'Lokale Benutzer zur Auswahl:'
    getent -s files passwd | awk -F: '$3>=1000 && $3<60000 {print "  "$1" (UID "$3")"}'
    printf 'Linux-Benutzer für den Desktop-Zugang: '
    read -r remote_user
    case "$remote_user" in ''|*[!a-zA-Z0-9_.-]*|-*) echo 'Ungültiger Benutzername.' >&2; exit 2;; esac
    remote_entry=$(getent -s files passwd "$remote_user") || { echo 'Lokaler Benutzer fehlt.' >&2; exit 1; }
    remote_uid=$(printf '%s\n' "$remote_entry" | cut -d: -f3)
    remote_home=$(printf '%s\n' "$remote_entry" | cut -d: -f6)
    remote_shell=$(printf '%s\n' "$remote_entry" | cut -d: -f7)
    [ "$remote_uid" -ge 1000 ] && [ "$remote_uid" -lt 60000 ] || { echo 'Normales Benutzerkonto erforderlich.' >&2; exit 1; }
    case "$remote_shell" in */nologin|*/false|'') echo 'Dieses Konto erlaubt keine Anmeldung.' >&2; exit 1;; esac
    case "$remote_home" in /*) ;; *) echo 'Ungültiges Benutzerverzeichnis.' >&2; exit 1;; esac
    [ -d "$remote_home" ] && [ ! -L "$remote_home" ] || { echo 'Benutzerverzeichnis fehlt oder ist ein Symlink.' >&2; exit 1; }
    desktop_packages=''
    if ! command -v startxfce4 >/dev/null 2>&1; then
        if ask 'XFCE ist nicht installiert. XFCE für den Remote-Desktop zusätzlich installieren?'; then
            desktop_packages='xfce4 xfce4-goodies'
        else
            echo 'XRDP-Einrichtung übersprungen.'; return
        fi
    fi
    echo 'Bestehendes Benutzerpasswort für die RDP-Anmeldung verwenden. Kontopasswörter werden nicht verändert.'
    apt-get -o APT::Update::Error-Mode=any update
    # desktop_packages contains only fixed package names chosen above.
    apt-get install -y xrdp xorgxrdp xserver-xorg-core dbus-x11 xterm ssl-cert $desktop_packages
    /usr/sbin/usermod -aG ssl-cert xrdp
    [ "$(stat -c '%a' /tmp)" = 1777 ] || {
        echo '/tmp hat ungewöhnliche Rechte. Bitte prüfen; keine automatische globale Änderung.' >&2; exit 1;
    }
    # Write as the selected user, never as root through a user-controlled path.
    runuser -u "$remote_user" -- /bin/sh -s -- "$remote_home" <<'SESSION'
set -eu
umask 077
session_home=$1
session_backup=$(mktemp -d "$session_home/.xrdp-fix-backup-XXXXXXXX")
for name in .xsession .xsessionrc .Xclients .Xauthority; do
    if [ -e "$session_home/$name" ] || [ -L "$session_home/$name" ]; then
        cp -a -- "$session_home/$name" "$session_backup/$name"
    fi
done
for name in .xsessionrc .Xclients; do
    if [ -e "$session_home/$name" ] || [ -L "$session_home/$name" ]; then
        mv -- "$session_home/$name" "$session_backup/$name.disabled"
    fi
done
session_file=$(mktemp "$session_home/.xsession-new-XXXXXXXX")
cat > "$session_file" <<'XSESSION'
#!/bin/sh
unset DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startxfce4
XSESSION
chmod 755 "$session_file"
mv -fT -- "$session_file" "$session_home/.xsession"
printf 'Sitzungskonfiguration gesichert: %s\n' "$session_backup"
SESSION
    echo 'XRDP-Neustart: bestehende Remote-Sitzungen können getrennt werden.'
    systemctl enable xrdp.service
    systemctl restart xrdp-sesman.service xrdp.service
    systemctl is-active --quiet xrdp.service xrdp-sesman.service
    say "XRDP bereit für $remote_user. RDP-Client: SERVER-IP, Sitzung Xorg. Standardport: 3389."
    echo 'Bei bestehender XRDP-Konfiguration gilt deren Port. Erst lokal abmelden, falls die parallele Sitzung Probleme verursacht.'
    echo 'Diagnose: journalctl -u xrdp -u xrdp-sesman -b --no-pager -n 100'
}

root_install() {
    deb=$1;mode=$2;add_user=$3;add_uid=$4
    case "$mode" in install|setup|extras) ;; *) echo 'Ungültiger Modus.' >&2; exit 2;; esac
    if [ "$mode" != extras ]; then check_deb_platform "$deb"; fi
    if [ "$mode" = setup ]; then prepare_debian; fi
    if [ "$mode" = extras ]; then
        [ -r /etc/os-release ] || exit 1
        . /etc/os-release
        [ "${ID:-}" = debian ] && [ "${VERSION_ID:-}" = 13 ] || { echo 'Zusatzinstallationen sind für Debian 13 vorgesehen.' >&2; exit 1; }
        say 'Nur Zusatzinstallationen: Manager und Paketquellen bleiben unverändert.'
        apt-get -o APT::Update::Error-Mode=any update
        additional_packages
    fi
    if [ -n "$add_user" ]; then
        entry=$(getent -s files passwd "$add_user") || { echo 'Lokales Benutzerkonto fehlt.' >&2; exit 1; }
        account_uid=$(printf '%s\n' "$entry" | cut -d: -f3)
        [ "$account_uid" = "$add_uid" ] && [ "$account_uid" -ge 1000 ] && [ "$account_uid" -lt 60000 ] || {
            echo 'Nur das aufrufende normale lokale Benutzerkonto darf freigegeben werden.' >&2; exit 1;
        }
        apt-get install sudo
        /usr/sbin/usermod -aG sudo -- "$add_user"
        echo 'sudo-Gruppe ergänzt. Für sudo einmal vollständig abmelden und neu anmelden.'
    fi
    if [ "$mode" != extras ]; then
        say "Heimserver Manager installieren: $deb"
        apt install -- "$deb"
    fi
    say 'SSH: Terminalzugriff und Dateiübertragung mit einem vorhandenen Linux-Konto. Installiert openssh-server und aktiviert den Dienst; bestehende SSH-Regeln bleiben erhalten.'
    if ask 'SSH-Fernzugang installieren und aktivieren?'; then setup_ssh; fi
    say 'XRDP: grafischer Fernzugang per RDP in eine eigene XFCE-Sitzung. XFCE kann bei Bedarf ergänzt werden; Sitzungsdateien werden gesichert. Bestehende RDP-Verbindungen können getrennt werden.'
    if ask 'XRDP-Desktop-Fernzugang einrichten / reparieren (kann bestehende RDP-Sitzungen trennen)?'; then setup_xrdp; fi
    echo 'Firewall und Routerfreigaben werden nicht verändert. Für externen Zugang ein VPN verwenden.'
    say 'Installation abgeschlossen. Kein automatischer Neustart.'
    [ "$mode" = extras ] || echo 'HTTPS-Adresse und Zertifikat-Fingerabdruck zeigt die Paketinstallation an. Stammzertifikat auf Clients importieren; HTTP ist nur intern erreichbar.'
    [ ! -f /var/run/reboot-required ] || echo 'Das System meldet einen erforderlichen Neustart.'
    [ "$mode" = install ] || echo 'Nach Kernel-/Firmware-/Microcode-Updates ist ein Neustart sinnvoll.'
}
if [ "${1:-}" = --root-run ]; then
    [ "$(id -u)" -eq 0 ] && [ "$#" -eq 5 ] || exit 2
    root_install "$2" "$3" "$4" "$5"
    exit
fi
if [ "${1:-}" = --check ]; then
    [ "$#" -eq 2 ] || { echo "Aufruf: sh install_deb.sh --check DATEI.deb" >&2; exit 2; }
    check_deb_platform "$2"
    echo "Zielplattform passt. Keine Installation ausgeführt; Abhängigkeiten und Funktionstests stehen gegebenenfalls noch aus."
    exit 0
fi
if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
    echo 'Aufruf: sh /pfad/install_deb.sh [DEB-Datei]'
    echo 'Modus 1/2: genau eine DEB neben dem Skript oder Dateipfad angeben. Modus 3: Zusatzinstallationen ohne DEB.'
    exit
fi
script_path=$(realpath -- "$0")
script_dir=$(dirname -- "$script_path")
if [ "$#" -gt 1 ]; then echo 'Aufruf: sh install_deb.sh [DEB-Datei]' >&2; exit 2; fi
say '1: Heimserver Manager installieren / aktualisieren'
echo '   Verwendet die DEB; SSH und XRDP können anschließend optional ergänzt werden.'
echo '2: Debian 13 nach Offline-Installation einrichten, danach Manager installieren'
echo '   Prüft Paketquellen, ergänzt Basispakete und bietet Zusatzinstallationen einzeln an.'
echo '3: Nur Zusatzinstallationen auswählen – ohne Manager-DEB'
echo '   Werkzeuge, Firmware, Microcode, NetworkManager, Systempflege, SSH und XRDP.'
echo '   Jede Zusatzinstallation wird erklärt und einzeln abgefragt; Standard ist Nein.'
printf 'Modus [1/2/3, Standard 1]: '
read -r mode_choice || { echo "Keine Auswahl eingegeben; abgebrochen." >&2; exit 2; }
case "${mode_choice:-1}" in 1) mode=install;; 2) mode=setup;; 3) mode=extras;; *) echo 'Abgebrochen.' >&2; exit 2;; esac
deb=''
if [ "$mode" != extras ]; then
if [ "$#" -eq 0 ]; then
    set -- "$script_dir"/*.deb
    if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
        echo 'Bitte genau eine DEB-Datei neben das Skript legen oder ihren Pfad als Argument angeben.' >&2; exit 2
    fi
elif [ ! -f "$1" ]; then
    if [ -f "$script_dir/$1" ]; then set -- "$script_dir/$1";
    else printf 'DEB-Datei nicht gefunden: %s\n' "$1" >&2; exit 2; fi
fi
deb=$(realpath -- "$1")
check_deb_platform "$deb"
case "$deb" in *.deb) ;; *) echo 'Bitte eine DEB-Datei auswählen.' >&2; exit 2;; esac
fi

if [ "$(id -u)" -eq 0 ]; then root_install "$deb" "$mode" '' ''; exit; fi
say 'Die Installation benötigt einmalig Administratorrechte.'
echo '1: sudo (eigenes Benutzerpasswort)'
echo '2: su (root-Passwort, auch wenn sudo fehlt)'
echo '3: Benutzer dauerhaft zur sudo-Gruppe hinzufügen und installieren (root-Passwort)'
printf 'Auswahl [1/2/3]: '
read -r choice
case "$choice" in
 1)
    command -v sudo >/dev/null || { echo 'sudo fehlt. Erneut starten und 2 für su wählen.' >&2; exit 1; }
    exec sudo /bin/sh "$script_path" --root-run "$deb" "$mode" '' '';;
 2) exec su -s /bin/sh -c 'exec /bin/sh "$1" --root-run "$2" "$3" "" ""' root sh "$script_path" "$deb" "$mode";;
 3)
    install_user=$(id -un);install_uid=$(id -u)
    printf 'Benutzer %s erhält dauerhafte Administratorrechte über sudo.\n' "$install_user"
    exec su -s /bin/sh -c 'exec /bin/sh "$1" --root-run "$2" "$3" "$4" "$5"' root sh "$script_path" "$deb" "$mode" "$install_user" "$install_uid";;
 *) echo 'Abgebrochen.' >&2; exit 1;;
esac
