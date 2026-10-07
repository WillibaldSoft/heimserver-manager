# KVM Management

Native manager module under `/kvm`, based on `kvm_vm_manager_V8.sh`.

## Functions

- Existing libvirt system VMs with status, CPU, RAM, firmware, disks, network, and autostart.
- Search, detail view, SSH console command, XML download.
- Start, regular shutdown, restart, pause/resume, and separately confirmed hard power-off.
- ISO installation including Rescuezilla ISO; templates for Linux desktop/server, Windows 11, HAOS, legacy Windows, and DOS/Windows 98.
- Import of qcow2/raw/img/VMDK as independent qcow2 copy. No change to the source file.
- Offline clone with new UUID/MAC, offline disk export to qcow2/raw.
- Offline CPU/RAM adjustment, ISO eject, autostart; configuration backup before changes.
- Removal exclusively of VM definition with exact name confirmation. Disks/NVRAM/TPM are preserved.
- Persistent, serialized background jobs with logs in `kvm_jobs` in the existing SQLite database.
- Central sleep protection for active VMs, jobs, and unknown KVM status.

## Limitations Compared to V8

The shell script is not executed as a web process. It does not automatically install packages, and its guest repair/user changes are not applied. Guest hostname, static IP, machine-id, and credentials of a clone must be adjusted before parallel operation. TPM-/Passthrough-/Filesystem-sharing clones and complex CPU-/NUMA configurations are rejected for manual handling. Snapshots are displayed; make changes via virt-manager. Prepare OVA and VMX separately beforehand; VMDK import only handles the selected disk. A disk export is not a complete VM backup.

All new installations start powered off; autostart is disabled by default. Virtual disk capacity plus reserve is checked against available storage in advance. The ISO is copied to the new VM directory so that file permissions of media shares do not prevent startup.

## Operation

`qemu:///system`; data under `/VM`; ISO suggestions from `/VM/iso` and `/srv/iso`. CPU/RAM changes save XML under `STATE_DIR/kvm-xml-backups` with mode 0600. Definitions without password fields can be downloaded via the UI.

Reboots interrupt running jobs. The next start marks them as interrupted; there is no automatic retry and no automatic deletion of partial results. Check VM list/target folder before re-running a job. Avoid simultaneous changes via external tools during a KVM job.

Prerequisites: python3-libvirt, libvirt-clients, libvirt-daemon-system, qemu-utils, virtinst, ovmf, optionally swtpm/swtpm-tools. Browser access uses the existing access control of the Server Manager. All mutating routes use POST and their own session CSRF tokens; no shell interpolation. Host and user for console assistance are configured in settings.

## Validation

`python3 -m unittest discover -s tests -p 'test_kvm_manager.py' -v`

The tests use simulated domains and temporary databases; production VMs are neither started nor modified. Additionally: check libvirt inventory, XML generation with local virt-install, HTML routes, and blocker integration.

References: https://libvirt.org/python.html · https://www.libvirt.org/manpages/virsh.html · https://virt-manager.org/
