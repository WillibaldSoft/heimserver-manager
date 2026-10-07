HEIMSERVER MANAGER CLIENT – WINDOWS 0.2.2
September 30, 2026 – GPL-3.0-or-later (see LICENSE)

For Windows 10 and Windows 11 with .NET Framework 4.8 or newer.
A standalone Windows EXE; no Python, Bash, WSL or Mono installation
on the Windows PC required. Not digitally signed. Check origin before execution
and the included SHA256 checksum.

SETUP
1. Download EXE and open as normal Windows user.
2. In Manager under Network / Client Agents create a separate client for this
Windows PC and download its setup (.json).
3. Choose "Import Profile (.json)" in the app and verify entries.
4. Keep "Start status icon at Windows login" enabled if desired.
5. "Activate Agent": save settings, set up start menu/auto-start and regular heartbeat. No administrator required.

"Install for User" copies the EXE to
%LOCALAPPDATA%\Programs\HeimserverManagerClient\0.2.2 and creates the start menu entry.
With auto-start selection enabled this also happens upon saving.
Windows can delay auto-starts or disable them in Settings / Apps /
auto-start. The icon may be located in the hidden notification area.

FUNCTIONS
- Wake server: Wake-on-LAN, Recovery call, both methods or no wake.
- Server required / release: Report need directly to the manager.
- Wake and connect: wake up, wait for reachability for a maximum of ten minutes,
  then report server requirement. No network drive will be mounted.
- Prepare access: wake up and wait; no file access monitoring.
- Heartbeat every 60 seconds; reachability check approximately every 15 seconds.
- Three operating modes like the Linux agent: start with server (automatic
  waking and reporting), do not start server, only wake on explicit call.
- The next heartbeat message resets the requirement according to the operating mode.
- Settings, JSON profile import, log, abortable actions,
  status icon, startup menu, and user auto-start. A second launch opens the window
  of the existing instance; no second Heartbeat process.
- When the Windows PC wakes up, the status is checked again.

SETTINGS AND TOKENS
The JSON profile has the same format as on the Linux desktop client. It contains
a personal agent token: do not share it. Set up a separate client in the manager
for each PC used simultaneously. Linux configuration files are not automatically
searched for or executed as shell code under Windows.
Saved settings are stored under %LOCALAPPDATA%\HeimserverManagerClient
and encrypted with Windows-DPAPI for the current user.
config.dat.bak holds the previous encrypted configuration before. A copy
of these files to another PC/user is not a transferable profile.
Network and recovery addresses as well as tokens are not written to the log.
The EXE does not contain personal server data or credentials.

OPERATION / TERMINATE
Closing the window minimizes it to the notification area; agent and heartbeat continue running.
In the icon menu "End agent and status symbol" also terminates the heartbeat.
Unlike the Linux timer, the Windows agent runs in the same process as the
status symbol. Logging off ends this user session; there is no Windows service.
After logging on again, it starts according to auto-start and saved operating mode.
The display "reachable" alone is not proof of a successful login.
Faulty tokens are detected by the authenticated heartbeat.

DEACTIVATION AND REMOVAL
"Deactivate agent" stops reports and removes user auto-start. A requirement already reported runs out according to manager run time; for immediate release select "Release server" beforehand. Settings remain intact.
"Remove Auto-start / Startup menu entry" additionally deactivates the startup menu item.
Then end the app via the icon menu. If necessary, delete the program folder and separately
the settings folder in the user profile. Do not remove dependencies.
For a later update first end the running app via the icon menu,
than open the new EXE and select "Install for user".

TEST BUILD / LIMITS
- EXE built with Mono-C# compiler for .NET; no Mono libraries included.
- 15 core checks plus HTTP protocol check against local test server:
  modes, profiles, authentication, Wake packet, Recovery, Redirect protection, abort.
- Windows Forms window and tray component checked on the test display under Mono.
- Real start on Windows 10/11, Windows-DPAPI, startup menu and auto-start there
  not yet live tested. This first Windows version is experimental.
- Wake-on-LAN requires a suitably configured network card/network; sending a
  Magic packet does not confirm successful server start.
