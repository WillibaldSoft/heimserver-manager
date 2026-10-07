# Central Alarms

Under **Alarms**, ntfy delivery, storage thresholds and alarm sources are managed. Previous ntfy settings remain in the same local database entries. An empty token field retains the stored token; to remove it there is a separate selection. The token does not appear in HTML and is not passed as a process argument. For external ntfy servers use HTTPS. Redirects are not followed during delivery.

Automatic delivery is initially disabled. Storage/SMART is pre-selected as source; backups, DynDNS, certificates and system services are optional. Select only permanently required services. Monitoring reads existing states and does not start updates or backups or repairs.

- Storage: usage and SMART warnings from the storage check.
- Backups: missing/overdue required backup monitoring tasks and errors of the last central backup job.
- DynDNS: provider errors or missed checks.
- Certificates: warning after 30 days, critical after 7 days or upon invalidity.
- Services: selected services are missing or not active.

The check interval is adjustable from 1 to 1440 minutes (default: 5). The optional daily reminder uses local server time (default: 09:00) and runs independently of the interval, with up to a 30-second delay. If the manager is stopped or the server is sleeping, no check takes place. An external failover watcher is not replaced by this.

**Check now (without delivery)** updates the local preview.
**Check and send due alarms** sends only overdue warnings if ntfy is enabled.
**Send ntfy test message** sends a test notification.
These actions use already saved settings.

New, re-occurring or worsened warnings are sent. Unchanged warnings are repeated once daily at the set time. The reminder can be disabled separately. After interruptions, the reminder for the current day is made up, not for past days. Successful deliveries are saved so that restarts do not trigger duplicate notifications. A previously deactivated hourly reminder remains deactivated. Delivery errors are retried earliest after five minutes. States persist across restarts.

Storage alarms contain device, mount name and mount points for assignment.
Other sources default to containing only the affected module designation.
The optional detailed transmission can include local paths or domains.
Access credentials belong exclusively in the local configuration, not in source code, package or documentation. Old storage links with `send=1` no longer trigger delivery; delivery actions are centrally managed under Alarms.
