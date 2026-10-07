#!/usr/bin/env bash
# ====================================================================
# Client-Mount-Manager V2.3
# Systemweite SMB/CIFS- und NFS-Mounts mit systemd .mount + .automount
# Standard: Automount, robust bei schlafendem/offline Server
# ====================================================================

set -o errexit
set -o pipefail
set -o nounset

VERSION="2.3.4"
MOUNT_BASE="/SVL"
SYSTEMD_DIR="/etc/systemd/system"
CRED_DIR="${SYSTEMD_DIR}/credentials"
CONFIG_DIR="/etc/client-mount-manager"
SERVER_CONF="${CONFIG_DIR}/servers.conf"
DEFAULT_PROFILE="SVL"
SERVER_IP_DEFAULT="server.example.org"
AUTOMOUNT_IDLE_TIMEOUT="10min"
SMB_VERSION="3.1.1"
NFS_VERSION="4.2"

LOG_DIR="/var/log/client-mount-manager"
RUN_DIR="/run/client-mount-manager"
BACKUP_DIR="/var/backups/client-mount-manager"
EXPORT_DIR="/var/backups/client-mount-manager/export"
LOG_FILE="${LOG_DIR}/client-mount-manager.log"
LOCK_FILE="${RUN_DIR}/client-mount-manager.lock"

esc_base="$(systemd-escape --path "$MOUNT_BASE")"

# --------------------------------------------------------------------
# Basis / Rechte / Logging
# --------------------------------------------------------------------
need_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Rootrechte erforderlich. Starte mit sudo:"
    echo "sudo $0 ${*:-}"
    exit 1
  fi
}

init_dirs() {
  mkdir -p "$LOG_DIR" "$RUN_DIR" "$BACKUP_DIR" "$EXPORT_DIR" "$CRED_DIR" "$CONFIG_DIR"
  chmod 700 "$RUN_DIR" "$CRED_DIR"
  touch "$LOG_FILE"
  chmod 600 "$LOG_FILE" 2>/dev/null || true
  if [[ ! -f "$SERVER_CONF" ]]; then
    cat > "$SERVER_CONF" <<EOF_CONF
# Client-Mount-Manager Serverprofile
# Format: NAME|IP|USER|MOUNT_BASE
SVL|${SERVER_IP_DEFAULT}|${SUDO_USER:-${USER:-exampleuser}}|${MOUNT_BASE}
EOF_CONF
    chmod 600 "$SERVER_CONF"
  fi
}

log() { echo "[$(date '+%F %T')] $*" >> "$LOG_FILE"; }
log_err() { echo "[$(date '+%F %T')] ERROR: $*" >> "$LOG_FILE"; }
msg() { echo "$*"; log "$*"; }
pause() { read -rp "Weiter mit [Enter]..." _; }

rotate_log() {
  [[ -f "$LOG_FILE" ]] || return 0
  if [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0) -gt 1048576 ]]; then
    mv "$LOG_FILE" "${LOG_FILE}.1" 2>/dev/null || true
    echo "[$(date '+%F %T')] ROTATED" > "$LOG_FILE"
  fi
}

lock_or_exit() {
  if [[ -f "$LOCK_FILE" ]]; then
    echo "⚠️ Manager läuft vermutlich bereits:"
    cat "$LOCK_FILE" 2>/dev/null || true
    read -rp "Lock entfernen? (j/n): " a
    [[ "$a" =~ ^[Jj]$ ]] || exit 1
    rm -f "$LOCK_FILE"
  fi
  echo "PID=$$ USER=${SUDO_USER:-$USER} TIME=$(date)" > "$LOCK_FILE"
}

cleanup() { rm -f "$LOCK_FILE" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

terminal_wrapper() {
  if [[ ! -t 0 ]]; then
    for term in x-terminal-emulator gnome-terminal mate-terminal xfce4-terminal konsole; do
      if command -v "$term" >/dev/null 2>&1; then
        exec "$term" -- bash -c "sudo -v || { echo 'sudo fehlgeschlagen'; read -rp Enter...; exit 1; }; exec sudo bash '$0' --from-wrapper"
      fi
    done
    echo "Kein Terminal gefunden. Bitte im Terminal starten: sudo bash $0"
    exit 1
  fi
  if [[ "${1:-}" == "--from-wrapper" ]]; then
    shift || true
    export LAUNCHED_FROM_WRAPPER=1
  fi
}

finish_if_wrapper() {
  if [[ "${LAUNCHED_FROM_WRAPPER:-0}" == "1" ]]; then
    echo
    read -rp "Fertig. Fenster mit [Enter] schließen..." _
  fi
}

# --------------------------------------------------------------------
# Distribution / Paketverwaltung
# --------------------------------------------------------------------
OS_ID="unknown"
OS_ID_LIKE=""
OS_NAME="Unbekannt"
OS_VERSION=""
OS_FAMILY="unknown"
PKG_MANAGER="none"

detect_distribution() {
  local os_release="/etc/os-release"

  OS_ID="unknown"
  OS_ID_LIKE=""
  OS_NAME="Unbekannt"
  OS_VERSION=""
  OS_FAMILY="unknown"
  PKG_MANAGER="none"

  if [[ -r "$os_release" ]]; then
    # /etc/os-release ist Shell-kompatibel und stammt vom System.
    # shellcheck disable=SC1091
    . "$os_release"

    OS_ID="${ID:-unknown}"
    OS_ID_LIKE="${ID_LIKE:-}"
    OS_NAME="${PRETTY_NAME:-${NAME:-$OS_ID}}"
    OS_VERSION="${VERSION_ID:-}"
  fi

  case "${OS_ID,,}" in
    debian|ubuntu|linuxmint|lmde)
      OS_FAMILY="debian"
      ;;
    opensuse-tumbleweed|opensuse-leap|opensuse|sles|sled)
      OS_FAMILY="suse"
      ;;
    *)
      case " ${OS_ID_LIKE,,} " in
        *" debian "*|*" ubuntu "*)
          OS_FAMILY="debian"
          ;;
        *" suse "*|*" opensuse "*)
          OS_FAMILY="suse"
          ;;
      esac
      ;;
  esac

  if command -v apt-get >/dev/null 2>&1 \
      && [[ "$OS_FAMILY" == "debian" ]]; then
    PKG_MANAGER="apt"
  elif command -v zypper >/dev/null 2>&1 \
      && [[ "$OS_FAMILY" == "suse" ]]; then
    PKG_MANAGER="zypper"
  fi
}

show_distribution() {
  echo "Betriebssystem:"
  echo "  ${OS_NAME}"
  echo "  Familie: ${OS_FAMILY}"
  echo "  Paketmanager: ${PKG_MANAGER}"
}

