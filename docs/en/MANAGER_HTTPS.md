# HTTPS Access to Home Server Manager

New DEB first installations install Apache, OpenSSL, Certbot and the Apache plugin for Certbot in addition to existing dependencies.
Apache establishes a connection to the local manager port. Other Apache websites are not overwritten. Fail2ban remains optional; it is not required for TLS and can be configured under Web & Security.

A new package installation proposes `<rechnername>` and creates a private HTTPS virtual host on port 443 with a local certificate authority. The Manager HTTP backend listens exclusively on 127.0.0.1. If HTTPS setup fails, check Apache and ports from the server terminal and repeat `sudo dpkg --configure server-manager`. There is no external HTTP fallback. See Settings → HTTPS.

## Private Access

1. Open Settings → HTTPS. Check hostname, HTTPS port and allowed networks.
2. Verify setup and confirm the preview.
3. Set the name in local DNS/Router to the static server IP. Alternatively
   use hosts files on clients; the interface shows the paths.
4. Download public root certificate, compare fingerprint with output at
   the server and import as trusted CA on devices.
5. Open HTTPS address and check login, downloads and uploads.
6. Switch client agents to HTTPS address after certificate import.
   Agents do not automatically follow HTTP redirects.

Windows can add the CA for the current user in "Trusted Root Certification Authorities". Debian/Mint: copy CRT
after `/usr/local/share/ca-certificates/` and execute `sudo update-ca-certificates`.
Browsers with their own certificate store may require separate import.
Private keys are not offered for download. The CA is unique per server;
hostname/networks can be changed later in the same form.

By default, the private virtual host allows RFC1918 IPv4, loopback, and private/link-local IPv6 networks. Add the specific LAN prefix when using global IPv6 at home. DNS, router and firewall settings are not changed automatically. The package binds the unencrypted HTTP backend only to 127.0.0.1; clients use HTTPS. Check differing legacy manual installations separately.

## Renewal

`server-manager-https-renew.timer` checks daily with up to one hour random
delay; missed runs are caught up. Server certificate is valid for one year
and renewed when less than 30 days remaining. Apache is checked and
reloaded. Local CA is valid ten years and not automatically replaced;
CA change must be planned due to client trust establishment.

Errors are visible in service journal. Changes to Apache save own
configuration files. Failed activation rolls these back; initially created local CA remains intact.
Already active other websites and their certificates remain unchanged.

## Public Domain Later

Settings → HTTPS → "Later: public domain and certificate". Set own
manager login password. Select domain and optionally existing valid
Let's Encrypt certificate; otherwise specify email and consent for issuance.
For HTTP-01 DNS and external ports 80/443 must point to this server.
The new public VHost exists in addition to private access.
Public certificates renewed by Certbot with Apache reload hook.

Preview explicitly shows publication. DNS/port forwarding
not set up automatically. Existing domain Vhosts not replaced;
available and editable under Web & Security.

## Proxy and Login

The Manager trusts HTTPS metadata only from the local Apache proxy with its host-specific internal key. Arbitrary X-Forwarded headers do not establish HTTPS trust. HTTPS session cookies receive Secure. The original client IP and HTTPS scheme are used for login and form-origin checks. The internal HTTP backend is not a public LAN endpoint.

The short computer name is only a default during initial setup. Under Settings → HTTPS Access, the private HTTPS name can be changed later. Saved names persist across updates. The change issues a new server certificate with the existing CA; it does not alter the Linux machine name. Adjust DNS/hosts entries, bookmarks, and client profiles accordingly.

Private HTTPS access can use both a hostname and a fixed server IP. Optional IP access uses its own port (default 8443), adjustable under HTTPS Access. The certificate also contains the IP; the same network restrictions and login apply. Trust the root certificate on clients. Update the setting when the IP changes.