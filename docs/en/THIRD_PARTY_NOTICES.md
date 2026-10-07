# Third-Party Components

## Included: Makeself 2.5.0-1 (Debian package version)

- Path: `modules/fotolabor/vendor/makeself/`
- Origin: https://makeself.io/ and Debian package `makeself`
- Copyright: 1998–2023 Stéphane Peter and other authors mentioned in the source code.
- License: **GPL-2.0-or-later** (Debian designation: GPL-2+).
- Unchanged license and copyright notices: `COPYING` and `copyright` in the directory above.
- The shell sources are included. The project license does not replace these notices.

## Separately Installed Dependencies and Applications

Python, Flask, Werkzeug, Pillow, libvirt, Waitress, and system tools are installed via the specified package dependencies. Optionally installed apps and additional packages retain their respective licenses. Their files are not generally covered by this manager's project license.

Before incorporating further third-party sources, document their origin, license, and required notices. This overview does not claim to comprehensively capture all transitive or future dependencies.

## Optionally Downloaded: Digital Devices dddvb

Driver version 0.9.41 is downloaded from the manufacturer's repository https://github.com/DigitalDevices/dddvb upon explicitly initiated installation.
It is not part of the manager DEB. Its source and license files are preserved unchanged in the driver source directory; the GPL-3.0-or-later license of the manager does not replace the driver's license.

## Optional NVIDIA Drivers

The NVIDIA administrator installs packages from configured system sources upon explicit request. NVIDIA drivers and firmware are not delivered with the manager and retain their own, partially proprietary license terms. The GPL-3.0-or-later of the manager does not license these components. Applicable licenses are those specified in the respective Debian packages.
