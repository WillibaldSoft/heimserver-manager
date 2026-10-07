# NVIDIA Drivers under Apps

The own NVIDIA card shows PCI graphics cards, GPU names determined via nvidia-smi, loaded and disk-installed module versions, DKMS per kernel, kernel headers, and Secure Boot. Installed package versions are compared against candidates from configured APT sources. This is not a comparison with the latest NVIDIA website version. Package lists can be explicitly updated via a logged background job.

Automatic actions are planned for Debian 13:
- Hardware check: install or update nvidia-detect. Installing alone does not deploy a graphics driver. Then reopen the administration page.
- Reinstallation if there is an unambiguous nvidia-detect recommendation for nvidia-driver.
- Update existing nvidia-driver/nvidia-kernel-dkms within the same package family or reinstall including appropriate kernel headers.

Every package installation requires a one-time preview valid for ten minutes and confirmation. The preview displays concrete versions and simulated changes. After updating the package lists, the plan is compared again; if anything has changed, a new preview must be created. Removals, downgrades, foreign driver families, and detected .run installations are not automatically accepted. Package sources will not be added or overwritten. Missing candidates must be resolved via system package sources; NVIDIA packages require matching Debian components including non-free.

Running GPU compute processes lock driver changes. End graphical sessions and other GPU users before making changes. Usage that starts only during installation cannot be excluded. If Secure Boot is enabled, the DKMS key must already be enrolled; an unknown status blocks installation. The manager does not change firmware/MOK settings.

The manager unloads no drivers, restarts no display server, and performs no system reboot. Debian package scripts may restart services; updates to user libraries can affect running applications. Activation after driver changes occurs via a separately scheduled reboot. In case of errors, partial rollbacks are possible; automatic full rollback is not performed. A status report is stored in the manager state directory before the action. All actions use existing APT jobs, logs, and sleep blockers.

The drivers themselves are not included with delivery. NVIDIA components retain their own, partly proprietary license terms. GPL-3.0-or-later applies to the manager, not the installed drivers.

References:
- https://wiki.debian.org/NvidiaGraphicsDrivers
- https://packages.debian.org/stable/nvidia-detect
