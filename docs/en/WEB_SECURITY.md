# Web & Security

Under Server → Web & Security you find Apache, certificates, and Fail2ban. Status queries do not change configuration. Installer & Setup contains separate installers for Apache, Certbot, and Fail2ban. Each installer is available as a standalone Python file for Debian/Ubuntu:

    python3 installer-apache.py --check
    sudo python3 installer-apache.py --install

Use the actual download name. Without --install, only a check is performed. Existing packages are not specifically updated; missing packages may install additional dependencies. Services are activated and started after configuration verification. Occupied web ports prevent initial installation of Apache.

Changes require a preview and approval. Jobs run under systemd, log their status, and automatically block sleep. Modified initial configurations require a new preview. Backup snapshots are stored in the respective job folder under the configured state directory/web-security/jobs.

Certificates are validated using public certificate files. HTTPS targets are explicitly specified: domain, port, optional direct connection IP and local certificate name. Validation uses domain/SNI and checks the certificate chain. A fingerprint comparison indicates whether the service actually serves the local certificate. DNS, NAT, and firewall can affect external validations from the server.

Initial installation of a certificate requires an existing Apache website, publicly matching DNS, and accessibility on port 80. Existing certificates use their stored Certbot renewal configuration. A renewal test may execute existing pre-/post-hooks. The status of an active timer alone does not prove successful renewal.

The optional server manager login protection logs only the direct connection IP on failed attempts. Your own Fail2ban rule blocks access to the configured server manager port for 15 minutes after five attempts within ten minutes; loopback is exempted. Behind a reverse proxy, the rule must be adjusted to its access path; any forwarded headers are not trusted. Existing jails remain intact. The rule becomes active only upon explicit setup.

## Manage Individual Certificates

In the certificate overview, "Install Certificate for Domain" leads directly to configuration. A domain name results in its own certificate; optionally entered additional names share this certificate.

"Delete..." first checks references in actually mounted Apache files, nginx, Postfix, Dovecot, HAProxy, local systemd units, Certbot renewal hooks, and stored HTTPS targets. Found usages block deletion. External copies and arbitrary applications cannot be fully automatically detected.

After entering the full certificate name, a preview follows. Only upon confirmation does `certbot delete --non-interactive --cert-name NAME` start. Immediately before that, usage and initial state are rechecked. Deleted is the entire Certbot certificate group including private key, local versions, and renewal configuration; for multiple domains all are affected. DNS, website files, and external copies remain intact. The action is not a revocation and does not create an additional copy of the private key.

Reference: https://eff-certbot.readthedocs.io/en/stable/using.html#safely-deleting-certificates

## Edit Apache Files

The usage indicator links regular `sites-available/*.conf` to a logged-in admin editor. "Active/Inactive" controls the associated link in `sites-enabled`. The preview shows text differences and status changes. Changes since opening or preview are rejected.

Before takeover, content, permissions, and link state are backed up to the protected job folder. A failed configuration test restores original and activation. If reload fails, the old configuration is additionally reloaded again. Deactivation affects all VirtualHosts of the file. Even inactive edited files are temporarily mounted for a configuration test without loading them live.

The certificate check uses Apache's `DUMP_INCLUDES`: unmounted websites and backups appear separately and do not block. Explicitly mounted backups remain blockers. Before reactivating an old file, any certificate references contained within it must still be valid.
