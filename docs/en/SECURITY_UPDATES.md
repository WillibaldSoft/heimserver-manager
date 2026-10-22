# Automatic security updates
Under Applications → System packages → Automatic security updates, administrators can install `unattended-upgrades` and `needrestart` and enable or disable automation. New installations default to disabled.

The systemd timer checks every two hours daily (00, 02, …, 22, local server time), with up to five minutes of randomized delay. It does not wake the machine. Missed runs are caught up at the next boot. Backups, installations and other APT jobs defer a run until the next scheduled attempt. An APT job blocks sleep while running. Disabling does not interrupt an ongoing package installation.

Only available updates from official Debian or Ubuntu security repositories are considered; Mint uses its Ubuntu base. This is not a full CVE scanner or a critical-only classification. Unknown distributions are rejected. Containers and separately installed applications are excluded. Package holds and administrator blacklists remain effective. No automatic package cleanup, distribution upgrade or server reboot.

needrestart automatically restarts affected services, then checks again in batch mode. Local exclusions remain effective. Outstanding services, security updates and kernel/microcode reboot requirements remain visible; package success does not guarantee that all vulnerabilities are fixed. Service restarts can interrupt existing connections. Other configured APT timers remain unchanged.

ntfy uses the existing enabled configuration under Alarms. Notifications cover installed updates, failures and pending restarts. Unchanged warnings are suppressed; failed delivery is retried on the next run. Without detail consent, only counts are transmitted, not package or service names. Credentials and raw logs are never sent. The security page displays failed or disabled notification delivery.

Sources: https://manpages.debian.org/testing/needrestart/needrestart.1.en.html and https://sources.debian.org/src/unattended-upgrades/2.12/README.md

Read-only diagnostics: `sudo python3 /opt/server-manager/tools/security/check_run.py`. Completion verification uses the status marker or stored results from older runs; a missing command log entry no longer incorrectly indicates that no check ran.
