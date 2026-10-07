#!/usr/bin/env bash
# V20 Full System Migration — Automatischer Restore + GPG-TTY-Fix 1
# Based on V19.2, original workflows retained
set -Eeuo pipefail

AUTO_ROOT_MOUNT="/mnt/home-backup-root"
AUTO_HOME_MOUNT="/mnt/home-backup-root/home"
AUTO_MOUNTED_ROOT="false"
AUTO_MOUNTED_HOME="false"

SCRIPT_NAME="$(basename "$0")"
DATE_STR="$(date +%F_%H-%M-%S)"

BACKUP_ROOT_NAME="linux-client-backup"
SERVER_BACKUP_ROOT_NAME="linux-server-backup"
META_DIR_NAME=".backup-meta"
FILES_DIR_NAME="files"
APPS_DIR_NAME="apps"
DESKTOP_ASSETS_DIR_NAME="desktop-assets"
SYSTEM_CONFIG_DIR_NAME="system-config"
LIBVIRT_DIR_NAME="virtual-machines"
DOCKER_DIR_NAME="docker-container"
SERVER_SERVICES_DIR_NAME="server-services"
REPORTS_DIR_NAME="reports"
SERVER_USERS_DIR_NAME="users"
SERVER_DB_DIR_NAME="databases"
SERVER_NEXTCLOUD_DIR_NAME="nextcloud"
DCONF_DIR_NAME="desktop-state"
ACL_DIR_NAME="acl-backups"
MOUNTED_DATA_DIR_NAME="mounted-data"

STORAGE_DIR=""
CLIENT_ID=""
USB_MOUNTPOINT=""
USB_FSTYPE=""
BACKUP_BASE_DIR=""
BACKUP_DIR=""
SERVER_BACKUP_BASE_DIR=""
SERVER_BACKUP_DIR=""
USB_LOG_FILE=""
BACKUP_MODE="normal"
LIVE_MODE="false"
REQUESTED_ROOT_MOUNT_MODE="rw"
SOURCE_HOME=""
SOURCE_USER=""
SOURCE_UID=""
SOURCE_GID=""
SOURCE_GROUP=""
SOURCE_HOST=""
LOCAL_LOG_DIR=""
LOCAL_LOG_FILE=""
TEMP_WORK_DIR=""
APT_CACHE_DIR=""
RSYNC_PARTIAL_DIR=""
CHROOT_PREPARED="false"
FAILED_APPS_REPORT=""

BASE_EXCLUDES=(
    --exclude=.cache/
    --exclude=.local/share/Trash/
    --exclude=.gvfs
    --exclude=.gvfs/
    --exclude=.thumbnails/
    --exclude=Downloads/.tmp/
    --exclude=.mozilla/firefox/*.default*/lock
    --exclude=.mozilla/firefox/*.default*/.parentlock
    --exclude=.mozilla/firefox/*.default-release*/lock
    --exclude=.mozilla/firefox/*.default-release*/.parentlock
    --exclude=.config/google-chrome/Singleton*
    --exclude=.config/chromium/Singleton*
    --exclude=.config/BraveSoftware/Brave-Browser/Singleton*
    --exclude=.Xauthority-c
    --exclude=.xsession-errors.old
    --exclude=IPC$
    --exclude=IPC\$/
)

AGGRESSIVE_EXCLUDES=(
    --exclude=.var/
    --exclude=.local/share/containers/
    --exclude=.local/share/flatpak/
    --exclude=.steam/
    --exclude=.local/share/Steam/
    --exclude=.cargo/
    --exclude=.npm/
    --exclude=.yarn/
    --exclude=.cache-loader/
    --exclude=.ccache/
    --exclude=.wine/drive_c/windows/temp/
    --exclude=.mozilla/firefox/*/cache2/
    --exclude=.config/Code/Cache/
    --exclude=.config/Code/CachedData/
    --exclude=.config/Code/Service\ Worker/CacheStorage/
    --exclude=.config/BraveSoftware/Brave-Browser/*Cache*
    --exclude=.config/google-chrome/*Cache*
    --exclude=.config/chromium/*Cache*
    --exclude=.local/share/baloo/
    --exclude=.local/share/recently-used.xbel
    --exclude=.Trash*/
    --exclude=Downloads/
    --exclude=VirtualBox\ VMs/
    --exclude=.local/share/libvirt/
)

# Wird für normalen Home-Restore und Komplett-Wiederherstellung benutzt.
# Verhindert, dass alte Lock-/Session-/Runtime-Dateien zurückgeschrieben werden.
RESTORE_EXCLUDES=(
    --exclude=.cache/
    --exclude=.local/share/Trash/
    --exclude=.gvfs
    --exclude=.gvfs/
    --exclude=.dbus/
    --exclude=.Xauthority
    --exclude=.ICEauthority
    --exclude=.xsession-errors
    --exclude=.xsession-errors.old
    --exclude=.xsession-errors*

    --exclude=.mozilla/firefox/*/lock
    --exclude=.mozilla/firefox/*/.parentlock
    --exclude=.mozilla/firefox/*.default*/lock
    --exclude=.mozilla/firefox/*.default*/.parentlock
    --exclude=.mozilla/firefox/*.default-release*/lock
    --exclude=.mozilla/firefox/*.default-release*/.parentlock
    --exclude=.mozilla/firefox/*/startupCache/

    --exclude=.config/google-chrome/Singleton*
    --exclude=.config/chromium/Singleton*
    --exclude=.config/BraveSoftware/Brave-Browser/Singleton*

    --exclude=.local/share/keyrings/*.lock
    --exclude=.config/pulse/*-runtime
    --exclude=.config/session/
)

# Speziell für Wiederherstellung innerhalb einer laufenden grafischen Sitzung.
# Kein --delete. Keine aggressiven Desktop-/Runtime-Überschreibungen.
LIVE_RESTORE_EXCLUDES=(
    --exclude=.cache/
    --exclude=.gvfs
    --exclude=.gvfs/
    --exclude=.dbus/
    --exclude=.Xauthority
    --exclude=.ICEauthority
    --exclude=.xsession-errors
    --exclude=.xsession-errors.old
    --exclude=.xsession-errors*
    --exclude=.local/share/Trash/

    --exclude=.mozilla/firefox/*/lock
    --exclude=.mozilla/firefox/*/.parentlock
    --exclude=.mozilla/firefox/*/sessionstore*
    --exclude=.mozilla/firefox/*/startupCache/

    --exclude=.config/google-chrome/Singleton*
    --exclude=.config/chromium/Singleton*
    --exclude=.config/BraveSoftware/Brave-Browser/Singleton*

    --exclude=.config/pulse/*-runtime
    --exclude=.config/dconf/user
    --exclude=.local/share/keyrings/*.lock
    --exclude=.config/cinnamon-session/
    --exclude=.config/xfce4/xfconf/xfce-perchannel-xml/displays.xml

    --exclude=.steam/steam.pid
    --exclude=.var/app/*/cache/
)

AUTO_EXCLUDES=()
EFFECTIVE_EXCLUDES=()

RSYNC_COMMON_OPTS=(
    -aHAXx
    --numeric-ids
    --info=progress2
    --human-readable
)

# Kein -o und kein -g, damit chown am Ende zentral passiert.
# Das ist robuster bei Restore auf laufendem System oder anderer Distribution.
RSYNC_RESTORE_OPTS=(
    -aHAXx
    --numeric-ids
    --info=progress2
    --human-readable
)

APP_RESTORE_MODE="safe"

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export APT_LISTCHANGES_FRONTEND=none

die() { echo "Fehler: $*" >&2; exit 1; }
info() { echo "[INFO] $*" >&2; }
warn() { echo "[WARN] $*" >&2; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Benötigtes Programm fehlt: $1"; }
has_cmd() { command -v "$1" >/dev/null 2>&1; }

apt_get_usb_cache() {
    local opts=()
    if [[ -n "${APT_CACHE_DIR:-}" ]]; then
        mkdir -p "$APT_CACHE_DIR/archives/partial" 2>/dev/null || true
        opts=(
            -o "Dir::Cache=$APT_CACHE_DIR"
            -o "Dir::Cache::archives=$APT_CACHE_DIR/archives"
        )
    fi
    apt-get "${opts[@]}" "$@"
}


check_live_overlay_space() {
    local target="${1:-/}" avail fs
    fs="$(findmnt -no FSTYPE --target "$target" 2>/dev/null || true)"
    avail="$(df -Pm "$target" 2>/dev/null | awk 'NR==2 {print $4}')"
    [[ -n "$avail" ]] || return 0
    if [[ "$LIVE_MODE" == "true" || "$fs" == "overlay" || "$fs" == "aufs" ]]; then
        echo
        info "Live-/Overlay-Speicherprüfung für $target:"
        df -h "$target" 2>/dev/null || true
        if (( avail < 512 )); then
            warn "Sehr wenig freier Overlay-/Root-Speicher: ${avail} MB frei."
            warn "USB-Temp ist aktiv, aber apt/dpkg kann trotzdem etwas Root-Speicher brauchen."
        fi
    fi
}


cleanup_old_persistent_apt_cache_config() {
    local f="/etc/apt/apt.conf.d/99-home-backup-usb-cache"
    if [[ -f "$f" ]]; then
        warn "Entferne alte permanente APT-Cache-Konfiguration: $f"
        rm -f "$f" || warn "Konnte alte APT-Cache-Konfiguration nicht entfernen: $f"
    fi
}

setup_usb_temp_workdir() {
    [[ -n "$BACKUP_BASE_DIR" ]] || die "BACKUP_BASE_DIR ist leer. USB muss zuerst vorbereitet sein."

    cleanup_old_persistent_apt_cache_config

    TEMP_WORK_DIR="$BACKUP_BASE_DIR/.temp"
    APT_CACHE_DIR="$TEMP_WORK_DIR/apt-cache"
    RSYNC_PARTIAL_DIR="$TEMP_WORK_DIR/rsync-partial"

    mkdir -p "$TEMP_WORK_DIR" "$APT_CACHE_DIR/archives/partial" "$RSYNC_PARTIAL_DIR" "$TEMP_WORK_DIR/logs" "$TEMP_WORK_DIR/xdg-cache" "$TEMP_WORK_DIR/flatpak-cache"
    chmod 700 "$TEMP_WORK_DIR" "$APT_CACHE_DIR" "$RSYNC_PARTIAL_DIR" "$TEMP_WORK_DIR/logs" "$TEMP_WORK_DIR/xdg-cache" "$TEMP_WORK_DIR/flatpak-cache" 2>/dev/null || true

    export TMPDIR="$TEMP_WORK_DIR"
    export TEMP="$TEMP_WORK_DIR"
    export TMP="$TEMP_WORK_DIR"
    export XDG_CACHE_HOME="$TEMP_WORK_DIR/xdg-cache"
    export FLATPAK_SYSTEM_CACHE_DIR="$TEMP_WORK_DIR/flatpak-cache"

    info "Temporäre Arbeitsdaten werden auf USB ausgelagert:"
    echo "  TEMP_WORK_DIR    : $TEMP_WORK_DIR"
    echo "  APT_CACHE_DIR    : $APT_CACHE_DIR"
    echo "  RSYNC_PARTIAL_DIR: $RSYNC_PARTIAL_DIR"

    info "APT-Cache wird NICHT permanent umgestellt."
    info "APT nutzt den USB-Cache nur temporär pro apt-get-Aufruf."

    if [[ "$LIVE_MODE" == "true" ]]; then
        LOCAL_LOG_DIR="$TEMP_WORK_DIR/logs"
        LOCAL_LOG_FILE="$LOCAL_LOG_DIR/backup-${DATE_STR}.log"
    fi

    check_live_overlay_space /
    check_live_overlay_space /tmp
}

cleanup_usb_temp_workdir_menu() {
    [[ -n "$TEMP_WORK_DIR" && -d "$TEMP_WORK_DIR" ]] || { warn "Kein TEMP_WORK_DIR aktiv."; return 0; }
    echo
    warn "Temporäre Arbeitsdaten löschen:"
    echo "  $TEMP_WORK_DIR"
    read -r -p "Wirklich löschen? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || { info "Nicht gelöscht."; return 0; }
    rm -rf "$TEMP_WORK_DIR"
    info "Temporäre Arbeitsdaten gelöscht."
}


safe_chown_tree() {
    v20_note 'manuell prüfen' 'Kein rekursives chown: Eigentümer werden beim V20-Home-Restore explizit gewählt.'
}

run_menu_action() {
    local title="$1"
    shift
    local rc=0

    echo
    info "$title"

    set +e
    "$@"
    rc=$?
    set -e

    if [[ "$rc" -eq 0 ]]; then
        info "Aktion abgeschlossen: $title"
    else
        warn "Aktion wurde mit Fehlercode $rc beendet: $title"
        warn "Das Hauptmenü bleibt aktiv. Details stehen im Log."
    fi

    pause_enter
}


apt_install_noninteractive() {
    apt_get_usb_cache install -y \
        -o Dpkg::Options::="--force-confold" \
        -o Dpkg::Options::="--force-confdef" \
        "$@"
}

preseed_common_eulas() {
    if has_cmd debconf-set-selections; then
        echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections || true
        echo "ttf-mscorefonts-installer msttcorefonts/present-mscorefonts-eula note" | debconf-set-selections || true
        echo "ttf-mscorefonts-installer msttcorefonts/dldir string" | debconf-set-selections || true
    fi
}

recover_interrupted_dpkg() {
    if [[ -f /var/lib/dpkg/lock || -f /var/lib/dpkg/lock-frontend ]]; then
        warn "Prüfe auf unterbrochene dpkg/apt-Vorgänge ..."
    fi

    if has_cmd fuser; then
        if fuser /var/lib/dpkg/lock >/dev/null 2>&1 || fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
            warn "APT/dpkg läuft noch. Warte kurz, statt Lock-Dateien zu löschen ..."
            sleep 10
        fi
    fi

    dpkg --audit >/dev/null 2>&1 || true

    if dpkg --audit 2>/dev/null | grep -q .; then
        warn "dpkg ist unvollständig konfiguriert. Versuche automatische Reparatur ..."
        preseed_common_eulas
        dpkg --configure -a || warn "dpkg --configure -a konnte nicht alles reparieren."
    fi
}


usage() {
    cat <<EOF
$SCRIPT_NAME [Optionen]

Interaktiv:
  sudo ./$SCRIPT_NAME

Direkt aus installiertem System:
  sudo ./$SCRIPT_NAME --normal

Direkt aus Live-System:
  sudo ./$SCRIPT_NAME --live --source-home /mnt/root/home/exampleuser --source-user exampleuser

Optionen:
  --normal                       normales installiertes System sichern/wiederherstellen
  --live                         Live-System-Modus aktivieren
  --source-home PFAD             zu sicherndes/wiederherzustellendes Home-Verzeichnis
  --source-user NAME             Benutzername des installierten Systems
  --source-uid UID               UID manuell setzen, falls nicht ermittelbar
  --source-gid GID               GID manuell setzen, falls nicht ermittelbar
  --source-group NAME            Gruppenname manuell setzen
  --storage-dir PFAD             Lokaler Linux-Arbeitsordner des portablen Werkzeugs
  --client-id NAME               Ursprünglicher Rechnername, auch beim Live-USB
  --usb MOUNTPOINT               USB-Mount direkt vorgeben
  --help                         Hilfe anzeigen

Hinweis:
  Direktrestore in ein laufendes Home ist riskant.
  Dafür gibt es im Menü den sicheren Live-Desktop-Restore ohne --delete.
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --normal) LIVE_MODE="false"; shift ;;
            --live) LIVE_MODE="true"; shift ;;
            --source-home) SOURCE_HOME="${2:-}"; shift 2 ;;
            --source-user) SOURCE_USER="${2:-}"; shift 2 ;;
            --source-uid) SOURCE_UID="${2:-}"; shift 2 ;;
            --source-gid) SOURCE_GID="${2:-}"; shift 2 ;;
            --source-group) SOURCE_GROUP="${2:-}"; shift 2 ;;
            --storage-dir) STORAGE_DIR="${2:-}"; shift 2 ;;
            --client-id) CLIENT_ID="${2:-}"; shift 2 ;;
            --usb) USB_MOUNTPOINT="${2:-}"; shift 2 ;;
            --help|-h) usage; exit 0 ;;
            *) die "Unbekannte Option: $1" ;;
        esac
    done
}

pause_enter() {
    echo
    read -r -p "Enter drücken zum Fortfahren ..." _
    echo
}

human_bytes() {
    local bytes="${1:-0}"
    numfmt --to=iec-i --suffix=B "$bytes"
}

get_avail_bytes() {
    local path="$1"
    df -PB1 "$path" | awk 'NR==2 {print $4}'
}

choose_start_mode() {
    local choice

    if [[ -n "$SOURCE_HOME" || "$LIVE_MODE" == "true" ]]; then
        return 0
    fi

    echo
    echo "Startmodus:"
    echo "  1) Normales installiertes System"
    echo "  2) Live-System: installiertes Linux read-write mounten und Home auswählen"
    echo
    read -r -p "Auswahl [1-2]: " choice

    case "$choice" in
        1) LIVE_MODE="false" ;;
        2) LIVE_MODE="true" ;;
        *) die "Ungültige Auswahl." ;;
    esac
}

list_linux_root_candidates() {
    lsblk -prno NAME,FSTYPE,SIZE,LABEL,UUID,MOUNTPOINTS | \
    awk '$2 ~ /^(ext2|ext3|ext4|btrfs|xfs|f2fs)$/ { print }'
}

mount_has_option() {
    local path="$1"
    local wanted="$2"
    local opts

    opts="$(findmnt -no OPTIONS --target "$path" 2>/dev/null || true)"
    [[ -n "$opts" && ",$opts," == *",$wanted,"* ]]
}

mount_is_readonly() {
    mount_has_option "$1" ro
}

mount_partition_mode() {
    local dev="$1"
    local mp="$2"
    local mode="${3:-rw}"
    local src fstype opts

    mkdir -p "$mp"

    if mountpoint -q "$mp"; then
        src="$(findmnt -no SOURCE --target "$mp" 2>/dev/null || true)"
        fstype="$(findmnt -no FSTYPE --target "$mp" 2>/dev/null || true)"
        opts="$(findmnt -no OPTIONS --target "$mp" 2>/dev/null || true)"

        warn "$mp ist bereits gemountet."
        echo "  Quelle : ${src:-unbekannt}"
        echo "  FSType : ${fstype:-unbekannt}"
        echo "  Optionen: ${opts:-unbekannt}"

        if [[ "$mode" == "rw" ]]; then
            if mount_is_readonly "$mp"; then
                warn "$mp ist readonly gemountet. Versuche remount rw ..."
                mount -o remount,rw "$mp" || die "Remount rw fehlgeschlagen: $mp"
            fi

            if mount_is_readonly "$mp"; then
                die "$mp ist weiterhin readonly. Restore nicht möglich."
            fi
        fi

        return 0
    fi

    if [[ "$mode" == "ro" ]]; then
        info "Mounte $dev readonly nach $mp ..."
        mount -o ro "$dev" "$mp" || die "Readonly-Mount fehlgeschlagen: $dev -> $mp"
    else
        info "Mounte $dev read-write nach $mp ..."
        mount -o rw "$dev" "$mp" || {
            warn "RW-Mount fehlgeschlagen. Versuche Mount mit Journal-Recovery ..."
            mount "$dev" "$mp" || die "RW-Mount fehlgeschlagen: $dev -> $mp"
        }

        if mount_is_readonly "$mp"; then
            die "$mp wurde readonly gemountet. Restore nicht möglich. Dateisystem prüfen."
        fi
    fi
}

mount_partition_ro_or_rw() {
    # Kompatibilitätswrapper für alte Aufrufe.
    # Standard ist jetzt rw, damit Restore nicht versehentlich auf readonly läuft.
    mount_partition_mode "$1" "$2" "${3:-rw}"
}

ensure_path_writable_for_restore() {
    local path="$1"
    local mp testfile

    [[ -e "$path" ]] || die "Restore-Ziel existiert nicht: $path"

    mp="$(findmnt -no TARGET --target "$path" 2>/dev/null || true)"

    [[ -n "$mp" ]] || die "Kein Mountpoint für Restore-Ziel gefunden: $path"

    if mount_is_readonly "$path"; then
        warn "Restore-Ziel liegt auf readonly Mount: $mp"
        warn "Versuche remount rw ..."
        mount -o remount,rw "$mp" || die "Remount rw fehlgeschlagen: $mp"
    fi

    if mount_is_readonly "$path"; then
        die "Restore-Ziel ist weiterhin readonly: $path"
    fi

    testfile="$path/.restore-write-test-$$"
    touch "$testfile" 2>/dev/null || die "Restore-Ziel ist nicht beschreibbar: $path"
    rm -f "$testfile"

    info "Restore-Ziel ist beschreibbar: $path"
}

