# Open WebUI und App-Installer

Open WebUI (Ollama-Oberfläche) ist als App `open_webui` eingebunden. Der Manager
liest den existierenden Container `open-webui`, erkennt dessen Zustand und Image,
prüft die WebUI auf Port 3000 und zeigt unter Health den lokalen Ollama-Dienst.
Die vorhandene Einzelcontainerinstallation und ihr Volume bleiben unverändert.

## Oberfläche

- `/apps`: Open WebUI in den vorhandenen App-Karten; „WebUI öffnen“ und
  „Installer“ pro App.
- `/apps/open_webui`: reguläre App-Detailansicht mit Status und Health.
- `/apps/installers`: alle zehn App-Profile einschließlich derzeit nicht installierter
  Apps. Nicht installierte Apps bleiben ansonsten gemäß bestehender Sichtbarkeit
  aus der Hauptübersicht ausgeblendet.
- `/apps/<id>/installer`: Installationsart, Ziel, Bestands-/Portprüfung, WebUI-Adresse
  und ZIP-Download. Loopback-Links werden auf den Servernamen im aktuellen Browser
  umgeschrieben. Nextcloud öffnet `/nextcloud/` anstelle von `status.php`.
- `/apps/installers/new`: neue Einzelcontainer-App mit Image, Ports und persistentem
  Datenpfad registrieren. App-Manager und Installer sind sofort ohne Neustart verfügbar.

Die vorhandenen WebUI-Adressen werden aus den App-Profilen übernommen. Nur HTTP(S) ohne eingebaute
Zugangsdaten sowie lokale Modulpfade sind erlaubt; Links öffnen mit `noopener`.
Profiländerungen und Installationsstarts sind POST-Aktionen mit CSRF-Schutz. Eigene Profile und WebUI-URLs
liegen atomar gespeichert in `/var/lib/server-manager/app-installers/profiles.json`.
Die Auswahl eines Images ist eine Vertrauensentscheidung des Administrators.

## Ausführbare Installerpakete

ZIP enthält `installer.py`, `profile.json`, `README.txt`, `SHA256SUMS` und bei Bedarf
lokale Programmdateien. Entpacken und zunächst `python3 installer.py --check` ausführen.
Erst `sudo python3 installer.py --install --bind <Server-IPv4>` installiert. Ohne
Bind-Adresse verwenden Container und ComfyUI Loopback. Pakete werden nicht durch
Aufrufen einer Webseite, Vorschau oder Download ausgeführt. Die explizite Installation über den Knopf läuft als sichtbarer Hintergrundauftrag.

Das Ziel darf noch nicht existieren. Vorhandene Dienste, Container, App-Pfade,
Portbelegung und Symlinks im Zielpfad verhindern eine Neuinstallation. Installationen
ersetzen keine vorhandenen Daten. Wiederherstellung erfolgt über die bestehenden
Backup-/Restore-Funktionen. Nach Fehlern bleiben neue Dateien zur Diagnose erhalten;
es wird nichts automatisch gelöscht. Ein Abschlussmarker wird erst nach erfolgreicher
Ausführung geschrieben.

### Profile

- Open WebUI: offizielles Image, persistente Daten, aktivierte Anmeldung, neu erzeugter
  WebUI-Schlüssel und Ollama-Verbindung über `host.docker.internal`. Ollama muss dort
  erreichbar sein; dessen Bind-Adresse und Firewall werden nicht geändert.
- Immich: zusammengehörige Compose-/ENV-Dateien desselben offiziellen Releases;
  eigene Bibliothek/Datenbank und zufälliges Datenbankpasswort.
- Paperless-ngx: App, PostgreSQL und Redis; persistente Daten und zufällige Schlüssel.
  Admin nach Installation interaktiv mit `createsuperuser` anlegen.
- Stirling PDF: offizielles Image mit persistenten Konfigurations- und Arbeitsordnern.
- Nextcloud: neue Docker-Installation mit MariaDB. Kein Umbau der bestehenden nativen
  Apache-Installation. Ersteinrichtung danach in der WebUI.
- ComfyUI: offizielles Git-Repository, venv, CPU-PyTorch und Dienst als Benutzer
  `comfyui`. GPU-Treiber, CUDA/ROCm und Modelle separat einrichten.
- Tvheadend: Installation aus den bereits konfigurierten APT-Quellen. Ein Paketkandidat
  muss vorhanden sein; es werden keine fremden Paketquellen ungefragt eingetragen.
- Mounts/Freigaben: `cifs-utils` und `nfs-common`; keine Änderung von `/etc/fstab`.
- OSCam: lokale Binary für dieselbe Architektur, neue minimale WebIF-Konfiguration
  mit zufälligem Passwort und zunächst nur lokalem Zugriff. Keine Reader-/Nutzerdaten.
