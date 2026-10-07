# Scanner Module

`/scanner` manages the existing Flask scanner API from `/opt/scanner-api/scan_api.py` and `scanner-api.service`. The basis is the existing script with PDF, quick-PDF, JPG, and TIFF scan sessions. The Home Assistant endpoints `/pdfscan`, `/quickscan`, `/jpgscan`, `/tiffscan`, `/finish`, `/cancel`, and `/status` remain intact. No scan is triggered by administrative checks.

## Settings

- Fixed scanner IPv4, port, eSCL/WSD protocol and path; alternatively existing SANE device detection with automatic discovery.
- API bind address and API port (previously 0.0.0.0:8181).
- Output folder and existing Linux service user. The session folder remains `/var/lib/scansession`.
- For the fixed scanner IP, only a dedicated SANE profile under `/etc/scanner-api/sane` is used. The system-wide SANE configuration is not replaced.
- The service receives its settings via a dedicated systemd drop-in and `/etc/scanner-api/server-manager.env`.

Configure scanner address, device detection, service user, and output folder on new servers before installation.

## Installation and Changes

Installation runs in a separate systemd unit with a maximum runtime of 30 minutes. Only missing packages are installed: python3, python3-flask, sane-utils, sane-airscan, img2pdf. Existing scans are not deleted. OCR is not implemented.

An active session or occupied scan lock prevents takeover. Managed files are backed up under the respective job in `/var/lib/server-manager/scanner/jobs/<ID>/backup`; `backup-files.json` assigns backups to their target paths. In case of a failed API restart check, files and previous operational state are restored. A hard process/host crash may require manual restoration from this backup; interrupted jobs will be visibly marked. Package installations are not automatically rolled back.

Deviant API scripts modified outside the module are not overwritten. Configuration changes and installers are CSRF-protected and check the configuration revision. Running installations and open scan sessions report a sleep blocker.

## Checks and Home Assistant

API status, API configuration, TCP reachability of the scanner, and SANE detection are separate results. This is not a physical scan test. Check write permissions for the service user on the output folder. The Home-Assistant YAML can be displayed and downloaded; existing rest/rest_command sections must be merged. If the API port or bind address changes, adjust clients accordingly.

Reference: https://github.com/alexpevzner/sane-airscan/blob/master/airscan.conf
