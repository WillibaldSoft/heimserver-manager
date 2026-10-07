POWER & RECOVERY API 2.2 – INSTALLATION AND UPDATE

In the Manager: Applications → Manage Apps → Power & Recovery API.
Open on the machine that runs continuously; not on the sleeping target server.
To unpack this ZIP and run as root for another machine:
  sudo python3 /vollstaendiger/Pfad/install.py
Use su - first if you do not have sudo membership. Debian/Mint with systemd and APT.

Legacy Detection
Known: old ipmi-power-api.service with /opt/ipmi-power-api.py (2.1-stable)
and Manager installation 1.0/2.2. Imports only literal values via AST; legacy Python code is never executed. Unknown legacy remains untouched.
Run the installer again to change settings/version.
Detected addresses, BMC users, wait times, and passwords are adopted.
The previous password is retained with empty input; it is not displayed.
Explicitly select concrete local LAN IP and allowed client IPs/networks.
Old binding to 0.0.0.0 must be replaced. Align existing URLs to the same LAN IP
and the same port. IP releases are not user logins.
Only trusted LAN/VPN; no public port forwarding.

Changes compared to 2.1-stable
- systemd service without root (DynamicUser), password as protected credential file,
  no longer in Python code or process arguments.
- Asynchronous GET/POST /recover and /poweron: 202 means accepted, not finished.
  /status or /summary show recover_active, phase, last_action and last_error.
  Concurrent job results in 409. /version and /health remain read-only.
- /soft, /reset and /cycle as direct endpoints are removed.
- Shutdown/Reset is never sent to the target server during installation.
- With target off: Power on. On and pingable: no switch action.
  On without Ping: optional Soft. After wait time optionally a Reset,
  only if the target remains on and not pingable thereafter.
- Soft/Reset are disabled in new installations. During migration, previous
  active options are adopted and displayed for explicit confirmation.
  Soft can shut down; Reset may cause data loss. Missing Ping does not distinguish Standby from firewall, network issue, or system halt.
- Ping confirms only the machine, not Nextcloud or other applications.

Update and Restore
Running recovery jobs block changes. Do not start new recovery calls during migration.
The following are installed: python3-flask, python3-waitress,
ipmitool and iputils-ping. No OpenIPMI hardware required on the continuous runner.
Protected restore under /var/lib/server-manager/power-api-backups.
On startup errors, previous files are restored; packages remain intact.
During updates, autostart and running/stopped state are preserved.
The old source file with password remains exclusively in the protected backup.

Program: /opt/server-manager-power-api/power_api.py
Configuration: /etc/server-manager-power-api/config.json
Password: /etc/server-manager-power-api/ipmi-password
Service: ipmi-power-api.service
Status: http://RECOVERY-SERVER:8182/status
Recovery: http://RECOVERY-SERVER:8182/recover
Store recovery URL in Manager under Settings → Server & Module Paths → Network.
New client JSON profiles adopt the active setting.
Home-Assistant-YAML remains available under Client Agents. No router/DNS
change and no Nextcloud wake proxy are part of this installer.
