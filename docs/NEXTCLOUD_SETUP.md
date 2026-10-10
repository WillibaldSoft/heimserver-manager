# Geführte Nextcloud-Neuinstallation

Apps → Nextcloud → Installer fragt Nativ/Docker, Domain, E-Mail, Adminname/Passwort, Programm- und separaten Datenordner sowie Docker-Port ab. Vorgaben kommen aus Server & Modulpfade. Die aktuelle Bestandsinstallation wird nicht konvertiert. Auf dem bestehenden Server sperren belegte Pfade bzw. erkannte Nextcloud-Container die Neuinstallation.

Der Komplettinstaller ist für Debian 13 ausgelegt. Er ergänzt Apache/Certbot sowie bei nativ PHP, MariaDB, Redis; bei Docker eine fehlende Debian-Docker-Engine samt Compose und erzeugt Nextcloud/MariaDB/Redis-Container. Eine vorhandene fremde Docker-Installation benötigt ein passendes Compose-v2-Plugin. Admin und Datenbank werden eingerichtet, Domain und Proxyvertrauen konfiguriert, ein Fünf-Minuten-Timer und Certbot-Erneuerung aktiviert. Abschließend werden OCC und HTTPS geprüft. Der Datenordner muss neu sein und außerhalb des Programmordners liegen. Bestehende Daten werden nicht überschrieben.

DNS und Routerfreigaben für Ports 80/443 müssen vorab passen. SMTP, externe Speicher, Talk und zusätzliche Apps sind separate Konfigurationen. Nativ verwendet ein per SHA-256 verifiziertes offizielles aktuelles Nextcloud-Archiv; Docker das offizielle stable-apache-Image mit MariaDB 11.4. Keine Neuinstallation wurde auf dem bestehenden Produktivserver ausgeführt. Ein realer vollständiger Neuinstallationslauf auf einem leeren Zielserver steht noch aus.

Die Vorschau zeigt keine Passwörter. Temporäre Angaben liegen im geschützten Server-State, maximal zehn Minuten gültig; alte Vorschauen werden beim nächsten Aufruf bereinigt. Job-Zugangsdaten werden nach dem Installationsversuch entfernt. Docker-Datenbank- und initiale Admin-Secrets bleiben als rootgeschützte Dateien bei der Installation, da die Compose-Konfiguration diese verwendet. Downloadpakete enthalten keine Passwörter; das Passwort wird auf dem Zielserver verdeckt im Terminal abgefragt.

Die Installation verändert nur eigens angelegte App-Pfade und Website-Konfigurationen, installiert jedoch systemweite Abhängigkeiten. Sie ist kein transaktionales Betriebssystem-Deployment. Bei Fehlern bleiben bereits erzeugte Dateien/Pakete zur Diagnose erhalten; bestehende Zielpfade sperren blindes Wiederholen. Ein fehlgeschlagener Zertifikats- oder Abschlusstest wird als Fehler gemeldet.

Offizielle Grundlagen:
- https://docs.nextcloud.com/server/stable/admin_manual/installation/system_requirements.html
- https://docs.nextcloud.com/server/stable/admin_manual/installation/command_line_installation.html
- https://github.com/nextcloud/docker


## Gemeinsame Nextcloud-Karte

Die vorhandene native Installation behält ihre Manager-Klasse, Routen und
Backup-Historie. Die Karte nennt die Installationsart. Eine mit dem Installer
eingerichtete Docker-Installation erhält dieselbe Kartenbezeichnung, aber eine
eigene interne Kennung `nextcloud_docker`, damit Sicherungen und Aktionen niemals
mit der nativen Installation verwechselt werden. Sind beide vorhanden, erscheinen
getrennte Karten „Nextcloud · Nativ“ und „Nextcloud · Docker“.

Der Installer bietet weiterhin Nativ und Docker für eine neue Installation an;
ein bestehender Bestand wird nicht migriert oder überschrieben. Unbekannte
extern installierte Docker-Stacks werden nicht automatisch übernommen.

Docker verwendet OCC für die Betriebsbereitschaft. Native Apache-, Datenbank- und
Updater-Kommandos werden dafür niemals verwendet. Die native Sicherung,
Wiederherstellung und Updatevorbereitung bleiben unverändert.

## Docker-Sicherungen und Updates