- Server Manager: Code-Bootstrap aus versionierten Repositorydateien plus den aktuellen
  Installer-Modulen, venv und systemd-Dienst mit neuem Session-Schlüssel. Hostdienste,
  Moduleinrichtung und Daten benötigen eigene Einrichtung bzw. Backups. Kein Klonen
  des kompletten produktiven Servers.

Zielplattform der Pakete ist Debian 13 / Python 3.13. Docker-Profile benötigen Docker
Engine mit Compose; diese Grundlage wird nicht automatisch über ein fremdes Shell-
Skript installiert. Tags/Upstream-Releases werden zum Installationszeitpunkt geladen.
OSCam-Bundles sind zusätzlich architektur- und laufzeitabhängig. Bei Server Manager
und OSCam gelten deren bestehenden Dienstbindungen; `--bind` verändert diese nicht.

## Prüfungen

`tests/test_app_installers.py`: Host-/IPv6-Linkbildung, URL-/Profilvalidierung, CSRF,
Bestandsschutz, Port-/Symlinkprüfung, Paketinhalt, dynamische Registrierung, Docker-
Status, persistente Compose-Daten, Schlüsselgenerierung und simulierte Ausführung.
Keine Testinstallation ersetzt eine laufende App. Eine frische Komplettinstallation
auf einem separaten Debian-System ist damit nicht als getestet behauptet.

Quellen für die Vorlagen:
- https://docs.openwebui.com/getting-started/quick-start/
- https://docs.immich.app/install/docker-compose/
- https://docs.paperless-ngx.com/setup/
- https://docs.stirlingpdf.com/Installation/Docker%20Install/
- https://hub.docker.com/_/nextcloud
- https://docs.comfy.org/installation/manual_install


## Direkte Installation im Apps-Modul

Der Installer startet fehlende Apps jetzt über „Jetzt auf diesem Server installieren“.
Bereits vorhandene Apps erhalten keinen Installationsknopf. Die serverseitige
Bestandsprüfung erfolgt erneut beim POST und unmittelbar vor Ausführung.
Ein separater systemd-Auftrag führt den Installer aus und überlebt einen Neustart
des Server-Managers. Status und Protokoll erscheinen auf der Auftragsseite.
Es läuft höchstens eine Installation gleichzeitig; währenddessen besteht ein
Schlaf-Blocker. Fehlgeschlagene bzw. unterbrochene Aufträge werden ausdrücklich
angezeigt, vorhandene Daten bleiben erhalten. Downloads bleiben als Zusatzoption.
Die zusätzliche WebUI-Konfiguration im Installer entfällt; JSON-Links wurden aus
App-Karten und Kopfaktionen entfernt, die Diagnose-API bleibt verfügbar.

## Open-WebUI-Updates

Die Versionsprüfung liest `/api/version` der laufenden App und vergleicht mit dem
neuesten offiziellen Stable-Release. Ein Docker-Tag wie `main` ist keine Versionsnummer.
Netzwerkfehler werden als „Nicht prüfbar“ mit Ursache angezeigt.

Der bestätigte Echtlauf verwendet den bestehenden Prepare-/Backup-Mechanismus.
Für den erkannten Einzelcontainer mit genau einem lokalen benannten Datenvolume
und Bridge-Netzwerk ist ein eigener Updatepfad implementiert:

1. Container, freie Kapazität und exklusive Nutzung des Volumes prüfen.
2. Das konkrete Stable-Image vollständig herunterladen; noch keine Unterbrechung.
3. Alten Container anhalten und das Datenvolume vollständig per rsync kopieren.
4. Alten Container mit deaktiviertem Autostart als Rückfallstand behalten.
5. Neuen Container mit bisherigen Benutzer-Einstellungen und der Datenkopie starten.
   Alte Image-Standardwerte werden nicht über neue Image-Standardwerte kopiert.
6. Erwartete App-Version und Docker-Gesundheitszustand prüfen.
7. Bei einem Fehler den neuen Container entfernen und den ursprünglichen Container
   mit unverändertem Originalvolume und ursprünglicher Restart-Policy starten.

Andere Mount-/Netzwerkvarianten werden vor einer Änderung ausdrücklich blockiert.
Geschützte Transaktionsdaten liegen unter
`/var/lib/server-manager/open-webui-updates/<id>/` (inklusive Originalkonfiguration,
nur root-lesbar). Sie werden nicht in öffentlichen Update-Protokollen angezeigt.
Nach Erfolg bleiben alter Container und altes Datenvolume als Rückfallstand erhalten.
Die regulären App-Backups folgen anschließend dem Volume des aktuellen Containers.
Während des gesamten Updates ist ein Schlaf-Blocker aktiv.

Die vorhandene App-Update-Engine führt den Ablauf aus; ein Prozess-/Hostabbruch
während des Wechsels erfordert Prüfung der Transaktionsdatei und ggf. manuelles
Starten des erhaltenen Originalcontainers. Es gibt keine automatische Bereinigung
von Rückfallständen oder Datenvolumes.
