# Digital Devices · DVB Drivers

Under Apps and Manage Apps, the card leads to Digital Device Management.
It displays PCI cards along with their PCI revision, loaded and installed ddbridge drivers,
kernel headers, Secure Boot status, and registered DKMS states per kernel. The PCI revision
is not a firmware version; neither is the firmware flashed nor automatically changed.

Explicit version checking queries the official GitHub Release API.
Errors are treated as unknown state, not as "current". New stable releases
are displayed. Initially, only 0.9.41 can be installed automatically,
with a fixed HTTPS download and a stored SHA256 checksum.
Later drivers require new approval in the Manager, not just a new tag.

Installation and updates support Debian 13 on detected Digital Devices PCI
hardware. After preview and confirmation, DKMS, build tools, and headers
for the running kernel are installed. Two modes can be selected: manufacturer-dvb-core
or Kernel-dvb-core. The latter may restrict manufacturer functions.
The manufacturer-dvb-core may affect other DVB devices.

An existing target version is not overwritten. Repair rebuilds from the
available registered sources and retains their DKMS configuration.
Older registered 0.9.x states up to 0.9.40 can be updated to the verified state;
nearlier, unknown, or manually installed module states block automatic adoption.
Source folders and older DKMS registrations remain intact.
No automatic uninstallation. For previous settings such as fmode,
The existing modprobe configuration remains decisive.

Actions run as persistent systemd jobs via the existing APT management
with logging and sleep blockers. Kernel and inventory are rechecked before execution.
In case of errors, packages, sources, or DKMS files may already be modified;
no complete automatic rollback is possible. Inventory and existing dkms.conf are
backed up beforehand under the Manager data directory dddvb/before-*.

Loaded drivers are not unloaded, Tvheadend is not restarted, and the server is not automatically rebooted.
After installation, a scheduled restart for activation is planned. No new manual driver changes
are started during this time. Secure Boot must either be disabled or possess a DKMS key
certified by mokutil as enrolled. An unclear state blocks operation.
DKMS rebuilds on future kernel updates again, provided drivers and kernels are compatible;
compatibility with any future kernels is not guaranteed.

The Manager does not deliver the driver in its DEB package. The downloaded
manufacturer sources retain their own license along with license files.

Sources:
- https://github.com/DigitalDevices/dddvb/releases/tag/0.9.41
- https://support.digital-devices.eu/index.php?article=187
