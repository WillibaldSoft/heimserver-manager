# DynDNS Module and Multi DynDNS v4

Integration based on `multi-dyndns-manager-v3.9.sh` from
`einem vorhandenen DynDNS-Skript`. The Shell-Updater has been implemented as an independently
callable Python-3 core, so that the interface and schedule use the same verified logic.
The old interactive manager is not executed in the web process.

## Operation

- `/dyndns`: Provider, Status, last validation check, last confirmed update,
  IP addresses, provider blocks and next timer schedule.
- "Take over existing script" reads v3 configurations as pure data.
The preview contains no secrets. Unreadable configurations prevent
the takeover of all providers instead of silently skipping individual entries.
- The takeover saves a private backup under
`/var/lib/server-manager/dyndns/backups/<Zeitstempel>/restore.json`,
preserves original configurations and existing provider blocks, and replaces
the existing `multi-dyndns-update.service` / `.timer` combination.
- "Add Provider" or "Edit" manages host, IP mode, login,
update URL and active status. Empty password and URL fields receive saved values.
deletion requires confirmation in the form and does not delete any DNS entry.
- "Check IP & DNS" determines addresses and authoritative A/AAAA entries; it sends
no update to the provider. "Update now" starts the systemd service and
continues to respect provider blocks, strategy and retry intervals.
- Pause/activate schedule controls the existing timer. An ongoing update job is not
terminated when paused.
- Under "Schedule & IP Detection", interval, strategy, IPv6 interface
and block duration can be changed. Saving activates the schedule.
- The download contains Python core, shell starter and instructions without credentials.
Configuration occurs in the module; CLI calls: `--status`, `--check`, `--run-update`.

## Improvements over v3.9

Configuration is no longer executed with `source`. HTTPS requests are handled in
the Python process without secrets in process arguments. Status files contain no
URLs, authentication headers or provider raw responses. Credential files and
backups are stored atomically with mode 0600. Browser responses use
`Cache-Control: no-store`; write forms have CSRF and revision protection.

IPv4-only and IPv6-only operate independently of each other. IPv6 ignores private,
link-local, temporary and unusable addresses. Missing optional addresses are not
sent as empty update parameters to avoid unintended deletion or autodetection of the wrong family.

Cache, attempts, success and provider blocks are stored per provider. An error with Provider B does not lose the success of Provider A. Only explicitly confirmed responses count as success. Unknown responses are not classified as OK. HTTP 429, 911 and known rate-limit texts set wait times.

Authoritative DNS answers are determined via SOA/NS and checked against the AA flag;
no comparison only with the Fritzbox cache is performed. After a confirmed update,
a wait time of at least one hour prevents repeated updates due to DNS delays.
Failed attempts use increasing intervals. A cross-process file lock protects configuration changes, validation and updates. During this period DynDNS reports as blocker for Sleep & Wake.

## Limits and Operation

The service requires Python 3, iproute2 and dnsutils; no package installation from
the web form. Standard templates: DDNSS (Key/Password), INWX, dynv6, DuckDNS. Further
v3-GET providers can be taken over with their HTTPS URL. Custom URLs require an exact success response. Cloudflare was in v3 only an incomplete placeholder template and is intentionally not imported as a functional record API.

Direct A/AAAA entries are validated; CNAME chains, provider-specific JSON APIs,
DNSSEC verification and DNS record creation are not offered. Public
DNS propagation is not part of a positive provider response. No
router/firewall changes, no modifications to Apache, Nextcloud or HA VMs.

The new schedule has no OnBootSec and no immediate catch-up: the takeover does not trigger an update. Existing providers remain with the old updater until taken over. The new configuration is located under `/etc/server-manager/dyndns.json`.

## Evidence

Tests in `tests/test_dyndns.py` use temporary configurations and simulated network/systemd calls. Real provider updates are not automatic tests.

Provider documentation:
- https://dyn.ddnss.de/info.php
- https://kb.inwx.com/de-de/8-dyndns/167-einrichtung-synology
- https://dynv6.com/docs/apis
- https://www.duckdns.org/spec.jsp
