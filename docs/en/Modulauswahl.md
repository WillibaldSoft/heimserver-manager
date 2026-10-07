# Module Selection per Server

Under **Settings → Module Selection**, you can select Home Network/Presence/Client Agents and the TV module.
After logging in, the overview displays a setup hint as long as no selection has been saved for this installation yet.
The selection is stored exclusively locally in `/etc/server-manager/modules.json` (or the configured configuration folder).

- Main Server: Keep Home Network & Presence enabled if needed.
- Secondary Server: Turn off when another server already monitors the devices.
- Disabled home network monitoring does not send new scans, accepts no client agent notifications (HTTP 503), and provides no associated sleep blockers. Saved devices, agents, and previous presence settings remain intact. An individual test that is already running may briefly continue to run.
- DynDNS and Virtual Machines are independent main areas. When home network monitoring is disabled, the Network section from the main navigation and overview is hidden.
- TV automatic: only display and monitor when TVHeadend is available locally or a connection has been established.
- TV active: deliberately configured monitoring; connection errors continue to protect against sleep mode.
- TV disabled: hide the area, turn off TV sleep blockers and TV wake-up candidates. The TVHeadend service itself remains unchanged.

The LAN interface and IPv4 network can be explicitly set. Without a default value, the unique active IPv4 standard route is evaluated.
Existing explicit `lan_network` values from Server & Module Paths are preserved; module selection may overwrite them for monitoring purposes.
Docker-, TAP-, libvirt- and comparable virtual interfaces are not automatically selected.
In case of ambiguous detection, specify a LAN interface and an IPv4 network with at most 4096 addresses.
The detection does neither change the IP address nor Bridge, Route or network configuration of the operating system.