choose_separate_home_partition() {
    local candidates=() line choice dev
    local i=1

    echo
    warn "Unter $AUTO_ROOT_MOUNT wurde kein nutzbares /home mit Benutzerverzeichnissen gefunden."
    echo "Möglicherweise hat das System eine separate Home-Partition."
    echo
    echo "  1) Separate Home-Partition auswählen"
    echo "  2) Abbrechen"
    echo
    read -r -p "Auswahl [1-2]: " choice

    case "$choice" in
        1) ;;
        2) die "Abgebrochen. Root war vermutlich nicht die richtige Partition oder /home ist separat." ;;
        *) die "Ungültige Auswahl." ;;
    esac

    while IFS= read -r line; do
        [[ -n "$line" ]] && candidates+=("$line")
    done < <(list_linux_root_candidates)

    [[ ${#candidates[@]} -gt 0 ]] || die "Keine mögliche Home-Partition gefunden."

    echo
    echo "Mögliche Home-Partitionen:"
    for line in "${candidates[@]}"; do
        echo "  [$i] $line"
        ((i++))
    done
    echo
    read -r -p "Home-Partition auswählen [1-${#candidates[@]}]: " choice
    [[ "$choice" =~ ^[0-9]+$ ]] || die "Ungültige Auswahl."
    (( choice >= 1 && choice <= ${#candidates[@]} )) || die "Auswahl außerhalb des Bereichs."

    dev="$(awk '{print $1}' <<<"${candidates[$((choice-1))]}")"

    if mountpoint -q "$AUTO_HOME_MOUNT"; then
        umount "$AUTO_HOME_MOUNT" 2>/dev/null || true
    fi

    info "Mounte separate Home-Partition $dev nach $AUTO_HOME_MOUNT ..."
    mount_partition_mode "$dev" "$AUTO_HOME_MOUNT" "$REQUESTED_ROOT_MOUNT_MODE"
    AUTO_MOUNTED_HOME="true"

    [[ -d "$AUTO_HOME_MOUNT" ]] || die "Home-Mount fehlgeschlagen: $AUTO_HOME_MOUNT"
}

choose_and_mount_live_root() {
    local candidates=() line choice dev
    local i=1

    if [[ -n "$SOURCE_HOME" ]]; then
        return 0
    fi

    while IFS= read -r line; do
        [[ -n "$line" ]] && candidates+=("$line")
    done < <(list_linux_root_candidates)

    [[ ${#candidates[@]} -gt 0 ]] || die "Keine Linux-Dateisystem-Partition gefunden. Manuell mounten und --source-home angeben."

    echo
    echo "Mögliche Linux-Systempartitionen:"
    for line in "${candidates[@]}"; do
        echo "  [$i] $line"
        ((i++))
    done
    echo
    read -r -p "Root-Partition auswählen [1-${#candidates[@]}]: " choice
    [[ "$choice" =~ ^[0-9]+$ ]] || die "Ungültige Auswahl."
    (( choice >= 1 && choice <= ${#candidates[@]} )) || die "Auswahl außerhalb des Bereichs."

    dev="$(awk '{print $1}' <<<"${candidates[$((choice-1))]}")"

    mkdir -p "$AUTO_ROOT_MOUNT"

    if mountpoint -q "$AUTO_ROOT_MOUNT"; then
        warn "$AUTO_ROOT_MOUNT ist bereits gemountet. Verwende vorhandenen Mount."
    else
        info "Mounte $dev nach $AUTO_ROOT_MOUNT ..."
        mount_partition_mode "$dev" "$AUTO_ROOT_MOUNT" "$REQUESTED_ROOT_MOUNT_MODE"
        AUTO_MOUNTED_ROOT="true"
    fi

    if [[ ! -d "$AUTO_ROOT_MOUNT/home" ]]; then
        echo
        echo "Inhalt von $AUTO_ROOT_MOUNT:"
        ls -la "$AUTO_ROOT_MOUNT" || true
        choose_separate_home_partition
        return 0
    fi

    if ! find "$AUTO_ROOT_MOUNT/home" -mindepth 1 -maxdepth 1 -type d -print -quit 2>/dev/null | grep -q .; then
        echo
        echo "Inhalt von $AUTO_ROOT_MOUNT/home:"
        ls -la "$AUTO_ROOT_MOUNT/home" || true
        choose_separate_home_partition
        return 0
    fi
}

choose_live_home() {
    local homes=() dir choice i=1

    [[ -n "$SOURCE_HOME" ]] && return 0

    choose_and_mount_live_root

    while IFS= read -r -d '' dir; do
        homes+=("$dir")
    done < <(find "$AUTO_ROOT_MOUNT/home" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)

    [[ ${#homes[@]} -gt 0 ]] || die "Keine Home-Verzeichnisse unter $AUTO_ROOT_MOUNT/home gefunden."

    if [[ ${#homes[@]} -eq 1 ]]; then
        SOURCE_HOME="${homes[0]}"
        SOURCE_USER="$(basename "$SOURCE_HOME")"
        info "Home automatisch gewählt: $SOURCE_HOME"
        return 0
    fi

    echo
    echo "Gefundene Home-Verzeichnisse:"
    for dir in "${homes[@]}"; do
        echo "  [$i] $dir"
        ((i++))
    done
    echo
    read -r -p "Home auswählen [1-${#homes[@]}]: " choice
    [[ "$choice" =~ ^[0-9]+$ ]] || die "Ungültige Auswahl."
    (( choice >= 1 && choice <= ${#homes[@]} )) || die "Auswahl außerhalb des Bereichs."

    SOURCE_HOME="${homes[$((choice-1))]}"
    SOURCE_USER="$(basename "$SOURCE_HOME")"
}

resolve_source_identity() {
    if [[ "$LIVE_MODE" == "true" ]]; then
        choose_live_home
        [[ -n "$SOURCE_HOME" ]] || die "Im Live-Modus konnte kein Home gewählt werden."
        [[ -d "$SOURCE_HOME" ]] || die "SOURCE_HOME existiert nicht: $SOURCE_HOME"

        SOURCE_USER="${SOURCE_USER:-$(basename "$SOURCE_HOME")}"

        if [[ -z "$SOURCE_UID" || -z "$SOURCE_GID" ]]; then
            SOURCE_UID="$(stat -c '%u' "$SOURCE_HOME")"
            SOURCE_GID="$(stat -c '%g' "$SOURCE_HOME")"
        fi

        if [[ -z "$SOURCE_GROUP" ]]; then
            SOURCE_GROUP="$(getent group "$SOURCE_GID" | cut -d: -f1 || true)"
            SOURCE_GROUP="${SOURCE_GROUP:-$SOURCE_GID}"
        fi

        SOURCE_HOST="$(hostname -s 2>/dev/null || hostname)-live"
        LOCAL_LOG_DIR="/tmp/home-usb-backup-${SOURCE_USER}"
    else
        SOURCE_USER="${SOURCE_USER:-${SUDO_USER:-$USER}}"
        SOURCE_UID="$(id -u "$SOURCE_USER")"
        SOURCE_GID="$(id -g "$SOURCE_USER")"
        SOURCE_GROUP="$(id -gn "$SOURCE_USER")"
        SOURCE_HOME="$(getent passwd "$SOURCE_USER" | cut -d: -f6)"
        SOURCE_HOST="$(hostname -s 2>/dev/null || hostname)"
        LOCAL_LOG_DIR="${SOURCE_HOME}/.local/state/home-usb-backup"
    fi

    [[ -n "$SOURCE_HOME" ]] || die "Home-Verzeichnis konnte nicht ermittelt werden."
    [[ -d "$SOURCE_HOME" ]] || die "Home-Verzeichnis existiert nicht: $SOURCE_HOME"

    LOCAL_LOG_FILE="${LOCAL_LOG_DIR}/backup-${DATE_STR}.log"
}

init_logging() {
    mkdir -p "$LOCAL_LOG_DIR" 2>/dev/null || LOCAL_LOG_DIR="/tmp/home-usb-backup-${SOURCE_USER}"
    mkdir -p "$LOCAL_LOG_DIR"
    LOCAL_LOG_FILE="${LOCAL_LOG_DIR}/backup-${DATE_STR}.log"
    touch "$LOCAL_LOG_FILE"

    if [[ -n "${USB_LOG_FILE:-}" ]]; then
        mkdir -p "$(dirname "$USB_LOG_FILE")"
        touch "$USB_LOG_FILE"
        exec > >(tee -a "$LOCAL_LOG_FILE" "$USB_LOG_FILE") 2>&1
    else
        exec > >(tee -a "$LOCAL_LOG_FILE") 2>&1
    fi
}

find_usb_mounts() {
    local search_roots=("/media" "/run/media" "/mnt")
    local mp src pkname transport rm

    for root in "${search_roots[@]}"; do
        [[ -d "$root" ]] || continue
        while IFS= read -r -d '' mp; do
            mountpoint -q "$mp" || continue
            src="$(findmnt -no SOURCE --target "$mp" 2>/dev/null || true)"
            [[ "$src" == /dev/* ]] || continue
            pkname="$(lsblk -no PKNAME "$src" 2>/dev/null | head -n1 || true)"
            [[ -n "$pkname" ]] || pkname="$(basename "$src")"
            rm="$(lsblk -ndo RM "/dev/$pkname" 2>/dev/null | head -n1 || echo 0)"
            transport="$(lsblk -ndo TRAN "/dev/$pkname" 2>/dev/null | head -n1 || true)"
            if [[ "$rm" == "1" || "$transport" == "usb" ]]; then
                [[ -r "$mp" && -x "$mp" ]] && printf '%s\n' "$mp"
            fi
        done < <(find "$root" -mindepth 1 -maxdepth 2 -type d -print0 2>/dev/null)
    done | awk '!seen[$0]++'
}

choose_usb_mountpoint() {
    local candidates=() line i=1 choice

    if [[ -n "$USB_MOUNTPOINT" ]]; then
        mountpoint -q "$USB_MOUNTPOINT" || die "Angegebener USB-Pfad ist kein Mountpoint: $USB_MOUNTPOINT"
        return 0
    fi

    while IFS= read -r line; do
        [[ -n "$line" ]] && candidates+=("$line")
    done < <(find_usb_mounts)

    [[ ${#candidates[@]} -gt 0 ]] || die "Kein zugreifbarer USB-Mount gefunden. USB ggf. manuell mounten und mit --usb angeben."

    if [[ ${#candidates[@]} -eq 1 ]]; then
        USB_MOUNTPOINT="${candidates[0]}"
        return 0
    fi

    echo
    echo "Gefundene USB-Mounts:"
    for mp in "${candidates[@]}"; do
        echo "  [$i] $mp"
        ((i++))
    done
    echo
    read -r -p "USB-Mount auswählen [1-${#candidates[@]}]: " choice
    [[ "$choice" =~ ^[0-9]+$ ]] || die "Ungültige Auswahl."
    (( choice >= 1 && choice <= ${#candidates[@]} )) || die "Auswahl außerhalb des Bereichs."
    USB_MOUNTPOINT="${candidates[$((choice-1))]}"
}

get_usb_fstype() {
    USB_FSTYPE="$(findmnt -no FSTYPE --target "$USB_MOUNTPOINT" 2>/dev/null || true)"
    [[ -n "$USB_FSTYPE" ]] || USB_FSTYPE="unbekannt"
}

filesystem_supports_unix_perms() {
    case "$USB_FSTYPE" in
        ext2|ext3|ext4|xfs|btrfs|f2fs) return 0 ;;
        *) return 1 ;;
    esac
}

print_filesystem_permission_hint() {
    get_usb_fstype
    if filesystem_supports_unix_perms; then
        info "Dateisystem $USB_FSTYPE unterstützt normale Linux-Rechte."
    else
        warn "Dateisystem $USB_FSTYPE unterstützt vermutlich keine echten Linux-Dateirechte."
        warn "Für saubere Linux-Home-Backups ist ext4 auf USB klar besser als exFAT/NTFS."
    fi
}

ensure_usb_writable() {
    local testfile
    [[ -n "$USB_MOUNTPOINT" ]] || die "USB_MOUNTPOINT ist leer."
    [[ -d "$USB_MOUNTPOINT" ]] || die "USB-Mount existiert nicht: $USB_MOUNTPOINT"
    [[ -r "$USB_MOUNTPOINT" && -x "$USB_MOUNTPOINT" ]] || die "USB-Mount ist nicht betretbar: $USB_MOUNTPOINT"
    testfile="$USB_MOUNTPOINT/.write-test-$$"
    touch "$testfile" 2>/dev/null || die "USB-Mount ist nicht beschreibbar: $USB_MOUNTPOINT"
    rm -f "$testfile"
}

set_backup_paths() {
    ensure_usb_writable
    get_usb_fstype

    BACKUP_BASE_DIR="$USB_MOUNTPOINT/$BACKUP_ROOT_NAME"
    if [[ -n "$CLIENT_ID" ]]; then
        [[ "$CLIENT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || die "Ungültige Rechnerkennung"
        BACKUP_BASE_DIR="$BACKUP_BASE_DIR/$CLIENT_ID"
    fi
    BACKUP_DIR="$BACKUP_BASE_DIR/$SOURCE_USER"

    [[ -e "$BACKUP_BASE_DIR" && ! -d "$BACKUP_BASE_DIR" ]] && die "Pfad existiert, ist aber kein Verzeichnis: $BACKUP_BASE_DIR"
    mkdir -p "$BACKUP_DIR"

    if filesystem_supports_unix_perms; then
        chmod 700 "$BACKUP_DIR" 2>/dev/null || true
        chown "$SOURCE_UID:$SOURCE_GID" "$BACKUP_DIR" 2>/dev/null || true
    fi
}

set_server_backup_paths() {
    local host
    host="$(hostname -s 2>/dev/null || hostname)"
    SERVER_BACKUP_BASE_DIR="$USB_MOUNTPOINT/$SERVER_BACKUP_ROOT_NAME"
    SERVER_BACKUP_DIR="$SERVER_BACKUP_BASE_DIR/$host"
    mkdir -p "$SERVER_BACKUP_DIR"
    chmod 700 "$SERVER_BACKUP_DIR" 2>/dev/null || true
}

server_backup_path() {
    [[ -n "$SERVER_BACKUP_DIR" ]] || set_server_backup_paths
    echo "$SERVER_BACKUP_DIR"
}

export_all_users_and_ids() {
    local base users_dir
    base="$(server_backup_path)"
    users_dir="$base/$SERVER_USERS_DIR_NAME"
    mkdir -p "$users_dir"

    info "Exportiere Benutzer/UID/GID ..."

    cp -a /etc/passwd "$users_dir/passwd.full" 2>/dev/null || true
    cp -a /etc/group "$users_dir/group.full" 2>/dev/null || true
    cp -a /etc/subuid "$users_dir/subuid.full" 2>/dev/null || true
    cp -a /etc/subgid "$users_dir/subgid.full" 2>/dev/null || true

    {
        echo -e "username\tuid\tgid\tprimary_group\thome\tshell"
        awk -F: '$3 >= 1000 && $3 < 65534 {print $1 "\t" $3 "\t" $4 "\t" $1 "\t" $6 "\t" $7}' /etc/passwd
        awk -F: '$1 ~ /^(www-data|mysql|postgres|docker|libvirt-qemu|tvheadend|_apt)$/ {print $1 "\t" $3 "\t" $4 "\t" $1 "\t" $6 "\t" $7}' /etc/passwd
    } | awk 'NF && !seen[$0]++' > "$users_dir/server-users.tsv"

    {
        echo "created=$(date --iso-8601=seconds)"
        echo "host=$(hostname -f 2>/dev/null || hostname)"
        echo
        cat "$users_dir/server-users.tsv"
    } > "$users_dir/user-id-report.txt"

    info "Gespeichert: $users_dir/server-users.tsv"
}

show_server_users_for_client_mapping() {
    local users_file
    users_file="$(server_backup_path)/$SERVER_USERS_DIR_NAME/server-users.tsv"
    [[ -f "$users_file" ]] || export_all_users_and_ids

    echo
    echo "Gespeicherte Benutzer/IDs für Zuordnung:"
    column -t -s $'\t' "$users_file" 2>/dev/null || cat "$users_file"
    echo
}

backup_server_core_configs() {
    local base
    base="$(server_backup_path)"
    mkdir -p "$base/system"

    warn "Sichere Server-Basiskonfiguration ..."
    rsync -aHAX --numeric-ids /etc "$base/system/" \
        --exclude='shadow' --exclude='shadow-' --exclude='gshadow' --exclude='gshadow-' \
        || warn "/etc nicht vollständig gesichert."

    [[ -d /usr/local ]] && rsync -aHAX --numeric-ids /usr/local "$base/system/" || true
    [[ -d /opt ]] && rsync -aHAX --numeric-ids /opt "$base/system/" || true
    [[ -d /var/spool/cron ]] && mkdir -p "$base/system/var-spool" && rsync -aHAX --numeric-ids /var/spool/cron "$base/system/var-spool/" || true

    export_all_users_and_ids
    save_identity_and_hardware_report
    save_systemd_mounts_and_acls
    v19_svl backup || die "SVL-Konfiguration konnte nicht vollständig gesichert werden."
}

backup_server_dbs() {
    local base db_dir dumpcmd
    base="$(server_backup_path)"
    db_dir="$base/$SERVER_DB_DIR_NAME"
    mkdir -p "$db_dir"

    info "Sichere Datenbanken, falls vorhanden ..."

    dumpcmd="$(command -v mariadb-dump || command -v mysqldump || true)"
    if [[ -n "$dumpcmd" ]]; then
        "$dumpcmd" --all-databases --single-transaction --quick --routines --events > "$db_dir/mysql-all-databases.sql" 2>"$db_dir/mysql-dump.err" || warn "MariaDB/MySQL Dump fehlgeschlagen."
    fi

    if has_cmd pg_dumpall; then
        sudo -u postgres pg_dumpall > "$db_dir/postgresql-all.sql" 2>"$db_dir/postgresql-dump.err" || warn "PostgreSQL Dump fehlgeschlagen."
    fi
}

backup_server_nextcloud() {
    local base nc_dir ncroot data_dir
    base="$(server_backup_path)"
    nc_dir="$base/$SERVER_NEXTCLOUD_DIR_NAME"
    mkdir -p "$nc_dir"

    info "Sichere Nextcloud, falls vorhanden ..."

    ncroot=""
    for p in /var/www/html/nextcloud /var/www/nextcloud; do
        [[ -f "$p/occ" ]] && ncroot="$p" && break
    done

    if [[ -z "$ncroot" ]]; then
        warn "Nextcloud occ nicht gefunden."
        return 0
    fi

    sudo -u www-data php "$ncroot/occ" status > "$nc_dir/occ-status.txt" 2>/dev/null || true
    sudo -u www-data php "$ncroot/occ" config:list system > "$nc_dir/occ-config-system.json" 2>/dev/null || true
    data_dir="$(sudo -u www-data php "$ncroot/occ" config:system:get datadirectory 2>/dev/null || true)"

    rsync -aHAX --numeric-ids "$ncroot" "$nc_dir/" || warn "Nextcloud Webroot nicht vollständig gesichert."

    if [[ -n "$data_dir" && -d "$data_dir" ]]; then
        mkdir -p "$nc_dir/data"
        rsync -aHAX --numeric-ids --info=progress2 "$data_dir/" "$nc_dir/data/" || warn "Nextcloud-Daten nicht vollständig gesichert."
    fi
}

backup_server_all() {
    echo
    warn "Vollständiges Debian-Server-Backup."
    warn "Ablage getrennt unter: $USB_MOUNTPOINT/$SERVER_BACKUP_ROOT_NAME/<hostname>"
    read -r -p "Starten? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || return 0

    set_server_backup_paths
    backup_server_core_configs
    backup_server_dbs
    backup_server_nextcloud
    save_docker_container_data
    save_libvirt_vms
    save_server_services
    save_mounted_data_roots
    create_restore_report
    info "Server-Backup abgeschlossen: $SERVER_BACKUP_DIR"
}

restore_server_core_configs() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_server_core_configs systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local base
    base="$(server_backup_path)"
    [[ -d "$base/system" ]] || die "Keine Server-Systemkonfiguration gefunden: $base/system"

    warn "Server-Basiskonfiguration wiederherstellen."
    warn "passwd/shadow/group/machine-id/fstab werden NICHT blind überschrieben."
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || return 0

    if [[ -d "$base/system/etc" ]]; then
        rsync -aHAX --numeric-ids --force \
            --exclude=passwd --exclude=passwd- \
            --exclude=shadow --exclude=shadow- \
            --exclude=group --exclude=group- \
            --exclude=gshadow --exclude=gshadow- \
            --exclude=machine-id \
            --exclude=fstab --exclude=crypttab \
            "$base/system/etc/" /etc/ || warn "/etc Restore unvollständig."
        [[ -f "$base/system/etc/fstab" ]] && cp -a "$base/system/etc/fstab" "/etc/fstab.server-restored-${DATE_STR}" || true
    fi

    [[ -d "$base/system/usr-local" ]] && rsync -aHAX --numeric-ids --force "$base/system/usr-local" /usr/ || true
    [[ -d "$base/system/opt" ]] && rsync -aHAX --numeric-ids --force "$base/system/opt" / || true
    systemctl daemon-reload 2>/dev/null || true
}

# Altes, fehlerhaftes server_menu() entfernt.
# Die gültige Server-Menüdefinition befindet sich weiter unten bei den neuen Menüstrukturen.

ensure_client_backup_compatibility() {
    local old_base="$USB_MOUNTPOINT/linux-home-backup"
    local new_base="$USB_MOUNTPOINT/$BACKUP_ROOT_NAME"

    if [[ "$BACKUP_ROOT_NAME" == "linux-client-backup" && ! -e "$new_base" && -d "$old_base" ]]; then
        warn "Vorhandenes altes Backup gefunden: $old_base"
        warn "Erzeuge Kompatibilitäts-Symlink: $new_base -> $old_base"
        ln -s "$old_base" "$new_base" 2>/dev/null || warn "Symlink konnte nicht erstellt werden."
    fi

    if [[ ! -d "$BACKUP_DIR/$FILES_DIR_NAME" && -d "$old_base/$SOURCE_USER/$FILES_DIR_NAME" ]]; then
        warn "Client-Backup liegt noch im alten Pfad. Verwende alten Pfad:"
        BACKUP_BASE_DIR="$old_base"
        BACKUP_DIR="$old_base/$SOURCE_USER"
        echo "  BACKUP_DIR: $BACKUP_DIR"
    fi
}


setup_usb_logfile() {
    mkdir -p "$BACKUP_DIR/$META_DIR_NAME"
    if filesystem_supports_unix_perms; then
        chmod 700 "$BACKUP_DIR/$META_DIR_NAME" 2>/dev/null || true
        chown "$SOURCE_UID:$SOURCE_GID" "$BACKUP_DIR/$META_DIR_NAME" 2>/dev/null || true
    fi
    USB_LOG_FILE="$BACKUP_DIR/$META_DIR_NAME/session-${DATE_STR}.log"
}

show_usb_info() {
    local avail total used src
    src="$(findmnt -no SOURCE --target "$USB_MOUNTPOINT" 2>/dev/null || true)"
    total="$(df -PB1 "$USB_MOUNTPOINT" | awk 'NR==2 {print $2}')"
    used="$(df -PB1 "$USB_MOUNTPOINT" | awk 'NR==2 {print $3}')"
    avail="$(df -PB1 "$USB_MOUNTPOINT" | awk 'NR==2 {print $4}')"
    echo "Datenträger:"
    echo "  Mountpoint : $USB_MOUNTPOINT"
    echo "  Gerät      : ${src:-unbekannt}"
    echo "  FSType     : $USB_FSTYPE"
    echo "  Gesamt     : $(human_bytes "$total")"
    echo "  Belegt     : $(human_bytes "$used")"
    echo "  Frei       : $(human_bytes "$avail")"
}

write_metadata() {
    local meta_dir="$BACKUP_DIR/$META_DIR_NAME"
    mkdir -p "$meta_dir"
    cat > "$meta_dir/info.txt" <<EOF
backup_user=$SOURCE_USER
backup_uid=$SOURCE_UID
backup_gid=$SOURCE_GID
backup_group=$SOURCE_GROUP
backup_home=$SOURCE_HOME
backup_host=$SOURCE_HOST
backup_created=$(date --iso-8601=seconds)
backup_mode=$BACKUP_MODE
backup_fstype=$USB_FSTYPE
live_mode=$LIVE_MODE
kernel=$(uname -r)
EOF

    if [[ -f "$AUTO_ROOT_MOUNT/etc/os-release" ]]; then
        v20_save_os_release "$AUTO_ROOT_MOUNT/etc/os-release" "$meta_dir/os-release.source" 2>/dev/null || true
    elif [[ -f /etc/os-release ]]; then
        v20_save_os_release /etc/os-release "$meta_dir/os-release.source" 2>/dev/null || true
    fi

    if filesystem_supports_unix_perms; then
        chmod 600 "$meta_dir/info.txt" 2>/dev/null || true
        chown "$SOURCE_UID:$SOURCE_GID" "$meta_dir/info.txt" 2>/dev/null || true
    fi
}

show_backup_info() {
    local meta_file="$BACKUP_DIR/$META_DIR_NAME/info.txt"
    if [[ -f "$meta_file" ]]; then
        echo
        echo "Backup-Metadaten:"
        sed 's/^/  /' "$meta_file"
    else
        warn "Keine Backup-Metadaten gefunden."
    fi
    if [[ -d "$BACKUP_DIR/$FILES_DIR_NAME" ]]; then
        echo
        echo "Home-Backup:"
        du -sh "$BACKUP_DIR/$FILES_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$APPS_DIR_NAME" ]]; then
        echo
        echo "Programm-Listen:"
        find "$BACKUP_DIR/$APPS_DIR_NAME" -maxdepth 1 -type f -printf '  %f\n' 2>/dev/null | sort || true
    fi
    if [[ -d "$BACKUP_DIR/$DESKTOP_ASSETS_DIR_NAME" ]]; then
        echo
        echo "Systemweite Desktop-Assets:"
        du -sh "$BACKUP_DIR/$DESKTOP_ASSETS_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$SYSTEM_CONFIG_DIR_NAME" ]]; then
        echo
        echo "Erweiterte Systemkonfiguration:"
        du -sh "$BACKUP_DIR/$SYSTEM_CONFIG_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$LIBVIRT_DIR_NAME" ]]; then
        echo
        echo "KVM/libvirt/VMs:"
        du -sh "$BACKUP_DIR/$LIBVIRT_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$DOCKER_DIR_NAME" ]]; then
        echo
        echo "Docker/Container:"
        du -sh "$BACKUP_DIR/$DOCKER_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$SERVER_SERVICES_DIR_NAME" ]]; then
        echo
        echo "Serverdienste:"
        du -sh "$BACKUP_DIR/$SERVER_SERVICES_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$MOUNTED_DATA_DIR_NAME" ]]; then
        echo
        echo "Gemountete Datenlaufwerke:"
        du -sh "$BACKUP_DIR/$MOUNTED_DATA_DIR_NAME" 2>/dev/null || true
    fi
    if [[ -d "$BACKUP_DIR/$REPORTS_DIR_NAME" ]]; then
        echo
        echo "Berichte:"
        find "$BACKUP_DIR/$REPORTS_DIR_NAME" -maxdepth 1 -type f -printf '  %f\n' 2>/dev/null | sort || true
    fi
}

choose_backup_mode() {
    local choice
    echo
    echo "Backup-Modus:"
    echo
    echo "  1) Normal / Migration / 1:1-nahe Wiederherstellung"
    echo "     Sichert Home-Daten, App-Profile, Desktop-Einstellungen, Flatpak-Daten,"
    echo "     Browser-/Mailprofile, Themes, Icons, KeePassXC-Datenbank im Home usw."
    echo "     Empfohlen für Neuinstallation, anderen PC oder echte Wiederherstellung."
    echo
    echo "  2) Aggressiv / Clean / schlankes Backup"
    echo "     Lässt große oder reproduzierbare Daten weg:"
    echo "     Downloads, Steam, Flatpak-Appdaten, Container, Caches, Libvirt usw."
    echo "     Gut für ein sauberes Datenbackup, NICHT für 1:1-Systemmigration."
    echo
    read -r -p "Auswahl [1-2]: " choice
    case "$choice" in
        1) BACKUP_MODE="normal" ;;
        2) BACKUP_MODE="aggressive" ;;
        *) die "Ungültige Auswahl." ;;
    esac
    info "Backup-Modus: $BACKUP_MODE"
}

detect_problem_paths() {
    AUTO_EXCLUDES=()
    local rel path

    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        AUTO_EXCLUDES+=( "--exclude=$rel" "--exclude=$rel/" )
    done < <(
        findmnt -Rno TARGET 2>/dev/null | awk -v home="$SOURCE_HOME/" '$0 ~ "^" home {
            rel=$0; sub("^" home, "", rel); if (rel != "" && rel != ".") print rel
        }' | sort -u
    )

    while IFS= read -r -d '' path; do
        rel="${path#"$SOURCE_HOME"/}"
        [[ "$rel" == "$path" || -z "$rel" ]] && continue
        case "$rel" in
            .gvfs|.gvfs/*|.cache|.cache/*|.local/share/Trash|.local/share/Trash/*) continue ;;
        esac
        if [[ ! -r "$path" || ! -x "$path" ]]; then
            AUTO_EXCLUDES+=( "--exclude=$rel" "--exclude=$rel/" )
        fi
        case "$rel" in
            *'$'*|*":"*|*.fuse_hidden*|*.mount*|*.portal*|IPC\$|IPC\$/*)
                AUTO_EXCLUDES+=( "--exclude=$rel" "--exclude=$rel/" ) ;;
        esac
    done < <(find "$SOURCE_HOME" -mindepth 1 -maxdepth 2 -type d -print0 2>/dev/null)

    if [[ ${#AUTO_EXCLUDES[@]} -gt 0 ]]; then
        mapfile -t AUTO_EXCLUDES < <(printf '%s\n' "${AUTO_EXCLUDES[@]}" | awk 'NF && !seen[$0]++')
    fi
}

build_effective_excludes() {
    EFFECTIVE_EXCLUDES=()
    EFFECTIVE_EXCLUDES+=( "${BASE_EXCLUDES[@]}" )
    [[ "$BACKUP_MODE" == "aggressive" ]] && EFFECTIVE_EXCLUDES+=( "${AGGRESSIVE_EXCLUDES[@]}" )
    EFFECTIVE_EXCLUDES+=( "${AUTO_EXCLUDES[@]}" )
}

print_effective_excludes() {
    echo
    echo "Aktive Ausschlüsse:"
    printf '  %s\n' "${EFFECTIVE_EXCLUDES[@]}"
    echo
}

show_detected_problem_paths() {
    detect_problem_paths
    build_effective_excludes
    echo
    if [[ ${#AUTO_EXCLUDES[@]} -eq 0 ]]; then
        info "Keine zusätzlichen Problemordner erkannt."
    else
        warn "Zusätzlich automatisch ausgeschlossene Pfade:"
        printf '  %s\n' "${AUTO_EXCLUDES[@]}"
    fi
    echo
}

get_backup_source_size_bytes() {
    local dir="$1" tmpdir statsfile total_bytes
    tmpdir="$(mktemp -d)"
    statsfile="$(mktemp)"
    info "Berechne Backup-Größe. Das kann bei vielen Dateien dauern ..."
    rsync -aHAXxn --numeric-ids --delete --stats "${EFFECTIVE_EXCLUDES[@]}" "$dir/" "$tmpdir/" >"$statsfile" 2>/dev/null || true
    total_bytes="$(awk -F': ' '/Total file size:/ {gsub(/[^0-9]/, "", $2); print $2}' "$statsfile" | tail -n1)"
    rm -rf "$tmpdir" "$statsfile"
    [[ -n "$total_bytes" ]] || total_bytes=0
    echo "$total_bytes"
}

check_backup_space() {
    local source_size avail required_with_reserve
    source_size="$(get_backup_source_size_bytes "$SOURCE_HOME")"
    source_size="${source_size##*$'\n'}"
    [[ "$source_size" =~ ^[0-9]+$ ]] || die "Größenberechnung fehlgeschlagen: '$source_size'"
    avail="$(get_avail_bytes "$USB_MOUNTPOINT")"
    required_with_reserve=$(( source_size * 115 / 100 ))
    echo
    echo "Platzprüfung:"
    echo "  Geschätzte Backup-Größe    : $(human_bytes "$source_size")"
    echo "  Benötigt inkl. Reserve     : $(human_bytes "$required_with_reserve")"
    echo "  Frei auf Datenträger       : $(human_bytes "$avail")"
    (( avail >= required_with_reserve )) || die "Zu wenig freier Platz auf dem Datenträger."
    info "Platzprüfung erfolgreich."
}

source_root_for_apps() {
    if [[ "$LIVE_MODE" == "true" && -d "$AUTO_ROOT_MOUNT/etc" ]]; then
        echo "$AUTO_ROOT_MOUNT"
    elif [[ "$LIVE_MODE" == true ]]; then
        die "Live-Zielroot fehlt. Zielsystem unter $AUTO_ROOT_MOUNT mounten."
    else
        echo "/"
    fi
}

prepare_target_chroot() {
    local root
    root="$(source_root_for_apps)"

    [[ -d "$root" ]] || die "Target root fehlt: $root"

    if [[ "$root" == "/" ]]; then
        return 0
    fi

    if [[ "$CHROOT_PREPARED" == "true" ]]; then
        return 0
    fi

    info "Bereite chroot einmalig vor: $root"

    mkdir -p "$root/proc" "$root/sys" "$root/dev" "$root/run" "$root/tmp" "$root/etc"

    mountpoint -q "$root/proc" || mount --bind /proc "$root/proc"
    mountpoint -q "$root/sys"  || mount --bind /sys "$root/sys"
    mountpoint -q "$root/dev"  || mount --bind /dev "$root/dev"
    mountpoint -q "$root/run"  || mount --bind /run "$root/run"

    cp -L /etc/resolv.conf "$root/etc/resolv.conf" 2>/dev/null || true

    CHROOT_PREPARED="true"
    info "chroot vorbereitet."
}

cleanup_target_chroot() {
    local root
    root="$(source_root_for_apps)"

    [[ "$root" == "/" ]] && {
        CHROOT_PREPARED="false"
FAILED_APPS_REPORT=""
        return 0
    }

    if [[ "$CHROOT_PREPARED" != "true" ]]; then
        return 0
    fi

    info "Bereinige chroot-Mounts ..."

    umount -lf "$root/proc" 2>/dev/null || true
    umount -lf "$root/sys" 2>/dev/null || true
    umount -lf "$root/dev" 2>/dev/null || true
    umount -lf "$root/run" 2>/dev/null || true

    CHROOT_PREPARED="false"
FAILED_APPS_REPORT=""
}

target_has_cmd() {
    local cmd="$1"
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        command -v "$cmd" >/dev/null 2>&1
    else
        [[ -x "$root/usr/bin/$cmd" || -x "$root/bin/$cmd" || -x "$root/usr/sbin/$cmd" || -x "$root/sbin/$cmd" ]]
    fi
}

target_apt_update() {
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        apt_get_usb_cache update
        return $?
    fi

    prepare_target_chroot

    chroot "$root" env \
        DEBIAN_FRONTEND=noninteractive \
        NEEDRESTART_MODE=a \
        APT_LISTCHANGES_FRONTEND=none \
        apt-get update
}

target_apt_install() {
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        apt_install_noninteractive "$@" || {
            report_failed_app "APT" "$*" "Installation fehlgeschlagen"
            return 1
        }
        return 0
    fi

    prepare_target_chroot

    chroot "$root" env \
        DEBIAN_FRONTEND=noninteractive \
        NEEDRESTART_MODE=a \
        APT_LISTCHANGES_FRONTEND=none \
        apt-get install -y \
        -o Dpkg::Options::="--force-confold" \
        -o Dpkg::Options::="--force-confdef" \
        "$@" || {
            report_failed_app "APT" "$*" "Installation im Zielsystem/chroot fehlgeschlagen"
            return 1
        }
}

target_flatpak_available() {
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        command -v flatpak >/dev/null 2>&1
        return $?
    fi

    [[ -x "$root/usr/bin/flatpak" ]]
}

target_flatpak_app_installed() {
    local app="$1"
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        flatpak info "$app" >/dev/null 2>&1
        return $?
    fi

    prepare_target_chroot
    chroot "$root" flatpak info "$app" >/dev/null 2>&1
}

target_flatpak_remote_add_flathub() {
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
        return $?
    fi

    prepare_target_chroot
    chroot "$root" flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
}

target_flatpak_install_app() {
    local origin="$1"
    local app="$2"
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        flatpak install -y --or-update "$origin" "$app" || flatpak install -y --or-update flathub "$app" || {
            report_failed_app "Flatpak" "$app" "Flatpak-Installation fehlgeschlagen"
            return 1
        }
        return 0
    fi

    prepare_target_chroot

    chroot "$root" flatpak install -y --or-update "$origin" "$app" || \
    chroot "$root" flatpak install -y --or-update flathub "$app" || {
        report_failed_app "Flatpak" "$app" "Flatpak-Installation im Zielsystem/chroot fehlgeschlagen"
        return 1
    }
}

target_apt_cache_show() {
    local pkg="$1"
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        apt-cache show "$pkg" >/dev/null 2>&1
        return $?
    fi

    prepare_target_chroot
    chroot "$root" apt-cache show "$pkg" >/dev/null 2>&1
}

target_package_installed() {
    local pkg="$1"
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"
        return $?
    fi

    prepare_target_chroot
    chroot "$root" dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"
}


setup_failed_apps_report() {
    local desktop_dir

    desktop_dir="$SOURCE_HOME/Desktop"

    if [[ ! -d "$desktop_dir" && -d "$SOURCE_HOME/Schreibtisch" ]]; then
        desktop_dir="$SOURCE_HOME/Schreibtisch"
    fi

    mkdir -p "$desktop_dir"

    FAILED_APPS_REPORT="$desktop_dir/nicht-installierbare-apps.txt"

    cat > "$FAILED_APPS_REPORT" <<EOF
Nicht installierbare oder problematische Anwendungen
Erstellt: $(date --iso-8601=seconds)
Quelle Backup: $BACKUP_DIR
Ziel-Home: $SOURCE_HOME
Live-Modus: $LIVE_MODE

Hinweis:
Diese Liste enthält Pakete/Apps, die übersprungen wurden, nicht verfügbar waren
oder bei der Installation Fehler erzeugt haben.

EOF

    if [[ -n "${SOURCE_UID:-}" && -n "${SOURCE_GID:-}" ]]; then
        chown "$SOURCE_UID:$SOURCE_GID" "$FAILED_APPS_REPORT" 2>/dev/null || true
    fi

    info "Fehlerbericht für Apps: $FAILED_APPS_REPORT"
}

report_failed_app() {
    local type="$1"
    local app="$2"
    local reason="$3"

    [[ -n "${FAILED_APPS_REPORT:-}" ]] || return 0

    {
        echo "[$type]"
        echo "App/Paket : $app"
        echo "Grund     : $reason"
        echo
    } >> "$FAILED_APPS_REPORT"

    if [[ -n "${SOURCE_UID:-}" && -n "${SOURCE_GID:-}" ]]; then
        chown "$SOURCE_UID:$SOURCE_GID" "$FAILED_APPS_REPORT" 2>/dev/null || true
    fi
}


create_flatpak_after_first_boot_script() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local appfile="$apps_dir/flatpak-apps.tsv"
    local desktop_dir script
    local app branch origin installation

    [[ -f "$appfile" ]] || return 0

    desktop_dir="$SOURCE_HOME/Desktop"
    if [[ ! -d "$desktop_dir" && -d "$SOURCE_HOME/Schreibtisch" ]]; then
        desktop_dir="$SOURCE_HOME/Schreibtisch"
    fi
    mkdir -p "$desktop_dir"

    script="$desktop_dir/install-flatpaks-nach-erster-anmeldung.sh"

    cat > "$script" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

echo "Installiere Flatpaks nach der ersten Anmeldung ..."
echo

if ! command -v flatpak >/dev/null 2>&1; then
    echo "Flatpak fehlt. Installiere flatpak per APT ..."
    sudo apt update
    sudo apt install -y flatpak
fi

flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

EOF

    while IFS=$'\t' read -r app branch origin installation; do
        [[ -n "$app" ]] || continue
        [[ "$app" == "Application ID" ]] && continue
        origin="${origin:-flathub}"

        cat >> "$script" <<EOF
echo "Installiere: $app"
flatpak info "$app" >/dev/null 2>&1 || flatpak install -y --or-update "$origin" "$app" || flatpak install -y --or-update flathub "$app" || echo "FEHLER: $app konnte nicht installiert werden"
echo
EOF
    done < "$appfile"

    cat >> "$script" <<'EOF'

echo "Flatpak-Nachinstallation abgeschlossen."
read -r -p "Enter drücken zum Schließen ..."
EOF

    chmod +x "$script"
    if [[ -n "${SOURCE_UID:-}" && -n "${SOURCE_GID:-}" ]]; then
        chown "$SOURCE_UID:$SOURCE_GID" "$script" 2>/dev/null || true
    fi

    info "Flatpak-Nachinstallationsskript erstellt: $script"
}

target_dpkg_configure_a() {
    local root
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        dpkg --configure -a
        return $?
    fi

    prepare_target_chroot
    chroot "$root" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a dpkg --configure -a
}

target_fix_cdrom_repositories() {
    local root file changed="false"
    root="$(source_root_for_apps)"

    if [[ "$root" == "/" ]]; then
        fix_cdrom_repositories
        return 0
    fi

    [[ -d "$root/etc/apt" ]] || return 0

    info "Prüfe Zielsystem auf störende cdrom:-Repositories ..."

    if [[ -f "$root/etc/apt/sources.list" ]] && grep -Eq '^[[:space:]]*deb[[:space:]]+cdrom:' "$root/etc/apt/sources.list"; then
        cp -a "$root/etc/apt/sources.list" "$root/etc/apt/sources.list.bak-${DATE_STR}" 2>/dev/null || true
        sed -Ei 's|^[[:space:]]*(deb[[:space:]]+cdrom:.*)|# DISABLED-BY-BACKUP-SCRIPT \1|g' "$root/etc/apt/sources.list"
        changed="true"
    fi

    if [[ -d "$root/etc/apt/sources.list.d" ]]; then
        while IFS= read -r file; do
            [[ -f "$file" ]] || continue
            if grep -Eq '^[[:space:]]*deb[[:space:]]+cdrom:' "$file"; then
                cp -a "$file" "${file}.bak-${DATE_STR}" 2>/dev/null || true
                sed -Ei 's|^[[:space:]]*(deb[[:space:]]+cdrom:.*)|# DISABLED-BY-BACKUP-SCRIPT \1|g' "$file"
                changed="true"
            fi
        done < <(find "$root/etc/apt/sources.list.d" -type f 2>/dev/null)
    fi

    if [[ "$changed" == "true" ]]; then
        info "cdrom:-Einträge im Zielsystem deaktiviert."
    else
        info "Keine aktiven cdrom:-Einträge im Zielsystem gefunden."
    fi
}

recover_interrupted_target_dpkg() {
    local root
    root="$(source_root_for_apps)"

    preseed_common_eulas

    if [[ "$root" == "/" ]]; then
        recover_interrupted_dpkg
        return 0
    fi

    prepare_target_chroot

    if chroot "$root" dpkg --audit 2>/dev/null | grep -q .; then
        warn "dpkg im Zielsystem ist unvollständig konfiguriert. Versuche Reparatur im chroot ..."
        target_dpkg_configure_a || warn "dpkg --configure -a im Zielsystem konnte nicht alles reparieren."
    fi
}


save_program_lists() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local root
    root="$(source_root_for_apps)"

    mkdir -p "$apps_dir"

    echo
    info "Erstelle Programm- und Paketlisten ..."
    echo "  System-Root : $root"
    echo "  Ziel        : $apps_dir"

    if [[ -f "$root/etc/os-release" ]]; then
        v20_save_os_release "$root/etc/os-release" "$apps_dir/os-release" 2>/dev/null || true
    fi

    if [[ "$root" == "/" ]]; then
        if has_cmd dpkg-query; then
            dpkg-query -W -f='${db:Status-Status}\t${binary:Package}\t${Version}\t${Architecture}\n' | awk -F '\t' '$1=="installed" {print $2"\t"$3"\t"$4}' > "$apps_dir/dpkg-installed.tsv" || true
        fi
        if has_cmd apt-mark; then
            apt-mark showmanual | sort > "$apps_dir/apt-manual.txt" || true
        fi
        if has_cmd flatpak; then
            flatpak remotes --columns=name,url,options > "$apps_dir/flatpak-remotes.txt" 2>/dev/null || true
            flatpak list --app --columns=application,branch,origin,installation > "$apps_dir/flatpak-apps.tsv" 2>/dev/null || true
        fi
    else
        if [[ -x "$root/usr/bin/dpkg-query" ]]; then
            chroot "$root" dpkg-query -W -f='${db:Status-Status}\t${binary:Package}\t${Version}\t${Architecture}\n' | awk -F '\t' '$1=="installed" {print $2"\t"$3"\t"$4}' > "$apps_dir/dpkg-installed.tsv" || true
        fi
        if [[ -x "$root/usr/bin/apt-mark" ]]; then
            chroot "$root" apt-mark showmanual | sort > "$apps_dir/apt-manual.txt" || true
        fi
        if [[ -x "$root/usr/bin/flatpak" ]]; then
            chroot "$root" flatpak remotes --columns=name,url,options > "$apps_dir/flatpak-remotes.txt" 2>/dev/null || true
            chroot "$root" flatpak list --app --columns=application,branch,origin,installation > "$apps_dir/flatpak-apps.tsv" 2>/dev/null || true
        else
            warn "Flatpak im Quellsystem nicht gefunden oder im Live-Chroot nicht ausführbar."
        fi
    fi

    if [[ -d "$root/etc/apt" ]]; then
        mkdir -p "$apps_dir/apt-sources.list.d" "$apps_dir/apt-keyrings/etc-apt-keyrings" "$apps_dir/apt-keyrings/trusted.gpg.d"
        cp -a "$root/etc/apt/sources.list" "$apps_dir/sources.list" 2>/dev/null || true
        [[ -d "$root/etc/apt/sources.list.d" ]] && cp -a "$root/etc/apt/sources.list.d/." "$apps_dir/apt-sources.list.d/" 2>/dev/null || true
        [[ -d "$root/etc/apt/keyrings" ]] && cp -a "$root/etc/apt/keyrings/." "$apps_dir/apt-keyrings/etc-apt-keyrings/" 2>/dev/null || true
        [[ -d "$root/etc/apt/trusted.gpg.d" ]] && cp -a "$root/etc/apt/trusted.gpg.d/." "$apps_dir/apt-keyrings/trusted.gpg.d/" 2>/dev/null || true
        [[ -f "$root/etc/apt/trusted.gpg" ]] && cp -a "$root/etc/apt/trusted.gpg" "$apps_dir/apt-keyrings/trusted.gpg" 2>/dev/null || true
    fi

    {
        echo "created=$(date --iso-8601=seconds)"
        echo "root=$root"
        echo "user=$SOURCE_USER"
        echo "host=$SOURCE_HOST"
    } > "$apps_dir/app-backup-info.txt"

    if target_has_cmd rpm; then
        if [[ "$root" == / ]]; then
            rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' > "$apps_dir/rpm-installed.tsv"
            zypper --xmlout packages --userinstalled > "$apps_dir/rpm-user.xml" || true
        else
            chroot "$root" rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' > "$apps_dir/rpm-installed.tsv"
        fi
    fi
    if [[ "$root" == / ]] && has_cmd flatpak; then
        runuser -u "$SOURCE_USER" -- flatpak list --user --app --columns=application,branch,origin,installation >> "$apps_dir/flatpak-apps.tsv" 2>/dev/null || true
    fi
    if [[ -s "$apps_dir/rpm-user.xml" ]]; then
        python3 - "$apps_dir/rpm-user.xml" "$apps_dir/rpm-user.txt" <<'RPM_PY'
import sys, xml.etree.ElementTree as ET
try:
    names=sorted({x.get('name') for x in ET.parse(sys.argv[1]).iter() if x.tag in ('solvable','package') and x.get('name')})
    open(sys.argv[2],'w').write('\n'.join(names)+'\n')
except (OSError, ET.ParseError) as e:
    print('RPM-Auswahlliste unvollständig:',e,file=sys.stderr)
RPM_PY
    fi
    info "Programm-Listen erstellt."
}

save_desktop_assets() {
    local assets_dir="$BACKUP_DIR/$DESKTOP_ASSETS_DIR_NAME"
    local root
    root="$(source_root_for_apps)"

    mkdir -p "$assets_dir"

    echo
    info "Sichere systemweite Desktop-Assets ..."
    echo "  System-Root : $root"
    echo "  Ziel        : $assets_dir"
    echo "  Enthält     : /usr/share/themes, /usr/share/icons, /usr/share/backgrounds, /usr/share/fonts"

    if [[ -d "$root/usr/share/themes" ]]; then
        mkdir -p "$assets_dir/usr-share-themes"
        rsync -aHAX --numeric-ids --delete "$root/usr/share/themes/" "$assets_dir/usr-share-themes/" || warn "Themes konnten nicht vollständig gesichert werden."
    fi

    if [[ -d "$root/usr/share/icons" ]]; then
        mkdir -p "$assets_dir/usr-share-icons"
        rsync -aHAX --numeric-ids --delete "$root/usr/share/icons/" "$assets_dir/usr-share-icons/" || warn "Icons konnten nicht vollständig gesichert werden."
    fi

    if [[ -d "$root/usr/share/backgrounds" ]]; then
        mkdir -p "$assets_dir/usr-share-backgrounds"
        rsync -aHAX --numeric-ids --delete "$root/usr/share/backgrounds/" "$assets_dir/usr-share-backgrounds/" || warn "Hintergründe konnten nicht vollständig gesichert werden."
    fi

    if [[ -d "$root/usr/share/fonts" ]]; then
        mkdir -p "$assets_dir/usr-share-fonts"
        rsync -aHAX --numeric-ids --delete "$root/usr/share/fonts/" "$assets_dir/usr-share-fonts/" || warn "Schriften konnten nicht vollständig gesichert werden."
    fi

    {
        echo "created=$(date --iso-8601=seconds)"
        echo "root=$root"
        echo "user=$SOURCE_USER"
        echo "host=$SOURCE_HOST"
    } > "$assets_dir/desktop-assets-info.txt"

    info "Desktop-Assets gesichert."
}

restore_desktop_assets() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_desktop_assets systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local assets_dir="$BACKUP_DIR/$DESKTOP_ASSETS_DIR_NAME"
    local rc=0

    [[ -d "$assets_dir" ]] || {
        warn "Keine systemweiten Desktop-Assets im Backup gefunden."
        warn "Themes im Home wie ~/.themes, ~/.icons und ~/.local/share/themes werden trotzdem über Home-Restore wiederhergestellt."
        return 0
    }

    echo
    warn "Systemweite Themes/Icons/Hintergründe/Schriften werden nach /usr/share zurückgespielt."
    warn "Das ist nötig, wenn z.B. eine XP-Optik unter /usr/share/themes statt im Home lag."
    echo

    mkdir -p /usr/share/themes /usr/share/icons /usr/share/backgrounds /usr/share/fonts

    if [[ -d "$assets_dir/usr-share-themes" ]]; then
        info "Stelle /usr/share/themes wieder her ..."
        rsync -aHAX --numeric-ids "$assets_dir/usr-share-themes/" /usr/share/themes/ || rc=1
    fi

    if [[ -d "$assets_dir/usr-share-icons" ]]; then
        info "Stelle /usr/share/icons wieder her ..."
        rsync -aHAX --numeric-ids "$assets_dir/usr-share-icons/" /usr/share/icons/ || rc=1
    fi

    if [[ -d "$assets_dir/usr-share-backgrounds" ]]; then
        info "Stelle /usr/share/backgrounds wieder her ..."
        rsync -aHAX --numeric-ids "$assets_dir/usr-share-backgrounds/" /usr/share/backgrounds/ || rc=1
    fi

    if [[ -d "$assets_dir/usr-share-fonts" ]]; then
        info "Stelle /usr/share/fonts wieder her ..."
        rsync -aHAX --numeric-ids "$assets_dir/usr-share-fonts/" /usr/share/fonts/ || rc=1
    fi

    if has_cmd fc-cache; then
        info "Aktualisiere Font-Cache ..."
        fc-cache -f || true
    fi

    if has_cmd gtk-update-icon-cache; then
        find /usr/share/icons -mindepth 1 -maxdepth 1 -type d | while read -r icon_dir; do
            [[ -f "$icon_dir/index.theme" ]] || continue
            gtk-update-icon-cache -f "$icon_dir" >/dev/null 2>&1 || true
        done
    fi

    if [[ "$rc" -eq 0 ]]; then
        info "Systemweite Desktop-Assets wiederhergestellt."
    else
        warn "Einige Desktop-Assets konnten nicht vollständig wiederhergestellt werden."
    fi
}


restore_programs_menu() {
    echo
    echo "Programm-Wiederherstellung:"
    echo "  1) VOLLSTAENDIG: alle im Original installierten APT-Pakete + Flatpaks"
    echo "  2) Sicher: nur manuell installierte APT-Pakete + Flatpaks"
    echo "  3) Nur Flatpak-Apps installieren"
    echo "  4) Überspringen"
    echo
}

install_flatpak_apps_from_backup() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local appfile="$apps_dir/flatpak-apps.tsv"
    local remotefile="$apps_dir/flatpak-remotes.txt"
    local app branch origin installation
    local root

    root="$(source_root_for_apps)"

    [[ -f "$appfile" ]] || { warn "Keine Flatpak-App-Liste gefunden."; return 0; }

    create_flatpak_after_first_boot_script

    echo
    info "Flatpak-Wiederherstellung"
    echo "  Zielroot : $root"
    echo "  Live     : $LIVE_MODE"

    if ! target_flatpak_available; then
        warn "flatpak ist im Zielsystem nicht installiert. Installiere flatpak im Zielsystem per APT/chroot."
        target_fix_cdrom_repositories
        preseed_common_eulas
        recover_interrupted_target_dpkg
        target_apt_update || warn "apt update im Zielsystem meldete Fehler. Versuche flatpak-Installation trotzdem."
        target_apt_install flatpak || {
            warn "flatpak konnte im Zielsystem nicht installiert werden."
            local report_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
            mkdir -p "$report_dir"
            cp -a "$appfile" "$report_dir/missing-flatpaks-to-install-after-first-boot.tsv" 2>/dev/null || true
            warn "Liste gespeichert: $report_dir/missing-flatpaks-to-install-after-first-boot.tsv"
            return 0
        }
    fi

    if [[ -s "$remotefile" ]]; then
        info "Füge Flathub im Zielsystem hinzu ..."
        target_flatpak_remote_add_flathub || warn "Flathub konnte im Zielsystem nicht hinzugefügt werden."
    else
        target_flatpak_remote_add_flathub || true
    fi

    info "Installiere Flatpak-Apps im Zielsystem ..."
    while IFS=$'\t' read -r app branch origin installation; do
        [[ -n "$app" ]] || continue
        [[ "$app" == "Application ID" ]] && continue

        origin="${origin:-flathub}"
        branch="${branch:-stable}"

        if target_flatpak_app_installed "$app"; then
            info "Flatpak bereits im Zielsystem installiert, überspringe: $app"
            continue
        fi

        info "Flatpak ins Zielsystem: $app ($origin/$branch)"
        target_flatpak_install_app "$origin" "$app" || {
            warn "Flatpak konnte im Zielsystem nicht installiert werden: $app"
            report_failed_app "Flatpak" "$app" "Flatpak-Installation im Zielsystem fehlgeschlagen"
        }
    done < "$appfile"

    info "Flatpak-Wiederherstellung im Zielsystem abgeschlossen."
    warn "Falls einzelne Flatpaks im chroot wegen GPG/OSTree/DBus scheiterten: Desktop-Skript nach erstem Boot ausführen."
    warn "Flatpak-Nachinstallation kann nach erstem Boot über install-flatpaks-nach-erster-anmeldung.sh abgeschlossen werden."
}

target_apt_fix_broken() {
    local root
    root="$(source_root_for_apps)"

    info "Repariere ggf. unterbrochene APT/dpkg-Zustaende im Zielsystem ..."
    target_dpkg_configure_a || true

    if [[ "$root" == "/" ]]; then
        DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a APT_LISTCHANGES_FRONTEND=none \
            apt-get -f install -y \
            -o Dpkg::Options::="--force-confold" \
            -o Dpkg::Options::="--force-confdef" || true
    else
        prepare_target_chroot
        chroot "$root" env \
            DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a APT_LISTCHANGES_FRONTEND=none \
            apt-get -f install -y \
            -o Dpkg::Options::="--force-confold" \
            -o Dpkg::Options::="--force-confdef" || true
    fi

    target_dpkg_configure_a || true
}

read_os_release_value() {
    local file="$1" key="$2"
    [[ -f "$file" ]] || return 1
    sed -nE "s/^${key}=//p" "$file" | tail -n1 | sed 's/^\"//;s/\"$//'
}

restore_original_apt_sources_if_compatible() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local root src_os="$apps_dir/os-release" dst_os
    local src_id src_ver src_code dst_id dst_ver dst_code answer
    root="$(source_root_for_apps)"
    dst_os="$root/etc/os-release"

    [[ -f "$src_os" && -f "$dst_os" ]] || return 0
    src_id="$(read_os_release_value "$src_os" ID || true)"
    src_ver="$(read_os_release_value "$src_os" VERSION_ID || true)"
    src_code="$(read_os_release_value "$src_os" VERSION_CODENAME || true)"
    dst_id="$(read_os_release_value "$dst_os" ID || true)"
    dst_ver="$(read_os_release_value "$dst_os" VERSION_ID || true)"
    dst_code="$(read_os_release_value "$dst_os" VERSION_CODENAME || true)"

    if [[ "$src_id" != "$dst_id" || -z "$src_id" ]]; then
        warn "APT-Quellen werden nicht uebernommen: Quelle=$src_id Ziel=$dst_id"
        return 0
    fi

    if [[ -n "$src_code" && -n "$dst_code" && "$src_code" != "$dst_code" ]]; then
        warn "APT-Quellen werden nicht automatisch uebernommen: Codename Quelle=$src_code Ziel=$dst_code"
        return 0
    fi

    echo
    info "Quell- und Zielsystem passen fuer APT-Quellen: $src_id ${src_ver:-?} ${src_code:-}"
    read -r -p "Gesicherte APT-Quellen und Schluessel des Originalsystems zusaetzlich einspielen? [ja/NEIN]: " answer
    [[ "$answer" == "ja" ]] || return 0

    mkdir -p "$root/etc/apt/sources.list.d" "$root/etc/apt/keyrings" "$root/etc/apt/trusted.gpg.d"
    if [[ -d "$apps_dir/apt-sources.list.d" ]]; then
        cp -a "$apps_dir/apt-sources.list.d/." "$root/etc/apt/sources.list.d/" || true
    fi
    # Haupt-sources.list nur bei exakt gleicher ID + Codename/Version ersetzen.
    if [[ -f "$apps_dir/sources.list" && "$src_id" == "$dst_id" && ( -z "$src_code" || "$src_code" == "$dst_code" ) ]]; then
        cp -a "$root/etc/apt/sources.list" "$root/etc/apt/sources.list.pre-backup-restore-${DATE_STR}" 2>/dev/null || true
        cp -a "$apps_dir/sources.list" "$root/etc/apt/sources.list" || true
    fi
    [[ -d "$apps_dir/apt-keyrings/etc-apt-keyrings" ]] && cp -a "$apps_dir/apt-keyrings/etc-apt-keyrings/." "$root/etc/apt/keyrings/" 2>/dev/null || true
    [[ -d "$apps_dir/apt-keyrings/trusted.gpg.d" ]] && cp -a "$apps_dir/apt-keyrings/trusted.gpg.d/." "$root/etc/apt/trusted.gpg.d/" 2>/dev/null || true
    [[ -f "$apps_dir/apt-keyrings/trusted.gpg" ]] && cp -a "$apps_dir/apt-keyrings/trusted.gpg" "$root/etc/apt/trusted.gpg" 2>/dev/null || true

    target_fix_cdrom_repositories
    info "Gesicherte APT-Quellen/Schluessel eingespielt."
}

install_all_apt_packages_from_backup() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local pkgfile="$apps_dir/dpkg-installed.tsv"
    local allpkgs available missing unavailable pkg answer root
    local total_count=0 installed_count=0 missing_count=0 unavailable_count=0 after_missing=0

    [[ -f "$pkgfile" ]] || { warn "Keine komplette dpkg-Paketliste gefunden: $pkgfile"; return 0; }

    root="$(source_root_for_apps)"
    allpkgs="$(mktemp)"
    available="$(mktemp)"
    missing="$(mktemp)"
    unavailable="$(mktemp)"
    trap 'rm -f "$allpkgs" "$available" "$missing" "$unavailable"' RETURN

    # binary:Package kann Architekturqualifier enthalten. Fuer APT ist das gueltig.
    awk -F '\t' 'NF && $1 ~ /^[A-Za-z0-9][A-Za-z0-9.+_-]*(:[A-Za-z0-9_-]+)?$/ {print $1}' "$pkgfile" | sort -u > "$allpkgs"
    total_count=$(wc -l < "$allpkgs")

    echo
    warn "VOLLSTAENDIGER APT-RESTORE: Ziel ist der Paketbestand des Originalsystems."
    warn "Dabei werden auch Bibliotheken, Laufzeitpakete, Desktop-Komponenten, Treiber und Systempakete installiert, sofern fuer das Ziel verfuegbar."
    warn "Exakte alte Paketversionen werden NICHT erzwungen; APT installiert die aktuell verfuegbaren Versionen der Ziel-Repositories."
    echo "  Pakete im Originalsystem: $total_count"

    restore_original_apt_sources_if_compatible
    target_fix_cdrom_repositories
    preseed_common_eulas
    recover_interrupted_target_dpkg
    target_apt_fix_broken

    info "Aktualisiere Paketlisten im Zielsystem ..."
    target_apt_update || warn "apt update meldete Fehler; es wird mit den verfuegbaren Paketlisten weitergearbeitet."

    info "Pruefe Paketverfuegbarkeit und bereits installierten Bestand ..."
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        if target_package_installed "$pkg"; then
            ((installed_count++)) || true
            printf '%s\n' "$pkg" >> "$available"
            continue
        fi
        if target_apt_cache_show "$pkg"; then
            printf '%s\n' "$pkg" >> "$available"
            printf '%s\n' "$pkg" >> "$missing"
            ((missing_count++)) || true
        else
            printf '%s\n' "$pkg" >> "$unavailable"
            ((unavailable_count++)) || true
            report_failed_app "APT" "$pkg" "Im Original installiert, aber in den Ziel-Repositories nicht verfuegbar"
        fi
    done < "$allpkgs"

    echo
    info "Kompletter Paketabgleich:"
    echo "  Original gesamt       : $total_count"
    echo "  Bereits installiert   : $installed_count"
    echo "  Noch zu installieren  : $missing_count"
    echo "  Nicht verfuegbar      : $unavailable_count"

    if (( unavailable_count > 0 )); then
        local report_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
        mkdir -p "$report_dir"
        cp -f "$unavailable" "$report_dir/apt-original-nicht-verfuegbar.txt" 2>/dev/null || true
        warn "Nicht verfuegbare Originalpakete: $report_dir/apt-original-nicht-verfuegbar.txt"
    fi

    (( missing_count > 0 )) || { info "Alle verfuegbaren Originalpakete sind bereits installiert."; return 0; }

    echo
    read -r -p "Jetzt alle $missing_count fehlenden verfuegbaren Originalpakete in EINER APT-Transaktion installieren? [ja/NEIN]: " answer
    [[ "$answer" == "ja" ]] || { info "Vollstaendiger APT-Restore uebersprungen."; return 0; }

    mapfile -t _full_apt_pkgs < "$missing"
    info "Starte gemeinsame APT-Installation fuer ${#_full_apt_pkgs[@]} Pakete ..."
    if target_apt_install "${_full_apt_pkgs[@]}"; then
        info "APT-Gesamttransaktion abgeschlossen."
    else
        warn "APT-Gesamttransaktion meldete einen Fehler. Reparatur wird versucht, danach werden Restpakete erneut geprueft."
        target_apt_fix_broken
    fi

    # Zweiter Durchlauf: nur noch wirklich fehlende Pakete in moderaten Bloecken installieren.
    : > "$missing"
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        target_package_installed "$pkg" || printf '%s\n' "$pkg" >> "$missing"
    done < "$available"
    after_missing=$(wc -l < "$missing")

    if (( after_missing > 0 )); then
        warn "Nach der Gesamttransaktion fehlen noch $after_missing Paket(e). Versuche Bloecke zu je 50 Paketen."
        mapfile -t _remaining_pkgs < "$missing"
        local i chunk=( )
        for ((i=0; i<${#_remaining_pkgs[@]}; i+=50)); do
            chunk=("${_remaining_pkgs[@]:i:50}")
            target_apt_install "${chunk[@]}" || {
                warn "Ein Paketblock konnte nicht vollstaendig installiert werden; dpkg/APT wird repariert."
                target_apt_fix_broken
            }
        done
    fi

    target_apt_fix_broken

    local final_missing="$BACKUP_DIR/$REPORTS_DIR_NAME/apt-original-nach-restore-fehlend.txt"
    mkdir -p "$BACKUP_DIR/$REPORTS_DIR_NAME"
    : > "$final_missing"
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        if ! target_package_installed "$pkg"; then
            printf '%s\n' "$pkg" >> "$final_missing"
            report_failed_app "APT" "$pkg" "Nach vollstaendigem Paketrestore weiterhin nicht installiert"
        fi
    done < "$allpkgs"

    if [[ -s "$final_missing" ]]; then
        warn "Einige Originalpakete fehlen weiterhin. Liste: $final_missing"
    else
        rm -f "$final_missing"
        info "Paketabgleich erfolgreich: alle im Backup erfassten und auf dem Ziel installierbaren Originalpakete sind vorhanden."
    fi
}

install_apt_manual_from_backup() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local pkgfile="$apps_dir/apt-manual.txt"
    local filtered
    local pkg
    local ok_count=0
    local fail_count=0
    local skip_count=0

    [[ -f "$pkgfile" ]] || { warn "Keine APT-Manual-Liste gefunden."; return 0; }

    warn "APT-Restore installiert Paketnamen aus apt-manual.txt ins Zielsystem."
    warn "Kernel, NVIDIA/CUDA, Firmware, Live-/Installer- und unpassende Mint/LMDE-Pakete werden gefiltert."
    warn "PPAs/Ubuntu-spezifische Quellen werden absichtlich NICHT automatisch übernommen."

    target_fix_cdrom_repositories
    preseed_common_eulas
    recover_interrupted_target_dpkg

    info "Aktualisiere Paketlisten im Zielsystem ..."
    target_apt_update || warn "apt update im Zielsystem meldete Fehler. Paketfilter läuft trotzdem mit vorhandenen Paketlisten weiter."

    filtered="$(mktemp)"
    info "Filtere problematische oder nicht verfügbare Pakete ..."
    filter_problematic_packages "$pkgfile" "$filtered"

    if [[ ! -s "$filtered" ]]; then
        warn "Keine installierbaren APT-Pakete aus der Liste gefunden."
        rm -f "$filtered"
        return 0
    fi

    echo
    info "Installiere gefilterte APT-Pakete einzeln im Zielsystem ..."
    warn "Keine xargs-Funktion mehr: target_apt_install wird direkt pro Paket aufgerufen."
    echo

    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue

        if target_package_installed "$pkg"; then
            info "Bereits installiert, überspringe: $pkg"
            ((skip_count++)) || true
            continue
        fi

        info "APT installiere ins Zielsystem: $pkg"

        if target_apt_install "$pkg"; then
            if target_package_installed "$pkg"; then
                info "Installiert: $pkg"
                ((ok_count++)) || true
            else
                warn "APT meldete Erfolg, Paket wirkt aber nicht installiert: $pkg"
                report_failed_app "APT" "$pkg" "APT meldete Erfolg, Paket danach nicht installiert"
                ((fail_count++)) || true
            fi
        else
            warn "APT-Installation fehlgeschlagen: $pkg"
            report_failed_app "APT" "$pkg" "Installation fehlgeschlagen"
            ((fail_count++)) || true
        fi
    done < "$filtered"

    echo
    info "APT-Restore Zusammenfassung:"
    echo "  Installiert   : $ok_count"
    echo "  Übersprungen  : $skip_count"
    echo "  Fehlgeschlagen: $fail_count"

    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        if ! target_package_installed "$pkg"; then
            report_failed_app "APT" "$pkg" "Nachprüfung: Paket ist nach Restore nicht installiert"
        fi
    done < "$filtered"

    if grep -qx "keepassxc" "$pkgfile"; then
        if ! target_package_installed keepassxc && ! target_has_cmd keepassxc; then
            warn "KeePassXC wurde per APT nicht installiert. Versuche Flatpak-Fallback im Zielsystem ..."
            if ! target_flatpak_available; then
                target_fix_cdrom_repositories
                target_apt_update || true
                target_apt_install flatpak || true
            fi
            target_flatpak_remote_add_flathub || true
            target_flatpak_install_app flathub org.keepassxc.KeePassXC || {
                warn "KeePassXC Flatpak-Fallback im Zielsystem fehlgeschlagen."
                report_failed_app "Flatpak" "org.keepassxc.KeePassXC" "KeePassXC Flatpak-Fallback fehlgeschlagen"
            }
        fi
    fi

    rm -f "$filtered"
}

check_expected_photo_apps() {
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local pkgfile="$apps_dir/apt-manual.txt"
    local pkg

    [[ -f "$pkgfile" ]] || return 0

    for pkg in darktable rawtherapee digikam; do
        if grep -qx "$pkg" "$pkgfile"; then
            if ! target_package_installed "$pkg"; then
                warn "Wichtige Foto-App aus apt-manual.txt fehlt nach Restore: $pkg"
                report_failed_app "APT" "$pkg" "War in apt-manual.txt, ist nach Restore aber nicht installiert"
            fi
        fi
    done
}


do_program_restore() {
    if v19_is_suse; then v19_program_restore; return $?; fi
    local choice

    setup_failed_apps_report
    save_manual_deb_apps_report
    [[ -d "$BACKUP_DIR/$APPS_DIR_NAME" ]] || { warn "Keine Programm-Listen im Backup gefunden."; return 0; }

    prepare_target_chroot
    trap cleanup_target_chroot RETURN

    restore_programs_menu
    read -r -p "Auswahl [1-3]: " choice

    case "$choice" in
        1)
            install_all_apt_packages_from_backup
            install_flatpak_apps_from_backup
            ;;
        2)
            install_apt_manual_from_backup
            install_flatpak_apps_from_backup
            ;;
        3)
            install_flatpak_apps_from_backup
            ;;
        4)
            info "Programm-Wiederherstellung übersprungen."
            ;;
        *)
            die "Ungültige Auswahl."
            ;;
    esac
    check_expected_photo_apps

    if [[ -n "${FAILED_APPS_REPORT:-}" && -f "$FAILED_APPS_REPORT" ]]; then
        echo
        info "Liste nicht installierbarer/problematischer Apps:"
        echo "  $FAILED_APPS_REPORT"
    fi

}

do_full_restore() {
    if v19_is_suse; then v19_migrate; return $?; fi
    echo
    warn "Komplett-Wiederherstellung bedeutet: Programme installieren + Home zurückspielen."
    warn "Zwischen Mint 22.3 und LMDE 7 werden nicht alle APT-Pakete identisch verfügbar sein."
    warn "Für laufendes Ein-Benutzer-System ist Menüpunkt 8 sicherer als dieser Vollrestore."
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Komplett-Wiederherstellung abgebrochen."

    do_program_restore
    restore_desktop_assets
    do_restore
    create_restore_report
}

do_backup() {
    local source_dir="$SOURCE_HOME/" target_dir="$BACKUP_DIR/$FILES_DIR_NAME/" rsync_rc=0
    local partial_opts=()
    [[ -n "${RSYNC_PARTIAL_DIR:-}" && -d "${RSYNC_PARTIAL_DIR:-/nonexistent}" ]] && partial_opts=(--partial "--partial-dir=$RSYNC_PARTIAL_DIR")
    [[ -d "$SOURCE_HOME" ]] || die "Home-Verzeichnis nicht gefunden: $SOURCE_HOME"
    [[ "$USB_MOUNTPOINT" != "$SOURCE_HOME"* ]] || die "Ziel liegt im Home-Verzeichnis. Abbruch wegen Rekursion."
    mkdir -p "$target_dir"
    if filesystem_supports_unix_perms; then
        chmod 700 "$target_dir" 2>/dev/null || true
        chown "$SOURCE_UID:$SOURCE_GID" "$target_dir" 2>/dev/null || true
    fi
    need_cmd gpg
    filesystem_supports_unix_perms || die "V20 benötigt Unix-Dateirechte auf dem Backupmedium."
    umask 077
    chmod 700 "$BACKUP_DIR"
    write_metadata
    save_program_lists
    save_desktop_assets
    save_identity_and_hardware_report
    save_full_desktop_state
    save_systemd_mounts_and_acls
    v19_svl backup || die "SVL-Konfiguration konnte nicht vollständig gesichert werden."
    v20_backup || die "V20-Komponentenbackup unvollständig."
    echo
    info "Starte Backup"
    echo "  Quelle : $source_dir"
    echo "  Ziel   : $target_dir"
    echo "  Modus  : $BACKUP_MODE"
    echo "  Live   : $LIVE_MODE"
    echo
    set +e
    rsync "${RSYNC_COMMON_OPTS[@]}" "${partial_opts[@]}" --delete "${EFFECTIVE_EXCLUDES[@]}" "$source_dir" "$target_dir"
    rsync_rc=$?
    set -e
    sync
    case "$rsync_rc" in
        0) info "Backup abgeschlossen." ;;
        23) warn "Backup weitgehend abgeschlossen, aber einzelne Dateien/Attribute konnten nicht kopiert werden. rsync code 23." ;;
        *) die "rsync fehlgeschlagen mit Fehlercode $rsync_rc" ;;
    esac
    show_backup_info
    echo
    echo "Logfiles:"
    echo "  Lokal : $LOCAL_LOG_FILE"
    echo "  USB   : $USB_LOG_FILE"
}

restore_target_menu() {
    echo
    echo "Restore-Ziel:"
    echo "  [1] restore-test im Quell-Home"
    echo "  [2] direkt ins Quell-Home"
    echo "  [3] Abbrechen"
    echo
}

do_restore() {
    if v19_is_suse; then v19_home_restore; return $?; fi
    local source_dir="$BACKUP_DIR/$FILES_DIR_NAME/" target_choice target_dir rsync_rc=0
    local partial_opts=()
    [[ -n "${RSYNC_PARTIAL_DIR:-}" && -d "${RSYNC_PARTIAL_DIR:-/nonexistent}" ]] && partial_opts=(--partial "--partial-dir=$RSYNC_PARTIAL_DIR")
    [[ -d "$source_dir" ]] || die "Kein Backup gefunden unter: $source_dir"
    [[ -d "$SOURCE_HOME" ]] || die "Ziel-Home nicht gefunden: $SOURCE_HOME"

    show_backup_info
    restore_target_menu
    read -r -p "Auswahl: " target_choice

    case "$target_choice" in
        1)
            target_dir="$SOURCE_HOME/restore-test/"
            mkdir -p "$target_dir"
            ;;
        2)
            target_dir="$SOURCE_HOME/"
            ;;
        3)
            info "Restore abgebrochen."
            return 0
            ;;
        *)
            die "Ungültige Auswahl."
            ;;
    esac

    ensure_path_writable_for_restore "$target_dir"

    echo
    info "Restore"
    echo "  Quelle : $source_dir"
    echo "  Ziel   : $target_dir"
    echo

    warn "Restore-Ausschlüsse aktiv:"
    printf '  %s\n' "${RESTORE_EXCLUDES[@]}"
    echo

    if [[ "$target_dir" == "$SOURCE_HOME/" ]]; then
        warn "Direkt-Restore ins Home sollte NICHT in einer laufenden Sitzung dieses Benutzers passieren."
        warn "Besser: Menüpunkt 8, Live-System, root-Konsole oder anderer Admin-Benutzer."
        read -r -p "Direkt ins Home wiederherstellen und mit --delete spiegeln? [ja/NEIN]: " confirm_home
        [[ "$confirm_home" == "ja" ]] || die "Restore abgebrochen."

        set +e
        rsync "${RSYNC_RESTORE_OPTS[@]}" "${partial_opts[@]}" \
            --delete \
            --delete-excluded \
            --force \
            "${RESTORE_EXCLUDES[@]}" \
            "$source_dir" "$target_dir"
        rsync_rc=$?
        set -e
    else
        read -r -p "Nach restore-test wiederherstellen? [ja/NEIN]: " confirm_test
        [[ "$confirm_test" == "ja" ]] || die "Restore abgebrochen."

        set +e
        rsync "${RSYNC_RESTORE_OPTS[@]}" "${partial_opts[@]}" \
            --force \
            "${RESTORE_EXCLUDES[@]}" \
            "$source_dir" "$target_dir"
        rsync_rc=$?
        set -e
    fi

    case "$rsync_rc" in
        0)
            info "Restore rsync abgeschlossen."
            ;;
        23|24)
            warn "Restore weitgehend abgeschlossen, aber einzelne Dateien konnten nicht kopiert/gelöscht werden. rsync Code: $rsync_rc"
            ;;
        *)
            die "Restore fehlgeschlagen mit rsync Fehlercode $rsync_rc"
            ;;
    esac

    info "Setze Besitz auf $SOURCE_UID:$SOURCE_GID ..."
    safe_chown_tree "$SOURCE_UID:$SOURCE_GID" "$target_dir"

    sync
    info "Restore abgeschlossen."
    echo
    echo "Logfiles:"
    echo "  Lokal : $LOCAL_LOG_FILE"
    echo "  USB   : $USB_LOG_FILE"
}

do_live_system_restore() {
    v20_home; return $?
    if v19_is_suse; then v19_home_restore; return $?; fi
    local source_dir="$BACKUP_DIR/$FILES_DIR_NAME/"
    local target_dir="$SOURCE_HOME/"
    local rsync_rc=0
    local partial_opts=()
    [[ -n "${RSYNC_PARTIAL_DIR:-}" && -d "${RSYNC_PARTIAL_DIR:-/nonexistent}" ]] && partial_opts=(--partial "--partial-dir=$RSYNC_PARTIAL_DIR")

    [[ -d "$source_dir" ]] || die "Kein Backup gefunden unter: $source_dir"
    [[ -d "$target_dir" ]] || die "Home-Verzeichnis nicht gefunden: $target_dir"

    echo
    warn "RESTORE AUF LAUFENDES SYSTEM"
    warn "Geeignet, wenn nur ein Benutzer existiert und die grafische Sitzung läuft."
    warn "Es wird bewusst KEIN --delete verwendet."
    warn "Aktive Sitzungs-, Lock-, Keyring-, Browser- und Display-Dateien werden ausgelassen."
    warn "Dieser Modus ist sicherer, aber kein bitgenauer Vollrestore."
    echo

    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    ensure_path_writable_for_restore "$target_dir"

    echo
    info "Aktive Live-Restore-Ausschlüsse:"
    printf '  %s\n' "${LIVE_RESTORE_EXCLUDES[@]}"
    echo

    info "Starte sicheren Live-Restore ..."
    echo "  Quelle : $source_dir"
    echo "  Ziel   : $target_dir"
    echo

    set +e
    rsync "${RSYNC_RESTORE_OPTS[@]}" "${partial_opts[@]}" \
        --update \
        --inplace \
        --force \
        "${LIVE_RESTORE_EXCLUDES[@]}" \
        "$source_dir" "$target_dir"
    rsync_rc=$?
    set -e

    case "$rsync_rc" in
        0)
            info "Live-Restore abgeschlossen."
            ;;
        23|24)
            warn "Live-Restore weitgehend erfolgreich. Einzelne Runtime-Dateien wurden übersprungen. rsync Code: $rsync_rc"
            ;;
        *)
            die "Live-Restore fehlgeschlagen. rsync Fehlercode: $rsync_rc"
            ;;
    esac

    echo
    info "Korrigiere Besitzrechte ..."
    safe_chown_tree "$SOURCE_UID:$SOURCE_GID" "$target_dir"

    sync

    echo
    warn "Empfohlen: danach rebooten oder komplett ab- und wieder anmelden."
    echo
    echo "Logfiles:"
    echo "  Lokal : $LOCAL_LOG_FILE"
    echo "  USB   : $USB_LOG_FILE"
}

do_desktop_app_settings_restore() {
    v20_desktop; return $?
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local source_dir="$BACKUP_DIR/$FILES_DIR_NAME/"
    local target_dir="$SOURCE_HOME/"
    local rsync_rc=0
    local partial_opts=()
    [[ -n "${RSYNC_PARTIAL_DIR:-}" && -d "${RSYNC_PARTIAL_DIR:-/nonexistent}" ]] && partial_opts=(--partial "--partial-dir=$RSYNC_PARTIAL_DIR")

    [[ -d "$source_dir" ]] || die "Kein Backup gefunden unter: $source_dir"
    [[ -d "$target_dir" ]] || die "Home-Verzeichnis nicht gefunden: $target_dir"

    echo
    warn "DESKTOP-/APP-EINSTELLUNGEN VOLLSTÄNDIG WIEDERHERSTELLEN"
    warn "Ziel: möglichst 1:1 auf anderem PC oder nach Neuinstallation."
    warn "Dabei werden bewusst auch empfindliche Desktop- und App-Daten zurückgespielt:"
    echo "  - ~/.config inklusive dconf/Cinnamon/App-Einstellungen"
    echo "  - ~/.local/share inklusive Keyrings, Appdaten, Icons, Hintergrundverweise"
    echo "  - ~/.var/app Flatpak-Appdaten"
    echo "  - Browser-/Mailprofile, Themes, Icons, KeePassXC-Konfiguration"
    echo "  - systemweite Themes/Icons/Hintergründe/Schriften aus /usr/share"
    echo
    warn "NICHT empfohlen in laufender grafischer Sitzung desselben Benutzers."
    warn "Optimal: Live-System oder Recovery/root-Konsole, Zielbenutzer abgemeldet."
    warn "Wenn du es trotzdem laufend machst, danach zwingend rebooten."
    echo

    read -r -p "Vollständige Desktop-/App-Einstellungen wirklich zurückspielen? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    ensure_path_writable_for_restore "$target_dir"

    restore_desktop_assets

    echo
    info "Starte vollständigen Desktop-/App-Restore ..."
    echo "  Quelle : $source_dir"
    echo "  Ziel   : $target_dir"
    echo
    warn "Kein --delete: vorhandene neue Dateien bleiben erhalten."
    warn "Lock-/Socket-/Cache-Dateien werden weiterhin ausgelassen."

    local DESKTOP_FULL_EXCLUDES=(
        --exclude=.cache/
        --exclude=.gvfs
        --exclude=.gvfs/
        --exclude=.dbus/
        --exclude=.Xauthority
        --exclude=.ICEauthority
        --exclude=.xsession-errors
        --exclude=.xsession-errors.old
        --exclude=.xsession-errors*
        --exclude=.local/share/Trash/

        --exclude=.mozilla/firefox/*/lock
        --exclude=.mozilla/firefox/*/.parentlock
        --exclude=.mozilla/firefox/*/startupCache/

        --exclude=.config/google-chrome/Singleton*
        --exclude=.config/chromium/Singleton*
        --exclude=.config/BraveSoftware/Brave-Browser/Singleton*

        --exclude=.local/share/keyrings/*.lock
        --exclude=.config/pulse/*-runtime
        --exclude=.steam/steam.pid
    )

    set +e
    rsync "${RSYNC_RESTORE_OPTS[@]}" "${partial_opts[@]}" \
        --force \
        "${DESKTOP_FULL_EXCLUDES[@]}" \
        "$source_dir" "$target_dir"
    rsync_rc=$?
    set -e

    case "$rsync_rc" in
        0)
            info "Desktop-/App-Restore abgeschlossen."
            ;;
        23|24)
            warn "Desktop-/App-Restore weitgehend erfolgreich. Einzelne Runtime-Dateien wurden übersprungen. rsync Code: $rsync_rc"
            ;;
        *)
            die "Desktop-/App-Restore fehlgeschlagen. rsync Fehlercode: $rsync_rc"
            ;;
    esac

    info "Setze Besitz auf $SOURCE_UID:$SOURCE_GID ..."
    safe_chown_tree "$SOURCE_UID:$SOURCE_GID" "$target_dir"

    sync

    echo
    warn "Jetzt rebooten. Viele Einstellungen werden erst nach Neuanmeldung aktiv."
    echo "Logfiles:"
    echo "  Lokal : $LOCAL_LOG_FILE"
    echo "  USB   : $USB_LOG_FILE"
}


backup_path_from_root() {
    local root="$1"
    local abs_path="$2"
    local dest="$3"
    local label="$4"

    if [[ -e "$root$abs_path" ]]; then
        mkdir -p "$dest"
        info "Sichere $label: $root$abs_path"
        rsync -aHAX --numeric-ids "$root$abs_path" "$dest/" || warn "Nicht vollständig gesichert: $abs_path"
    else
        warn "Nicht vorhanden, überspringe: $root$abs_path"
    fi
}

restore_path_to_root() {
    local src_parent="$1"
    local name="$2"
    local dest_parent="$3"
    local label="$4"

    if [[ -e "$src_parent/$name" ]]; then
        mkdir -p "$dest_parent"
        info "Stelle $label wieder her: $dest_parent/$name"
        rsync -aHAX --numeric-ids --force "$src_parent/$name" "$dest_parent/" || warn "Nicht vollständig wiederhergestellt: $name"
    else
        warn "Nicht im Backup vorhanden, überspringe: $src_parent/$name"
    fi
}

save_identity_and_hardware_report() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local root
    root="$(source_root_for_apps)"

    mkdir -p "$reports_dir"

    info "Erstelle Benutzer-/Hardware-/Systembericht ..."

    {
        echo "created=$(date --iso-8601=seconds)"
        echo "source_root=$root"
        echo "source_user=$SOURCE_USER"
        echo "source_uid=$SOURCE_UID"
        echo "source_gid=$SOURCE_GID"
        echo "source_group=$SOURCE_GROUP"
        echo "source_host=$SOURCE_HOST"
        echo
        echo "===== os-release ====="
        [[ -f "$root/etc/os-release" ]] && cat "$root/etc/os-release"
        echo
        echo "===== passwd relevant ====="
        [[ -f "$root/etc/passwd" ]] && awk -F: -v u="$SOURCE_USER" -v uid="$SOURCE_UID" '$1==u || $3==uid {print}' "$root/etc/passwd"
        echo
        echo "===== group relevant ====="
        if [[ -f "$root/etc/group" ]]; then
            awk -F: -v g="$SOURCE_GROUP" -v gid="$SOURCE_GID" -v u="$SOURCE_USER" '
                $1==g || $3==gid {
                    print
                    next
                }
                {
                    n=split($4, members, ",")
                    for (i=1; i<=n; i++) {
                        if (members[i] == u) {
                            print
                            next
                        }
                    }
                }
            ' "$root/etc/group"
        fi
        echo
        echo "===== subuid/subgid ====="
        [[ -f "$root/etc/subuid" ]] && grep -E "^${SOURCE_USER}:" "$root/etc/subuid" || true
        [[ -f "$root/etc/subgid" ]] && grep -E "^${SOURCE_USER}:" "$root/etc/subgid" || true
    } > "$reports_dir/identity-report.txt"

    {
        echo "created=$(date --iso-8601=seconds)"
        echo "host=$(hostname -f 2>/dev/null || hostname)"
        echo "kernel=$(uname -a)"
        echo
        echo "===== lsblk ====="
        lsblk -f 2>/dev/null || true
        echo
        echo "===== fstab ====="
        [[ -f "$root/etc/fstab" ]] && cat "$root/etc/fstab"
        echo
        echo "===== lspci ====="
        lspci -nnk 2>/dev/null || true
        echo
        echo "===== lsusb ====="
        lsusb 2>/dev/null || true
        echo
        echo "===== inxi ====="
        inxi -Fxxxz 2>/dev/null || true
        echo
        echo "===== networkmanager connections ====="
        find "$root/etc/NetworkManager/system-connections" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort || true
        echo
        echo "===== systemd enabled ====="
        systemctl list-unit-files --state=enabled 2>/dev/null || true
        echo
        echo "===== dpkg manual ====="
        apt-mark showmanual 2>/dev/null | sort || true
    } > "$reports_dir/hardware-system-report.txt"

    info "Berichte erstellt: $reports_dir"
}

save_extended_system_config() {
    local cfg_dir="$BACKUP_DIR/$SYSTEM_CONFIG_DIR_NAME"
    local root
    root="$(source_root_for_apps)"
    mkdir -p "$cfg_dir"

    echo
    warn "Sichere erweiterte Systemkonfiguration."
    warn "Enthält sensible Dateien wie SSH-, Netzwerk- und ggf. Dienstkonfigurationen."
    echo

    backup_path_from_root "$root" "/etc" "$cfg_dir" "komplettes /etc"
    backup_path_from_root "$root" "/usr/local" "$cfg_dir" "/usr/local"
    backup_path_from_root "$root" "/opt" "$cfg_dir" "/opt"
    backup_path_from_root "$root" "/var/spool/cron" "$cfg_dir/var-spool" "Cronjobs"
    backup_path_from_root "$root" "/var/lib/flatpak" "$cfg_dir/var-lib" "systemweite Flatpaks"

    save_identity_and_hardware_report
    save_full_desktop_state
    save_systemd_mounts_and_acls
    v19_svl backup || die "SVL-Konfiguration konnte nicht vollständig gesichert werden."
    info "Erweiterte Systemkonfiguration gesichert."
}

restore_extended_system_config() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_extended_system_config systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local cfg_dir="$BACKUP_DIR/$SYSTEM_CONFIG_DIR_NAME"

    [[ -d "$cfg_dir" ]] || die "Keine erweiterte Systemkonfiguration im Backup gefunden: $cfg_dir"

    echo
    warn "ERWEITERTE SYSTEMKONFIGURATION WIEDERHERSTELLEN"
    warn "Das stellt /etc, /usr/local, /opt, Cronjobs und systemweite Flatpaks zurück."
    warn "Sicherheitsbremsen:"
    echo "  - /etc/passwd, /etc/shadow, /etc/group, /etc/gshadow werden NICHT überschrieben"
    echo "  - /etc/fstab und /etc/crypttab werden als .restored abgelegt"
    echo "  - /etc/machine-id wird NICHT überschrieben"
    echo "  - kein --delete"
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    if [[ -d "$cfg_dir/etc" ]]; then
        info "Stelle /etc selektiv wieder her ..."
        rsync -aHAX --numeric-ids --force \
            --exclude=passwd --exclude=passwd- \
            --exclude=shadow --exclude=shadow- \
            --exclude=group --exclude=group- \
            --exclude=gshadow --exclude=gshadow- \
            --exclude=machine-id \
            --exclude=fstab --exclude=crypttab \
            "$cfg_dir/etc/" /etc/ || warn "/etc nicht vollständig wiederhergestellt."

        [[ -f "$cfg_dir/etc/fstab" ]] && cp -a "$cfg_dir/etc/fstab" "/etc/fstab.restored-${DATE_STR}" || true
        [[ -f "$cfg_dir/etc/crypttab" ]] && cp -a "$cfg_dir/etc/crypttab" "/etc/crypttab.restored-${DATE_STR}" || true
    fi

    restore_path_to_root "$cfg_dir" "usr-local" "/usr" "/usr/local"
    restore_path_to_root "$cfg_dir" "opt" "/" "/opt"

    if [[ -d "$cfg_dir/var-spool/cron" ]]; then
        mkdir -p /var/spool
        rsync -aHAX --numeric-ids --force "$cfg_dir/var-spool/cron" /var/spool/ || warn "Cronjobs nicht vollständig wiederhergestellt."
    fi

    if [[ -d "$cfg_dir/var-lib/flatpak" ]]; then
        mkdir -p /var/lib
        rsync -aHAX --numeric-ids --force "$cfg_dir/var-lib/flatpak" /var/lib/ || warn "Systemweite Flatpaks nicht vollständig wiederhergestellt."
    fi

    systemctl daemon-reload 2>/dev/null || true
    info "Erweiterte Systemkonfiguration wiederhergestellt."
    warn "Prüfe danach /etc/fstab.restored-${DATE_STR} manuell, bevor du fstab ersetzt."
}

save_libvirt_vms() {
    local vm_dir="$BACKUP_DIR/$LIBVIRT_DIR_NAME"
    local root
    root="$(source_root_for_apps)"
    mkdir -p "$vm_dir"

    echo
    warn "Sichere KVM/libvirt-Konfiguration und VM-Daten."
    warn "VM-Images können sehr groß sein."
    echo

    backup_path_from_root "$root" "/etc/libvirt" "$vm_dir" "/etc/libvirt"
    backup_path_from_root "$root" "/var/lib/libvirt" "$vm_dir/var-lib" "/var/lib/libvirt"
    backup_path_from_root "$root" "/VM" "$vm_dir" "/VM"

    if has_cmd virsh && [[ "$root" == "/" ]]; then
        mkdir -p "$vm_dir/virsh-dumps"
        virsh list --all --name 2>/dev/null | while read -r vm; do
            [[ -n "$vm" ]] || continue
            virsh dumpxml "$vm" > "$vm_dir/virsh-dumps/${vm}.xml" 2>/dev/null || true
        done
    fi

    info "KVM/libvirt/VMs gesichert."
}

restore_libvirt_vms() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_libvirt_vms systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local vm_dir="$BACKUP_DIR/$LIBVIRT_DIR_NAME"
    [[ -d "$vm_dir" ]] || die "Keine VM-Sicherung gefunden: $vm_dir"

    echo
    warn "KVM/libvirt/VMs wiederherstellen."
    warn "Beste Praxis: libvirtd vorher stoppen, wenn keine VMs laufen."
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    restore_path_to_root "$vm_dir" "etc-libvirt" "/etc" "/etc/libvirt"
    if [[ -d "$vm_dir/var-lib/libvirt" ]]; then
        mkdir -p /var/lib
        rsync -aHAX --numeric-ids --force "$vm_dir/var-lib/libvirt" /var/lib/ || warn "/var/lib/libvirt nicht vollständig wiederhergestellt."
    fi
    restore_path_to_root "$vm_dir" "VM" "/" "/VM"

    systemctl daemon-reload 2>/dev/null || true
    systemctl restart libvirtd 2>/dev/null || systemctl restart libvirt-bin 2>/dev/null || true
    info "VM-Restore abgeschlossen."
}

save_docker_container_data() {
    local docker_dir="$BACKUP_DIR/$DOCKER_DIR_NAME"
    local root
    root="$(source_root_for_apps)"
    mkdir -p "$docker_dir"

    echo
    warn "Sichere Docker/Container-Konfiguration."
    warn "Gesichert werden Konfiguration, Compose-nahe Pfade und Volumes."
    warn "Komplette Images werden bewusst nicht exportiert; die zieht Docker neu."
    echo

    backup_path_from_root "$root" "/etc/docker" "$docker_dir" "/etc/docker"
    backup_path_from_root "$root" "/var/lib/docker/volumes" "$docker_dir/var-lib-docker" "Docker Volumes"
    backup_path_from_root "$root" "/opt/docker" "$docker_dir" "/opt/docker"
    backup_path_from_root "$root" "/srv/docker" "$docker_dir" "/srv/docker"
    backup_path_from_root "$root" "/opt/immich" "$docker_dir/extra" "Immich Compose-Verzeichnis"

    if has_cmd docker && [[ "$root" == "/" ]]; then
        mkdir -p "$docker_dir/docker-reports"
        docker ps -a > "$docker_dir/docker-reports/docker-ps-a.txt" 2>/dev/null || true
        docker images > "$docker_dir/docker-reports/docker-images.txt" 2>/dev/null || true
        docker volume ls > "$docker_dir/docker-reports/docker-volume-ls.txt" 2>/dev/null || true
    fi

    info "Docker/Container-Daten gesichert."
}

restore_docker_container_data() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_docker_container_data systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local docker_dir="$BACKUP_DIR/$DOCKER_DIR_NAME"
    [[ -d "$docker_dir" ]] || die "Keine Docker-Sicherung gefunden: $docker_dir"

    echo
    warn "Docker/Container-Daten wiederherstellen."
    warn "Docker sollte dafür gestoppt sein. Das Skript versucht es automatisch."
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    systemctl stop docker docker.socket containerd 2>/dev/null || true

    restore_path_to_root "$docker_dir" "etc-docker" "/etc" "/etc/docker"
    if [[ -d "$docker_dir/var-lib-docker/volumes" ]]; then
        mkdir -p /var/lib/docker
        rsync -aHAX --numeric-ids --force "$docker_dir/var-lib-docker/volumes" /var/lib/docker/ || warn "Docker Volumes nicht vollständig wiederhergestellt."
    fi
    restore_path_to_root "$docker_dir" "opt-docker" "/opt" "/opt/docker"
    restore_path_to_root "$docker_dir" "srv-docker" "/srv" "/srv/docker"

    if [[ -d "$docker_dir/extra/immich" ]]; then
        mkdir -p /opt
        rsync -aHAX --numeric-ids --force "$docker_dir/extra/immich" /opt/ || warn "Immich-Verzeichnis nicht vollständig wiederhergestellt."
    fi

    systemctl start containerd docker 2>/dev/null || true
    info "Docker/Container-Restore abgeschlossen."
}

save_server_services() {
    local srv_dir="$BACKUP_DIR/$SERVER_SERVICES_DIR_NAME"
    local root
    root="$(source_root_for_apps)"
    mkdir -p "$srv_dir"

    echo
    warn "Sichere Serverdienst-Konfigurationen."
    echo

    backup_path_from_root "$root" "/etc/apache2" "$srv_dir/etc" "Apache"
    backup_path_from_root "$root" "/etc/nginx" "$srv_dir/etc" "Nginx"
    backup_path_from_root "$root" "/etc/php" "$srv_dir/etc" "PHP"
    backup_path_from_root "$root" "/etc/mysql" "$srv_dir/etc" "MySQL/MariaDB Config"
    backup_path_from_root "$root" "/etc/postgresql" "$srv_dir/etc" "PostgreSQL Config"
    backup_path_from_root "$root" "/etc/tvheadend" "$srv_dir/etc" "Tvheadend Config"
    backup_path_from_root "$root" "/var/lib/tvheadend" "$srv_dir/var-lib" "Tvheadend Daten"
    backup_path_from_root "$root" "/etc/letsencrypt" "$srv_dir/etc" "Let's Encrypt"
    backup_path_from_root "$root" "/var/www" "$srv_dir/var" "Webroot"

    info "Serverdienste gesichert."
}

restore_server_services() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen "Legacy-Systemrestore bei abweichender/unbekannter Plattform gesperrt; V20-Komponenten verwenden."; return 1; }
    v20_confirm "Legacy-Komponente restore_server_services systemweit wiederherstellen" || return 0
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local srv_dir="$BACKUP_DIR/$SERVER_SERVICES_DIR_NAME"
    [[ -d "$srv_dir" ]] || die "Keine Serverdienst-Sicherung gefunden: $srv_dir"

    echo
    warn "Serverdienste wiederherstellen."
    warn "Apache/Nginx/PHP/Tvheadend/Let's Encrypt/Webroot können überschrieben werden."
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    if [[ -d "$srv_dir/etc" ]]; then
        rsync -aHAX --numeric-ids --force "$srv_dir/etc/" /etc/ || warn "Server-/etc nicht vollständig wiederhergestellt."
    fi
    if [[ -d "$srv_dir/var-lib/tvheadend" ]]; then
        mkdir -p /var/lib
        rsync -aHAX --numeric-ids --force "$srv_dir/var-lib/tvheadend" /var/lib/ || warn "Tvheadend-Daten nicht vollständig wiederhergestellt."
    fi
    if [[ -d "$srv_dir/var/www" ]]; then
        mkdir -p /var
        rsync -aHAX --numeric-ids --force "$srv_dir/var/www" /var/ || warn "Webroot nicht vollständig wiederhergestellt."
    fi

    systemctl daemon-reload 2>/dev/null || true
    systemctl reload apache2 2>/dev/null || true
    systemctl reload nginx 2>/dev/null || true
    systemctl restart tvheadend 2>/dev/null || true
    info "Serverdienst-Restore abgeschlossen."
}

create_restore_report() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local report="$reports_dir/restore-report-${DATE_STR}.txt"
    mkdir -p "$reports_dir"

    {
        echo "Restore-/Backup-Bericht"
        echo "created=$(date --iso-8601=seconds)"
        echo "target_host=$(hostname -f 2>/dev/null || hostname)"
        echo "target_kernel=$(uname -a)"
        echo "target_user=$SOURCE_USER"
        echo "target_home=$SOURCE_HOME"
        echo
        echo "===== Backup-Inhalt ====="
        find "$BACKUP_DIR" -maxdepth 2 -mindepth 1 -type d -printf '%p\n' 2>/dev/null | sort
        echo
        echo "===== Ziel OS ====="
        [[ -f /etc/os-release ]] && cat /etc/os-release
        echo
        echo "===== APT Probleme ====="
        dpkg --audit 2>/dev/null || true
        echo
        echo "===== Aktivierte Dienste ====="
        systemctl list-unit-files --state=enabled 2>/dev/null || true
    } > "$report"

    info "Restore-Report erstellt: $report"
    write_final_restore_notes
}

show_reports() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    [[ -d "$reports_dir" ]] || { warn "Keine Reports vorhanden."; return 0; }

    echo
    echo "Reports:"
    find "$reports_dir" -maxdepth 1 -type f -printf '  %f\n' 2>/dev/null | sort
    echo
    if [[ -f "$reports_dir/hardware-system-report.txt" ]]; then
        echo "Hardware-/Systembericht:"
        sed -n '1,120p' "$reports_dir/hardware-system-report.txt"
    fi
}

do_full_expert_backup() {
    echo
    warn "VOLLSTÄNDIGES MIGRATIONS-BACKUP"
    warn "Sichert Home, Programme, Desktop-Assets, erweiterte Systemkonfig, VMs, Docker, Serverdienste und Reports."
    warn "Das kann je nach VMs/Docker sehr groß werden."
    echo
    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    choose_backup_mode
    detect_problem_paths
    build_effective_excludes
    show_usb_info
    show_detected_problem_paths
    print_effective_excludes
    check_backup_space
    do_backup
    save_extended_system_config
    save_libvirt_vms
    save_docker_container_data
    save_server_services
    save_mounted_data_roots
    create_restore_report
}


show_existing_backup_status() {
    echo
    show_usb_info
    echo
    if [[ -d "$BACKUP_DIR/$FILES_DIR_NAME" ]]; then
        info "Vorhandenes Backup gefunden."
        show_backup_info
    else
        warn "Für Benutzer $SOURCE_USER ist auf diesem Datenträger noch kein Backup vorhanden."
    fi
}

main_menu() {
    echo
    echo "==========================================="
    echo " Linux Backup / Migration"
    echo "==========================================="
    echo " Benutzer : $SOURCE_USER"
    echo " UID/GID  : $SOURCE_UID:$SOURCE_GID"
    echo " Home     : $SOURCE_HOME"
    echo " Host     : $SOURCE_HOST"
    echo " Live     : $LIVE_MODE"
    echo " Modus    : $BACKUP_MODE"
    echo
    echo "  1) Client/Desktop"
    echo "     Home, Programme, Desktopzustand, dconf, Themes, Datenlaufwerke."
    echo
    echo "  2) Debian Server"
    echo "     Serverconfigs, Benutzer/UID/GID, Nextcloud, DBs, Docker, KVM, Dienste."
    echo
    echo "  3) Werkzeuge"
    echo "     USB-Temp, rw-Check, Installationsziel, Reports."
    echo
    echo " 99) Beenden"
    echo
    echo "Ablage:"
    echo "  Client: $BACKUP_DIR"
    echo "  Server: ${SERVER_BACKUP_DIR:-$USB_MOUNTPOINT/$SERVER_BACKUP_ROOT_NAME/<hostname>}"
    echo
}

prepare_environment() {
    [[ "$EUID" -eq 0 ]] || die "Bitte mit sudo starten."
    need_cmd python3
    need_cmd rsync
    need_cmd getent
    need_cmd findmnt
    need_cmd mountpoint
    need_cmd lsblk
    need_cmd find
    need_cmd df
    need_cmd du
    need_cmd numfmt
    need_cmd chown
    need_cmd awk
    need_cmd mktemp
    need_cmd tee
    need_cmd sort
    need_cmd stat
}

fix_cdrom_repositories() {
    local changed="false"
    local file

    [[ -d /etc/apt ]] || return 0
    info "Prüfe auf störende cdrom:-Repositories ..."

    if [[ -f /etc/apt/sources.list ]] && grep -Eq '^[[:space:]]*deb[[:space:]]+cdrom:' /etc/apt/sources.list; then
        cp -a /etc/apt/sources.list "/etc/apt/sources.list.bak-${DATE_STR}" 2>/dev/null || true
        sed -Ei 's|^[[:space:]]*(deb[[:space:]]+cdrom:.*)|# DISABLED-BY-BACKUP-SCRIPT \1|g' /etc/apt/sources.list
        changed="true"
    fi

    if [[ -d /etc/apt/sources.list.d ]]; then
        while IFS= read -r file; do
            [[ -f "$file" ]] || continue
            if grep -Eq '^[[:space:]]*deb[[:space:]]+cdrom:' "$file"; then
                cp -a "$file" "${file}.bak-${DATE_STR}" 2>/dev/null || true
                sed -Ei 's|^[[:space:]]*(deb[[:space:]]+cdrom:.*)|# DISABLED-BY-BACKUP-SCRIPT \1|g' "$file"
                changed="true"
            fi
        done < <(find /etc/apt/sources.list.d -type f 2>/dev/null)
    fi

    if [[ "$changed" == "true" ]]; then
        info "cdrom:-Einträge deaktiviert."
    else
        info "Keine aktiven cdrom:-Einträge gefunden."
    fi
}

get_current_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${ID:-unknown}:${VERSION_ID:-unknown}:${ID_LIKE:-}"
    else
        echo "unknown:unknown:"
    fi
}

filter_problematic_packages() {
    local infile="$1"
    local outfile="$2"
    local current_distro pkg

    current_distro="$(get_current_distro)"
    info "Aktuelle Ziel-Distribution: $current_distro"

    : > "$outfile"

    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue

        case "$pkg" in
            linux-image-*|linux-headers-*|linux-modules-*|linux-modules-extra-*|linux-tools-*|linux-generic*|linux-oem*|linux-hwe*|linux-firmware*|firmware-*)
                warn "Überspringe Kernel/Firmware: $pkg"
                report_failed_app "APT" "$pkg" "Bewusst gefiltert: Kernel/Firmware"
                continue
                ;;
            nvidia-*|libnvidia-*|xserver-xorg-video-nvidia*|cuda-*|nsight-*|opencl-nvidia*)
                warn "Überspringe NVIDIA/CUDA-Treiberpaket: $pkg"
                report_failed_app "APT" "$pkg" "Bewusst gefiltert: NVIDIA/CUDA/Treiber"
                continue
                ;;
            virtualbox-*|virtualbox)
                warn "Überspringe VirtualBox-Kernelpaket: $pkg"
                report_failed_app "APT" "$pkg" "Bewusst gefiltert: VirtualBox-Kernelpaket"
                continue
                ;;
            ttf-mscorefonts-installer)
                warn "Überspringe problematischen Microsoft-Schriften-Installer: $pkg"
                report_failed_app "APT" "$pkg" "Bewusst gefiltert: Microsoft-Schriften-Installer/EULA"
                continue
                ;;
            *-dbg|*-dbgsym)
                continue
                ;;
            live-*|casper|ubiquity|ubiquity-*|calamares|calamares-*)
                warn "Überspringe Live-/Installer-Paket: $pkg"
                report_failed_app "APT" "$pkg" "Bewusst gefiltert: Live-/Installer-Paket"
                continue
                ;;
        esac

        if [[ "$current_distro" == debian:* ]]; then
            case "$pkg" in
                ubuntu-*|ubuntu-drivers-common|software-properties-common|software-properties-gtk|mintupgrade|mintupgrade-*)
                    warn "Nicht passend für LMDE/Debian: $pkg"
                    report_failed_app "APT" "$pkg" "Nicht passend für LMDE/Debian"
                    continue
                    ;;
            esac
        fi

        if [[ "$current_distro" == linuxmint:* ]]; then
            case "$pkg" in
                task-*|live-task-*|debian-installer-*|debian-reference*|debian-faq)
                    warn "Debian-spezifisch, übersprungen: $pkg"
                    report_failed_app "APT" "$pkg" "Debian-spezifisch, auf Ziel-Mint übersprungen"
                    continue
                    ;;
            esac
        fi

        if target_apt_cache_show "$pkg"; then
            printf '%s\n' "$pkg" >> "$outfile"
        else
            warn "APT-Paket im Zielsystem nicht verfügbar, überspringe: $pkg"
            report_failed_app "APT" "$pkg" "Nicht in Ziel-Repositories vorhanden"
        fi
    done < "$infile"
}


prepare_usb() {
    if [[ -n "$STORAGE_DIR" ]]; then
        [[ "$STORAGE_DIR" == /* && -d "$STORAGE_DIR" && ! -L "$STORAGE_DIR" ]] || die "Ungültiger Arbeitsordner"
        USB_MOUNTPOINT="$STORAGE_DIR"
    else
        choose_usb_mountpoint
    fi
    get_usb_fstype
    print_filesystem_permission_hint
    ensure_usb_writable
    set_backup_paths
    ensure_client_backup_compatibility
    set_server_backup_paths
    setup_usb_logfile
}

action_backup() {
    choose_backup_mode
    detect_problem_paths
    build_effective_excludes
    show_usb_info
    show_detected_problem_paths
    print_effective_excludes
    check_backup_space
    do_backup
}

action_restore() {
    show_existing_backup_status
    do_restore
}

action_backup_info() {
    show_existing_backup_status
}

action_problem_paths() {
    show_detected_problem_paths
    print_effective_excludes
}

action_program_restore() {
    show_existing_backup_status
    do_program_restore
}

action_full_restore() {
    show_existing_backup_status
    do_full_restore
}

action_live_restore() {
    show_existing_backup_status
    do_live_system_restore
}

action_desktop_restore() {
    show_existing_backup_status
    do_desktop_app_settings_restore
    create_restore_report
}

action_extended_config_backup() {
    save_extended_system_config
}

action_extended_config_restore() {
    show_existing_backup_status
    restore_extended_system_config
    create_restore_report
}

action_libvirt_backup() {
    save_libvirt_vms
}

action_libvirt_restore() {
    show_existing_backup_status
    restore_libvirt_vms
    create_restore_report
}

action_docker_backup() {
    save_docker_container_data
}

action_docker_restore() {
    show_existing_backup_status
    restore_docker_container_data
    create_restore_report
}

action_server_backup() {
    save_server_services
}

action_server_restore() {
    show_existing_backup_status
    restore_server_services
    create_restore_report
}

action_reports_create() {
    save_identity_and_hardware_report
    save_full_desktop_state
    save_systemd_mounts_and_acls
    v19_svl backup || die "SVL-Konfiguration konnte nicht vollständig gesichert werden."
}

action_reports_show() {
    create_restore_report
    show_reports
}

action_full_desktop_backup() {
    save_full_desktop_state
}

action_full_desktop_restore() {
    show_existing_backup_status
    restore_full_desktop_state
    restore_systemd_mounts_and_acls
    create_restore_report
}


action_cleanup_temp() {
    cleanup_usb_temp_workdir_menu
}

action_full_expert_backup() {
    do_full_expert_backup
}


save_full_desktop_state() {
    local dconf_dir="$BACKUP_DIR/$DCONF_DIR_NAME"

    mkdir -p "$dconf_dir"

    echo
    info "Sichere vollständigen Desktopzustand ..."
    echo "  Enthält Cinnamon/GTK/Nemo/Applets/Desklets/dconf"

    if has_cmd dconf; then
        dconf dump / > "$dconf_dir/dconf-full.ini" 2>/dev/null || warn "dconf dump fehlgeschlagen."
    fi

    local desktop_paths=(
        ".config/cinnamon"
        ".local/share/cinnamon"
        ".config/gtk-3.0"
        ".config/gtk-4.0"
        ".config/nemo"
        ".config/autostart"
        ".config/menus"
        ".config/plank"
        ".local/share/backgrounds"
        ".local/share/themes"
        ".local/share/icons"
    )

    for rel in "${desktop_paths[@]}"; do
        if [[ -e "$SOURCE_HOME/$rel" ]]; then
            mkdir -p "$dconf_dir/home"
            rsync -aHAX --numeric-ids "$SOURCE_HOME/$rel" "$dconf_dir/home/" || warn "Nicht vollständig gesichert: $rel"
        fi
    done

    if [[ -f "$SOURCE_HOME/.config/monitors.xml" ]]; then
        cp -a "$SOURCE_HOME/.config/monitors.xml" "$dconf_dir/" 2>/dev/null || true
    fi

    if [[ -f "$SOURCE_HOME/.config/displays.xml" ]]; then
        cp -a "$SOURCE_HOME/.config/displays.xml" "$dconf_dir/" 2>/dev/null || true
    fi

    info "Desktopzustand gesichert."
}

restore_full_desktop_state() {
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local dconf_dir="$BACKUP_DIR/$DCONF_DIR_NAME"

    [[ -d "$dconf_dir" ]] || die "Kein Desktopzustand im Backup gefunden."

    echo
    warn "Vollständigen Desktopzustand wiederherstellen."
    warn "Optimal im Live-System oder nach Abmeldung des Zielbenutzers."
    echo

    read -r -p "Fortfahren? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    ensure_path_writable_for_restore "$SOURCE_HOME"

    if [[ -d "$dconf_dir/home" ]]; then
        rsync -aHAX --numeric-ids --force "$dconf_dir/home/" "$SOURCE_HOME/" || warn "Desktopdateien nicht vollständig wiederhergestellt."
    fi

    if has_cmd dconf && [[ -f "$dconf_dir/dconf-full.ini" ]]; then
        info "Stelle dconf-Datenbank wieder her ..."
        dconf load / < "$dconf_dir/dconf-full.ini" || warn "dconf load fehlgeschlagen."
    fi

    if [[ "$LIVE_MODE" != "true" ]]; then
        warn "Monitorprofile werden auf laufendem System NICHT automatisch zurückgespielt."
    else
        [[ -f "$dconf_dir/monitors.xml" ]] && cp -a "$dconf_dir/monitors.xml" "$SOURCE_HOME/.config/" 2>/dev/null || true
        [[ -f "$dconf_dir/displays.xml" ]] && cp -a "$dconf_dir/displays.xml" "$SOURCE_HOME/.config/" 2>/dev/null || true
    fi

    safe_chown_tree "$SOURCE_UID:$SOURCE_GID" "$SOURCE_HOME"

    info "Desktopzustand wiederhergestellt."
}

save_systemd_mounts_and_acls() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local acl_dir="$BACKUP_DIR/$ACL_DIR_NAME"

    mkdir -p "$reports_dir"
    mkdir -p "$acl_dir"

    echo
    info "Sichere systemd-Mounts und ACLs ..."

    systemctl list-unit-files > "$reports_dir/systemd-unit-files.txt" 2>/dev/null || true
    systemctl list-units --type=mount > "$reports_dir/systemd-mounts.txt" 2>/dev/null || true
    mount > "$reports_dir/active-mounts.txt" 2>/dev/null || true
    findmnt -R > "$reports_dir/findmnt.txt" 2>/dev/null || true

    if [[ -d /Serverspeicher ]] && has_cmd getfacl; then
        getfacl -R /Serverspeicher > "$acl_dir/serverspeicher-acl.txt" 2>/dev/null || warn "ACL-Export fehlgeschlagen."
    fi

    info "systemd-Mounts und ACLs gesichert."
}

restore_systemd_mounts_and_acls() {
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local acl_dir="$BACKUP_DIR/$ACL_DIR_NAME"

    echo
    warn "ACLs und systemd-Mount-Konfiguration wiederherstellen."
    echo

    if [[ -f "$acl_dir/serverspeicher-acl.txt" ]] && has_cmd setfacl; then
        read -r -p "ACLs für /Serverspeicher wiederherstellen? [ja/NEIN]: " confirm_acl
        if [[ "$confirm_acl" == "ja" ]]; then
            setfacl --restore="$acl_dir/serverspeicher-acl.txt" || warn "ACL-Restore fehlgeschlagen."
        fi
    fi

    systemctl daemon-reload 2>/dev/null || true

    info "ACL-/Mount-Restore abgeschlossen."
}

apt_package_installed() {
    local pkg="$1"
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"
}

flatpak_app_installed() {
    local app="$1"
    flatpak info "$app" >/dev/null 2>&1
}


action_check_restore_mount() {
    echo
    info "Prüfe Restore-Ziel und Mountmodus ..."
    echo "  SOURCE_HOME: $SOURCE_HOME"
    findmnt --target "$SOURCE_HOME" || true
    ensure_path_writable_for_restore "$SOURCE_HOME"
}

action_check_install_target() {
    local root
    root="$(source_root_for_apps)"
    echo
    info "Installationszielprüfung"
    echo "  LIVE_MODE : $LIVE_MODE"
    echo "  Zielroot  : $root"
    if [[ "$root" == "/" ]]; then
        warn "Installationen laufen im aktuell gebooteten System."
    else
        info "Installationen laufen per chroot im gemounteten Zielsystem."
        echo "  os-release Zielsystem:"
        [[ -f "$root/etc/os-release" ]] && sed 's/^/    /' "$root/etc/os-release" || true
        prepare_target_chroot
        chroot "$root" sh -c 'echo "  chroot ok: $(. /etc/os-release 2>/dev/null; echo ${PRETTY_NAME:-unknown})"' || warn "chroot-Test fehlgeschlagen."
        cleanup_target_chroot
    fi
}

action_check_target_installation() {
    local root
    root="$(source_root_for_apps)"

    echo
    info "Prüfe Installationsziel"
    echo "  LIVE_MODE : $LIVE_MODE"
    echo "  Zielroot  : $root"

    if [[ "$root" == "/" ]]; then
        warn "Installationen laufen im aktuell gebooteten System."
    else
        prepare_target_chroot
        echo
        echo "Zielsystem /etc/os-release:"
        chroot "$root" cat /etc/os-release 2>/dev/null || warn "os-release im Zielsystem nicht lesbar."
        echo
        echo "Zielsystem apt:"
        chroot "$root" apt-get --version 2>/dev/null | head -n1 || warn "apt im Zielsystem nicht ausführbar."
        echo
        echo "Zielsystem dpkg Status Test:"
        chroot "$root" dpkg-query -W bash 2>/dev/null || true
        cleanup_target_chroot
    fi
}



save_manual_deb_apps_report() {
    local desktop_dir report
    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"

    desktop_dir="$SOURCE_HOME/Desktop"
    if [[ ! -d "$desktop_dir" && -d "$SOURCE_HOME/Schreibtisch" ]]; then
        desktop_dir="$SOURCE_HOME/Schreibtisch"
    fi
    mkdir -p "$desktop_dir"

    report="$desktop_dir/manuell-installierte-deb-apps.txt"

    {
        echo "Manuell installierte .deb Anwendungen"
        echo "Erstellt: $(date --iso-8601=seconds)"
        echo
        echo "Diese Liste enthält Pakete, die möglicherweise NICHT aus Standard-Repositories stammen."
        echo "Sie sollten nach dem Restore manuell geprüft werden."
        echo
    } > "$report"

    if [[ -f "$apps_dir/apt-manual.txt" ]]; then
        grep -Ei 'chrome|edge|teamviewer|anydesk|virtualbox|vivaldi|opera|skype|zoom|discord|slack|citrix|google-earth|parsec|rustdesk|obsidian|plex|jdownloader|brave|onlyoffice|softmaker|megasync|drawio|postman|mongodb|xampp|xampp-linux|winehq|nordvpn|expressvpn|mullvad|surfshark|protonvpn' \
            "$apps_dir/apt-manual.txt" 2>/dev/null | sort -u >> "$report" || true
    fi

    echo >> "$report"
    echo "Zusätzliche Prüfung empfohlen für:" >> "$report"
    echo "  - lokal installierte .deb Dateien" >> "$report"
    echo "  - Hersteller-Repositories" >> "$report"
    echo "  - Fremdquellen/PPA" >> "$report"
    echo "  - proprietäre Anwendungen" >> "$report"

    chown "$SOURCE_UID:$SOURCE_GID" "$report" 2>/dev/null || true

    info "Bericht für manuell installierte .deb Apps erstellt: $report"
}


default_mounted_data_roots() {
    printf '%s\n' "/Serverspeicher" "/VM"
}

save_mounted_data_roots() {
    local data_dir="$BACKUP_DIR/$MOUNTED_DATA_DIR_NAME"
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local root rel target
    local rc=0

    mkdir -p "$data_dir" "$reports_dir"

    echo
    warn "Gemountete Datenlaufwerke sichern."
    warn "Datenpfade: /Serverspeicher, /VM; /SVL nur Konfiguration"
    warn "Das kann sehr groß werden. Nur fortfahren, wenn der USB-Datenträger genug Platz hat."
    echo
    read -r -p "Gemountete Datenlaufwerke wirklich sichern? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || {
        info "Gemountete Datenlaufwerke nicht gesichert."
        return 0
    }

    {
        echo "created=$(date --iso-8601=seconds)"
        echo
        echo "===== findmnt ====="
        findmnt -R 2>/dev/null || true
        echo
        echo "===== mount ====="
        mount 2>/dev/null || true
        echo
        echo "===== fstab ====="
        [[ -f /etc/fstab ]] && cat /etc/fstab || true
        echo
        echo "===== systemd mount units ====="
        find /etc/systemd/system -maxdepth 1 \( -name "*.mount" -o -name "*.automount" \) -print -exec cat {} \; 2>/dev/null || true
    } > "$reports_dir/mounted-data-report.txt"

    while IFS= read -r root; do
        [[ -e "$root" ]] || {
            warn "Nicht vorhanden, überspringe: $root"
            continue
        }

        rel="${root#/}"
        target="$data_dir/$rel"

        echo
        info "Sichere gemounteten Datenpfad:"
        echo "  Quelle: $root"
        echo "  Ziel  : $target"

        mkdir -p "$target"

        rsync -aHAX --numeric-ids --info=progress2 --human-readable \
            --exclude='lost+found/' \
            "$root/" "$target/" || {
                warn "Datenpfad nicht vollständig gesichert: $root"
                rc=1
            }

        if has_cmd getfacl; then
            mkdir -p "$BACKUP_DIR/$ACL_DIR_NAME"
            getfacl -P -- "$root" > "$BACKUP_DIR/$ACL_DIR_NAME/${rel//\//_}-acl.txt" 2>/dev/null || true
        fi
    done < <(default_mounted_data_roots)

    if [[ "$rc" -eq 0 ]]; then
        info "Gemountete Datenlaufwerke gesichert."
    else
        warn "Einige gemountete Datenlaufwerke wurden nicht vollständig gesichert."
    fi
}

restore_mounted_data_roots() {
    if v19_is_suse; then warn "Legacy-Restore auf openSUSE gesperrt. Client-Menü 10 für Migration verwenden."; return 1; fi
    local data_dir="$BACKUP_DIR/$MOUNTED_DATA_DIR_NAME"
    local item name dest rc=0

    [[ -d "$data_dir" ]] || die "Keine Sicherung gemounteter Datenlaufwerke gefunden: $data_dir"

    echo
    warn "Gemountete Datenlaufwerke wiederherstellen."
    warn "Wiederhergestellt werden vorhandene Sicherungen unter:"
    echo "  $data_dir"
    echo
    warn "Mountdefinitionen aus /etc/fstab und systemd werden NICHT blind aktiviert."
    warn "Prüfe danach reports/mounted-data-report.txt und /etc/fstab.restored-*."
    echo
    read -r -p "Gemountete Datenlaufwerke wirklich zurückspielen? [ja/NEIN]: " confirm
    [[ "$confirm" == "ja" ]] || {
        info "Restore gemounteter Datenlaufwerke abgebrochen."
        return 0
    }

    while IFS= read -r item; do
        [[ -d "$item" ]] || continue
        name="$(basename "$item")"
        [[ "$name" != SVL ]] || { warn "SVL-Datenrestore gesperrt: nur Mount-Konfiguration übernehmen."; continue; }
        [[ "$name" == Serverspeicher || "$name" == VM ]] || { warn "Nicht erlaubter Datenroot: $name"; continue; }
        dest="/$name"

        echo
        info "Stelle Datenpfad wieder her:"
        echo "  Quelle: $item/"
        echo "  Ziel  : $dest/"

        mkdir -p "$dest"

        rsync -aHAX --numeric-ids --info=progress2 --human-readable \
            --force \
            "$item/" "$dest/" || {
                warn "Datenpfad nicht vollständig wiederhergestellt: $dest"
                rc=1
            }

        if [[ -f "$BACKUP_DIR/$ACL_DIR_NAME/${name}-acl.txt" ]] && has_cmd setfacl; then
            warn "ACL-Datei vorhanden für $dest."
            read -r -p "ACLs für $dest wiederherstellen? [ja/NEIN]: " acl_confirm
            if [[ "$acl_confirm" == "ja" ]]; then
                setfacl --restore="$BACKUP_DIR/$ACL_DIR_NAME/${name}-acl.txt" || warn "ACL-Restore fehlgeschlagen: $dest"
            fi
        fi
    done < <(find "$data_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

    systemctl daemon-reload 2>/dev/null || true

    if [[ "$rc" -eq 0 ]]; then
        info "Gemountete Datenlaufwerke wiederhergestellt."
    else
        warn "Einige gemountete Datenlaufwerke wurden nicht vollständig wiederhergestellt."
    fi
}

restore_mount_definitions_hint() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"

    echo
    info "Mountdefinitionen prüfen"
    echo "  Report: $reports_dir/mounted-data-report.txt"
    echo
    warn "Automatisches Überschreiben von /etc/fstab ist absichtlich deaktiviert."
    warn "Grund: UUIDs und Gerätepfade können auf anderer Hardware anders sein."
    warn "Empfohlen:"
    echo "  1. /etc/fstab.restored-* prüfen"
    echo "  2. UUIDs mit blkid vergleichen"
    echo "  3. systemd .mount/.automount Units prüfen"
    echo "  4. Danach systemctl daemon-reload"
    echo
    if [[ -f "$reports_dir/mounted-data-report.txt" ]]; then
        sed -n '1,160p' "$reports_dir/mounted-data-report.txt"
    else
        warn "Kein mounted-data-report.txt gefunden."
    fi
}

write_final_restore_notes() {
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local notes="$reports_dir/wiederherstellung-hinweise.txt"

    mkdir -p "$reports_dir"

    cat > "$notes" <<EOF
Empfohlene Wiederherstellungs-Reihenfolge

1. Live-System starten
2. Skript starten
3. Menü 25: Restore-Ziel rw prüfen/remounten
4. Menü 7: Komplett-Wiederherstellung
5. Menü 23: vollständigen Desktopzustand wiederherstellen
6. Optional:
   - Menü 12: erweiterte Systemkonfiguration
   - Menü 14: KVM/libvirt/VMs
   - Menü 16: Docker/Container
   - Menü 18: Serverdienste
7. Zielsystem booten
8. Auf dem Desktop prüfen:
   - nicht-installierbare-apps.txt
   - install-flatpaks-nach-erster-anmeldung.sh

Wichtig:
- APT wird im Live-Modus per chroot ins Zielsystem installiert.
- Flatpak wird versucht, kann im chroot aber wegen GPG/OSTree/DBus scheitern.
  Dafür liegt ein Nachinstallationsskript auf dem Desktop.
- Kernel, NVIDIA/CUDA, Firmware und Bootloader werden bewusst nicht blind migriert.
EOF

    info "Hinweisdatei erstellt: $notes"
}


action_mounted_data_backup() {
    save_mounted_data_roots
}

action_mounted_data_restore() {
    show_existing_backup_status
    restore_mounted_data_roots
    create_restore_report
}

action_mount_definitions_hint() {
    show_existing_backup_status
    restore_mount_definitions_hint
}


client_restore_steps_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " V20 Restore: Daten / Standard / Full / Migration / Komponenten"
        echo "================================"
        echo "Empfohlene Reihenfolge aus Live-System:"
        echo "  1 -> 2 -> 3 -> 4 -> optional 5 -> 6"
        echo
        echo "  1) Restore-Ziel rw prüfen/remounten"
        echo "     Prüft das gemountete Zielsystem und stellt read-write sicher."
        echo
        echo "  2) Programme installieren"
        echo "     Installiert APT-Pakete ins Zielsystem; Flatpak ggf. per Nachinstallationsskript."
        echo
        echo "  3) Home wiederherstellen"
        echo "     Spielt Home-Daten zurück."
        echo
        echo "  4) Desktopzustand wiederherstellen"
        echo "     dconf, Cinnamon/GTK/Nemo, Applets, Themes, Icons, Hintergrundbilder."
        echo
        echo "  5) Gemountete Datenlaufwerke wiederherstellen"
        echo "     /SVL, /Serverspeicher, /VM aus eigener Sicherung."
        echo
        echo "  6) Reports prüfen/erstellen"
        echo "     nicht-installierbare Apps, Flatpak-Nachinstallationsskript, Restore-Report."
        echo
        echo "  7) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Client: Restore-Ziel rw prüfen/remounten" action_check_restore_mount ;;
            2) run_menu_action "Client: Programme installieren" action_program_restore ;;
            3) run_menu_action "Client: Home wiederherstellen" action_restore ;;
            4) run_menu_action "Client: Desktopzustand wiederherstellen" action_full_desktop_restore ;;
            5) run_menu_action "Client: Gemountete Datenlaufwerke wiederherstellen" action_mounted_data_restore ;;
            6) run_menu_action "Client: Reports prüfen/erstellen" action_reports_show ;;
            7) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

client_data_mounts_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Client Datenlaufwerke / Mounts"
        echo "================================"
        echo "  1) Gemountete Datenlaufwerke sichern"
        echo "     /Serverspeicher, /VM inklusive ACLs; /SVL nur Konfiguration."
        echo
        echo "  2) Gemountete Datenlaufwerke wiederherstellen"
        echo "     Stellt gesicherte Datenpfade zurück."
        echo
        echo "  3) Mountdefinitionen anzeigen/prüfen"
        echo "     fstab, systemd .mount/.automount, findmnt."
        echo
        echo "  4) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Client: Gemountete Datenlaufwerke sichern" action_mounted_data_backup ;;
            2) run_menu_action "Client: Gemountete Datenlaufwerke wiederherstellen" action_mounted_data_restore ;;
            3) run_menu_action "Client: Mountdefinitionen anzeigen/prüfen" action_mount_definitions_hint ;;
            4) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

client_reports_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Client Diagnose / Reports"
        echo "================================"
        echo "  1) Backup-Info anzeigen"
        echo "  2) Problemordner prüfen"
        echo "  3) Benutzer-/Hardware-/Systembericht erstellen"
        echo "  4) Reports anzeigen/Restore-Report erstellen"
        echo "  5) Installationsziel prüfen"
        echo "  6) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Client: Backup-Info anzeigen" action_backup_info ;;
            2) run_menu_action "Client: Problemordner prüfen" action_problem_paths ;;
            3) run_menu_action "Client: Benutzer-/Hardware-/Systembericht erstellen" action_reports_create ;;
            4) run_menu_action "Client: Reports anzeigen/Restore-Report erstellen" action_reports_show ;;
            5) run_menu_action "Client: Installationsziel prüfen" action_check_target_installation ;;
            6) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

client_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Client/Desktop Backup/Restore"
        echo "================================"
        echo "Ablage: $BACKUP_DIR"
        echo
        echo "  1) Komplettes Client-Backup"
        echo "     Home, Programmlisten, Desktop-Assets, dconf, SVL-Konfiguration, Reports."
        echo
        echo "  2) V20 Restore: Daten / Standard / Full / Migration / Komponenten"
        echo "     Geführte Restore-Reihenfolge für Live-System/Neuinstallation."
        echo
        echo "  3) Programme wiederherstellen"
        echo "     APT/Flatpak nach Backup-Liste; Fehlerbericht auf Ziel-Desktop."
        echo
        echo "  4) Desktopzustand wiederherstellen"
        echo "     dconf, Cinnamon/GTK/Nemo, Themes, Icons, Applets."
        echo
        echo "  5) Datenlaufwerke / Mounts"
        echo "     /SVL, /Serverspeicher, /VM und Mountdefinitionen."
        echo
        echo "  6) Diagnose / Reports"
        echo "     Backup-Info, Problemordner, Installationsziel, Restore-Reports."
        echo
        echo "  7) Backup-Modus wählen/erklären"
        echo "     Normal = Migration/1:1-nah, Aggressiv = schlank."
        echo
        echo "  8) Restore auf laufendes System, sicherer Modus"
        echo "     Kein --delete; für aktiven Desktop-Benutzer."
        echo
        echo "  9) Zurück"
        echo "  10) Mint → Tumbleweed: Home, Programme, SVL-Automounts"
        echo "  11) SVL-Konfiguration rekonstruieren (auch Mint/Debian)"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            10) run_menu_action "Tumbleweed-Migration" v19_migrate ;;
            11) run_menu_action "SVL-Konfiguration" v19_svl restore ;;
            1) run_menu_action "Client: Komplettes Backup" action_backup ;;
            2) run_menu_action "V20 Automatischer Restore" v20_restore_menu ;;
            3) run_menu_action "Client: Programme wiederherstellen" action_program_restore ;;
            4) run_menu_action "Client: Desktopzustand wiederherstellen" action_full_desktop_restore ;;
            5) client_data_mounts_menu ;;
            6) client_reports_menu ;;
            7)
                info "Client: Backup-Modus wählen/erklären"
                choose_backup_mode
                detect_problem_paths
                build_effective_excludes
                pause_enter
                ;;
            8) run_menu_action "Client: Restore auf laufendes System" action_live_restore ;;
            9) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

server_restore_steps_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Debian Server Restore Schritt für Schritt"
        echo "================================"
        echo "  1) Benutzer/UID/GID anzeigen"
        echo "     Zeigt server-users.tsv zur Rechte-/ACL-Zuordnung."
        echo
        echo "  2) Server-Basiskonfiguration wiederherstellen"
        echo "     /etc selektiv, /usr/local, /opt; ohne passwd/shadow/machine-id/fstab blind zu überschreiben."
        echo
        echo "  3) Serverdienste wiederherstellen"
        echo "     Apache/Nginx/PHP/Tvheadend/Let's Encrypt/Webroot."
        echo
        echo "  4) Docker/Container wiederherstellen"
        echo "     Docker-Konfig und Volumes."
        echo
        echo "  5) KVM/libvirt/VMs wiederherstellen"
        echo "     libvirt-Konfig, VM-Images, /VM."
        echo
        echo "  6) Mounts/Datenlaufwerke wiederherstellen"
        echo "     /Serverspeicher, /VM inklusive ACLs; /SVL nur Konfiguration."
        echo
        echo "  7) Reports prüfen"
        echo
        echo "  8) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) show_server_users_for_client_mapping; pause_enter ;;
            2) run_menu_action "Server: Basiskonfiguration wiederherstellen" restore_server_core_configs ;;
            3) run_menu_action "Server: Serverdienste wiederherstellen" action_server_restore ;;
            4) run_menu_action "Server: Docker/Container wiederherstellen" action_docker_restore ;;
            5) run_menu_action "Server: KVM/libvirt/VMs wiederherstellen" action_libvirt_restore ;;
            6) run_menu_action "Server: Mounts/Datenlaufwerke wiederherstellen" action_mounted_data_restore ;;
            7) run_menu_action "Server: Reports prüfen" action_reports_show ;;
            8) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

server_services_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Debian Server Dienste"
        echo "================================"
        echo "  1) Serverdienste sichern"
        echo "     Apache/Nginx/PHP/Tvheadend/Let's Encrypt/Webroot."
        echo
        echo "  2) Serverdienste wiederherstellen"
        echo
        echo "  3) Nextcloud sichern"
        echo
        echo "  4) Datenbanken sichern"
        echo "     MariaDB/MySQL, PostgreSQL."
        echo
        echo "  5) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Server: Serverdienste sichern" save_server_services ;;
            2) run_menu_action "Server: Serverdienste wiederherstellen" action_server_restore ;;
            3) run_menu_action "Server: Nextcloud sichern" backup_server_nextcloud ;;
            4) run_menu_action "Server: Datenbanken sichern" backup_server_dbs ;;
            5) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

server_container_vm_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Debian Server Docker / KVM"
        echo "================================"
        echo "  1) Docker/Container sichern"
        echo "  2) Docker/Container wiederherstellen"
        echo "  3) KVM/libvirt/VMs sichern"
        echo "  4) KVM/libvirt/VMs wiederherstellen"
        echo "  5) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Server: Docker/Container sichern" save_docker_container_data ;;
            2) run_menu_action "Server: Docker/Container wiederherstellen" action_docker_restore ;;
            3) run_menu_action "Server: KVM/libvirt/VMs sichern" save_libvirt_vms ;;
            4) run_menu_action "Server: KVM/libvirt/VMs wiederherstellen" action_libvirt_restore ;;
            5) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

# Überschreibt das einfache Server-Menü aus älteren Versionen durch die neue logische Struktur.
server_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Debian Server Backup/Restore"
        echo "================================"
        echo "Ablage: $USB_MOUNTPOINT/$SERVER_BACKUP_ROOT_NAME/<hostname>"
        echo
        echo "  1) Komplettes Server-Backup"
        echo "     Serverconfigs, Benutzer/IDs, DBs, Nextcloud, Docker, libvirt, Dienste, Mounts."
        echo
        echo "  2) Server-Restore Schritt für Schritt"
        echo "     Geführter Restore für Debian-Server."
        echo
        echo "  3) Benutzer / UID / GID"
        echo "     Exportieren und anzeigen für Rechte-/ACL-/Client-Zuordnung."
        echo
        echo "  4) Dienste"
        echo "     Serverdienste, Nextcloud, Datenbanken."
        echo
        echo "  5) Docker / Container / KVM"
        echo
        echo "  6) Mounts / Datenlaufwerke"
        echo
        echo "  7) Reports"
        echo
        echo "  8) Server-Basiskonfiguration sichern"
        echo
        echo "  9) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Server: Komplettes Backup" backup_server_all ;;
            2) server_restore_steps_menu ;;
            3)
                run_menu_action "Server: Benutzer/UID/GID exportieren" export_all_users_and_ids
                show_server_users_for_client_mapping
                pause_enter
                ;;
            4) server_services_menu ;;
            5) server_container_vm_menu ;;
            6) client_data_mounts_menu ;;
            7) run_menu_action "Server: Reports" action_reports_show ;;
            8) run_menu_action "Server: Basiskonfiguration sichern" backup_server_core_configs ;;
            9) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}

tools_menu() {
    local choice
    while true; do
        echo
        echo "================================"
        echo " Werkzeuge"
        echo "================================"
        echo "  1) USB-Temp-Arbeitsdaten löschen"
        echo "  2) Restore-Ziel rw prüfen/remounten"
        echo "  3) Installationsziel prüfen"
        echo "  4) Backup-Info anzeigen"
        echo "  5) Problemordner prüfen"
        echo "  6) Reports anzeigen/erstellen"
        echo "  7) Zurück"
        echo
        read -r -p "Auswahl: " choice
        case "$choice" in
            1) run_menu_action "Werkzeuge: USB-Temp löschen" action_cleanup_temp ;;
            2) run_menu_action "Werkzeuge: Restore-Ziel rw prüfen/remounten" action_check_restore_mount ;;
            3) run_menu_action "Werkzeuge: Installationsziel prüfen" action_check_target_installation ;;
            4) run_menu_action "Werkzeuge: Backup-Info anzeigen" action_backup_info ;;
            5) run_menu_action "Werkzeuge: Problemordner prüfen" action_problem_paths ;;
            6) run_menu_action "Werkzeuge: Reports anzeigen/erstellen" action_reports_show ;;
            7) return 0 ;;
            *) warn "Ungültige Auswahl."; pause_enter ;;
        esac
    done
}


main() {
    local choice
    parse_args "$@"
    prepare_environment
    choose_start_mode
    resolve_source_identity
    init_logging

    echo "$SCRIPT_NAME — V20 Full System Migration"
    echo
    echo "Sichert ein Home-Verzeichnis auf einen USB-Datenträger."
    echo "Live-Modus: $LIVE_MODE"
    echo "Benutzer:   $SOURCE_USER"
    echo "UID/GID:    $SOURCE_UID:$SOURCE_GID"
    echo "Home:       $SOURCE_HOME"
    echo

    prepare_usb
    setup_usb_temp_workdir
    init_logging
    detect_problem_paths
    build_effective_excludes
    info "Datenträger ausgewählt: $USB_MOUNTPOINT"

    while true; do
        main_menu
        read -r -p "Bitte Menüpunkt eingeben und Enter drücken: " choice
        echo
        case "$choice" in
            1)
                info "Hauptmenü: Client/Desktop"
                client_menu
                ;;
            2)
                info "Hauptmenü: Debian Server"
                server_menu
                ;;
            3)
                info "Hauptmenü: Werkzeuge"
                tools_menu
                ;;
            99)
                info "Beendet."
                exit 0
                ;;
            *)
                warn "Ungültige Auswahl: '$choice'"
                pause_enter
                ;;
        esac
    done
}

# ---- v19: distribution-aware migration and configuration-only SVL backup ----
v19_is_suse() {
    local root; root="$(source_root_for_apps)"
    grep -Eq '^ID="?opensuse(-tumbleweed|-slowroll|-leap)?"?$' "$root/etc/os-release"
}

v19_program_restore() {
    [[ "$LIVE_MODE" != true ]] || {
        warn "Tumbleweed-Programmmigration bitte im gestarteten Zielsystem ausführen; Home-Restore ist offline möglich."
        return 1
    }
    need_cmd zypper

    local apps_dir="$BACKUP_DIR/$APPS_DIR_NAME"
    local reports_dir="$BACKUP_DIR/$REPORTS_DIR_NAME"
    local report="$reports_dir/tumbleweed-packages.tsv"
    local candidates="$reports_dir/tumbleweed-install-kandidaten.txt"
    local skipped="$reports_dir/tumbleweed-nicht-automatisch-uebernommen.txt"
    local src="$reports_dir/tumbleweed-quellpakete.txt"
    local p rpm reason answer count=0
    local -a install_pkgs=()

    mkdir -p "$reports_dir"
    printf 'Quelle\tZiel\tStatus\n' > "$report"
    : > "$candidates"
    : > "$skipped"
    : > "$src"

    # Nur explizit manuell markierte Pakete aus dem Quellsystem betrachten.
    # rpm-user.txt dient nur bei openSUSE->openSUSE; apt-manual.txt bei Mint/Debian->Tumbleweed.
    cat "$apps_dir/apt-manual.txt" "$apps_dir/rpm-user.txt" 2>/dev/null \
        | sed 's/:.*$//' \
        | grep -E '^[A-Za-z0-9][A-Za-z0-9.+_-]*$' \
        | sort -u > "$src" || true

    if [[ ! -s "$src" ]]; then
        warn "Keine Paketliste für Programmmigration gefunden."
    else
        info "Erzeuge konservative Tumbleweed-Anwendungsliste."

        while IFS= read -r p; do
            [[ -n "$p" ]] || continue
            rpm=""
            reason=""

            # Harte Ausschlüsse: keine Bibliotheken, Entwicklungs-/Debugpakete,
            # Kernel, Treiber, Firmware, Desktop-/Distro-Basis oder Paketmanager migrieren.
            case "$p" in
                lib*|*-dev|*-devel|*-dbg|*-dbgsym|*-debug*|*-doc|*-common|*-data|*-locale|*-l10n*|*-lang|*-langpack*|\
                linux-*|kernel*|grub*|shim*|nvidia*|cuda*|firmware*|mesa-*|xserver-xorg*|xorg*|wayland*|\
                mint*|ubuntu*|debian*|apt*|dpkg*|snapd|systemd*|init*|base-*|build-essential|\
                util-linux*|udev|sudo|passwd|login|cryptsetup*|lvm*|mdadm|plymouth*|\
                cinnamon*|muffin*|nemo*|lightdm*|slick-greeter|gdm*|sddm*|plasma*|kde-*|gnome-*|xfce4-*|\
                gcc*|g++*|make|cmake*|pkg-config|python3-*-dev|perl-base|bash|coreutils|findutils|grep|sed|awk|tar|gzip|xz-utils|\
                network-manager|network-manager-*|openssh-client|openssh-server|nfs-common|cifs-utils|samba*|avahi*|cups*|\
                fonts-*|fontconfig*|ca-certificates*|dbus*|policykit*|polkit*|pipewire*|pulseaudio*|alsa-*|bluez*)
                    reason="System/ABI/Desktop/Abhängigkeit"
                    ;;
            esac

            if [[ -n "$reason" ]]; then
                printf '%s\t%s\n' "$p" "$reason" >> "$skipped"
                printf '%s\t-\t%s: nicht automatisch migriert\n' "$p" "$reason" >> "$report"
                continue
            fi

            # Bewusst gepflegte Abbildung echter Benutzeranwendungen.
            # Identische Namen werden nur für bekannte Anwendungs-Pakete übernommen.
            case "$p" in
                firefox|firefox-esr) rpm="MozillaFirefox" ;;
                thunderbird) rpm="MozillaThunderbird" ;;
                libreoffice|libreoffice-*) rpm="libreoffice" ;;
                vlc) rpm="vlc" ;;
                darktable) rpm="darktable" ;;
                digikam) rpm="digikam" ;;
                gimp) rpm="gimp" ;;
                inkscape) rpm="inkscape" ;;
                rawtherapee) rpm="rawtherapee" ;;
                krita) rpm="krita" ;;
                audacity) rpm="audacity" ;;
                blender) rpm="blender" ;;
                kdenlive) rpm="kdenlive" ;;
                obs-studio) rpm="obs-studio" ;;
                handbrake|handbrake-gtk) rpm="handbrake-gtk" ;;
                ffmpeg) rpm="ffmpeg" ;;
                mpv) rpm="mpv" ;;
                smplayer) rpm="smplayer" ;;
                shotwell) rpm="shotwell" ;;
                simple-scan) rpm="simple-scan" ;;
                keepassxc) rpm="keepassxc" ;;
                filezilla) rpm="filezilla" ;;
                remmina) rpm="remmina" ;;
                virt-manager) rpm="virt-manager" ;;
                wireshark) rpm="wireshark" ;;
                gparted) rpm="gparted" ;;
                syncthing) rpm="syncthing" ;;
                rsync) rpm="rsync" ;;
                borgbackup) rpm="borgbackup" ;;
                restic) rpm="restic" ;;
                rclone) rpm="rclone" ;;
                p7zip|p7zip-full|7zip) rpm="7zip" ;;
                unrar) rpm="unrar" ;;
                yt-dlp) rpm="yt-dlp" ;;
                curl) rpm="curl" ;;
                wget) rpm="wget" ;;
                git) rpm="git" ;;
                vim|vim-gtk3) rpm="vim" ;;
                neovim) rpm="neovim" ;;
                mc) rpm="mc" ;;
                htop) rpm="htop" ;;
                btop) rpm="btop" ;;
                tmux) rpm="tmux" ;;
                tree) rpm="tree" ;;
                jq) rpm="jq" ;;
                sqlite3) rpm="sqlite3" ;;
                python3-pip) rpm="python3-pip" ;;
                flatpak) rpm="flatpak" ;;
                wine|wine64|wine32) rpm="wine" ;;
                winetricks) rpm="winetricks" ;;
                lutris) rpm="lutris" ;;
                steam-installer|steam) rpm="steam" ;;
                qbittorrent) rpm="qbittorrent" ;;
                transmission-gtk) rpm="transmission-gtk" ;;
                rhythmbox) rpm="rhythmbox" ;;
                easyeffects) rpm="easyeffects" ;;
                calibre) rpm="calibre" ;;
                stellarium) rpm="stellarium" ;;
                *)
                    printf '%s\tNicht in sicherer Anwendungsliste; manuell prüfen\n' "$p" >> "$skipped"
                    printf '%s\t-\tnicht automatisch zugeordnet\n' "$p" >> "$report"
                    continue
                    ;;
            esac

            # Doppelte Zielpakete vermeiden (z.B. mehrere LibreOffice-Unterpakete).
            if ! printf '%s\n' "${install_pkgs[@]:-}" | grep -Fxq -- "$rpm"; then
                if rpm -q "$rpm" >/dev/null 2>&1; then
                    printf '%s\t%s\tbereits installiert\n' "$p" "$rpm" >> "$report"
                else
                    install_pkgs+=("$rpm")
                    printf '%s\n' "$rpm" >> "$candidates"
                    printf '%s\t%s\tKandidat\n' "$p" "$rpm" >> "$report"
                fi
            else
                printf '%s\t%s\tbereits als Kandidat enthalten\n' "$p" "$rpm" >> "$report"
            fi
        done < "$src"
    fi

    count=${#install_pkgs[@]}
    echo
    info "Tumbleweed-Programmmigration: $count RPM-Anwendungspaket(e) als Kandidaten."
    if (( count > 0 )); then
        echo "----------------------------------------"
        printf '  %s\n' "${install_pkgs[@]}"
        echo "----------------------------------------"
        warn "Es werden bewusst KEINE Mint-Systempakete, Bibliotheken, Treiber oder Desktop-Basispakete übernommen."
        warn "Zypper installiert nur die für diese Anwendungen notwendigen Tumbleweed-Abhängigkeiten."
        echo
        if v20_confirm "Diese $count geprüften Anwendungspakete mit --no-recommends installieren"; then answer=ja; else answer=NEIN; fi
        if [[ "$answer" == "ja" ]]; then
            info "Repository-Metadaten aktualisieren ..."
            zypper --non-interactive refresh || {
                warn "Repository-Aktualisierung fehlgeschlagen. Keine Pakete installiert."
                return 1
            }

            echo
            info "Zypper-Trockenlauf zur Kontrolle:"
            if ! zypper install --dry-run --no-recommends -- "${install_pkgs[@]}"; then
                warn "Trockenlauf meldet ein Problem. Es wird NICHT automatisch installiert."
                warn "Kandidaten stehen in: $candidates"
            else
                echo
                if v20_confirm "Erfolgreichen Zypper-Probelauf ausführen"; then answer=ja; else answer=NEIN; fi
                if [[ "$answer" == "ja" ]]; then
                    if zypper --non-interactive install --no-recommends -- "${install_pkgs[@]}"; then
                        info "Ausgewählte Tumbleweed-Anwendungen installiert."
                    else
                        warn "Zypper konnte nicht alle ausgewählten Anwendungen installieren. Bericht prüfen."
                    fi
                else
                    info "RPM-Installation übersprungen."
                fi
            fi
        else
            info "RPM-Installation übersprungen."
        fi
    fi

    # V20 handles Flatpak scopes/remotes separately in v20_extra_software.
    for rpm in "${install_pkgs[@]}"; do
        if command rpm -q "$rpm" >/dev/null 2>&1; then
            printf '%s\t%s\tübernommen / installiert\n' "$rpm" "$rpm" >> "$report"
        else
            printf '%s\t%s\tnicht installiert / übersprungen / manuell prüfen\n' "$rpm" "$rpm" >> "$report"
        fi
    done

    echo
    info "Paketbericht: $report"
    info "Automatische Kandidaten: $candidates"
    info "Manuell zu prüfende Pakete: $skipped"
}

v19_home_restore() {
    local src="$BACKUP_DIR/$FILES_DIR_NAME" dest="$SOURCE_HOME" answer rc
    [[ -d "$src" && -d "$dest" && "$dest" != / && "$dest" != /root ]] || die "Ungültiges Home-Restore-Ziel."
    [[ "$SOURCE_UID" =~ ^[0-9]+$ && "$SOURCE_GID" =~ ^[0-9]+$ && "$SOURCE_UID" != 0 ]] || die "Ungültige Zielbenutzer-ID."
    [[ "$(realpath "$src")/" != "$(realpath "$dest")/"* && "$(realpath "$dest")/" != "$(realpath "$src")/"* ]] || die "Backup und Ziel überlappen."
    if [[ "$LIVE_MODE" != true ]] && pgrep -u "$SOURCE_UID" >/dev/null; then
        warn "Zielbenutzer hat laufende Prozesse. Bitte abmelden und von einer anderen Admin-Konsole starten."; return 1
    fi
    info "Tumbleweed-Home-Restore: $src → $dest; UID/GID $SOURCE_UID:$SOURCE_GID"
    warn "Vorhandene abweichende Dateien werden separat gesichert. Desktop-/Autostart-/Benutzerdienste bleiben im Backup zur manuellen Übernahme."
    read -r -p "Home übernehmen? [ja/NEIN]: " answer
    [[ "$answer" == ja ]] || return 1
    if findmnt -rn -o TARGET | awk -v h="$dest/" 'index($0,h)==1 {found=1} END {exit !found}'; then
        warn "Unter dem Ziel-Home sind Dateisysteme eingehängt. Vor Restore aushängen."; return 1
    fi
    local recovery="$(dirname "$dest")/.v19-before-restore-${SOURCE_USER}-${DATE_STR}"
    mkdir -m 700 "$recovery" || return 1
    # No delete; no recursive chown through mounts. Ownership applied only to copied entries.
    rsync -aHAXx --no-devices --no-specials \
        --chown="$SOURCE_UID:$SOURCE_GID" --backup --backup-dir="$recovery" \
        "${RESTORE_EXCLUDES[@]}" \
        --exclude=/.config/dconf/ --exclude=/.config/cinnamon/ \
        --exclude=/.local/share/cinnamon/ --exclude=/.config/autostart/ \
        --exclude=/.config/systemd/ --exclude=/.config/monitors.xml \
        --exclude=/.config/pulse/ --exclude=/.config/environment.d/ \
        --exclude=/.profile --exclude=/.xprofile --exclude=/.xsession \
        --exclude=/.local/share/flatpak/ "$src/" "$dest/" || { rc=$?; warn "Home-Restore unvollständig, rsync $rc"; return "$rc"; }
    info "Home übernommen. Vorherige Dateien: $recovery"
}

v20_svl_original() {
    need_cmd python3
    need_cmd systemd-escape
    need_cmd gpg
    local root; root="$(source_root_for_apps)"
    python3 - "$1" "$root" "$BACKUP_DIR/svl-config-v19" "$SOURCE_UID" "$SOURCE_GID" <<'PY'
import os, sys, re, json, pathlib, shutil, subprocess, datetime
# V20 private terminal passphrase input; independent of pinentry/agent TTY state.
def v20_gpg(arguments, data=None, encrypt=False):
    import getpass
    try:
        terminal = open('/dev/tty', 'w')
    except OSError:
        raise SystemExit('V20: Kein interaktives Terminal. Bitte direkt im Terminal mit sudo starten.')
    with terminal:
        secret = getpass.getpass('V20 Verschlüsselungspassphrase: ', stream=terminal)
        if not secret or len(secret.encode()) > 1024:
            raise SystemExit('V20: Passphrase leer oder zu lang; abgebrochen.')
        if encrypt and secret != getpass.getpass('Passphrase wiederholen: ', stream=terminal):
            raise SystemExit('V20: Passphrasen stimmen nicht überein; abgebrochen.')
    readfd, writefd = os.pipe()
    try:
        os.write(writefd, secret.encode() + b'\n')
        os.close(writefd); writefd = None
        del secret
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--pinentry-mode', 'loopback',
             '--passphrase-fd', str(readfd)] + arguments,
            input=data, stdout=subprocess.PIPE, pass_fds=(readfd,))
        if result.returncode:
            raise SystemExit('V20: GnuPG fehlgeschlagen (Passphrase/Datei prüfen); vorhandener Snapshot bleibt erhalten.')
        return result.stdout
    finally:
        os.close(readfd)
        if writefd is not None: os.close(writefd)
mode, root, archive, uid, gid = sys.argv[1:]
os.umask(0o077)
R=pathlib.Path(root); A=pathlib.Path(archive)
def log(s): print('[SVL] '+s)
def read(p):
    try: return p.read_text(errors='replace')
    except OSError: return ''
def valid(p):
    return p == '/SVL' or (p.startswith('/SVL/') and all(x not in ('','.','..') for x in p[1:].split('/')) and not any(c.isspace() for c in p))
def safe_dest(p):
    q=R/p.lstrip('/')
    if not q.resolve().is_relative_to(R.resolve()): raise ValueError('Pfad verlässt Zielroot: '+p)
    for parent in [q,*q.parents]:
        if parent == R: break
        if parent.is_symlink(): raise ValueError('Symlink-Ziel gesperrt: '+str(parent))
    return q
if mode == 'backup':
    A.mkdir(parents=True,exist_ok=True); os.chmod(A,0o700); os.chmod(A.parent,0o700)
    # Replace current snapshot, so removed definitions cannot return on a later restore.
    snapshot={'version':19,'paths':[], 'fstab':[], 'units':{}, 'credentials':{}}
    paths=set()
    for line in read(R/'etc/fstab').splitlines():
        f=line.split()
        if len(f)>=4 and not line.lstrip().startswith('#') and valid(f[1]):
            snapshot['fstab'].append(line); paths.add(f[1])
    for folder in ('etc/systemd/system',):
        d=R/folder
        if not d.is_dir(): continue
        for p in sorted(d.iterdir()):
            if p.suffix not in ('.mount','.automount') or p.is_symlink(): continue
            if any((R/v/p.name).exists() for v in ('usr/lib/systemd/system','lib/systemd/system')): continue
            content=read(p)
            where=re.findall(r'^Where=(.+)$',content,re.M)
            if not where or not valid(where[-1].strip()): continue
            paths.add(where[-1].strip())
            drops={}
            for base in ('usr/lib/systemd/system','etc/systemd/system'):
                dd=R/base/(p.name+'.d')
                if dd.is_dir():
                    for x in dd.glob('*.conf'): drops[x.name]=read(x)
            snapshot['units'][p.name]={'text':content,'dropins':drops}
    # mountinfo is read without touching /SVL or triggering an automount.
    for line in read(pathlib.Path('/proc/self/mountinfo')).splitlines():
        f=line.split(); p=f[4] if len(f)>4 else ''
        if root != '/':
            if not p.startswith(root.rstrip('/')+'/'): continue
            p=p[len(root.rstrip('/')):]
        if valid(p): paths.add(p)
    # Inspect only the underlying directory tree using a non-recursive bind mount;
    # child mounts are not cloned. No contents are copied.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='svl-structure-') as t:
        if subprocess.run(['mount','--bind',str(R),t],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            try:
                base=pathlib.Path(t)/'SVL'
                if base.is_dir() and not base.is_symlink():
                    for current, dirs, files in os.walk(base,followlinks=False):
                        dirs[:]=[d for d in dirs if not (pathlib.Path(current)/d).is_symlink()]
                        p='/'+str(pathlib.Path(current).relative_to(t))
                        if valid(p): paths.add(p)
            finally: subprocess.run(['umount',t],check=True)
        else: log('Struktur-Bind nicht möglich; Struktur aus fstab/Units/mountinfo erfasst.')
    snapshot['paths']=sorted(paths)
    texts=snapshot['fstab']+[v['text']+'\n'+'\n'.join(v['dropins'].values()) for v in snapshot['units'].values()]
    for text in texts:
        for p in re.findall(r'(?:credentials|cred)=([^,\s]+)',text):
            if p.startswith('/') and '..' not in pathlib.PurePosixPath(p).parts and not valid(p):
                q=R/p.lstrip('/')
                if 'SVL' not in q.resolve().parts and q.resolve().is_relative_to(R.resolve()) and q.is_file() and q.stat().st_size<1024*1024:
                    snapshot['credentials'][p]=read(q)
    # Retain manager-specific files for review; never execute restored scripts.
    manager=A/'manager-reference'; manager.mkdir(exist_ok=True)
    for folder in ('etc','usr/local/bin','usr/local/sbin'):
        d=R/folder
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and not p.is_symlink() and re.search(r'(client.*mount|mount.*manager)',p.name,re.I):
                    shutil.copy2(p,manager/(folder.replace('/','_')+'_'+p.name))
    tmp=A/'snapshot.gpg.tmp'
    v20_gpg(['--symmetric','--cipher-algo','AES256','--output',str(tmp)],data=json.dumps(snapshot,indent=2).encode(),encrypt=True)
    os.chmod(tmp,0o600); tmp.replace(A/'snapshot.json.gpg')
    log(f'{len(paths)} Mountpfade, {len(snapshot["units"])} Units; keine Freigabeinhalte kopiert.')
else:
    if (A/'snapshot.json.gpg').is_file():
        s=json.loads(v20_gpg(['--decrypt',str(A/'snapshot.json.gpg')]))
    elif (A/'snapshot.json').is_file():
        s=json.loads((A/'snapshot.json').read_text())
    else: log('Kein SVL-Backup vorhanden.'); sys.exit(0)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    import tempfile
    parent=safe_dest('/var/lib/home-backup'); parent.mkdir(parents=True,exist_ok=True)
    stage=pathlib.Path(tempfile.mkdtemp(prefix='svl-review-'+stamp+'-',dir=parent)); os.chmod(stage,0o700)
    (stage/'snapshot.json').write_text(json.dumps(s,indent=2)); os.chmod(stage/'snapshot.json',0o600)
    # Conservative reconstruction: only network mounts with declarative options.
    entries=[]
    for line in s['fstab']:
        f=line.split()
        if len(f)>=4: entries.append((f[1],f[0],f[2],f[3],None))
    for name,u in s['units'].items():
        if not name.endswith('.mount'): continue
        text=u['text']; fields=dict(re.findall(r'^(What|Where|Type|Options)=(.*)$',text,re.M))
        if u['dropins'] or re.search(r'^(Exec|Environment|RootDirectory|User|Group)',text,re.M):
            log(name+': Sonderkonfiguration/Drop-ins zur Prüfung abgelegt'); continue
        entries.append((fields.get('Where',''),fields.get('What',''),fields.get('Type',''),fields.get('Options','defaults'),name))
    # Restore only directory structure, never descend into existing mounted shares.
    live_mounts=[l.split()[4] for l in read(pathlib.Path('/proc/self/mountinfo')).splitlines() if len(l.split())>4]
    for path in s.get('paths',[]):
        if not valid(path): continue
        actual=str(R/path.lstrip('/'))
        if any(m!='/' and (actual==m or actual.startswith(m+'/')) for m in live_mounts if m.startswith(str(R/'SVL'))):
            log(path+': Struktur unter aktivem Mount übersprungen'); continue
        safe_dest(path).mkdir(parents=True,exist_ok=True)
    seen=set()
    for where,what,typ,opts,name in entries:
        if where in seen: continue
        seen.add(where)
        if not valid(where) or typ not in ('cifs','nfs','nfs4') or any(c in what+opts for c in '\n\r\t%'):
            log(where+': manuelle Prüfung (Typ/Pfad)'); continue
        if not ((typ=='cifs' and what.startswith('//')) or (typ.startswith('nfs') and ':' in what)):
            log(where+': ungültige Netzwerkquelle'); continue
        # Store credentials privately under a new controlled path, never overwrite /etc secrets.
        if re.search(r'(password|passwd|username|user)=',opts):
            log(where+': eingebettete Zugangsdaten manuell prüfen'); continue
        credential=re.search(r'(?:^|,)(?:credentials|cred)=([^,]+)',opts)
        if credential:
            secret=s.get('credentials',{}).get(credential.group(1))
            if secret is None: log(where+': referenzierte Zugangsdaten fehlen'); continue
            secretfile=stage/('credential-'+str(len(seen)))
            secretfile.write_text(secret); os.chmod(secretfile,0o600)
            targetsecret='/'+str(secretfile.relative_to(R))
            opts=re.sub(r'(^|,)(credentials|cred)=[^,]+',lambda m:m.group(1)+'credentials='+targetsecret,opts)
        if re.search(r'(?:^|,)(uid|gid)=',opts):
            if not uid.isdigit() or not gid.isdigit() or uid=='0':
                log(where+': Ziel-UID/GID ungültig'); continue
            opts=re.sub(r'(^|,)uid=[^,]+',lambda m:m.group(1)+'uid='+uid,opts)
            opts=re.sub(r'(^|,)gid=[^,]+',lambda m:m.group(1)+'gid='+gid,opts)
        if any(x in ('bind','rbind','remount','move') for x in opts.split(',')):
            log(where+': Bind-/Remount-Option manuell prüfen'); continue
        opts=','.join(x for x in opts.split(',') if not x.startswith('x-systemd.') and x not in ('auto','noauto','defaults'))
        if not re.fullmatch(r'[A-Za-z0-9_=,.:/+-]*',opts): log(where+': Optionen prüfen'); continue
        unit=subprocess.check_output(['systemd-escape','--path','--suffix=mount',where],text=True).strip()
        dest=safe_dest('/etc/systemd/system/'+unit)
        auto=dest.with_suffix('.automount')
        fstab=read(R/'etc/fstab')
        if dest.exists() or dest.is_symlink() or auto.exists() or auto.is_symlink() or any((R/base/unit).exists() for base in ('usr/lib/systemd/system','lib/systemd/system')) or any(len(f:=l.split())>1 and f[1]==where for l in fstab.splitlines() if not l.lstrip().startswith('#')):
            log(where+': vorhandene Zieldefinition bleibt erhalten'); continue
        if subprocess.run(['systemctl','--root',str(R),'is-enabled',unit],capture_output=True).returncode==0:
            log(where+': vorhandene Unit bleibt erhalten'); continue
        # Refuse paths below existing mounts: mkdir must never touch a remote share.
        live_mounts=[l.split()[4] for l in read(pathlib.Path('/proc/self/mountinfo')).splitlines() if len(l.split())>4]
        actual=str(R/where.lstrip('/'))
        if any(m!='/' and (actual==m or actual.startswith(m+'/')) for m in live_mounts if m.startswith(str(R/'SVL'))):
            log(where+': bereits eingehängt; manuell prüfen'); continue
        safe_dest(where).mkdir(parents=True,exist_ok=True)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text('[Unit]\nDescription=Restored SVL network mount\nWants=network-online.target\nAfter=network-online.target\n\n[Mount]\nWhat='+what+'\nWhere='+where+'\nType='+typ+'\nOptions='+('_netdev'+(','+opts if opts else ''))+'\nTimeoutSec=30\n')
        auto.write_text('[Unit]\nDescription=Restored SVL automount\n\n[Automount]\nWhere='+where+'\nTimeoutIdleSec=600\n\n[Install]\nWantedBy=multi-user.target\n')
        subprocess.run(['systemctl','--root',str(R),'enable',auto.name],check=True)
        log(where+': Automount für nächsten Start eingerichtet')
    log('Vollständige Originaldefinitionen, Zugangsdaten und Sonderfälle: '+str(stage))
    log('Nicht automatisch rekonstruierte Pfade nur nach Prüfung anlegen; keine Freigabe wurde geöffnet.')
PY
}

v19_migrate() {
    v19_is_suse || { warn "Diese Aktion benötigt openSUSE als Ziel."; return 1; }
    v19_home_restore || return $?
    v19_program_restore || warn "Programme noch offen; im gestarteten Zielsystem wiederholen."
    v19_svl restore || return $?
    info "Migration durchgeführt; Paketbericht und SVL-Prüfablage auf offene Aufgaben prüfen."
}

# ---- V20 Full System Migration ----
# All additions are defined before main; legacy backup layouts remain readable.
V20_REPORT=""
V20_CROSS=true
V20_SAME=false
v20_note() {
    printf '[V20 %s] %s\n' "$1" "$2"
    if [[ -n "$V20_REPORT" ]]; then printf '%s\t%s\n' "$1" "$2" >> "$V20_REPORT"; fi
}
v20_confirm() {
    if [[ "${V20_AUTO:-false}" == true ]]; then
        v20_note Info "Automatisch laut Restore-Plan: $*"
        return 0
    fi
    local answer
    read -r -p "$* [ja/NEIN]: " answer || return 1
    [[ "$answer" == ja ]]
}
v20_init_report() {
    umask 077
    mkdir -p "$BACKUP_DIR/reports" || return 1
    V20_REPORT="$BACKUP_DIR/reports/v20-$(date +%Y%m%d-%H%M%S)-$$.tsv"
    printf 'Status\tKomponente / Ergebnis\n' > "$V20_REPORT"
}
v20_compat() {
    local root src dst si di sv dv sa da
    root="$(source_root_for_apps)" || return 1
    src="$BACKUP_DIR/apps/os-release"; dst="$root/etc/os-release"
    if [[ ! -f "$src" ]]; then
        src="$BACKUP_DIR/migration-v20/inventory/etc_os-release"
        [[ -f "$src" ]] || src="$BACKUP_DIR/$META_DIR_NAME/os-release.source"
    fi
    si="$(read_os_release_value "$src" ID || true)"; di="$(read_os_release_value "$dst" ID || true)"
    sv="$(read_os_release_value "$src" VERSION_ID || true)"; dv="$(read_os_release_value "$dst" VERSION_ID || true)"
    sa="$(cat "$BACKUP_DIR/migration-v20/inventory/architecture" 2>/dev/null || true)"
    da="$(uname -m)"
    V20_CROSS=true; V20_SAME=false
    [[ -n "$si" && "$si" == "$di" ]] && V20_CROSS=false
    [[ "$V20_CROSS" == false && -n "$sv" && "$sv" == "$dv" && "$sa" == "$da" ]] && V20_SAME=true
    printf '\nV20 Full System Migration\nQuelle: %s %s (%s)\nZiel: %s %s (%s), Root: %s\n' "${si:-unbekannt}" "${sv:-rolling/unbekannt}" "${sa:-unbekannt}" "${di:-unbekannt}" "${dv:-rolling/unbekannt}" "$da" "$root"
    if [[ "$V20_SAME" == true ]]; then
        v20_note Info 'Gleiche Distribution, Version und Architektur; selektiver System-Restore möglich.'
    else
        v20_note 'manuell prüfen' 'Abweichende oder unbekannte Plattform: automatisch kompatibilitätsbewusster Migrationsmodus.'
    fi
}
v20_user() {
    [[ "$LIVE_MODE" != true ]] || return 125
    runuser -u "$SOURCE_USER" -- env HOME="$SOURCE_HOME" PATH="$SOURCE_HOME/.local/bin:$SOURCE_HOME/.npm-global/bin:$PATH" XDG_RUNTIME_DIR="/run/user/$SOURCE_UID" "$@"
}
v20_capture() {
    local file="$1"; shift
    if "$@" > "$file" 2> "$file.err"; then
        v20_note übernommen "Inventar $(basename "$file")"
    else
        v20_note 'nicht verfügbar' "Inventar $(basename "$file"); siehe .err (Live-System ggf. nur Referenz)."
    fi
}
# Global rsync gate, including legacy callers. No dereferencing, no /SVL,
# no traversal into nested mounts (also same-device bind mounts / automounts).
rsync() {
    local plan arg
    local -a guarded=()
    plan="$(mktemp)" || return 1
    if ! python3 - "$@" > "$plan" <<'PY_GUARD'
import os,sys,re
args=sys.argv[1:]
for a in args:
    if a in ('-L','--copy-links','--copy-dirlinks','--keep-dirlinks','-K','-k') or (a.startswith('-') and not a.startswith('--') and any(c in a[1:] for c in 'LKk')):
        raise SystemExit('V20: Symlink-Traversierung gesperrt')
def unescape(s): return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),s)
records=[l.split() for l in open('/proc/self/mountinfo') if len(l.split())>5]
mounts=[unescape(f[4]) for f in records]
svl_devices={f[2] for f in records if 'SVL' in unescape(f[4]).split('/') and f[2] != records[0][2]}
paths=[a for a in args if a.startswith('/')]
extra={'--exclude=SVL/***','--exclude=**/SVL/***','--exclude=system-connections/***','--exclude=**/system-connections/***','--exclude=proc/***','--exclude=sys/***','--exclude=dev/***','--exclude=run/***','--exclude=tmp/***','--one-file-system','--no-devices','--no-specials'}
for p in paths:
    # Option values beginning '/' may also appear; conservatively check them.
    p=os.path.abspath(p)
    if 'SVL' in p.split('/'):
        raise SystemExit('V20: /SVL als rsync-Pfad gesperrt')
    q=os.path.realpath(p)
    if 'SVL' in q.split('/'):
        raise SystemExit('V20: Symlink nach /SVL gesperrt')
    for m in mounts:
        if m.startswith(q.rstrip('/')+'/'):
            rel=os.path.relpath(m,q)
            # Escape rsync filter pattern metacharacters in actual mount names.
            rel=re.sub(r'([*?\[\\])',r'\\\1',rel)
            extra.add('--exclude=/'+rel+'/***')
            extra.add('--exclude=**/'+rel+'/***')
    # Reject a source that itself is a bind alias of an SVL subtree.
    for line in open('/proc/self/mountinfo'):
        f=line.split()
        if len(f)>5 and (q==unescape(f[4]) or q.startswith(unescape(f[4]).rstrip('/')+'/')) and ('SVL' in unescape(f[3]).split('/') or f[2] in svl_devices):
            raise SystemExit('V20: Bind-Alias von /SVL gesperrt')
for x in sorted(extra): sys.stdout.buffer.write(x.encode()+b'\0')
PY_GUARD
    then
        command rm -f "$plan"
        v20_note übersprungen 'rsync-Pfadsicherheitsprüfung fehlgeschlagen.'
        return 1
    fi
    mapfile -d '' -t guarded < "$plan"
    command rm -f "$plan"
    local -a original=()
    for arg in "$@"; do [[ "$arg" == -- ]] || original+=("$arg"); done
    command rsync "${original[@]}" "${guarded[@]}"
}
v20_copy() {
    local src="$1" dst="$2"
    [[ -e "$src" || -L "$src" ]] || { v20_note 'nicht verfügbar' "$src"; return 0; }
    mkdir -p "$(dirname "$dst")" || return 1
    if rsync -aHAX --numeric-ids -- "$src" "$dst"; then
        v20_note übernommen "$src"
    else
        v20_note 'manuell prüfen' "Kopie unvollständig: $src (ACL/xattrs/Dateisystem prüfen)"
        return 1
    fi
}
v20_backup() {
    local root b inv p name prefix
    root="$(source_root_for_apps)" || return 1
    v20_init_report || return 1
    filesystem_supports_unix_perms || { v20_note übersprungen "V20 benötigt ein Dateisystem mit Unix-Rechten (z.B. ext4); keine Secrets auf FAT/exFAT/NTFS."; return 1; }
    b="$BACKUP_DIR/migration-v20"; inv="$b/inventory"
    # A fresh snapshot avoids resurrecting removed units and packages.
    if [[ -e "$b" ]]; then mv "$b" "$b.previous-$(date +%s)-$$" || return 1; fi
    mkdir -p "$inv" "$b/payload" "$b/software" || return 1
    chmod 700 "$BACKUP_DIR" "$b"
    for p in etc/os-release etc/hostname etc/locale.conf etc/default/locale etc/timezone etc/passwd etc/group etc/shells; do
        [[ -f "$root/$p" ]] && cp -L -- "$root/$p" "$inv/${p//\//_}"
    done
    readlink "$root/etc/localtime" > "$inv/localtime-link" || true
    if [[ "$LIVE_MODE" == true ]]; then
        v20_note 'manuell prüfen' 'Offline-Quelle: laufender Kernel/Hardware sind Live-Umgebung; User-Paketlisten nach Start ergänzen.'
    fi
    if [[ "$LIVE_MODE" == true ]]; then
        if chroot "$root" uname -m > "$inv/architecture" 2>/dev/null; then :; else printf 'unknown\n' > "$inv/architecture"; fi
        # Kernel architecture describes the running live kernel; never imply same-platform offline.
        printf 'offline-unverified\n' > "$inv/architecture"
    else uname -m > "$inv/architecture"; fi
    v20_capture "$inv/kernel-diagnostic" uname -a
    v20_capture "$inv/locale-diagnostic" locale
    for p in lspci lsusb lsmod; do v20_capture "$inv/$p" "$p"; done
    v20_capture "$inv/dkms" dkms status
    v20_capture "$inv/inxi" inxi -Fxxxz
    v20_capture "$inv/ip-address" ip -brief address
    v20_capture "$inv/ip-route" ip route show
    v20_capture "$inv/nmcli" nmcli -f NAME,UUID,TYPE,DEVICE connection show
    v20_capture "$inv/printers" lpstat -p -d
    v20_capture "$inv/units" systemctl --root="$root" list-unit-files --no-pager
    if [[ "$LIVE_MODE" != true ]]; then
        v20_capture "$b/software/dpkg-selections" dpkg --get-selections
        v20_capture "$b/software/snap-list" snap list
        v20_capture "$b/software/pip-user.txt" v20_user python3 -m pip list --user --format=freeze
        v20_capture "$b/software/pipx.json" v20_user pipx list --json
        prefix="$(v20_user npm prefix -g 2>/dev/null || true)"
        if [[ "$prefix" == "$SOURCE_HOME/"* ]]; then
            v20_capture "$b/software/npm-user.json" v20_user npm list -g --depth=0 --json
        else v20_note übersprungen 'npm: globaler Prefix gehört nicht zum Benutzer-Home.'; fi
        for name in user system; do
            if [[ "$name" == user ]]; then
                v20_capture "$b/software/flatpak-$name-remotes" v20_user flatpak remotes --user --columns=name,url
                v20_capture "$b/software/flatpak-$name-apps" v20_user flatpak list --user --app --columns=ref,origin
            else
                v20_capture "$b/software/flatpak-$name-remotes" flatpak remotes --system --columns=name,url
                v20_capture "$b/software/flatpak-$name-apps" flatpak list --system --app --columns=ref,origin
            fi
        done
        v20_capture "$b/software/dconf.ini" v20_user dbus-run-session -- dconf dump /
        v20_capture "$b/software/crontab-user" crontab -u "$SOURCE_USER" -l
        v20_capture "$b/software/crontab-root" crontab -u root -l
    else
        [[ -x "$root/usr/bin/dpkg" ]] && v20_capture "$b/software/dpkg-selections" chroot "$root" dpkg --get-selections
    fi
    # Custom units: regular files only and no unit name existing in vendor folders.
    python3 - "$root" "$b" <<'PY_UNITS'
import os,sys,json,pathlib,re
r=pathlib.Path(sys.argv[1]); b=pathlib.Path(sys.argv[2]); units=[]
d=r/'etc/systemd/system'
if d.is_dir():
    for p in d.iterdir():
        if p.suffix not in ('.service','.timer','.mount','.automount','.socket','.target','.path'): continue
        if p.is_symlink() or not p.is_file(): continue
        if any((r/v/p.name).exists() for v in ('usr/lib/systemd/system','lib/systemd/system')): continue
        if re.search(r'^Where=/SVL(?:/|$)',p.read_text(errors='replace'),re.M): continue
        units.append(p.name)
(b/'custom-units.json').write_text(json.dumps(units))
PY_UNITS
    while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        v20_copy "$root/etc/systemd/system/$name" "$b/payload/etc/systemd/system/$name" || return 1
        [[ -d "$root/etc/systemd/system/$name.d" ]] && v20_copy "$root/etc/systemd/system/$name.d" "$b/payload/etc/systemd/system/$name.d"
    done < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))))' "$b/custom-units.json")
    for p in etc/apt/sources.list etc/apt/sources.list.d etc/apt/keyrings etc/apt/trusted.gpg etc/apt/trusted.gpg.d usr/share/keyrings usr/local/bin usr/local/sbin usr/local/share/fonts usr/local/share/themes usr/local/share/icons etc/cron.d etc/cron.daily etc/cron.weekly etc/cron.monthly etc/crontab etc/cups etc/udev/rules.d etc/samba/smb.conf etc/nfs.conf etc/idmapd.conf; do
        v20_copy "$root/$p" "$b/payload/$p" || return 1
    done
    # Offline cron remains reference, since spool formats differ by distro.
    [[ -d "$root/var/spool/cron" ]] && v20_copy "$root/var/spool/cron" "$b/cron-spool-reference"
    if [[ -d "$root/usr/share/keyrings" ]]; then v20_copy "$root/usr/share/keyrings" "$b/apt-keyrings-reference" || return 1; fi
    if v20_confirm 'Optionale NetworkManager-Profile privat sichern (enthalten möglicherweise Secrets)'; then
        if [[ -d "$root/etc/NetworkManager/system-connections" ]]; then
            need_cmd gpg
            python3 - "$root/etc/NetworkManager/system-connections" "$b/networkmanager.tar.gpg" <<'PY_NM_ENCRYPT' || return 1
import os,sys,subprocess,pathlib
# V20 private terminal passphrase input; independent of pinentry/agent TTY state.
def v20_gpg(arguments, data=None, encrypt=False):
    import getpass
    try:
        terminal = open('/dev/tty', 'w')
    except OSError:
        raise SystemExit('V20: Kein interaktives Terminal. Bitte direkt im Terminal mit sudo starten.')
    with terminal:
        secret = getpass.getpass('V20 Verschlüsselungspassphrase: ', stream=terminal)
        if not secret or len(secret.encode()) > 1024:
            raise SystemExit('V20: Passphrase leer oder zu lang; abgebrochen.')
        if encrypt and secret != getpass.getpass('Passphrase wiederholen: ', stream=terminal):
            raise SystemExit('V20: Passphrasen stimmen nicht überein; abgebrochen.')
    readfd, writefd = os.pipe()
    try:
        os.write(writefd, secret.encode() + b'\n')
        os.close(writefd); writefd = None
        del secret
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--pinentry-mode', 'loopback',
             '--passphrase-fd', str(readfd)] + arguments,
            input=data, stdout=subprocess.PIPE, pass_fds=(readfd,))
        if result.returncode:
            raise SystemExit('V20: GnuPG fehlgeschlagen (Passphrase/Datei prüfen); vorhandener Snapshot bleibt erhalten.')
        return result.stdout
    finally:
        os.close(readfd)
        if writefd is not None: os.close(writefd)

os.umask(0o077)
archive=subprocess.check_output(['tar','-C',sys.argv[1],'-cf','-','.'])
target=pathlib.Path(sys.argv[2]); temporary=target.with_suffix('.gpg.tmp')
v20_gpg(['--symmetric','--cipher-algo','AES256','--output',str(temporary)],data=archive,encrypt=True)
os.chmod(temporary,0o600); temporary.replace(target)
PY_NM_ENCRYPT
            v20_note übernommen 'NetworkManager-Profile verschlüsselt; Passphrase für Restore erforderlich.'
        else v20_note 'nicht verfügbar' 'NetworkManager-Profile'; fi
    fi
    if [[ -d "$root/opt" ]]; then
        for p in "$root/opt/"*; do
            [[ -d "$p" && ! -L "$p" ]] || continue
            if v20_confirm "Lokales Programm $p sichern"; then v20_copy "$p" "$b/payload/opt/$(basename "$p")" || return 1; fi
        done
    fi
    # Walk Home without crossing mounts or following symlinks (AppImages are in Home).
    python3 - "$SOURCE_HOME" "$b/software/appimages.json" <<'PY_APPS'
import os,sys,json,re
home=os.path.realpath(sys.argv[1]); result=[]
def dec(s):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),s)
mounts={dec(l.split()[4]) for l in open('/proc/self/mountinfo')}
for base,dirs,files in os.walk(home,followlinks=False):
    dirs[:]=[d for d in dirs if d!='SVL' and not os.path.islink(os.path.join(base,d)) and os.path.join(base,d) not in mounts]
    result.extend(os.path.relpath(os.path.join(base,f),home) for f in files if f.lower().endswith('.appimage'))
json.dump(result,open(sys.argv[2],'w'),indent=2)
PY_APPS
    v20_note Info 'AppImages im Home/ausgewählten /opt sind Dateien im Backup; externe Speicherorte manuell ergänzen.'
    printf 'V20 Full System Migration\n' > "$b/version"
    v20_note Info "Inventar und Komponenten: $b; Bericht: $V20_REPORT"
}
# Never let root dconf or a flattened legacy desktop export overwrite the user's settings.
save_full_desktop_state() { :; }
save_systemd_mounts_and_acls() { :; } # ACL/xattrs are in -aHAX; no recursive walk of network roots.
restore_full_desktop_state() { v20_desktop; }
restore_systemd_mounts_and_acls() { v20_svl_restore; }
v20_home() {
    local src="$BACKUP_DIR/files" dest="$SOURCE_HOME" recovery
    local -a opts=()
    v20_compat || return 1
    [[ -d "$src" && -d "$dest" && "$dest" != / && "$dest" != /root ]] || return 1
    [[ "$SOURCE_UID" =~ ^[0-9]+$ && "$SOURCE_GID" =~ ^[0-9]+$ && "$SOURCE_UID" != 0 ]] || return 1
    python3 - "$src" "$dest" <<'PY_OVERLAP' || return 1
import os,sys
s,d=map(os.path.realpath,sys.argv[1:]); c=os.path.commonpath([s,d])
if c in (s,d): raise SystemExit('Backup und Ziel überlappen')
PY_OVERLAP
    if [[ "$LIVE_MODE" != true ]] && pgrep -u "$SOURCE_UID" >/dev/null; then
        v20_note übersprungen 'Home: Benutzer hat laufende Prozesse. Abmelden und aus anderer Admin-Sitzung wiederholen.'; return 1
    fi
    if [[ "$V20_SAME" != true ]]; then
        opts+=(--exclude=/.config/dconf/ --exclude=/.config/autostart/ --exclude=/.config/systemd/ --exclude=/.config/environment.d/ --exclude=/.config/monitors.xml)
        v20_note 'manuell prüfen' 'Cross-Version/Distro: dconf separat; Autostart, User-Units, environment.d und Monitorprofil im Backup prüfen.'
    fi
    if { [[ "${V20_AUTO:-false}" == true ]] && [[ "$(stat -c %u "$src")" == "$SOURCE_UID" && "$(stat -c %g "$src")" == "$SOURCE_GID" ]]; } || { [[ "${V20_AUTO:-false}" != true ]] && v20_confirm "Originale numerische Eigentümer/ACL-IDs erhalten? Zielbenutzer $SOURCE_UID:$SOURCE_GID (bei NEIN Eigentümer auf Zielbenutzer abbilden)"; }; then
        opts+=(--numeric-ids)
    else
        opts+=(--chown="$SOURCE_UID:$SOURCE_GID")
        v20_note 'manuell prüfen' 'Eigentümer auf Zielbenutzer abgebildet; benannte ACL-Einträge mit alten IDs manuell prüfen.'
    fi
    v20_confirm "Home $src nach $dest übernehmen (abweichende Zieldateien separat sichern)" || { v20_note übersprungen Home; return 0; }
    recovery="$(dirname "$dest")/.v20-before-restore-${SOURCE_USER}-$(date +%s)-$$"
    mkdir -m 700 "$recovery" || return 1
    if rsync -aHAXx "${opts[@]}" --backup --backup-dir="$recovery" "${RESTORE_EXCLUDES[@]}" "$src/" "$dest/"; then
        v20_note übernommen "Home einschließlich Dotfiles/Fonts/MIME/Links; vorherige Dateien $recovery"
    else v20_note 'manuell prüfen' 'Home unvollständig (rsync-Fehler)'; return 1; fi
}
do_restore() { v20_home; }
v19_home_restore() { v20_home; }
v20_desktop() {
    local file="$BACKUP_DIR/migration-v20/software/dconf.ini"
    v20_compat || return 1
    [[ -s "$file" ]] || { v20_note 'nicht verfügbar' 'dconf-Dump'; return 0; }
    if [[ "${V20_AUTO:-false}" == true && "$V20_SAME" != true ]]; then v20_note 'manuell prüfen' 'dconf bei Plattformwechsel nur über Einzelkomponente übernehmen'; return 0; fi
    [[ "$LIVE_MODE" != true ]] || { v20_note 'manuell prüfen' 'dconf nach Start im Zielsystem übernehmen.'; return 0; }
    v20_confirm "dconf für $SOURCE_USER laden? Cross-Distro=$V20_CROSS, gleiche Version=$V20_SAME; kann Desktop-Einstellungen überschreiben" || { v20_note übersprungen dconf; return 0; }
    if v20_user dbus-run-session -- dconf load / < "$file"; then v20_note übernommen dconf
    else v20_note 'manuell prüfen' 'dconf fehlgeschlagen'; return 1; fi
}
v20_svl_restore() {
    v20_confirm 'SVL-Mountdefinitionen rekonstruieren und Automounts für nächsten Start aktivieren' || { v20_note übersprungen SVL; return 0; }
    if v20_svl_original restore; then v20_note übernommen 'SVL-Rekonstruktion ausgeführt; Detailmeldungen auf übersprungene Definitionen prüfen.'
    else v20_note 'manuell prüfen' 'SVL-Rekonstruktion fehlgeschlagen'; return 1; fi
}
v20_packages() {
    local mode answer root list p expected installed candidate spec
    local -a candidates=()
    v20_compat || return 1
    [[ "$LIVE_MODE" != true ]] || { v20_note 'manuell prüfen' 'Paketinstallation nach Boot ins Zielsystem ausführen; Offline-Home-Restore möglich.'; return 0; }
    if v19_is_suse; then
        v19_program_restore || { v20_note 'manuell prüfen' 'Zypper-Migration unvollständig; tumbleweed-packages.tsv prüfen'; return 1; }
        v20_note Info 'Zypper-Ergebnis: reports/tumbleweed-packages.tsv'
        return 0
    fi
    command -v apt-get >/dev/null || { v20_note 'nicht verfügbar' 'Unterstützter Paketmanager apt/zypper'; return 0; }
    mode=manual
    if [[ "$V20_SAME" == true ]] && v20_confirm 'Alle installierten dpkg-Pakete statt nur APT-manual als Kandidaten verwenden'; then mode=all; fi
    list="$BACKUP_DIR/apps/apt-manual.txt"
    [[ "$mode" == all ]] && list="$BACKUP_DIR/apps/dpkg-installed.tsv"
    [[ -s "$list" ]] || { v20_note 'nicht verfügbar' "$list"; return 0; }
    if [[ "$V20_SAME" == true ]]; then restore_original_apt_sources_if_compatible || return 1; fi
    v20_confirm 'APT-Paketindex des Zielsystems aktualisieren' || { v20_note übersprungen APT; return 0; }
    apt-get update || { v20_note 'manuell prüfen' 'apt-get update fehlgeschlagen'; return 1; }
    while IFS=$'\t' read -r p _; do
        [[ "$p" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9_-]+)?$ ]] || continue
        if [[ "$V20_SAME" != true && "$p" =~ ^(lib|linux-|linuxmint|mint|ubuntu|debian|grub|systemd|dkms|nvidia|firmware|xserver|cinnamon|lightdm) ]]; then
            v20_note übersprungen "System-/Distro-Paket $p"; continue
        fi
        expected="$(awk -F '\t' -v p="$p" '$1==p {print $2; exit}' "$BACKUP_DIR/apps/dpkg-installed.tsv" 2>/dev/null || true)"
        installed=""
        if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$p" 2>/dev/null || true)" == installed ]]; then
            installed="$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || true)"
        fi
        candidate="$(LC_ALL=C apt-cache policy "$p" | awk '/Candidate:/ {print $2; exit}')"
        spec="$(v20_package_spec "$p" "$expected" "$installed" "$candidate")" || continue
        [[ -n "$spec" ]] && candidates+=("$spec")
    done < "$list"
    [[ ${#candidates[@]} -gt 0 ]] || { v20_restore_holds; v20_audit_apt "$list"; return $?; }
    printf '%s\n' "${candidates[@]}" | sort -u > "$BACKUP_DIR/reports/v20-apt-candidates.txt"
    mapfile -t candidates < "$BACKUP_DIR/reports/v20-apt-candidates.txt"
    cat "$BACKUP_DIR/reports/v20-apt-candidates.txt"
    # --no-remove prevents a solver plan from deleting existing software.
    apt-get --simulate --no-remove install "${candidates[@]}" > "$BACKUP_DIR/reports/v20-apt-dry-run.txt" 2>&1 || { cat "$BACKUP_DIR/reports/v20-apt-dry-run.txt"; v20_note 'manuell prüfen' 'APT-Probelauf fehlgeschlagen'; return 1; }
    cat "$BACKUP_DIR/reports/v20-apt-dry-run.txt"
    v20_confirm 'Diesen APT-Installationsplan ausführen' || { v20_note übersprungen 'APT-Installationsplan'; return 0; }
    local -a approval_opts=()
    [[ "${V20_AUTO:-false}" == true ]] && approval_opts=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
    apt-get "${approval_opts[@]}" --no-remove install "${candidates[@]}" || { v20_note 'manuell prüfen' 'APT-Transaktion fehlgeschlagen; keine automatische Reparatur/Entfernung'; return 1; }
    # Selections are inventory; do not apply purge/deinstall states to a new OS.
    v20_restore_holds
    v20_note Info 'dpkg-selections: install/hold berücksichtigt; purge/deinstall bleiben im Bericht, keine Löschung auf neuem System.'
    v20_audit_apt "$list"
}
v20_flatpak_cmd() {
    local scope="$1"; shift
    if [[ "${V20_AUTO:-false}" == true && "${1:-}" == install ]]; then set -- "$@" --noninteractive -y; fi
    if [[ "$scope" == user ]]; then v20_user flatpak "$@" --user
    else flatpak "$@" --system; fi
}
v20_extra_software() {
    local b="$BACKUP_DIR/migration-v20/software" scope name url ref origin p ver prefix
    [[ "$LIVE_MODE" != true ]] || { v20_note 'manuell prüfen' 'Flatpak/Snap/pip/pipx/npm nach Zielsystem-Start ausführen.'; return 0; }
    if command -v flatpak >/dev/null; then
        for scope in user system; do
            [[ -f "$b/flatpak-$scope-remotes" ]] || continue
            while IFS=$'\t' read -r name url; do
                [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$url" == https://* && "$url" != *'@'* ]] || { v20_note 'manuell prüfen' "Flatpak Remote $name: URL prüfen"; continue; }
                if v20_confirm "Flatpak-Remote $scope/$name von $url hinzufügen (bestehenden beibehalten)"; then
                    v20_flatpak_cmd "$scope" remote-add --if-not-exists "$name" "$url" || { v20_note 'manuell prüfen' "Flatpak Remote $name"; continue; }
                fi
            done < "$b/flatpak-$scope-remotes"
            [[ -f "$b/flatpak-$scope-apps" ]] || continue
            while IFS=$'\t' read -r ref origin; do
                [[ "$ref" =~ ^app/[A-Za-z0-9._-]+/[A-Za-z0-9_-]+/[A-Za-z0-9._/-]+$ && "$origin" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || continue
                if v20_confirm "Flatpak $scope: $ref aus $origin installieren"; then
                    if v20_flatpak_cmd "$scope" install "$origin" "$ref"; then v20_note übernommen "Flatpak $ref"
                    else v20_note 'nicht verfügbar' "Flatpak $ref"; fi
                else v20_note übersprungen "Flatpak $ref"; fi
            done < "$b/flatpak-$scope-apps"
        done
    else v20_note 'nicht verfügbar' Flatpak; fi
    if [[ -s "$b/snap-list" ]] && command -v snap >/dev/null; then
        while read -r name ver _; do
            [[ "$name" == Name || ! "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]] && continue
            if snap list "$name" >/dev/null 2>&1; then v20_note übernommen "Snap vorhanden: $name"; continue; fi
            # No automatic --classic / --devmode; snap itself must reject these.
            if v20_confirm "Snap $name im stabilen Standardkanal installieren (ursprüngliche Version $ver nur Referenz)"; then
                if snap install "$name"; then v20_note übernommen "Snap $name"
                else v20_note 'manuell prüfen' "Snap $name; Kanal/Confinement prüfen"; fi
            else v20_note übersprungen "Snap $name"; fi
        done < "$b/snap-list"
    else v20_note 'nicht verfügbar' 'Snap oder Snap-Inventar'; fi
    # Parse structured inventories, never evaluate package strings as shell code.
    local parsed
    parsed="$(mktemp)" || return 1
    python3 - "$b" > "$parsed" <<'PY_PKG'
import json,pathlib,re,sys
b=pathlib.Path(sys.argv[1])
for line in (b/'pip-user.txt').read_text().splitlines() if (b/'pip-user.txt').exists() else []:
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9.+!-]+',line): print('pip\t'+line)
    elif line: print('review\t'+line.replace('\t',' '))
try:
    j=json.loads((b/'pipx.json').read_text())
    for v in j.get('venvs',{}).values():
        p=v['metadata']['main_package']['package']; ver=v['metadata']['main_package'].get('package_version','')
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',p) and re.fullmatch(r'[A-Za-z0-9.+!-]+',ver): print('pipx\t'+p+'=='+ver)
except (OSError,ValueError,KeyError,TypeError): pass
try:
    j=json.loads((b/'npm-user.json').read_text())
    for p,v in j.get('dependencies',{}).items():
        if p in ('npm','corepack'): continue
        ver=v.get('version','')
        if re.fullmatch(r'(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*',p) and re.fullmatch(r'[0-9][A-Za-z0-9.+-]*',ver): print('npm\t'+p+'@'+ver)
except (OSError,ValueError,TypeError): pass
PY_PKG
    while IFS=$'\t' read -r scope p; do
        [[ "$scope" == review ]] && { v20_note 'manuell prüfen' "pip nicht aus Registry: $p"; continue; }
        v20_confirm "$scope Benutzerpaket $p für $SOURCE_USER installieren (kann Installationscode ausführen)" || { v20_note übersprungen "$scope $p"; continue; }
        case "$scope" in
            pip) if v20_user python3 -m pip install --user "$p"; then v20_note übernommen "pip $p"; else v20_note 'manuell prüfen' "pip $p: Python-Version/externally-managed prüfen; kein --break-system-packages"; fi ;;
            pipx) if v20_user pipx install "$p"; then v20_note übernommen "pipx $p"; else v20_note 'manuell prüfen' "pipx $p"; fi ;;
            npm)
                prefix="$(v20_user npm prefix -g 2>/dev/null || true)"
                if [[ "$prefix" != "$SOURCE_HOME/"* ]]; then v20_note übersprungen "npm $p: Prefix liegt außerhalb Home"; continue; fi
                if v20_user npm install -g "$p"; then v20_note übernommen "npm $p"; else v20_note 'manuell prüfen' "npm $p"; fi ;;
        esac
    done < "$parsed"
    command rm -f "$parsed"
    v20_note Info 'AppImages werden als Home-/opt-Dateien übernommen; Ausführbarkeit/Architektur auf Ziel prüfen.'
}
# For system configuration, refuse all destination symlink ancestors and
# preserve conflicting files in a private recovery tree. Never restore vendor libs.
v20_system_copy() {
    local rel="$1" root src dest recovery
    root="$(source_root_for_apps)" || return 1
    src="$BACKUP_DIR/migration-v20/payload/$rel"; dest="$root/$rel"
    [[ -e "$src" ]] || { v20_note 'nicht verfügbar' "$rel"; return 0; }
    python3 - "$src" "$dest" <<'PY_DEST' || return 1
import pathlib,sys,os
s,d=map(pathlib.Path,sys.argv[1:])
for p in (d,*d.parents):
    if p.is_symlink(): raise SystemExit('Symlink im Systemziel gesperrt: '+str(p))
# Preflight existing destination ancestors of every source entry, before writing.
if s.is_dir():
    for base,dirs,files in os.walk(s,followlinks=False):
        for n in dirs+files:
            p=d/(pathlib.Path(base)/n).relative_to(s)
            for a in (p,*p.parents):
                if a.is_symlink(): raise SystemExit('Symlink im Systemziel gesperrt: '+str(a))
PY_DEST
    recovery="$root/var/lib/home-backup/v20-recovery-$(date +%s)-$$"
    mkdir -p "$recovery" "$(dirname "$dest")" || return 1
    chmod 700 "$recovery"
    if [[ -d "$src" ]]; then
        mkdir -p "$dest" || return 1
        rsync -aHAX --numeric-ids --backup --backup-dir="$recovery/$rel" "$src/" "$dest/" || return 1
    else
        rsync -aHAX --numeric-ids --backup --backup-dir="$recovery/$(dirname "$rel")" "$src" "$(dirname "$dest")/" || return 1
    fi
    v20_note übernommen "$rel; Konfliktkopien $recovery"
}
v20_system_components() {
    local component="$1" root p name state
    root="$(source_root_for_apps)" || return 1
    v20_compat || return 1
    if [[ "${V20_AUTO:-false}" == true && "$V20_SAME" != true ]]; then
        v20_note 'manuell prüfen' "$component: keine automatische Übernahme bei abweichender/unbekannter Plattform"
        return 0
    fi
    case "$component" in
        local)
            for p in usr/local/bin usr/local/sbin usr/local/share/fonts usr/local/share/themes usr/local/share/icons; do
                if v20_confirm "$p übernehmen? Plattformgleich=$V20_SAME; lokale Binärdateien vorher prüfen"; then v20_system_copy "$p" || return 1
                else v20_note übersprungen "$p"; fi
            done
            for p in "$BACKUP_DIR/migration-v20/payload/opt/"*; do
                [[ -d "$p" ]] || continue
                if v20_confirm "Ausgewähltes /opt/$(basename "$p") übernehmen? Architektur/Abhängigkeiten prüfen"; then v20_system_copy "opt/$(basename "$p")" || return 1; fi
            done ;;
        units)
            while IFS= read -r name; do
                [[ "$name" =~ ^[A-Za-z0-9_.@:-]+\.(service|timer|mount|automount|socket|target|path)$ ]] || { v20_note 'manuell prüfen' "Unitname $name"; continue; }
                if [[ -e "$root/usr/lib/systemd/system/$name" || -e "$root/lib/systemd/system/$name" ]]; then v20_note übersprungen "Vendor-Unit $name"; continue; fi
                if grep -qE '^Where=/SVL(/|$)' "$BACKUP_DIR/migration-v20/payload/etc/systemd/system/$name"; then v20_note übersprungen "SVL-Unit $name: separater Mount-Restore"; continue; fi
                if [[ "${V20_AUTO:-false}" == true ]]; then
                    if [[ -d "$BACKUP_DIR/migration-v20/payload/etc/systemd/system/$name.d" ]] || ! systemd-analyze verify "$BACKUP_DIR/migration-v20/payload/etc/systemd/system/$name" >> "$V20_REPORT" 2>&1; then
                        v20_note 'manuell prüfen' "Unit $name: Drop-ins vorhanden oder Validierung fehlgeschlagen"; continue
                    fi
                fi
                printf '\nCustom-Unit %s, Originalzustand:\n' "$name"
                awk -v n="$name" '$1==n {print}' "$BACKUP_DIR/migration-v20/inventory/units"
                cat "$BACKUP_DIR/migration-v20/payload/etc/systemd/system/$name"
                v20_confirm "Custom-Unit $name übernehmen? Exec-Pfade/Benutzer/Abhängigkeiten geprüft" || { v20_note übersprungen "$name"; continue; }
                v20_system_copy "etc/systemd/system/$name" || return 1
                [[ -d "$BACKUP_DIR/migration-v20/payload/etc/systemd/system/$name.d" ]] && v20_system_copy "etc/systemd/system/$name.d"
                state="$(awk -v n="$name" '$1==n {print $2; exit}' "$BACKUP_DIR/migration-v20/inventory/units")"
                if [[ "${V20_AUTO:-false}" == true && "$state" != enabled ]]; then
                    v20_note übersprungen "Aktivierung $name: Originalzustand $state"; continue
                fi
                if v20_confirm "Custom-Unit $name für nächsten Boot aktivieren (kein Start jetzt)"; then
                    systemctl --root="$root" enable "$name" || v20_note 'manuell prüfen' "Aktivierung $name fehlgeschlagen"
                fi
            done < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))))' "$BACKUP_DIR/migration-v20/custom-units.json") ;;
        cron)
            for p in etc/crontab etc/cron.d etc/cron.daily etc/cron.weekly etc/cron.monthly; do
                if v20_confirm "$p übernehmen? Befehle und Benutzer auf Ziel geprüft"; then v20_system_copy "$p" || return 1; fi
            done
            if [[ "$LIVE_MODE" != true ]]; then
                for name in user root; do
                    p="$BACKUP_DIR/migration-v20/software/crontab-$name"
                    [[ -s "$p" ]] || continue
                    cat "$p"
                    if v20_confirm "Crontab $name ersetzen"; then
                        local target_user="$SOURCE_USER"
                        [[ "$name" == root ]] && target_user=root
                        crontab -u "$target_user" -l > "$BACKUP_DIR/reports/crontab-before-$target_user-$(date +%s)" 2>/dev/null || true
                        crontab -u "$target_user" "$p" || return 1
                        v20_note übernommen "Crontab $target_user"
                    fi
                done
            else v20_note 'manuell prüfen' 'User-Crontabs nach Boot über crontab installieren; Spool nicht blind kopieren.'; fi ;;
        config)
            for p in etc/cups etc/udev/rules.d etc/samba/smb.conf etc/nfs.conf etc/idmapd.conf; do
                if [[ "${V20_AUTO:-false}" == true && "$LIVE_MODE" != true && "$p" == etc/cups ]] && systemctl is-active --quiet cups.service; then
                    v20_note 'manuell prüfen' 'CUPS läuft: Konfiguration nicht während des Betriebs ersetzen'; continue
                fi
                if [[ "$V20_SAME" != true ]]; then v20_note 'manuell prüfen' "$p: Cross-Plattform nur Referenz in migration-v20/payload"; continue; fi
                if v20_confirm "$p übernehmen (vorhandene Einstellungen ersetzen, Dienst vorher stoppen)"; then v20_system_copy "$p" || return 1; fi
            done ;;
        identity)
            v20_identity_restore || return 1 ;;
        network)
            v20_network_restore || return 1 ;;
    esac
}
v20_restore_menu_manual() {
    local choice component
    v20_init_report || return 1
    v20_compat || return 1
    printf '\n1) Daten (Home)\n2) Standard-Restore\n3) Vollständiger System-Restore\n4) Mint -> Tumbleweed Migration\n5) Komponenten auswählen\n0) Zurück\n'
    read -r -p 'Auswahl: ' choice || return 1
    case "$choice" in
        0) return 0 ;;
        1) v20_home ;;
        2|3|4)
            if [[ "$choice" == 4 ]] && ! v19_is_suse; then v20_note übersprungen 'Ziel ist nicht openSUSE'; return 1; fi
            v20_confirm 'Diesen Restore beginnen? Jede systemweite Komponente wird zusätzlich bestätigt' || return 0
            v20_home || return 1
            v20_packages || v20_note 'manuell prüfen' 'Paket-Restore unvollständig'
            v20_extra_software || v20_note 'manuell prüfen' 'Zusatzsoftware unvollständig'
            v20_desktop || v20_note 'manuell prüfen' 'Desktop unvollständig'
            if [[ "$choice" != 2 ]]; then
                for component in identity local units cron config network; do v20_system_components "$component" || v20_note 'manuell prüfen' "$component unvollständig"; done
                v20_svl_restore || v20_note 'manuell prüfen' 'SVL unvollständig'
            fi ;;
        5)
            printf 'Komponente: home packages software desktop local units cron config identity network svl\n'
            read -r component || return 1
            case "$component" in
                home) v20_home;; packages) v20_packages;; software) v20_extra_software;; desktop) v20_desktop;; svl) v20_svl_restore;;
                local|units|cron|config|identity|network) v20_system_components "$component";;
                *) v20_note übersprungen 'Unbekannte Komponente'; return 1;;
            esac ;;
        *) return 1 ;;
    esac
    v20_note Info "Restore-Bericht: $V20_REPORT"
}
do_full_restore() { v20_restore_menu; }
v19_migrate() { v20_restore_menu; }
do_program_restore() { v20_init_report && v20_packages && v20_extra_software; }


v19_svl() {
    if [[ "$1" == restore ]]; then v20_svl_restore
    else v20_svl_original "$@"; fi
}
v20_identity_restore() {
    local b="$BACKUP_DIR/migration-v20/inventory" name uid gid shell group member row
    [[ "$LIVE_MODE" != true ]] || { v20_note 'manuell prüfen' 'Benutzer/Gruppen nach Start im Zielsystem anlegen.'; return 0; }
    [[ -f "$b/etc_passwd" && -f "$b/etc_group" ]] || { v20_note 'nicht verfügbar' Benutzerinventar; return 0; }
    awk -F: '$3>=1000 && $3<60000 {printf "%s UID=%s GID=%s Shell=%s\n",$1,$3,$4,$7}' "$b/etc_passwd"
    if [[ "${V20_AUTO:-false}" == true ]]; then name="$SOURCE_USER"
    else read -r -p 'Benutzer für kontrollierte Anlage/Gruppenabgleich (leer=überspringen): ' name || return 1; fi
    [[ -n "$name" ]] || return 0
    [[ "$name" =~ ^[a-z_][a-z0-9_-]*$ ]] || return 1
    row="$(awk -F: -v n="$name" '$1==n && $3>=1000 && $3<60000 {print $3":"$4":"$7}' "$b/etc_passwd")"
    IFS=: read -r uid gid shell <<< "$row"
    [[ "$uid" =~ ^[0-9]+$ && "$gid" =~ ^[0-9]+$ && "$shell" == /* && "$shell" != *'/../'* && -x "$shell" ]] || { v20_note 'manuell prüfen' 'UID/GID oder Zielshell ungültig/nicht vorhanden'; return 1; }
    if getent passwd "$name" >/dev/null; then
        if [[ "$(id -u "$name")" != "$uid" || "$(id -g "$name")" != "$gid" ]]; then
            v20_note 'manuell prüfen' "ID-Konflikt $name: keine automatische Umnummerierung bestehender Benutzer"; return 1
        fi
    else
        getent passwd "$uid" >/dev/null && { v20_note 'manuell prüfen' "UID $uid bereits belegt"; return 1; }
        group="$(awk -F: -v g="$gid" '$3==g {print $1; exit}' "$b/etc_group")"
        [[ "$group" =~ ^[a-z_][a-z0-9_-]*$ ]] || return 1
        if getent group "$gid" >/dev/null; then
            [[ "$(getent group "$gid" | cut -d: -f1)" == "$group" ]] || { v20_note 'manuell prüfen' "GID $gid anderweitig belegt"; return 1; }
        elif getent group "$group" >/dev/null; then v20_note 'manuell prüfen' "Gruppenname $group anderweitig belegt"; return 1
        else
            v20_confirm "Gruppe $group mit GID $gid anlegen" || return 0
            groupadd -g "$gid" "$group" || return 1
        fi
        v20_confirm "Benutzer $name UID=$uid GID=$gid Shell=$shell Home=/home/$name anlegen (Passwort bleibt gesperrt)" || return 0
        useradd -m -u "$uid" -g "$gid" -s "$shell" "$name" || return 1
        v20_note übernommen "Benutzer $name angelegt; Passwort separat mit passwd setzen."
    fi
    while IFS=: read -r group _ gid member; do
        [[ ",$member," == *",$name,"* ]] || continue
        [[ "$group" =~ ^[a-z_][a-z0-9_-]*$ ]] || continue
        if ! getent group "$group" >/dev/null; then v20_note 'manuell prüfen' "Zusatzgruppe $group auf Ziel nicht vorhanden"; continue; fi
        if v20_confirm "$name der Zielgruppe $group hinzufügen (kann Administrator-/Geräterechte gewähren)"; then
            usermod -aG "$group" "$name" || return 1
            v20_note übernommen "Gruppe $group für $name"
        fi
    done < "$b/etc_group"
}
v20_network_restore() {
    local file="$BACKUP_DIR/migration-v20/networkmanager.tar.gpg" root
    [[ -f "$file" ]] || { v20_note 'nicht verfügbar' 'Verschlüsseltes NetworkManager-Backup'; return 0; }
    root="$(source_root_for_apps)" || return 1
    v20_confirm 'NetworkManager-Profile entschlüsseln und fehlende Profile mit 0600 übernehmen? Interfaces/Plugins müssen auf Ziel passen; vorhandene bleiben erhalten' || { v20_note übersprungen NetworkManager; return 0; }
    python3 - "$file" "$root" <<'PY_NM'
import pathlib,sys,subprocess,tarfile,io,os
# V20 private terminal passphrase input; independent of pinentry/agent TTY state.
def v20_gpg(arguments, data=None, encrypt=False):
    import getpass
    try:
        terminal = open('/dev/tty', 'w')
    except OSError:
        raise SystemExit('V20: Kein interaktives Terminal. Bitte direkt im Terminal mit sudo starten.')
    with terminal:
        secret = getpass.getpass('V20 Verschlüsselungspassphrase: ', stream=terminal)
        if not secret or len(secret.encode()) > 1024:
            raise SystemExit('V20: Passphrase leer oder zu lang; abgebrochen.')
        if encrypt and secret != getpass.getpass('Passphrase wiederholen: ', stream=terminal):
            raise SystemExit('V20: Passphrasen stimmen nicht überein; abgebrochen.')
    readfd, writefd = os.pipe()
    try:
        os.write(writefd, secret.encode() + b'\n')
        os.close(writefd); writefd = None
        del secret
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--pinentry-mode', 'loopback',
             '--passphrase-fd', str(readfd)] + arguments,
            input=data, stdout=subprocess.PIPE, pass_fds=(readfd,))
        if result.returncode:
            raise SystemExit('V20: GnuPG fehlgeschlagen (Passphrase/Datei prüfen); vorhandener Snapshot bleibt erhalten.')
        return result.stdout
    finally:
        os.close(readfd)
        if writefd is not None: os.close(writefd)
os.umask(0o077)
d=pathlib.Path(sys.argv[2])/'etc/NetworkManager/system-connections'
for p in (d,*d.parents):
    if p.is_symlink(): raise SystemExit('NetworkManager-Ziel enthält Symlink')
data=v20_gpg(['--decrypt',sys.argv[1]])
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    entries=[]
    for m in t:
        name=m.name.removeprefix('./')
        if m.isdir() and name in ('','.'): continue
        if not m.isfile() or '/' in name or name in ('','.','..'): raise SystemExit('Ungültiges Profil im Archiv')
        entries.append((name,t.extractfile(m).read()))
    d.mkdir(parents=True,exist_ok=True)
    for name,content in entries:
        p=d/name
        try: fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError: print('Übersprungen, vorhanden: '+name); continue
        with os.fdopen(fd,'wb') as f:f.write(content)
        print('Übernommen: '+name)
PY_NM
    local rc=$?
    if [[ "$rc" == 0 ]]; then v20_note übernommen 'NetworkManager-Import geprüft/ausgeführt; bestehende Profile beibehalten. Aktivierung separat nach Prüfung.'
    else v20_note 'manuell prüfen' 'NetworkManager-Import fehlgeschlagen'; fi
    return "$rc"
}


restore_original_apt_sources_if_compatible() {
    v20_compat || return 1
    [[ "$V20_SAME" == true ]] || { v20_note übersprungen 'APT-Quellen: Distribution/Version/Architektur nicht identisch'; return 0; }
    v20_confirm 'Originale APT-Quellen und Keyrings übernehmen? Damit wird den signierenden Schlüsseln vertraut' || return 0
    local p
    for p in etc/apt/sources.list etc/apt/sources.list.d etc/apt/keyrings etc/apt/trusted.gpg etc/apt/trusted.gpg.d usr/share/keyrings; do
        v20_system_copy "$p" || return 1
    done
}


v20_restore_holds() {
    local file="$BACKUP_DIR/migration-v20/software/dpkg-selections" p state
    [[ -f "$file" && "$V20_SAME" == true ]] || return 0
    while read -r p state; do
        [[ "$p" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9_-]+)?$ ]] || continue
        case "$state" in
            hold)
                if v20_confirm "Originalen APT-Hold für $p wieder setzen (verhindert Updates)"; then
                    if apt-mark hold "$p"; then v20_note übernommen "APT-Hold $p"; else v20_note 'manuell prüfen' "APT-Hold $p"; fi
                else v20_note übersprungen "APT-Hold $p"; fi ;;
            purge|deinstall) v20_note übersprungen "dpkg-Selection $state für $p: keine Pakete automatisch entfernen" ;;
        esac
    done < "$file"
}

# Automatic restore is scoped to this subshell; approval cannot leak to menus.
v20_restore_menu() (
    local choice component rc=0
    local V20_AUTO=false
    v20_init_report || return 1
    v20_compat || return 1
    printf '\nAutomatische Wiederherstellung\n1) Daten (Home)\n2) Standard (Home, Programme, Desktop)\n3) Vollständig (empfohlen)\n4) Mint -> Tumbleweed\n5) Einzelkomponenten / manuelle Auswahl\n6) Nur Programme reparieren / Versionen prüfen\n0) Zurück\n'
    read -r -p 'Auswahl [3]: ' choice || return 1
    choice="${choice:-3}"
    case "$choice" in
        0) return 0;;
        5) v20_restore_menu_manual; return $?;;
        1|2|3|4|6) :;;
        *) return 1;;
    esac
    if [[ "$choice" == 4 ]] && ! v19_is_suse; then v20_note übersprungen 'Ziel ist nicht openSUSE'; return 1; fi
    [[ -d "$BACKUP_DIR/files" && -d "$SOURCE_HOME" ]] || { v20_note 'nicht verfügbar' 'Backup-Home oder Ziel-Home fehlt'; return 1; }
    [[ "$SOURCE_UID" =~ ^[0-9]+$ && "$SOURCE_GID" =~ ^[0-9]+$ && "$SOURCE_UID" != 0 ]] || return 1
    if [[ "$choice" != 6 && "$LIVE_MODE" != true ]] && pgrep -u "$SOURCE_UID" >/dev/null; then
        v20_note 'manuell prüfen' 'Zielbenutzer ist aktiv. Bitte abmelden und von einer anderen Admin-Konsole starten.'; return 1
    fi
    printf '\nGeprüfter Restore-Plan\nBackup: %s\nZiel-Home: %s\nZielbenutzer: %s (%s:%s)\n' "$BACKUP_DIR" "$SOURCE_HOME" "$SOURCE_USER" "$SOURCE_UID" "$SOURCE_GID"
    if [[ "$choice" == 6 ]]; then printf 'Nur Programme prüfen/reparieren; Home und Desktop bleiben unverändert.\n'
    else printf 'Home: übernehmen, Konfliktkopien erstellen, nichts löschen.\nUID/GID: bei gleichen IDs erhalten, sonst Eigentümer auf Zielbenutzer abbilden.\n'; fi
    if [[ "$choice" != 1 ]]; then
        printf 'Programme: verfügbare Pakete aus Zielquellen; Probelauf muss erfolgreich sein.\nFlatpak/Snap/pip/pipx/npm: gesicherte, validierte Pakete installieren.\n'
        if [[ "$V20_SAME" == true ]]; then
            printf 'Gleiche Plattform: vollständige Paketliste und APT-Quellen/Schlüssel übernehmen.\n'
            [[ "$choice" == 6 ]] || printf 'dconf übernehmen.\n'
            if [[ "$choice" == 3 || "$choice" == 4 ]]; then
                printf 'Zusätzlich: Benutzerabgleich, lokale Programme, geprüfte Custom-Units, Cron, lokale Konfiguration, optionale Netzwerkprofile und SVL.\nCustom-Units: nur ursprünglich aktivierte Units aktivieren; nicht sofort starten.\n'
            fi
        else
            printf 'Migration: keine alten APT-Quellen, kein automatischer dconf-/Systemkonfigurationsimport.\nUnklare lokale Programme, Units, Cron und Identitäten verbleiben zur Prüfung im Bericht.\n'
        fi
        printf 'Paketmanager behalten bestehende Konfigurationsdateien; unbekannte Pakete werden gemeldet.\n'
    fi
    printf 'Verschlüsselte Archive benötigen weiterhin ihre Passphrase.\nBericht: %s\n' "$V20_REPORT"
    v20_confirm 'Diesen Plan jetzt selbstständig ausführen' || return 0
    V20_AUTO=true
    if [[ "$choice" != 6 ]]; then v20_home || return 1; fi
    if [[ "$choice" != 1 ]]; then
        v20_packages || { rc=1; v20_note 'manuell prüfen' 'Paket-Restore unvollständig'; }
        v20_extra_software || { rc=1; v20_note 'manuell prüfen' 'Zusatzsoftware unvollständig'; }
        if [[ "$choice" != 6 ]]; then v20_desktop || { rc=1; v20_note 'manuell prüfen' 'Desktop-Restore unvollständig'; }; fi
        if [[ "$choice" == 3 || "$choice" == 4 ]]; then
            for component in identity local units cron config network; do
                v20_system_components "$component" || { rc=1; v20_note 'manuell prüfen' "$component unvollständig"; }
            done
            v20_svl_restore || { rc=1; v20_note 'manuell prüfen' 'SVL unvollständig'; }
        fi
    fi
    v20_note Info "Automatik beendet, Fehlerstatus=$rc; übernommene und offene Punkte: $V20_REPORT"
    return "$rc"
)


# Save actual contents; atomic replacement also repairs a stale destination symlink.
v20_save_os_release() {
    local src="$1" dest="$2" tmp
    tmp="$(mktemp "${dest}.XXXXXX")" || return 1
    if cp -L -- "$src" "$tmp" && mv -fT -- "$tmp" "$dest"; then return 0; fi
    command rm -f -- "$tmp"
    return 1
}
# stdout is a validated APT install specification only; diagnostics go to stderr.
v20_package_spec() {
    local p="$1" expected="$2" installed="$3" candidate="$4"
    if [[ "$V20_SAME" == true && -n "$expected" ]]; then
        if [[ -n "$installed" ]] && dpkg --compare-versions "$installed" ge "$expected"; then
            v20_note übernommen "APT $p: Quelle=$expected Ziel=$installed" >&2; return 0
        fi
        if LC_ALL=C apt-cache madison "$p" | awk -F '|' -v v="$expected" '{gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2==v) found=1} END {exit !found}'; then
            printf '%s=%s\n' "$p" "$expected"; return 0
        fi
        if [[ -n "$candidate" && "$candidate" != '(none)' ]] && dpkg --compare-versions "$candidate" ge "$expected"; then
            printf '%s\n' "$p"; return 0
        fi
        v20_note 'manuell prüfen' "APT $p: benötigt mindestens $expected; installiert=${installed:-fehlt}, verfügbar=${candidate:-fehlt}. Originalquelle/Signaturschlüssel prüfen." >&2
        return 1
    fi
    if [[ -n "$installed" ]]; then
        v20_note Info "APT $p: Ziel=$installed, Quelle=${expected:-unbekannt}; plattformübergreifend keine Versionsgleichheit zugesichert" >&2
        return 0
    fi
    if [[ -n "$candidate" && "$candidate" != '(none)' ]]; then printf '%s\n' "$p"
    else v20_note 'nicht verfügbar' "APT $p: Quelle=${expected:-unbekannt}; Paketquelle/Installationsdatei fehlt" >&2; return 1; fi
}
v20_audit_apt() {
    local list="$1" p expected actual status failures=0
    local report="$BACKUP_DIR/reports/v20-software-versions.tsv"
    printf 'Paket\tQuellversion\tZielversion\tErgebnis\n' > "$report"
    while IFS=$'\t' read -r p _; do
        [[ "$p" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9_-]+)?$ ]] || continue
        expected="$(awk -F '\t' -v p="$p" '$1==p {print $2; exit}' "$BACKUP_DIR/apps/dpkg-installed.tsv" 2>/dev/null || true)"
        actual=''
        if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$p" 2>/dev/null || true)" == installed ]]; then
            actual="$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || true)"
        fi
        status='vorhanden; Version manuell vergleichen'
        if [[ -z "$actual" ]]; then status=FEHLT; failures=$((failures+1))
        elif [[ "$V20_SAME" == true && -n "$expected" ]]; then
            if dpkg --compare-versions "$actual" lt "$expected"; then status='ZU ALT'; failures=$((failures+1))
            elif dpkg --compare-versions "$actual" eq "$expected"; then status=identisch
            else status='neuer als Quelle'; fi
        fi
        printf '%s\t%s\t%s\t%s\n' "$p" "$expected" "${actual:-fehlt}" "$status" >> "$report"
    done < "$list"
    v20_note Info "Software-Abgleich: $report; fehlend/zu alt: $failures"
    [[ "$failures" == 0 ]]
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if [[ "${1:-}" == --version ]]; then echo 'V20 Full System Migration'; exit 0; fi
    main "$@"
fi
