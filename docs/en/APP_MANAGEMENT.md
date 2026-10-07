# Manage Apps

The app overview contains exclusively recognized, fully installed and displayed apps. A stopped service remains installed. Non-verifiable or partially existing installations remain visible under "Manage Apps".

Installation, uninstallation and visibility are managed under `/apps/manage`. The previous catalog link redirects there. App cards no longer contain an installer. Newly registered container apps will only be displayed after successful installation.

"Hide Only" changes exclusively the display settings. "Uninstall" first shows a current schedule and requires confirmation. The background job checks the plan again. Containers of a uniquely assigned Compose project are removed together, including database containers; volumes, bind mounts, images, and compose files remain intact. Volatile container contents are deleted. The container configuration is preserved for "Re-installation".

ComfyUI and OSCam: The known service is stopped/deactivated; the program and service file are kept on the same filesystem. Tvheadend: Package removal without purge or autoremove, only if APT would not remove additional packages. Reinstallation uses the preserved data.

The running Server Manager, shared mount tools, and existing native Nextcloud do not support automatic uninstallation. The interface lists reasons; hiding remains possible. Nextcloud as a standalone Docker stack is supported.

Protected restore data are located under `/var/lib/server-manager/app-lifecycle`. Incomplete uninstalls are not treated as successful and block automatic reinstallation until verification. App jobs use the existing serialized installer worker and sleep blocker. No production app is installed or removed during rollout of this UI change.