Unter Apps verwalten ist „Nextcloud · Docker“ auch als noch nicht installierte
Option vorhanden. Ohne Installation wird keine aktive App-Karte angezeigt und
es laufen keine Docker-Updates oder Sicherungen. Der Installer wählt Docker vor;
eine zusätzliche Instanz benötigt eigene Domain, freie Ports und eigene Ordner.
Neue Docker-Installationen erhalten eigene Apache- und Cron-Dateien. Bestehende
native Profile und Webadressen werden nicht überschrieben.

Unterstützt wird der vom Manager eingerichtete Compose-Stack mit den Diensten
app, db (MariaDB) und redis. Marker, Projektzugehörigkeit, aktive Mounts und
Nextcloud-Datenbankkonfiguration werden vor Änderungen geprüft. Andere Stacks
werden nicht automatisch verändert.

System- und Komplettbackup enthalten einen vollständigen logischen Dump der
Nextcloud-Datenbank einschließlich Routinen, Events und Triggern. Der Dump wird
im Datenbankcontainer mit dem dortigen Secret authentifiziert, komprimiert und
mit SHA-256 versehen. Passwörter gelangen nicht in Hostargumente oder Protokolle.
Komplettbackups enthalten zusätzlich Programm, Konfiguration, Secrets und den
separaten Benutzer-Datenordner; das laufende MariaDB-Datenverzeichnis wird nicht
als Dateikopie gesichert. Das Profil Datenbackup enthält weiterhin nur Dateien.

Für konsistente Datei-/SQL-Sicherungen wird Wartungsmodus eingeschaltet und nur
der Docker-App-Container angehalten. Nach der Sicherung, auch bei einer Ausnahme,
wird er wieder gestartet und Wartungsmodus ausgeschaltet. Währenddessen ist diese
Nextcloud-Instanz nicht erreichbar. Parallele Backup-/Update-Aufträge derselben
Instanz werden gesperrt. Ein Stromausfall/Prozessabbruch kann eine manuelle Prüfung
von Container und Wartungsmodus erfordern.

Update prüfen vergleicht plattformspezifische Image-Digests im offiziellen
Nextcloud-Repository. Unterstützt werden Aktualisierungen innerhalb der aktuellen
Hauptversion, keine automatischen Hauptversionswechsel oder Downgrades. Ein
freigegebener Echtlauf erfordert die gebundene Backup-Vorbereitung und erstellt
unmittelbar vor der Umstellung ein erneutes vollständiges Backup. Das Zielimage
wird per Digest fixiert, dessen tatsächliche Version geprüft und ausschließlich
`app` mit `--no-deps` neu erstellt. MariaDB und Redis werden nicht aktualisiert.
OCC-Version und Erreichbarkeit werden anschließend geprüft. Nach einer möglichen
Datenbankmigration erfolgt kein automatischer Image-Downgrade: Bei Fehlern bleibt
das vollständige Backup für eine bewusste gemeinsame Datei-/SQL-Rücksicherung
vorhanden. Automatischer Docker-SQL-Restore ist nicht Bestandteil dieses Ablaufs.

Grundlagen: https://github.com/nextcloud/docker und
https://docs.nextcloud.com/server/latest/admin_manual/maintenance/backup.html

## Nextcloud Wake

- Nextcloud-Wake: Inaktive Vorbereitung speichern, ohne Dienste, DNS, Router oder Zertifikate zu ändern. Getrennte spätere Gateway-Installation.
- Einstellbarer Statuspfad unterstützt Nextcloud in Unterordnern; DAV-Anfragen und bestehende URLs bleiben unverändert. Blocker-Profil vor Installation erforderlich; WebSockets bleiben ausgeschlossen.

### Diagnose der Aufweck- und Nachlaufgründe
Der Gateway protokolliert Anfragekennungen, pseudonymisierte Quelladressen, grobe Client-/Pfadkategorien sowie Recovery-Aufruf und Ergebnis im systemd-Journal. Keine vollständigen URLs, Header, Tokens oder Cookies. Maximal 120 Ereignisse pro Minute; ausgelassene Ereignisse werden später gezählt. Client-Kategorien beruhen auf unbestätigten User-Agent-Angaben. Schlafprotokolle nennen bei Nachlauf-Rücksetzungen die aktuellen Blocker oder einen Wach-Zeitplan. Zusätzliche Rücksetzungsprotokolle werden sieben Tage aufbewahrt. Gateway-Journalaufbewahrung richtet sich nach der systemweiten journald-Konfiguration. Keine rückwirkende Ermittlung früherer Auslöser.
