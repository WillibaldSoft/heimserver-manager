# Separate platform packages – Debian regular, Mint experimental

The experimental Debian phase ends after confirmed update operation. Mint remains experimental. v0.12-47 remains an unchanged backup snapshot. The productive Debian installation is not altered by development and building of test packages. No automatic merging or installation occurs. A Git tag does not replace a data backup.

| Package Profile | Accepted Operating System | Python Dependency |
|---|---|---|
| debian13 | ID=debian, VERSION_ID=13 | >= 3.13 |
| mint22 | ID=linuxmint, VERSION_ID=22 or 22.x, UBUNTU_CODENAME=noble | >= 3.12 |

ID_LIKE is explicitly insufficient. LMDE, Ubuntu itself, Debian 12, and unknown versions are blocked. LMDE will later require its own profile. Both packages are named server-manager internally and carry the same development version; filenames and release directories contain the profile. The Control field X-Heimserver-Target and package-target.json specify the target platform.

## Installation Check

`sh install_deb.sh --check DATEI.deb` checks the target platform without installation. The regular launcher checks before APT and before additional installations. Direct `dpkg -i`/`apt install` is additionally secured via preinst; config and postinst also check. Rejection of preinst occurs before unpacking the manager. APT can edit dependencies upon direct invocation beforehand; therefore, use the launcher for a check prior to any package action.

The new web update check rejects incorrect or missing platform information during upload and before execution. An older manager does not yet have this pre-check; however, the new DEB still checks its own platform independently. Old, already distributed DEBs are not subsequently altered and do not possess this lockout. Root can manipulate packages; the lockout protects against confusion and is not a security boundary relative to the administrator.

## Mint Test Scope and Limitations

The base build supports Python 3.12. This is not yet a full Mint release.
Debian-specific NVIDIA/dddvb installers remain blocked on Mint. Drivers there
must be managed via the Mint system administration until proprietary procedures are tested.
Optional app installers must be validated individually. The interface shows
the experimental status. Automatic sleep and RTC background actions
cannot run under Mint, including inherited activated settings.
Manual energy actions remain consciously triggerable management functions.
Debian retains its previous workflow.

ACL support depends on the target filesystem and mounting configuration. Mint is
not treated as ACL-incapable in general. Before release tests, verify tools getfacl
and setfacl along with read/write permissions, inheritance, user assignment, and Samba access
on a separate test directory on the intended drive.
Never replace existing shares en masse with a test configuration.

## Build and Release

    python3 tools/build_release.py --target debian13 --output-root dist
    python3 tools/build_release.py --target mint22 --output-root dist

Required before production release: genuine Debian-13 and Mint-22.x VMs with
fresh installation, cross-platform rejection test, reboot, login, update,
and uninstallation; followed by Samba/ACL, app, and desktop tests. DKMS and Secure Boot
must additionally be verified on suitable hardware. Emulated system identifiers and
extracted package scripts do not replace full VM installation tests.

## KVM from platform2 onwards
KVM package verification supports Debian 13 and Mint 22.x/Noble. NAT is the default;
select a LAN card via the dropdown if a LAN bridge is desired.
The active LAN takeover still requires an approved preview and
appropriate NetworkManager/ifupdown configuration. Package resolution was successfully simulated on
Mint 22.3. This does not replace real bridge/VM testing.
