# VM Backup and Restoration

Secure a regularly shut-down VM via KVM → VM Details → **Create backup**.
Keep it powered off throughout the entire backup process, also in external management tools.
KVM jobs and uploads are serialized; ongoing transfers and jobs block server sleep.
Download the package under **Backup & Restoration** or from the completed job.

The storage target is `system_backup_root/kvm`; the base folder can be changed in Settings → Server & Module Paths.
A package contains the original domain XML, all local disk images as compressed RAW data,
existing RAW UEFI NVRAM and the unencrypted emulated TPM 2.0 state.
SHA-256 checksums verify integrity, not the trustworthiness of origin.
Backups contain private guest data and must be stored accordingly protected.

Not included: RAM/Managed-Save state, ISO media, snapshot history, host software, and network configuration.
Secured disks include the installed guest system with programs, settings, and data.
Host devices/USB passthrough, host filesystem shares, network/block disks, chained or encrypted images,
encrypted/physical TPMs and unknown configuration elements are explicitly rejected.
Such VMs will not be misleadingly reported as fully backed up.

## Restore

1. Run the KVM installer on the target server (including qemu-utils, UEFI, swtpm/swtpm-tools).
2. In the installer select **Upload VM backup / restore** or open KVM → Backup & Restoration.
3. Specify package and free VM name; accept network or migrate all adapters to an existing bridge/libvirt network.
4. Keep upload window open in browser until completion. Then follow Archive verification and restoration under Jobs.
5. Check new powered-off VM and start it intentionally.

Existing VMs/folders are not overwritten. Restoration creates a new UUID and new MAC addresses,
disables auto-start, empties CD drives and binds the graphics console only to localhost.
The rest of supported virtual hardware is preserved. Local emulator paths and security labels will
be re-detected by libvirt. Firmware files must exist on target host; no automatic replacement
of unknown machine/CPU/firmware versions. A new VM identity may require renewed Windows activation or
BitLocker restoration. Guest IP, hostname, accounts and machine-id remain unchanged in filesystem.
Do not start original and restore unverified parallel in same network.

Uploads in 4-MiB blocks, max 1 TiB compressed; unpacked total size max 16 TiB.
At least 2 GiB memory reserve required; backup conservatively checks virtual disk total size twice,
restoration checks unpacked total size. RAW files are stored sparse.
The upload expires after 30 minutes of inactivity; restart discards started uploads.
On normal error temporary files are removed. After process termination `.build-*`,
`.restore-*` and `.partial` may remain: check job log and directory before manual removal.
Successful server backups are not automatically deleted or rotated.

## Technical safeguards

Only normal USTAR/GNU file entries with exactly expected names, sizes, and hashes are processed.
No links, traversal, PAX extensions, or automatic archive extraction. Uploaded disks are always
explicitly treated as RAW; foreign qcow2 headers cannot open host files as a backing file.
XML uses a positive list; paths are replaced, firmware paths limited to installed system firmware,
libvirt checks the final definition against its schema. VMs never start automatically.
