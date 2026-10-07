# Anmeldung am Server Manager

Neue Installationen und die erste Aktivierung der Anmeldung erhalten genau einmal den Benutzer `ADMIN` mit Passwort `ADMIN` (Großschreibung beachten). Ein vorhandener Zugang wird bei Neustarts und Updates nicht überschrieben. Unter Einstellungen → Zugang können Benutzername und Passwort geändert werden; hierfür ist das aktuelle Passwort erforderlich. Eigene Passwörter haben 8–256 Zeichen.

Die Anmeldedauer ist unter Einstellungen → Zugang zwischen 1 und 1440 Minuten einstellbar; Vorgabe sind acht Stunden. Sie läuft ab Anmeldung unabhängig von Aktivität. Danach erneut mit demselben Passwort anmelden. Abmelden erfolgt per geschütztem POST; eine Passwortänderung macht andere Sitzungen ungültig. Der Dienst speichert einen scrypt-Passworthash, einen zufälligen Sitzungsschlüssel und ein unabhängiges Automationstoken in `authentication.json` im Konfigurationsordner mit Dateirechten 0600. Diese Datei gehört nicht in Repositorys oder Installerarchive.

Das Installationspasswort wird nach der Anmeldung als noch aktiv gekennzeichnet. Der Paketinstaller richtet HTTPS ein; der HTTP-Backend-Port ist nur lokal auf 127.0.0.1 erreichbar. HTTPS-Sitzungscookies sind geschützt. Bestehende manuelle Installationen und deren Proxykonfiguration gesondert prüfen.

## Agenten und Zeitpläne

Client-Agenten-Endpunkte verwenden aktivierte, eigene Agenten-Tokens und gegebenenfalls die Benutzer-Geräte-Kopplung. Sie umgehen nicht die Zugangskontrolle zu Verwaltungsseiten. `/api/health` liefert öffentlich Erreichbarkeitsstatus, Zeit und die laufende Programmversion, damit Updates ihren Erfolg prüfen können. Server-Sicherungen bleiben Administratoren vorbehalten.

Lokale Backup- und Update-Prüf-Timer verwenden `tools/authenticated_request.py`. Der Helfer liest das Automationstoken aus der geschützten Datei, legt es nicht in Befehlszeilen offen und akzeptiert keine externe Zieladresse. Serverseitig gilt dieses Token nur für lokale POST-Aufrufe der Backup- und Update-Prüf-Endpunkte. Es erlaubt keinen allgemeinen API-Zugang. Ein Benutzerpasswortwechsel unterbricht diese Timer nicht.

Beim ersten Core-Start werden die bekannten lokalen curl-Aufrufe in App-Backup- und Update-Prüf-Diensten umgestellt. Originale liegen geschützt im Unterordner `auth-unit-backups`. Neue Backup-Zeitpläne verwenden bereits den Helfer. Die Umstellung startet selbst kein Backup.

Andere Integrationen müssen sich anmelden und das Sitzungscookie verwenden. POST-Aufrufe benötigen einen passenden Origin-Header oder den Sitzungs-CSRF-Wert im Feld `auth_csrf` beziehungsweise Header `X-Server-Manager-CSRF`. Zusätzliche Schutzprüfungen der jeweiligen Module bleiben bestehen.
