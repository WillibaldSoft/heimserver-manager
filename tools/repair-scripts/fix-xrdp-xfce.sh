#!/bin/sh
# Adapted from fix-xrdp-xfce.sh for explicit, logged server-side repair.
set -eu
PATH=$PATH:/usr/local/sbin:/usr/sbin:/sbin
export PATH
[ "$(id -u)" -eq 0 ] || { echo 'Als root starten: sh fix-xrdp-xfce.sh BENUTZER [--xwrapper] [--tmp]'; exit 1; }
[ "$#" -ge 1 ] || { echo 'Desktop-Benutzer fehlt.' >&2; exit 2; }
remote_user=$1;shift
fix_wrapper=0;fix_tmp=0
for option in "$@"; do
 case "$option" in --xwrapper) fix_wrapper=1;; --tmp) fix_tmp=1;; *) echo 'Ungültige Reparaturoption.' >&2; exit 2;; esac
done
case "$remote_user" in ''|*[!a-zA-Z0-9_.-]*|-*) echo 'Ungültiger Benutzername.' >&2; exit 2;; esac
entry=$(getent -s files passwd "$remote_user") || exit 1
remote_uid=$(printf '%s\n' "$entry" | cut -d: -f3)
remote_home=$(printf '%s\n' "$entry" | cut -d: -f6)
remote_shell=$(printf '%s\n' "$entry" | cut -d: -f7)
[ "$remote_uid" -ge 1000 ] && [ "$remote_uid" -lt 60000 ] || { echo 'Normales Benutzerkonto erforderlich.' >&2; exit 1; }
case "$remote_shell" in */nologin|*/false|'') echo 'Konto erlaubt keine Anmeldung.' >&2; exit 1;; esac
[ -d "$remote_home" ] && [ ! -L "$remote_home" ] || { echo 'Benutzerverzeichnis fehlt oder ist ein Symlink.' >&2; exit 1; }
state_root=${SERVER_MANAGER_STATE:-/var/lib/server-manager}
mkdir -p "$state_root/repair-backups"
backup=$(mktemp -d "$state_root/repair-backups/xrdp-XXXXXXXX")
echo "System-Sicherung: $backup"
if [ -e /etc/X11/Xwrapper.config ]; then cp -a /etc/X11/Xwrapper.config "$backup/"; fi
stat -c '%u %g %a' /tmp > "$backup/tmp-permissions.txt"
if [ "$fix_wrapper" -eq 1 ]; then
 [ ! -L /etc/X11/Xwrapper.config ] || { echo 'Xwrapper-Symlink zuerst manuell prüfen.' >&2; exit 1; }
fi
apt-get -o APT::Update::Error-Mode=any update
DEBIAN_FRONTEND=noninteractive apt-get install --reinstall -y xrdp xorgxrdp xserver-xorg-core xfce4 xfce4-goodies dbus-x11 xterm ssl-cert
if [ "$fix_wrapper" -eq 1 ]; then
 mkdir -p /etc/X11
 printf '%s\n' 'allowed_users=anybody' > /etc/X11/Xwrapper.config
 chmod 644 /etc/X11/Xwrapper.config
 chown root:root /etc/X11/Xwrapper.config
fi
usermod -aG ssl-cert xrdp
if [ "$fix_tmp" -eq 1 ]; then chown root:root /tmp;chmod 1777 /tmp; fi
[ "$(stat -c '%a' /tmp)" = 1777 ] || { echo '/tmp hat ungewöhnliche Rechte; optionale Reparatur prüfen.' >&2; exit 1; }
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

systemctl enable xrdp.service
systemctl restart xrdp-sesman.service xrdp.service
systemctl is-active --quiet xrdp.service xrdp-sesman.service
printf '%s\n' 'Reparatur abgeschlossen. Im RDP-Client die Sitzung Xorg auswählen und mit dem Linux-Benutzer anmelden.' 'XRDP verwendet eine eigene Desktop-Sitzung. Standardport 3389; bestehende Portkonfiguration bleibt erhalten.'
ss -ltn | head -30
