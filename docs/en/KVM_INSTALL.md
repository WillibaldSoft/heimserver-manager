# Debian 13: Installation without sudo group

A normal user account remains a normal account. Package installation requires administrative rights. The DEB is installed as root by APT/dpkg; it cannot grant itself administrator rights before startup.

Therefore, the package build additionally places `install_deb.sh` next to the DEB:

    sh install_deb.sh /vollstaendiger/pfad/Heimserver_Manager.deb

Selection 2 uses `su` and prompts for the root password. This also works if sudo is missing or the user is not in the sudo group. Selection 1 is for existing sudo permissions. No password is stored in the script; Selection 3 installs sudo as needed and adds exclusively the invoking normal local user account to the sudo group, which requires the root password. This selection grants permanent administrator rights; fully log out and log back in before using sudo in the user account. Selections 1 and 2 do not change group memberships. Alternatively, run `apt install /vollstaendiger/pfad/Heimserver_Manager.deb` as root.
After installation, the manager starts automatically as a system service.

# KVM / libvirt

Under Apps Manage → KVM / libvirt → Install or set up KVM / Bridge there is an approved installation plan. QEMU for amd64 or arm64, appropriate UEFI firmware, the libvirt system service, clients, virt-install, Python-libvirt, dnsmasq-base, bridge-utils and iproute2 along with their APT dependencies are installed. VT-x/AMD-V or the corresponding virtualization support must be available in BIOS/UEFI or hypervisor.

Network options:

- NAT: libvirt network `default`; no change to the host LAN connection.
- Existing Linux bridge: set up the libvirt network via `servermgr-lan`.
- New LAN bridge: only over a free wired network card without IP address, route, master or configuration, using ifupdown and interfaces.d. The bridge receives no host IP; VMs use the LAN. Existing management connections require separate takeover option (see below). WLAN, NetworkManager and systemd-networkd are not migrated.
  First set up a bridge with the respective network administration tool and then select the existing bridge option.

Optionally, a normal local user can be added to the libvirt and kvm groups. This allows management of system-wide VMs; re-login required. No sudo permission is granted. Automatic removal of KVM is disabled so that existing VMs and shared services are not inadvertently affected. Hiding remains possible.

References: https://wiki.debian.org/KVM and
https://libvirt.org/formatnetwork.html#using-an-existing-host-bridge

## Take over active LAN card

Additionally, there is the option "Take over active LAN card". Supported are manageable ifupdown configurations with static IPv4/IPv6 or DHCPv4.
MAC address, address options, gateway, DNS and explicit DHCP client details are transferred to the bridge. `auto` and the Networking service ensure autostart.
DHCP may assign a different address despite identical MAC (e.g., other IAID); confirmation is only possible if previous IPs and MACs are present again.

Before changes, configuration and state are saved. An independent systemd timer restores after five minutes without confirmation. A persistent boot service also restores unconfirmed configurations after a reboot.
After reconnecting in the KVM installer confirm "Connection works – keep bridge". Only then is the libvirt network servermgr-lan set up.

NetworkManager, systemd-networkd, WLAN,
DHCPv6, distributed/special include structures, network hooks and
interface-specific additional DHCP configurations are not automatically migrated. Manual bridge setup with the existing network administration tool is required here.
Do not make parallel network changes during an open migration.
The restore reduces risk but does not replace local console access.
