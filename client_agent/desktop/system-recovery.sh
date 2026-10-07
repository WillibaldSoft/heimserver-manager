#!/bin/bash
# Interactive client-only entry point. No manager/server backup authorization.
set -Eeuo pipefail
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [[ "${1:-}" == --check ]]; then
    missing=0
    for cmd in python3 rsync findmnt getfacl setfacl gpg tar; do
        command -v "$cmd" >/dev/null || { echo "Fehlt: $cmd"; missing=1; }
    done
    [[ -f "$base/system-migration.sh" ]] || { echo 'Sicherungsmodul fehlt.'; missing=1; }
    exit "$missing"
fi
[[ $EUID == 0 ]] || { echo 'Mit Administratorfreigabe starten.'; exit 1; }
source "$base/system-migration.sh"
# GUI uses explicit prompted reads; pipeline/data reads keep Bash semantics.
if [[ "${1:-}" == --gui ]]; then
    exec 3>&1 4<&0
    read() {
        local gui_prompt='' gui_arg gui_has_prompt=false
        local -a gui_args=("$@")
        local gui_i
        for ((gui_i=0;gui_i<${#gui_args[@]};gui_i++)); do
            if [[ "${gui_args[gui_i]}" == -p ]]; then
                gui_prompt=${gui_args[gui_i+1]};gui_has_prompt=true;break
            fi
        done
        if $gui_has_prompt; then
            printf '\nHSM_RECOVERY_PROMPT:%s\n' "$gui_prompt" >&3
            builtin read "${gui_args[@]}" <&4 || exit 130
        else
            builtin read "${gui_args[@]}"
        fi
    }
fi

# Do not expose the original server/DB/container menus in the client.
printf '\nSystem sichern & wiederherstellen\n1) Diesen Linux-Client sichern\n2) Installiertes Zielsystem vom Live-USB wiederherstellen\n0) Beenden\n'
read -r -p 'Auswahl: ' operation
[[ "$operation" == 0 ]] && exit 0
[[ "$operation" == 1 || "$operation" == 2 ]] || exit 1
prepare_environment
read -r -p 'Sicherungsablage auf eingehängter USB-Platte oder NFS-Serverablage: ' storage_path
python3 "$base/system_recovery.py" storage "$storage_path" >/dev/null
storage_device=$(stat -c %d "$storage_path")
USB_MOUNTPOINT="$storage_path";STORAGE_DIR="$storage_path"
# NFS is allowed only after an actual ownership and ACL capability check.
filesystem_supports_unix_perms() { case "$USB_FSTYPE" in ext2|ext3|ext4|xfs|btrfs|f2fs|nfs|nfs4) return 0;; *) return 1;; esac; }
probe=$(mktemp -d "$storage_path/.system-permissions-XXXXXXXX")
chmod 700 "$probe"
if ! (touch "$probe/file" && chown 12345:12345 "$probe/file" && [[ $(stat -c '%u:%g' "$probe/file") == 12345:12345 ]] && setfacl -m u:12346:r "$probe/file" && getfacl -cpn "$probe/file" | grep -q 'user:12346:r--'); then
    rm -rf -- "$probe";die 'Ziel erhält Eigentümer/ACLs nicht. NFS-Berechtigungen bzw. USB-Dateisystem prüfen.'
fi
rm -rf -- "$probe"
# Existing rsync guard plus target-device check at every transfer boundary.
eval "$(declare -f rsync | sed '1s/^rsync /migration_rsync /')"
rsync() {
    [[ $(stat -c %d "$storage_path") == "$storage_device" ]] || die 'Sicherungsdatenträger getrennt.'
    local rc=0
    migration_rsync "$@" || rc=$?
    [[ "$rc" != 23 ]] || rc=24
    return "$rc"
}
if [[ "$operation" == 1 ]]; then
    username=$(getent passwd "${PKEXEC_UID:-${SUDO_UID:-0}}" | cut -d: -f1)
    read -r -p "Zu sichernder Benutzer [${username:-}]: " selected_user
    SOURCE_USER="${selected_user:-$username}"
    [[ "$SOURCE_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] && [[ $(id -u "$SOURCE_USER") -ge 1000 ]] || die 'Normalen Client-Benutzer wählen.'
    LIVE_MODE=false;resolve_source_identity
    python3 "$base/system_recovery.py" storage "$storage_path" "$SOURCE_HOME" >/dev/null
    CLIENT_ID=$(hostname -s)
    [[ "$CLIENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || die 'Rechnername nicht als Sicherungskennung geeignet.'
    # Each operation gets a new directory; old snapshots never receive --delete.
    STORAGE_DIR=$(mktemp -d "$storage_path/System-$(date +%Y%m%d-%H%M%S)-XXXXXXXX")
    chmod 700 "$STORAGE_DIR"
    prepare_usb;setup_usb_temp_workdir;init_logging
    printf '\nGesichert werden Home, Programm-/Paketquellenlisten, Desktop und ausgewählte Systemkonfigurationen. Kein Festplattenabbild.\nZiel: %s\nOffene Programme schließen; ungesicherte Änderungen und laufende Datenbanken sind nicht konsistent.\n' "$STORAGE_DIR"
    if [[ "$USB_FSTYPE" == nfs* ]]; then echo 'Für die Dauer der Arbeit Schlafzeitplan am Server pausieren; dieser Ablauf verwendet keine Client-API.';fi
    read -r -p 'Sicherung starten? [ja/NEIN]: ' approval
    [[ "$approval" == ja ]] || exit 0
    touch "$STORAGE_DIR/.unvollstaendig"
    action_backup
    # rsync code 23 is a failure in this entry point, not a complete snapshot.
    rm -- "$STORAGE_DIR/.unvollstaendig"
    printf '\nSicherungsablage: %s\nRestore-Ordner: %s\nBerichte auf ausgelassene Bestandteile prüfen.\n' "$STORAGE_DIR" "$BACKUP_DIR"
else
    read -r -p 'Sicherungsordner mit Dateien, Programmlisten und Systemkomponenten: ' BACKUP_DIR
    BACKUP_DIR=$(python3 "$base/system_recovery.py" storage "$BACKUP_DIR")
    [[ "$BACKUP_DIR" == "$storage_path/"* ]] || die 'Stand muss in der gewählten Sicherungsablage liegen.'
    [[ -d "$BACKUP_DIR/files" && -d "$BACKUP_DIR/apps" ]] || die 'Keine unterstützte Systemsicherung; ZIP-Dateisicherungen im Client öffnen.'
    read -r -p 'Eingehängtes installiertes Zielsystem (z. B. /mnt/linux): ' AUTO_ROOT_MOUNT
    AUTO_ROOT_MOUNT=$(python3 "$base/system_recovery.py" restore "$AUTO_ROOT_MOUNT" "$BACKUP_DIR")
    read -r -p 'Vorhandener Benutzer im Zielsystem: ' SOURCE_USER
    mapfile -t identity < <(python3 "$base/system_recovery.py" user "$AUTO_ROOT_MOUNT" "$SOURCE_USER")
    [[ ${#identity[@]} == 3 ]] || die 'Zielbenutzer konnte nicht geprüft werden.'
    SOURCE_HOME=${identity[0]};SOURCE_UID=${identity[1]};SOURCE_GID=${identity[2]};SOURCE_GROUP=$SOURCE_GID
    LIVE_MODE=true;SOURCE_HOST=$(hostname -s);BACKUP_BASE_DIR=$(dirname "$BACKUP_DIR");LOCAL_LOG_DIR="$BACKUP_DIR/reports"
    get_usb_fstype;setup_usb_temp_workdir;init_logging
    printf '\nZiel: %s\nHome: %s\n1) Home\n2) Programme & Desktop\n3) Vollständige unterstützte Systemwiederherstellung\n0) Abbrechen\n' "$AUTO_ROOT_MOUNT" "$SOURCE_HOME"
    read -r -p 'Umfang: ' scope
    [[ "$scope" == 0 ]] && exit 0
    [[ "$scope" =~ ^[123]$ ]] || die 'Ungültige Auswahl.'
    echo 'Bestehende Konfigurationen können geändert werden. Paketquellen/Versionen werden geprüft. Benutzerprogramme können im Live-System manuelle Nacharbeit benötigen. Partitionen und Bootloader werden nicht eingerichtet.'
    read -r -p 'Zum Start WIEDERHERSTELLEN eingeben: ' approval
    [[ "$approval" == WIEDERHERSTELLEN ]] || exit 0
    v20_init_report;v20_compat
    if [[ "$scope" == 1 || "$scope" == 3 ]]; then v20_home;fi
    if [[ "$scope" == 2 || "$scope" == 3 ]]; then v20_packages;v20_extra_software;v20_desktop;fi
    if [[ "$scope" == 3 ]]; then
        for component in identity local units cron config network; do v20_system_components "$component";done
        v20_svl_restore
    fi
    printf '\nAblauf beendet. Übernommene, ausgelassene und manuell zu prüfende Bestandteile: %s\n' "$V20_REPORT"
fi