- Recovery service remains a separate setup on an reachable host.
- In case of network outage, checks/heartbeats are repeated, but no arbitrary
  manual actions are re-executed uncontrolled.

SOURCES / REBUILD
Source code and build.ps1 lie in the source archive. Under Windows with installed
.NET Framework: powershell -File .\build.ps1
References: Windows Forms, System. Drawing, System. Runtime. Serialization,
System. Security; exclusively Windows/.NET standard libraries.
Microsoft documentation:
https://learn.microsoft.com/en-us/dotnet/framework/install/on-windows-and-server
https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata
https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys


NEW IN CLIENT 0.2.2
Own file backups and restore in the client; server backups only via renewed manager administrator login in the browser. Private HTTPS with verified root certificate, optional hostname entry, and administrator approval.
First set up backups in the Manager desktop client security section and use a separate JSON profile per user. File backups are not complete system images.
Links, special files, ACLs, and operating system state are not fully backed up.
Details: docs/CLIENT_BACKUP_ACCESS.md in the manager source package.


Development status as of October 4, 2026 – Linking users and devices
- Linux Client 0.4.1 and Windows Client 0.2.3: own token and own sleep blocker per Manager user, device, and local user identity.
- Import JSON profile, set up HTTPS, log in to the manager, and select link user & device. Linux: in Own Client Backups dialog; Windows: directly in settings. Releasing Own Clients & Backups requires Role User or Administrator. Read-only permission cannot link.
- A single user on multiple PCs and multiple users on a PC can independently report their need. Release only affects the own entry.
- Server MAC is exported in JSON and taken over during linking. If both recovery address and server MAC exist, both wake-up paths are available in JSON.
- Device identification is derived locally from machine-id (Linux) or MachineGuid (Windows); local user identity from UID or SID. The MAC is only supplementary information. A changed system/user account may require relinking if necessary.
- New tokens are bound to these identities; copied profiles do not automatically fit other PCs/accounts. No hardware-based proof of identity: token and system access continue to be protected; identities can be mimicked.
- Account lockout, permission/password change, or disabled agent prevents further reports. Outdated needs expire according to existing heartbeat timeout.
- Old profiles remain visible as Unlinked (Altprofile) and function unchanged. After transitioning all users, disable the shared Altprofile together. Existing backup repositories are not moved; manager account backups remain independent of device linking. Manager logout ends only the web/backup session; disabling agent separately shuts down via agent.
- Windows build and transport tested; native Windows login/Registry SID and the interface have not yet been tested on an actual Windows PC.


Development status as of October 4, 2026 – Personal client setup
- After logging in to manager under https://SERVER:HTTPS-PORT/clients/setup download Linux DEB, Windows EXE and own setup profile.
- Releasing Own Clients & Backups and Role User/Administrator required. No view of foreign profiles or tokens. Read-only can download programs but cannot set up new device linking.
- Profile contains server address, server MAC, possibly private certificate information and a 15-minute valid one-time code. On the server only its hash is stored.
- Linux 0.4.2 / Windows 0.2.4: import profile, save, optionally set up private HTTPS after fingerprint verification; activating agent exchanges the code via verified HTTPS for own user-device token. No password storage.
- Each new profile replaces earlier unused codes of same account. Upon expiration, lost response or failed local storage fetch new profile. Permission change/account lockout also prevents redemption of existing codes.
- Start mode Start without server then select manually. Root certificate and hosts entry continue to be changed only upon explicit confirmation. Backup login remains separate; personal setup grants no server backup rights. Windows remains experimental, native Windows verification pending.

Language / Language
German for German desktop display language, otherwise English. Selection at program startup; after changing the desktop language restart the client.
The language in the manager browser and the JSON profile do not change this selection.
Install new client version; existing settings remain intact.
Own names, paths, technical protocols and output of external programs
(including the USB/NFS migration script) remain unchanged.

German for a German desktop display language; English for all other languages.
Restart the client after changing the desktop language. Browser language and
JSON profiles do not override this setting. Install the new client release;
exiting settings are preserved. Names, paths, technical logs and external
program output (including the USB/NFS migration script) remain unchanged.