install_required_packages() {
  case "$PKG_MANAGER" in
    apt)
      apt-get update
      DEBIAN_FRONTEND=noninteractive \
        apt-get install -y \
          smbclient \
          cifs-utils \
          nfs-common \
          gawk \
          sed \
          grep \
          coreutils \
          findutils \
          iputils-ping \
          tar
      ;;

    zypper)
      zypper --non-interactive refresh
      zypper --non-interactive install \
        samba-client \
        cifs-utils \
        nfs-client \
        gawk \
        sed \
        grep \
        coreutils \
        findutils \
        iputils \
        tar
      ;;

    *)
      echo "❌ Automatische Paketinstallation nicht unterstützt."
      echo
      echo "Erkannt:"
      show_distribution
      echo
      echo "Bitte die fehlenden Programme manuell installieren."
      return 1
      ;;
  esac
}


# --------------------------------------------------------------------
# Tools / Hilfen
# --------------------------------------------------------------------
check_tools() {
  local cmds=(
    systemctl
    awk
    sed
    grep
    findmnt
    systemd-escape
    ping
    timeout
    tar
  )

  local missing=()
  local c

  detect_distribution

  for c in "${cmds[@]}"; do
    command -v "$c" >/dev/null 2>&1 \
      || missing+=("$c")
  done

  command -v smbclient >/dev/null 2>&1 \
    || missing+=("smbclient")

  command -v mount.cifs >/dev/null 2>&1 \
    || missing+=("mount.cifs")

  command -v showmount >/dev/null 2>&1 \
    || missing+=("showmount")

  command -v mount.nfs >/dev/null 2>&1 \
    || missing+=("mount.nfs")

  if ((${#missing[@]})); then
    msg "🔧 Fehlende Werkzeuge: ${missing[*]}"
    show_distribution
    echo

    install_required_packages || return 1

    # Nach Installation wirklich noch einmal prüfen.
    missing=()

    for c in "${cmds[@]}"; do
      command -v "$c" >/dev/null 2>&1 \
        || missing+=("$c")
    done

    command -v smbclient >/dev/null 2>&1 \
      || missing+=("smbclient")

    command -v mount.cifs >/dev/null 2>&1 \
      || missing+=("mount.cifs")

    command -v showmount >/dev/null 2>&1 \
      || missing+=("showmount")

    command -v mount.nfs >/dev/null 2>&1 \
      || missing+=("mount.nfs")

    if ((${#missing[@]})); then
      echo "❌ Werkzeuge fehlen weiterhin: ${missing[*]}"
      return 1
    fi
  fi

  modprobe cifs 2>/dev/null || true
  modprobe nfs 2>/dev/null || true
}


server_reachable() {
  local ip="${1:-$SERVER_IP_DEFAULT}"
  ping -c1 -W1 "$ip" >/dev/null 2>&1 && return 0
  timeout 2 bash -c "</dev/tcp/$ip/445" >/dev/null 2>&1 && return 0
  timeout 2 bash -c "</dev/tcp/$ip/2049" >/dev/null 2>&1 && return 0
  return 1
}

smb_reachable() { timeout 2 bash -c "</dev/tcp/$1/445" >/dev/null 2>&1; }
nfs_reachable() { timeout 2 bash -c "</dev/tcp/$1/2049" >/dev/null 2>&1; }
unit_for_path() { systemd-escape --path "$1"; }

safe_name() { echo "$1" | sed 's#^/##; s#/#_#g; s#[^A-Za-z0-9._-]#_#g'; }

profile_line() { grep -E "^$1\|" "$SERVER_CONF" 2>/dev/null | head -n1 || true; }
profile_ip() { local l; l="$(profile_line "$1")"; [[ -n "$l" ]] && echo "$l" | cut -d'|' -f2 || echo "$SERVER_IP_DEFAULT"; }
profile_user() { local l; l="$(profile_line "$1")"; [[ -n "$l" ]] && echo "$l" | cut -d'|' -f3 || echo "${SUDO_USER:-$USER}"; }
profile_base() { local l; l="$(profile_line "$1")"; [[ -n "$l" ]] && echo "$l" | cut -d'|' -f4 || echo "$MOUNT_BASE"; }

select_profile() {
  local lines i sel name ip user base l
  mapfile -t lines < <(grep -Ev '^\s*(#|$)' "$SERVER_CONF" 2>/dev/null || true)
  if ((${#lines[@]} == 0)); then
    echo "$DEFAULT_PROFILE|$SERVER_IP_DEFAULT|${SUDO_USER:-$USER}|$MOUNT_BASE"
    return 0
  fi

  # Diese Funktion wird per command substitution aufgerufen.
  # Deshalb gehen Menüausgaben nach stderr; nur die Profilzeile geht nach stdout.
  echo "Serverprofile:" >&2
  i=1
  for l in "${lines[@]}"; do
    IFS='|' read -r name ip user base <<<"$l"
    [[ -n "${name:-}" && -n "${ip:-}" ]] || continue
    [[ -n "${user:-}" ]] || user="${SUDO_USER:-$USER}"
    [[ -n "${base:-}" ]] || base="$MOUNT_BASE"
    printf "%2d) %-12s %-15s User: %-12s Basis: %s\n" "$i" "$name" "$ip" "$user" "$base" >&2
    ((i+=1))
  done
  echo "[N] neues Profil  [Z] zurück" >&2
  read -rp "Auswahl [1]: " sel; sel=${sel:-1}
  [[ "$sel" =~ ^[Zz]$ ]] && return 1
  if [[ "$sel" =~ ^[Nn]$ ]]; then add_profile >&2; select_profile; return $?; fi
  if [[ "$sel" =~ ^[0-9]+$ && $sel -ge 1 && $sel -le ${#lines[@]} ]]; then
    IFS='|' read -r name ip user base <<<"${lines[$((sel-1))]}"
    [[ -n "${name:-}" ]] || name="$DEFAULT_PROFILE"
    [[ -n "${ip:-}" ]] || ip="$SERVER_IP_DEFAULT"
    [[ -n "${user:-}" ]] || user="${SUDO_USER:-$USER}"
    [[ -n "${base:-}" ]] || base="$MOUNT_BASE"
    echo "${name}|${ip}|${user}|${base}"
    return 0
  fi
  return 1
}

add_profile() {
  local name ip user base
  read -rp "Profilname [SVL]: " name; name=${name:-SVL}
  read -rp "Server-IP [${SERVER_IP_DEFAULT}]: " ip; ip=${ip:-$SERVER_IP_DEFAULT}
  read -rp "SMB-User [${SUDO_USER:-$USER}]: " user; user=${user:-${SUDO_USER:-$USER}}
  read -rp "Mount-Basis [${MOUNT_BASE}]: " base; base=${base:-$MOUNT_BASE}
  grep -vE "^${name}\|" "$SERVER_CONF" > "${SERVER_CONF}.tmp" 2>/dev/null || true
  mv "${SERVER_CONF}.tmp" "$SERVER_CONF"
  echo "${name}|${ip}|${user}|${base}" >> "$SERVER_CONF"
  chmod 600 "$SERVER_CONF"
  echo "✅ Profil gespeichert: $name"
}

# --------------------------------------------------------------------
# Backups / Export / Import
# --------------------------------------------------------------------
backup_units() {
  local ts dest
  ts="$(date +%F_%H-%M-%S)"
  dest="${BACKUP_DIR}/${ts}"
  mkdir -p "$dest"
  cp -a "${SYSTEMD_DIR}/${esc_base}-"*.mount "$dest" 2>/dev/null || true
  cp -a "${SYSTEMD_DIR}/${esc_base}-"*.automount "$dest" 2>/dev/null || true
  cp -a "$CRED_DIR" "$dest/credentials" 2>/dev/null || true
  cp -a "$SERVER_CONF" "$dest/servers.conf" 2>/dev/null || true
  msg "✅ Backup: $dest"
}

export_config() {
  local ts out work
  ts="$(date +%F_%H-%M-%S)"
  work="${EXPORT_DIR}/client-mount-manager-${ts}"
  out="${EXPORT_DIR}/client-mount-manager-${ts}.tar.gz"
  mkdir -p "$work/systemd" "$work/credentials" "$work/config"
  cp -a "${SYSTEMD_DIR}/${esc_base}-"*.mount "$work/systemd/" 2>/dev/null || true
  cp -a "${SYSTEMD_DIR}/${esc_base}-"*.automount "$work/systemd/" 2>/dev/null || true
  cp -a "$CRED_DIR"/* "$work/credentials/" 2>/dev/null || true
  cp -a "$SERVER_CONF" "$work/config/servers.conf" 2>/dev/null || true
  tar -C "$work" -czf "$out" .
  rm -rf "$work"
  chmod 600 "$out"
  echo "✅ Export erstellt: $out"
  pause
}

import_config() {
  local file
  read -rp "Pfad zum Export .tar.gz: " file
  [[ -f "$file" ]] || { echo "❌ Datei nicht gefunden"; pause; return; }
  backup_units
  local tmp="${RUN_DIR}/import-$$"
  mkdir -p "$tmp"
  tar -C "$tmp" -xzf "$file"
  cp -a "$tmp/systemd/"*.mount "$SYSTEMD_DIR/" 2>/dev/null || true
  cp -a "$tmp/systemd/"*.automount "$SYSTEMD_DIR/" 2>/dev/null || true
  cp -a "$tmp/credentials/"* "$CRED_DIR/" 2>/dev/null || true
  cp -a "$tmp/config/servers.conf" "$SERVER_CONF" 2>/dev/null || true
  chmod 600 "$CRED_DIR"/* 2>/dev/null || true
  rm -rf "$tmp"
  systemctl daemon-reload
  echo "✅ Import abgeschlossen. Danach Status/Reparatur prüfen."
  pause
}

# --------------------------------------------------------------------
# Unit-Listen
# --------------------------------------------------------------------
list_svl_mount_unit_files() {
  systemctl list-unit-files --type=mount --no-legend 2>/dev/null | awk '{print $1}' | grep "^${esc_base}-" || true
}
list_svl_automount_unit_files() {
  systemctl list-unit-files --type=automount --no-legend 2>/dev/null | awk '{print $1}' | grep "^${esc_base}-" || true
}

# --------------------------------------------------------------------
# Discovery SMB/NFS
# --------------------------------------------------------------------
discover_smb_shares() {
  local ip="$1"
  smbclient -L "$ip" -N --option='client min protocol=SMB2' 2>/dev/null \
    | awk '/Disk/ {print $1}' \
    | grep -vE '^(IPC\$|print\$)$' \
    | sort -u || true
}

discover_nfs_exports() {
  local ip="$1"
  showmount -e "$ip" 2>/dev/null \
    | awk 'NR>1 && $1 ~ /^\// {print $1}' \
    | sort -u || true
}

nfs_local_name() {
  local export_path="$1"
  basename "$export_path"
}

is_configured_target() {
  local target="$1" esc
  esc="$(unit_for_path "$target")"
  [[ -f "${SYSTEMD_DIR}/${esc}.mount" || -f "${SYSTEMD_DIR}/${esc}.automount" ]]
}

select_discovered_shares() {
  local ip="$1" mode sel i v s e name target key proto label
  local -a smb_all=() nfs_all=() entries=() labels=()

  echo "Suche Freigaben auf $ip ..."
  if smb_reachable "$ip" || server_reachable "$ip"; then
    mapfile -t smb_all < <(discover_smb_shares "$ip")
  fi
  if nfs_reachable "$ip" || server_reachable "$ip"; then
    mapfile -t nfs_all < <(discover_nfs_exports "$ip")
  fi

  if ((${#smb_all[@]} == 0 && ${#nfs_all[@]} == 0)); then
    echo "❌ Keine SMB-Freigaben oder NFS-Exporte gefunden."
    echo "SMB-Port 445: $(smb_reachable "$ip" && echo erreichbar || echo nicht_erreichbar)"
    echo "NFS-Port 2049: $(nfs_reachable "$ip" && echo erreichbar || echo nicht_erreichbar)"
    return 1
  fi

  echo "1) nur noch nicht konfigurierte"
  echo "2) alle anzeigen"
  read -rp "Auswahl (1/2) [1]: " mode; mode=${mode:-1}

  for s in "${smb_all[@]}"; do
    target="${MOUNT_BASE}/${s}"
    if [[ "$mode" == "1" ]] && is_configured_target "$target"; then continue; fi
    entries+=("SMB|$s|$s|$target")
  done

  for e in "${nfs_all[@]}"; do
    name="$(nfs_local_name "$e")"
    target="${MOUNT_BASE}/${name}"
    if [[ "$mode" == "1" ]] && is_configured_target "$target"; then continue; fi
    entries+=("NFS|$e|$name|$target")
  done

  if ((${#entries[@]} == 0)); then
    echo "⚠️ Keine neuen Freigaben. Mit 'alle anzeigen' erneut versuchen."
    return 1
  fi

  echo
  echo "Gefundene Freigaben:"
  printf "%2s  %-4s  %-28s  %s\n" "Nr" "Typ" "Name/Export" "Ziel"
  printf "%2s  %-4s  %-28s  %s\n" "--" "---" "-----------" "----"
  i=1
  for key in "${entries[@]}"; do
    IFS='|' read -r proto label name target <<<"$key"
    printf "%2d) %-4s  %-28s  %s\n" "$i" "$proto" "$label" "$target"
    ((i+=1))
  done
  echo "[A] alle  [Z] zurück"
  read -rp "Auswahl: " sel

  SELECTED=()
  [[ "$sel" =~ ^[Zz]$ ]] && return 1
  if [[ "$sel" =~ ^[Aa]$ ]]; then
    SELECTED=("${entries[@]}")
    return 0
  fi

  IFS=',' read -ra idx <<<"$sel"
  for v in "${idx[@]}"; do
    [[ "$v" =~ ^[0-9]+$ && $v -ge 1 && $v -le ${#entries[@]} ]] && SELECTED+=("${entries[$((v-1))]}")
  done
  ((${#SELECTED[@]})) || return 1
}

setup_selected_discovered() {
  local ip="$1" user="$2" item proto value name target
  for item in "${SELECTED[@]}"; do
    IFS='|' read -r proto value name target <<<"$item"
    case "$proto" in
      SMB) setup_smb_share "$ip" "$value" "$user" ;;
      NFS) setup_nfs_export_auto "$ip" "$value" "$name" ;;
      *) echo "Überspringe unbekannten Typ: $item" ;;
    esac
  done
  pause
}
# --------------------------------------------------------------------
# Unit-Erzeugung
# --------------------------------------------------------------------
write_smb_mount_unit() {
  local ip="$1" share="$2" target="$3" cred="$4" esc="$5"
  local opts="credentials=$cred,vers=${SMB_VERSION},rw,iocharset=utf8,serverino,noperm,cifsacl,_netdev"
  tee "${SYSTEMD_DIR}/${esc}.mount" >/dev/null <<EOF_MOUNT
[Unit]
Description=SMB Mount ${share}
Documentation=man:systemd.mount(5)
After=network-online.target
Wants=network-online.target

[Mount]
What=//${ip}/${share}
Where=${target}
Type=cifs
Options=${opts}
TimeoutSec=15

[Install]
WantedBy=multi-user.target
EOF_MOUNT
}

write_nfs_mount_unit() {
  local ip="$1" export_path="$2" target="$3" esc="$4"
  local name; name="$(basename "$export_path")"
  local opts="rw,_netdev,vers=${NFS_VERSION}"
  tee "${SYSTEMD_DIR}/${esc}.mount" >/dev/null <<EOF_MOUNT
[Unit]
Description=NFS Mount ${name}
Documentation=man:systemd.mount(5)
After=network-online.target
Wants=network-online.target

[Mount]
What=${ip}:${export_path}
Where=${target}
Type=nfs
Options=${opts}
TimeoutSec=15

[Install]
WantedBy=multi-user.target
EOF_MOUNT
}

write_automount_unit() {
  local proto="$1" name="$2" target="$3" esc="$4"
  tee "${SYSTEMD_DIR}/${esc}.automount" >/dev/null <<EOF_AUTO
[Unit]
Description=${proto} Automount ${name}
Documentation=man:systemd.automount(5)

[Automount]
Where=${target}
TimeoutIdleSec=${AUTOMOUNT_IDLE_TIMEOUT}

[Install]
WantedBy=multi-user.target
EOF_AUTO
}

verify_units() {
  local esc="$1"
  echo "🔎 systemd-analyze verify: ${esc}.mount / ${esc}.automount"
  if systemd-analyze verify "${SYSTEMD_DIR}/${esc}.mount" "${SYSTEMD_DIR}/${esc}.automount" >/tmp/client-mount-manager-verify.$$ 2>&1; then
    echo "✅ Unit-Verify ok"
    log "verify ok: ${esc}.mount ${esc}.automount"
  else
    echo "⚠️ Unit-Verify meldet Probleme:"
    cat /tmp/client-mount-manager-verify.$$
    log_err "verify failed for ${esc}: $(tr '\n' ' ' </tmp/client-mount-manager-verify.$$)"
  fi
  rm -f /tmp/client-mount-manager-verify.$$
}

check_ordering_cycles() {
  echo "🔎 Journal-Prüfung auf Ordering-Cycles..."
  local lines
  lines="$(journalctl -b --no-pager 2>/dev/null | grep -Ei 'ordering cycle|Found ordering cycle|cycle.*network-online|deleted to break ordering cycle' || true)"
  if [[ -n "$lines" ]]; then
    echo "⚠️ Mögliche Ordering-Cycles gefunden:"
    echo "$lines" | tail -20
  else
    echo "✅ Keine Ordering-Cycles im aktuellen Boot-Journal gefunden"
  fi
}

setup_smb_share() {
  local ip="$1"
  local share="$2"
  local default_user="$3"
  local target
  local cred
  local esc u pw reuse

  # Erst nachdem share lokal gesetzt ist, davon abhängige
  # Pfade berechnen. Andernfalls kann Bash noch einen
  # vorherigen/globalen Wert von $share verwenden.
  target="${MOUNT_BASE}/${share}"
  cred="${CRED_DIR}/${share}.cred"

  esc="$(unit_for_path "$target")"
  mkdir -p "$target" "$CRED_DIR"; chmod 700 "$CRED_DIR"
  if [[ -f "$cred" ]]; then
    read -rp "Credentials für $share vorhanden. Wiederverwenden? (J/n): " reuse
    if [[ ! "${reuse:-J}" =~ ^[JjYy]$ ]]; then
      read -rp "Benutzer [${default_user}]: " u; u=${u:-$default_user}
      read -rsp "Passwort: " pw; echo
      printf 'username=%s\npassword=%s\n' "$u" "$pw" > "$cred"
    fi
  else
    read -rp "Benutzer [${default_user}]: " u; u=${u:-$default_user}
    read -rsp "Passwort: " pw; echo
    printf 'username=%s\npassword=%s\n' "$u" "$pw" > "$cred"
  fi
  chmod 600 "$cred"
  backup_units
  write_smb_mount_unit "$ip" "$share" "$target" "$cred" "$esc"
  write_automount_unit "SMB" "$share" "$target" "$esc"
  verify_units "$esc"
  systemctl daemon-reload
  systemctl disable --now "${esc}.mount" >/dev/null 2>&1 || true
  systemctl reset-failed "${esc}.mount" "${esc}.automount" >/dev/null 2>&1 || true
  systemctl enable --now "${esc}.automount"
  echo "✅ SMB $share als Automount eingerichtet: $target"
}

setup_nfs_export() {
  local ip="$1" export_path="$2" name target esc custom
  name="$(basename "$export_path")"
  read -rp "Lokaler Name für ${export_path} [${name}]: " custom; custom=${custom:-$name}
  target="${MOUNT_BASE}/${custom}"; esc="$(unit_for_path "$target")"
  mkdir -p "$target"
  backup_units
  write_nfs_mount_unit "$ip" "$export_path" "$target" "$esc"
  write_automount_unit "NFS" "$custom" "$target" "$esc"
  verify_units "$esc"
  systemctl daemon-reload
  systemctl disable --now "${esc}.mount" >/dev/null 2>&1 || true
  systemctl reset-failed "${esc}.mount" "${esc}.automount" >/dev/null 2>&1 || true
  systemctl enable --now "${esc}.automount"
  echo "✅ NFS ${export_path} als Automount eingerichtet: $target"
}

setup_nfs_export_auto() {
  local ip="$1" export_path="$2" custom="$3" target esc
  [[ -n "$custom" ]] || custom="$(basename "$export_path")"
  target="${MOUNT_BASE}/${custom}"; esc="$(unit_for_path "$target")"
  mkdir -p "$target"
  backup_units
  write_nfs_mount_unit "$ip" "$export_path" "$target" "$esc"
  write_automount_unit "NFS" "$custom" "$target" "$esc"
  verify_units "$esc"
  systemctl daemon-reload
  systemctl disable --now "${esc}.mount" >/dev/null 2>&1 || true
  systemctl reset-failed "${esc}.mount" "${esc}.automount" >/dev/null 2>&1 || true
  systemctl enable --now "${esc}.automount"
  echo "✅ NFS ${export_path} als Automount eingerichtet: $target"
}

manual_smb() {
  local default_ip="${1:-$SERVER_IP_DEFAULT}"
  local default_user="${2:-${SUDO_USER:-$USER}}"
  local ip user share

  read -rp "Server-IP [${default_ip}]: " ip
  ip=${ip:-$default_ip}

  read -rp "SMB-Freigabe: " share
  [[ -n "$share" ]] || return

  read -rp "Benutzer [${default_user}]: " user
  user=${user:-$default_user}

  setup_smb_share "$ip" "$share" "$user"
  pause
}

manual_nfs() {
  local default_ip="${1:-$SERVER_IP_DEFAULT}"
  local ip export_path

  read -rp "Server-IP [${default_ip}]: " ip
  ip=${ip:-$default_ip}

  read -rp "NFS-Export-Pfad z.B. /srv/fotolabor: " export_path
  [[ -n "$export_path" ]] || return

  setup_nfs_export "$ip" "$export_path"
  pause
}

# --------------------------------------------------------------------
# Migration vorhandener Mounts zu Automount
# --------------------------------------------------------------------
migrate_existing_to_automount() {
  local units m where esc name typ count=0
  mapfile -t units < <(list_svl_mount_unit_files)
  ((${#units[@]})) || { echo "Keine ${MOUNT_BASE}-Mount-Units gefunden."; pause; return; }
  backup_units
  for m in "${units[@]}"; do
    where="$(systemctl show -p Where --value "$m" 2>/dev/null || true)"
    [[ -n "$where" && "$where" == ${MOUNT_BASE}/* ]] || continue
    esc="${m%.mount}"; name="$(basename "$where")"
    typ="$(systemctl show -p Type --value "$m" 2>/dev/null || echo SMB)"; typ=${typ^^}
    [[ "$typ" == "CIFS" ]] && typ="SMB"
    if [[ ! -f "${SYSTEMD_DIR}/${esc}.automount" ]]; then
      write_automount_unit "$typ" "$name" "$where" "$esc"
      verify_units "$esc"
      echo "➕ ${esc}.automount erstellt"
    else
      echo "↷ ${esc}.automount existiert bereits"
    fi
    systemctl daemon-reload
    systemctl disable --now "$m" >/dev/null 2>&1 || true
    systemctl reset-failed "$m" "${esc}.automount" >/dev/null 2>&1 || true
    systemctl enable --now "${esc}.automount"
    ((count+=1))
  done
  systemctl daemon-reload
  echo "✅ $count Mount-Units auf Automount umgestellt."
  pause
}

# --------------------------------------------------------------------
# Status / Info / Repair / Selftest
# --------------------------------------------------------------------
proto_for_unit() {
  local base="$1" t what
  t="$(systemctl show -p Type --value "${base}.mount" 2>/dev/null || true)"
  what="$(systemctl show -p What --value "${base}.mount" 2>/dev/null || true)"
  [[ "$t" == "cifs" || "$what" == //* ]] && { echo "SMB"; return; }
  [[ "$t" == nfs* || "$what" == *:* ]] && { echo "NFS"; return; }
  echo "?"
}

show_status() {
  local ip="${1:-$SERVER_IP_DEFAULT}" units autos u base where mstate astate mp proto what server
  server="offline"; server_reachable "$ip" && server="online"
  echo "==== Client-Mount-Manager V${VERSION} Status ===="
  echo "Server: $ip   $server   SMB: $(smb_reachable "$ip" && echo ok || echo --)   NFS: $(nfs_reachable "$ip" && echo ok || echo --)"
  echo "Mount-Basis: $MOUNT_BASE"
  echo
  printf "%-18s %-5s %-12s %-12s %-12s %s\n" "Freigabe" "Typ" "Mount" "Automount" "Zugriff" "Pfad"
  printf "%-18s %-5s %-12s %-12s %-12s %s\n" "--------" "---" "-----" "---------" "-------" "----"
  mapfile -t units < <(list_svl_mount_unit_files)
  mapfile -t autos < <(list_svl_automount_unit_files)
  declare -A seen=()
  for u in "${units[@]}" "${autos[@]}"; do
    base="${u%.mount}"; base="${base%.automount}"
    [[ -n "${seen[$base]:-}" ]] && continue
    seen[$base]=1
    where="$(systemctl show -p Where --value "${base}.mount" 2>/dev/null || systemctl show -p Where --value "${base}.automount" 2>/dev/null || true)"
    [[ -z "$where" ]] && where="${MOUNT_BASE}/$(echo "$base" | sed "s/^${esc_base}-//")"
    share="$(basename "$where")"
    mstate="$(systemctl is-active "${base}.mount" 2>/dev/null || true)"
    astate="$(systemctl is-active "${base}.automount" 2>/dev/null || true)"
    mp="wartet"; mountpoint -q "$where" && mp="gemountet"
    [[ "$mstate" == "failed" || "$astate" == "failed" ]] && mp="fehler"
    proto="$(proto_for_unit "$base")"
    printf "%-18s %-5s %-12s %-12s %-12s %s\n" "$share" "$proto" "${mstate:-n/a}" "${astate:-n/a}" "$mp" "$where"
  done
  echo
}

selftest() {
  local ip="${1:-$SERVER_IP_DEFAULT}" ok=0 warn=0 fail=0 units autos creds
  echo "==== Selftest V${VERSION} ===="
  if command -v systemctl >/dev/null; then echo "✓ systemd vorhanden"; ((ok+=1)); else echo "✗ systemd fehlt"; ((fail+=1)); fi
  if command -v mount.cifs >/dev/null; then echo "✓ CIFS vorhanden"; ((ok+=1)); else echo "✗ CIFS fehlt"; ((fail+=1)); fi
  if command -v mount.nfs >/dev/null; then echo "✓ NFS vorhanden"; ((ok+=1)); else echo "! NFS fehlt"; ((warn+=1)); fi
  if server_reachable "$ip"; then echo "✓ Server erreichbar: $ip"; ((ok+=1)); else echo "! Server aktuell nicht erreichbar: $ip"; ((warn+=1)); fi
  smb_reachable "$ip" && echo "✓ SMB-Port 445 erreichbar" || { echo "! SMB-Port 445 nicht erreichbar"; ((warn+=1)); }
  nfs_reachable "$ip" && echo "✓ NFS-Port 2049 erreichbar" || { echo "! NFS-Port 2049 nicht erreichbar"; ((warn+=1)); }
  units=$(list_svl_mount_unit_files | wc -l); autos=$(list_svl_automount_unit_files | wc -l); creds=$(find "$CRED_DIR" -maxdepth 1 -type f -name '*.cred' 2>/dev/null | wc -l)
  echo "Mount-Units:     $units"
  echo "Automount-Units: $autos"
  echo "Credentials:     $creds"
  if systemctl --failed --no-legend | grep -q "^${esc_base}-"; then echo "✗ Fehlerhafte SVL-Units vorhanden"; ((fail+=1)); else echo "✓ keine fehlerhaften SVL-Units"; ((ok+=1)); fi
  echo
  echo "Ergebnis: OK=$ok  WARN=$warn  FAIL=$fail"
}

info() {
  show_status "$SERVER_IP_DEFAULT"
  echo "Profile:       $SERVER_CONF"
  echo "Systemd-Units: $SYSTEMD_DIR"
  echo "Credentials:   $CRED_DIR"
  echo "Logs:          $LOG_FILE"
  echo "Backups:       $BACKUP_DIR"
  echo "Exports:       $EXPORT_DIR"
  echo
  echo "Serverprofile:"
  grep -Ev '^\s*(#|$)' "$SERVER_CONF" 2>/dev/null || echo "keine"
  echo
  echo "Letzte Fehler aus Journal:"
  journalctl -u "${esc_base}-*.mount" -u "${esc_base}-*.automount" -n 20 --no-pager 2>/dev/null || true
}

# Repariert bestehende Mount-/Automount-Units vollständig neu.
# Ziel: Automount ohne Netzwerk-Abhängigkeiten, Mount weiterhin mit network-online.target.
repair_existing_mount_units() {
  local units m esc where what type opts desc name repaired=0 failed=0
  local smb_user smb_pw reset_creds answer cred share ip export_path nfsver

  echo "🔧 Alle bestehenden ${MOUNT_BASE}-Mounts werden vollständig repariert..."
  echo "   .automount: ohne After/Wants network-online.target"
  echo "   .mount:     mit After/Wants network-online.target"
  echo "   CIFS:       Options werden neu gesetzt, credentials= wird erzwungen"
  echo

  read -rp "SMB-Zugangsdaten für alle CIFS-Mounts neu setzen? (j/N): " answer
  if [[ "${answer:-N}" =~ ^[JjYy]$ ]]; then
    reset_creds=1
    read -rp "SMB-Benutzer [${SUDO_USER:-$USER}]: " smb_user
    smb_user=${smb_user:-${SUDO_USER:-$USER}}
    read -rsp "SMB-Passwort: " smb_pw; echo
  else
    reset_creds=0
  fi

  backup_units
  systemctl daemon-reload

  mapfile -t units < <(list_svl_mount_unit_files)
  if ((${#units[@]} == 0)); then
    echo "⚠️ Keine ${MOUNT_BASE}-Mount-Units gefunden."
    pause
    return 0
  fi

  for m in "${units[@]}"; do
    esc="${m%.mount}"
    where="$(awk -F= '/^Where=/{print $2; exit}' "${SYSTEMD_DIR}/${m}" 2>/dev/null || true)"
    what="$(awk -F= '/^What=/{print $2; exit}'  "${SYSTEMD_DIR}/${m}" 2>/dev/null || true)"
    type="$(awk -F= '/^Type=/{print $2; exit}'  "${SYSTEMD_DIR}/${m}" 2>/dev/null || true)"

    # Fallback über systemctl show, falls Datei anders formatiert ist.
    [[ -n "$where" ]] || where="$(systemctl show -p Where --value "$m" 2>/dev/null || true)"
    [[ -n "$what"  ]] || what="$(systemctl show -p What --value "$m" 2>/dev/null || true)"
    [[ -n "$type"  ]] || type="$(systemctl show -p Type --value "$m" 2>/dev/null || true)"

    if [[ -z "$where" || "$where" != ${MOUNT_BASE}/* || -z "$what" || -z "$type" ]]; then
      echo "⚠️ Überspringe $m: unvollständige Unit-Daten"
      ((failed+=1)) || true
      continue
    fi

    name="$(basename "$where")"
    type="${type,,}"
    mkdir -p "$where" "$CRED_DIR"
    chmod 700 "$CRED_DIR"

    case "$type" in
      cifs)
        desc="SMB Mount ${name}"

        # Share aus //IP/Share ableiten. Falls das fehlschlägt, lokalen Namen verwenden.
        share="$(echo "$what" | sed -E 's#^//[^/]+/([^/]+).*#\1#')"
        [[ -n "$share" && "$share" != "$what" ]] || share="$name"
        cred="${CRED_DIR}/${share}.cred"

        # Kompatibilität: falls Credential unter lokalem Namen existiert, diesen nehmen.
        if [[ ! -f "$cred" && -f "${CRED_DIR}/${name}.cred" ]]; then
          cred="${CRED_DIR}/${name}.cred"
        fi

        cred_bad=0
        [[ -s "$cred" ]] || cred_bad=1
        grep -q '^username=' "$cred" 2>/dev/null || cred_bad=1
        grep -q '^password=' "$cred" 2>/dev/null || cred_bad=1
        if [[ "$reset_creds" == "1" || "$cred_bad" == "1" ]]; then
          if [[ "$reset_creds" != "1" ]]; then
            echo "Credentials fehlen/defekt für $name. Bitte eingeben."
            read -rp "SMB-Benutzer [${SUDO_USER:-$USER}]: " smb_user
            smb_user=${smb_user:-${SUDO_USER:-$USER}}
            read -rsp "SMB-Passwort: " smb_pw; echo
          fi
          printf 'username=%s\npassword=%s\n' "$smb_user" "$smb_pw" > "$cred"
        fi
        chmod 600 "$cred"

        # CIFS-Optionen bewusst NICHT aus defekter Alt-Unit übernehmen.
        opts="credentials=${cred},vers=${SMB_VERSION},rw,iocharset=utf8,serverino,noperm,cifsacl,_netdev"
        ;;
      nfs|nfs4)
        desc="NFS Mount ${name}"
        nfsver="$NFS_VERSION"
        [[ "$type" == "nfs4" ]] && type="nfs"
        opts="rw,_netdev,vers=${nfsver}"
        ;;
      *)
        echo "⚠️ Überspringe $m: unbekannter Typ $type"
        ((failed+=1)) || true
        continue
        ;;
    esac

    # Direkten Mount und Automount stoppen, damit die Unit-Dateien sicher ersetzt werden können.
    systemctl stop "${esc}.automount" >/dev/null 2>&1 || true
    systemctl disable --now "$m" >/dev/null 2>&1 || true
    systemctl reset-failed "$m" "${esc}.automount" >/dev/null 2>&1 || true

    tee "${SYSTEMD_DIR}/${esc}.mount" >/dev/null <<EOF_REPAIR_MOUNT
[Unit]
Description=${desc}
Documentation=man:systemd.mount(5)
After=network-online.target
Wants=network-online.target

[Mount]
What=${what}
Where=${where}
Type=${type}
Options=${opts}
TimeoutSec=15

[Install]
WantedBy=multi-user.target
EOF_REPAIR_MOUNT

    tee "${SYSTEMD_DIR}/${esc}.automount" >/dev/null <<EOF_REPAIR_AUTO
[Unit]
Description=Automount ${name}
Documentation=man:systemd.automount(5)

[Automount]
Where=${where}
TimeoutIdleSec=${AUTOMOUNT_IDLE_TIMEOUT}

[Install]
WantedBy=multi-user.target
EOF_REPAIR_AUTO

    verify_units "$esc"
    systemctl daemon-reload
    systemctl enable --now "${esc}.automount" >/dev/null 2>&1 || true
    echo "✅ repariert: ${esc}.mount + ${esc}.automount"
    ((repaired+=1)) || true
  done

  systemctl daemon-reload
  systemctl reset-failed >/dev/null 2>&1 || true
  check_ordering_cycles || true
  echo
  echo "✅ Reparatur fertig: $repaired repariert, $failed übersprungen."
  echo
  echo "Prüfen mit:"
  echo "  grep '^Options=' ${SYSTEMD_DIR}/${esc_base}-*.mount"
  echo "  systemctl list-units --type=automount | grep ${esc_base}-"
  pause
}

repair_automounts() {
  local units m where esc name typ repaired=0
  backup_units
  systemctl daemon-reload
  mapfile -t units < <(list_svl_mount_unit_files)
  for m in "${units[@]}"; do
    where="$(systemctl show -p Where --value "$m" 2>/dev/null || true)"
    [[ -n "$where" && "$where" == ${MOUNT_BASE}/* ]] || continue
    esc="${m%.mount}"; name="$(basename "$where")"
    typ="$(systemctl show -p Type --value "$m" 2>/dev/null || echo SMB)"; typ=${typ^^}; [[ "$typ" == "CIFS" ]] && typ="SMB"
    mkdir -p "$where"
    if [[ ! -f "${SYSTEMD_DIR}/${esc}.automount" ]]; then
      write_automount_unit "$typ" "$name" "$where" "$esc"
      verify_units "$esc"
      echo "➕ fehlende Automount-Unit erstellt: ${esc}.automount"
    fi
    systemctl reset-failed "$m" "${esc}.automount" >/dev/null 2>&1 || true
    systemctl disable --now "$m" >/dev/null 2>&1 || true
    systemctl enable --now "${esc}.automount" >/dev/null 2>&1 || true
    ((repaired+=1))
  done
  systemctl daemon-reload
  echo "✅ Reparatur abgeschlossen: $repaired Einträge geprüft."
  pause
}

trigger_automounts() {
  local autos a where
  mapfile -t autos < <(list_svl_automount_unit_files)
  for a in "${autos[@]}"; do
    where="$(systemctl show -p Where --value "$a" 2>/dev/null || true)"
    [[ -n "$where" ]] || continue
    echo "Trigger: $where"
    timeout 5 ls "$where" >/dev/null 2>&1 || true
  done
  echo "✅ Automounts getriggert."
  pause
}

# --------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------
credentials_menu() {
  local files i sel f share pw user
  while true; do
    clear
    echo "==== Credentials ===="
    mapfile -t files < <(find "$CRED_DIR" -maxdepth 1 -type f -name '*.cred' | sort)
    if ((${#files[@]})); then i=1; for f in "${files[@]}"; do echo "$i) $(basename "$f")"; ((i+=1)); done; else echo "keine Credentials"; fi
    echo
    echo "1) Passwort/Benutzer ändern"
    echo "2) Credential löschen"
    echo "3) Rechte reparieren"
    echo "0) zurück"
    read -rp "Auswahl: " sel
    case "$sel" in
      1) read -rp "Share-Name: " share; [[ -n "$share" ]] || continue; read -rp "Benutzer [${SUDO_USER:-$USER}]: " user; user=${user:-${SUDO_USER:-$USER}}; read -rsp "Passwort: " pw; echo; printf 'username=%s\npassword=%s\n' "$user" "$pw" > "${CRED_DIR}/${share}.cred"; chmod 600 "${CRED_DIR}/${share}.cred"; echo "✅ gespeichert"; pause ;;
      2) read -rp "Share-Name: " share; [[ -n "$share" ]] && rm -f "${CRED_DIR}/${share}.cred" && echo "✅ gelöscht"; pause ;;
      3) chmod 700 "$CRED_DIR"; chmod 600 "$CRED_DIR"/*.cred 2>/dev/null || true; echo "✅ Rechte repariert"; pause ;;
      0) return ;;
      *) echo "?"; sleep 1 ;;
    esac
  done
}

profiles_menu() {
  local sel
  while true; do
    clear
    echo "==== Serverprofile ===="
    grep -Ev '^\s*(#|$)' "$SERVER_CONF" 2>/dev/null || echo "keine"
    echo
    echo "1) Profil hinzufügen/ändern"
    echo "2) Profil löschen"
    echo "0) zurück"
    read -rp "Auswahl: " sel
    case "$sel" in
      1) add_profile; pause ;;
      2) read -rp "Profilname löschen: " name; [[ -n "$name" ]] && grep -vE "^${name}\|" "$SERVER_CONF" > "${SERVER_CONF}.tmp" && mv "${SERVER_CONF}.tmp" "$SERVER_CONF"; pause ;;
      0) return ;;
      *) echo "?"; sleep 1 ;;
    esac
  done
}

# --------------------------------------------------------------------
# Entfernen / Cleanup
# --------------------------------------------------------------------
delete_mounts() {
  local all i sel targets idx v base where
  mapfile -t all < <({ list_svl_mount_unit_files; list_svl_automount_unit_files; } | sed 's/\.mount$//;s/\.automount$//' | sort -u)
  ((${#all[@]})) || { echo "nichts"; pause; return; }
  i=1; for base in "${all[@]}"; do echo "$i) $base"; ((i+=1)); done
  echo "[A] alle  [Z] zurück"
  read -rp "Auswahl: " sel; sel=${sel:-Z}; [[ "$sel" =~ ^[Zz]$ ]] && return
  targets=()
  if [[ "$sel" =~ ^[Aa]$ ]]; then targets=("${all[@]}"); else IFS=',' read -ra idx <<<"$sel"; for v in "${idx[@]}"; do [[ "$v" =~ ^[0-9]+$ && $v -ge 1 && $v -le ${#all[@]} ]] && targets+=("${all[$((v-1))]}"); done; fi
  backup_units
  for base in "${targets[@]}"; do
    where="$(systemctl show -p Where --value "${base}.mount" 2>/dev/null || systemctl show -p Where --value "${base}.automount" 2>/dev/null || true)"
    systemctl disable --now "${base}.automount" >/dev/null 2>&1 || true
    systemctl disable --now "${base}.mount" >/dev/null 2>&1 || true
    [[ -n "$where" ]] && umount -f "$where" >/dev/null 2>&1 || true
    rm -f "${SYSTEMD_DIR}/${base}.mount" "${SYSTEMD_DIR}/${base}.automount"
    [[ -n "$where" ]] && rmdir "$where" >/dev/null 2>&1 || true
    echo "🗑️ entfernt: $base"
  done
  systemctl daemon-reload
  echo "✅ fertig"; pause
}

cleanup_broken() {
  local all base where
  mapfile -t all < <({ list_svl_mount_unit_files; list_svl_automount_unit_files; } | sed 's/\.mount$//;s/\.automount$//' | sort -u)
  backup_units
  for base in "${all[@]}"; do
    where="$(systemctl show -p Where --value "${base}.mount" 2>/dev/null || systemctl show -p Where --value "${base}.automount" 2>/dev/null || true)"
    if [[ -z "$where" || ! -d "$where" ]]; then
      systemctl disable --now "${base}.automount" "${base}.mount" >/dev/null 2>&1 || true
      rm -f "${SYSTEMD_DIR}/${base}.mount" "${SYSTEMD_DIR}/${base}.automount"
      echo "Bereinigt: $base"
    fi
  done
  systemctl daemon-reload
  echo "✅ Bereinigung fertig"; pause
}

# --------------------------------------------------------------------
# Menüs / CLI
# --------------------------------------------------------------------
setup_menu() {
  local prof name ip user base choice
  prof="$(select_profile)" || return
  IFS='|' read -r name ip user base <<<"$prof"
  [[ -n "${ip:-}" ]] || ip="$SERVER_IP_DEFAULT"
  [[ -n "${user:-}" ]] || user="${SUDO_USER:-$USER}"
  [[ -n "${base:-}" ]] || base="$MOUNT_BASE"
  MOUNT_BASE="$base"; esc_base="$(systemd-escape --path "$MOUNT_BASE")"

  echo "Server: $name ($ip)   Basis: $MOUNT_BASE"
  echo "1) Freigaben automatisch suchen"
  echo "2) Freigabe manuell anlegen"
  echo "3) Server wechseln / zurück"
  read -rp "Auswahl [1]: " choice; choice=${choice:-1}
  case "$choice" in
    1) select_discovered_shares "$ip" && setup_selected_discovered "$ip" "$user" ;;
    2)
       echo "1) SMB manuell"
       echo "2) NFS manuell"
       read -rp "Auswahl: " choice
       case "$choice" in
         1) manual_smb "$ip" "$user" ;;
         2) manual_nfs "$ip" ;;
         *) echo "?"; sleep 1 ;;
       esac
       ;;
    3) return ;;
    *) echo "?"; sleep 1 ;;
  esac
}

menu() {
  while true; do
    clear
    echo "==== Client-Mount-Manager V${VERSION} ===="
    echo "1) Freigaben suchen/einrichten (SMB/NFS)"
    echo "2) Mounts/Automounts entfernen"
    echo "3) Status anzeigen"
    echo "4) Info / Journal"
    echo "5) Defekte Einträge bereinigen"
    echo "6) Vorhandene Mounts um Automount erweitern"
    echo "7) Automounts reparieren"
    echo "8) Automounts jetzt triggern"
    echo "9) Backup der Mount-Konfiguration"
    echo "10) Export"
    echo "11) Import"
    echo "12) Selftest / Check"
    echo "13) Serverprofile verwalten"
    echo "14) Credentials verwalten"
    echo "15) Bestehende Mounts systemd-sauber reparieren"
    echo "0) Ende"
    read -rp "Auswahl: " c
    case "$c" in
      1) setup_menu ;;
      2) delete_mounts ;;
      3) show_status "$SERVER_IP_DEFAULT"; pause ;;
      4) info; pause ;;
      5) cleanup_broken ;;
      6) migrate_existing_to_automount ;;
      7) repair_automounts ;;
      8) trigger_automounts ;;
      9) backup_units; pause ;;
      10) export_config ;;
      11) import_config ;;
      12) selftest "$SERVER_IP_DEFAULT"; pause ;;
      13) profiles_menu ;;
      14) credentials_menu ;;
      15) repair_existing_mount_units ;;
      0) finish_if_wrapper; exit 0 ;;
      *) echo "?"; sleep 1 ;;
    esac
  done
}

usage() {
  cat <<EOF_USAGE
Client-Mount-Manager V${VERSION}

Aufruf:
  client-mount-manager menu
  client-mount-manager check
  client-mount-manager info
  client-mount-manager repair
  client-mount-manager repair-existing
  client-mount-manager automount
  client-mount-manager trigger
  client-mount-manager backup
  client-mount-manager export
  client-mount-manager import
  client-mount-manager cleanup

Ohne Argument startet das Menü.
EOF_USAGE
}

main() {
  terminal_wrapper "${1:-}"

  if [[ "${1:-}" == "--from-wrapper" ]]; then
    shift
  fi

  need_root "$@"
  init_dirs
  rotate_log
  lock_or_exit
  check_tools
  local cmd="${1:-menu}"
  case "$cmd" in
    menu) menu ;;
    check|status) selftest "$SERVER_IP_DEFAULT"; echo; show_status "$SERVER_IP_DEFAULT" ;;
    info) info ;;
    repair) repair_automounts ;;
    repair-existing|repair-units|fix-networkmanager) repair_existing_mount_units ;;
    automount|migrate) migrate_existing_to_automount ;;
    trigger) trigger_automounts ;;
    backup) backup_units ;;
    export) export_config ;;
    import) import_config ;;
    cleanup) cleanup_broken ;;
    help|-h|--help) usage ;;
    *) echo "Unbekannter Befehl: $cmd"; usage; exit 1 ;;
  esac
}

main "$@"
