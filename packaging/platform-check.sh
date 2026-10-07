# Shared by generated package scripts and the installation launcher.
heimserver_check_platform() {
    hs_target=$1
    hs_release=$2
    hs_id= hs_version= hs_base=
    [ -r "$hs_release" ] || { echo 'Installation blockiert: Betriebssystem nicht erkennbar.' >&2; return 1; }
    while IFS='=' read -r hs_key hs_value || [ -n "$hs_key" ]; do
        hs_value=${hs_value#\"}; hs_value=${hs_value%\"}
        hs_value=${hs_value#\'}; hs_value=${hs_value%\'}
        case "$hs_key" in
            ID) hs_id=$hs_value;;
            VERSION_ID) hs_version=$hs_value;;
            UBUNTU_CODENAME) hs_base=$hs_value;;
        esac
    done < "$hs_release"
    case "$hs_target:$hs_id:$hs_version:$hs_base" in
        debian13:debian:13:*) return 0;;
        mint22:linuxmint:22:noble|mint22:linuxmint:22.[0-9]:noble|mint22:linuxmint:22.[0-9][0-9]:noble) return 0;;
    esac
    printf 'Installation blockiert: Paket für %s, erkannt %s %s (Basis %s). Passendes Paket verwenden.\n' "$hs_target" "$hs_id" "$hs_version" "$hs_base" >&2
    return 1
}
