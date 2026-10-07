# Server & Modulpfade

Unter Einstellungen → Server & Modulpfade werden Datenbereiche, App-Installationsorte, Sicherungen, Netzwerk und Speicherbezeichnungen gepflegt. Der Scanner behält seine eigene Konfiguration; App-Webadressen werden weiter unter Apps verwalten gepflegt.

## Aktivierung

Die Seite schreibt eine geprüfte Vormerkung nach `server.pending.json` im Konfigurationsordner. Laufender Webprozess und neu gestartete Worker verwenden weiterhin den aktiven Stand. Erst der Core-Start aktiviert die Vormerkung atomar nach `server.json`; `server.previous.json` enthält den vorherigen Stand. Der Neustartknopf prüft laufende Modulaufträge. Bei extern gestarteten Arbeiten das Wartungsfenster selbst abstimmen. Keine Pfadänderung verschiebt Nutzdaten.

Backup-, Restore- und Update-Pfade stammen einheitlich aus dieser Konfiguration. Vorhandene Einstellungen aus `app_manager.json` werden als Ausgangswerte übernommen. Die alte allgemeine Einstellungsseite verlinkt auf die zentrale Pflege.

## Datenumzug

Die separate Umzugshilfe prüft Quell- und Zielordner und erstellt rsync-Vorschau-, Kopier- und Vergleichsbefehle. Alle schreibenden Apps stoppen, Datenträger und freien Platz prüfen, Daten inklusive Eigentümer/ACLs kopieren und vergleichen. Danach App-Dienste, Docker-Mounts, VM-Definitionen und Pfade anpassen. Die Quelle bleibt erhalten und wird nicht automatisch gelöscht. Eine Anpassung von App-Pfaden im Manager richtet bestehende Anwendungen nicht neu ein.

Fotolabor-Verlauf, Prüffreigaben, Reparaturen und Zeitpläne sind an den Bildbestand gebunden. Der erste Bestand verwendet unverändert die vorhandene Datenbank. Andere Hauptordner erhalten eine getrennte Datenbank und eigene Statusordner. Rückwechsel stellt den vorherigen Verlauf wieder zur Verfügung. Auch nach einer Kopie des Bildbestands muss am neuen Ort neu geprüft werden.

## Installation auf anderen Servern

- Programmstandort wird aus dem Quellcodepfad ermittelt.
- `SERVER_MANAGER_CONFIG`: Konfigurationsverzeichnis, Standard `/etc/server-manager`.
- `SERVER_MANAGER_STATE`: interner Statusordner, Standard `/var/lib/server-manager`.
- `SERVER_MANAGER_DB`: optionale Core-Datenbank, sonst im Statusordner.
- `SERVER_MANAGER_PORT`: HTTP-Port, Standard 9877.

Diese Variablen gehören in die systemd-Umgebung des Server Managers. App-Installer-, Scanner- und Modell-Worker übernehmen sie. Externe Dienste wie der eigenständige DynDNS-Timer benötigen dieselben Verzeichnisvariablen in ihrer eigenen Umgebung. sudoers-Regeln für privilegierte Helfer müssen auf den tatsächlichen Programmstandort zeigen; sie werden durch eine Pfadeinstellung nicht geändert.

Standardwerte bewahren den bisherigen Server. Auf einem neuen Host müssen Netzwerk, lokale Benutzer und Datenverzeichnisse vor produktiven Aktionen angepasst werden. Bestehende native App-Updatebefehle setzen weiterhin Pfade ohne Leerzeichen voraus; die zentrale Validierung erzwingt dies. Dateibrowser und allgemeine Datenpfade unterstützen Leerzeichen. Rechteprüfung in der Oberfläche erfolgt als Server Manager, nicht als jeweiliger App-Dienstbenutzer.
