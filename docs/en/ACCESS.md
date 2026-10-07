# Logging into the Home Server Manager

New installations and the first activation of logging in receive exactly once the user `ADMIN` with password `ADMIN` (pay attention to capitalization). An existing access is not overwritten on restarts and updates. Under Settings → Access, username and password can be changed; for this purpose, the current password is required. Custom passwords have 8–256 characters.

Session duration is adjustable under Settings → Access from 1 to 1440 minutes; the default is eight hours. It runs from login regardless of activity. Sign in again with the same password after expiry. Logout uses protected POST; changing the password invalidates other sessions. The service stores a scrypt password hash, a random session key and a separate automation token in `authentication.json` in the configuration directory with permissions 0600. Do not include this file in repositories or installer archives.

The installation password is marked as still active after login. The package installer sets up HTTPS; the HTTP backend is accessible only locally on 127.0.0.1. HTTPS session cookies are protected. Check existing manual installations and their proxy configurations separately.

## Agents and Schedules

Client-agent endpoints use their own active agent tokens and, where applicable, user-device binding. They do not bypass access control on administration pages. `/api/health` publicly returns reachability status, time and the running program version so updates can verify success. Server backups remain restricted to administrators.

Local backup and update validation timers use `tools/authenticated_request.py`. The helper reads the automation token from the protected file, does not expose it in command lines, and accepts no external target address. On the server side, this token is valid only for local POST calls to the backup and update validation endpoints. It allows no general API access. A user password change does not interrupt these timers.

On the first Core start, known local curl calls are migrated to App-Backup and Update-check services. Originals remain protected in the subfolder `auth-unit-backups`. New backup schedules already use the helper. The migration does not trigger a backup itself.

Other integrations must log in and use the session cookie. POST requests require an appropriate Origin header or the session CSRF value in field `auth_csrf` respectively header `X-Server-Manager-CSRF`. Additional protection checks of respective modules remain in place.
