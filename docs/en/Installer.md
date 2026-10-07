# Installer Plan

The later installer reproduces the Server Manager exclusively from Repository + Migrations.

## Steps

1. Install packages
2. Create user/group
3. Copy project to `/opt/server-manager`
4. Create `/etc/server-manager`
5. Create `/var/lib/server-manager`
6. Generate configuration files
7. Execute migrations
8. Install systemd service
9. Start service
10. Display project status

## No patch scripts

Patch scripts from development are not part of the installer.
