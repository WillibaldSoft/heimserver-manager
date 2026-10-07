# Server Manager als Debian-Paket

## Installation auf einem neuen Server

Debian 13 mit systemd, Netzwerkzugang zu den Debian-Paketquellen und administrativen Rechten:

    sudo apt install ./Server_Manager.deb

APT installiert die erforderlichen System- und Python-Pakete einschließlich Apache und HTTPS-Werkzeugen. Das Paket startet einen einzelnen Waitress-Prozess mit acht Threads als `server-manager.service` auf dem internen Port 9877, ausschließlich an 127.0.0.1. Der Dienst läuft als root, weil die Verwaltungsfunktionen Systemdienste, Datenträger und Benutzer bearbeiten. Zusätzliche Anwendungen wie Nextcloud, MariaDB, Samba oder Docker werden nicht automatisch installiert.

Die HTTPS-Adressen über Rechnername und Server-IP zeigt der Installer an. Öffentliches Stammzertifikat auf Clients nach Fingerabdruckprüfung importieren. Erstanmeldung: Benutzer ADMIN, Passwort ADMIN. Danach eigenes Passwort unter Einstellungen → Zugang setzen und Server & Modulpfade prüfen. Automatische Schlafaktionen sind im neuen Datenbestand nicht aktiv. Einzelheiten und Fehlerbehebung: RELEASE_INSTALLATION.txt.

Programm: `/opt/server-manager`, Einstellungen: `/etc/server-manager`, Datenbank/Status: `/var/lib/server-manager`, Python-Cache: `/var/cache/server-manager`. Der Dienst-Port kann in `/etc/server-manager/server-manager.env` angepasst werden. Danach `sudo systemctl restart server-manager`.

## Updates und Entfernen

    sudo apt install ./Server_Manager.deb
    sudo apt remove server-manager

Das Paket enthält weder bestehende Zugangsdaten noch Datenbanken, Zertifikate, DynDNS-Profile, App-Konfigurationen oder Sicherungen. Das Admin-Konto und die Konfiguration werden nur bei fehlenden Dateien initialisiert. Updates sowie remove/purge erhalten die erzeugten Einstellungen und Statusdaten. Vor einem Update eine Sicherung dieser Daten anlegen.

Eine vorhandene manuelle Installation unter `/opt/server-manager` wird beim ersten Paketinstallationsversuch erkannt und nicht überschrieben. Ihre Umstellung benötigt eine gesonderte Migration. Das Paket wurde nicht auf dem laufenden Produktivserver installiert.

## Paket selbst bauen

    python3 tools/build_deb.py --output dist/Server_Manager.deb

Für den Bau genügen Python 3 und `dpkg-deb`; weder root noch Netzwerkzugriff sind erforderlich. Vor dem Bau die vollständige Paketversion einschließlich Debian-Revision in `version.py` sowie die deutschen und englischen Dokumentationen setzen. Ein abweichender `--revision`-Wert wird abgewiesen. Neue veröffentlichte Quelländerungen benötigen eine höhere Revision. `SOURCE_DATE_EPOCH` legt den reproduzierbaren Zeitstempel fest (Standard 0).

Der Builder erstellt eine SHA-256-Prüfsummendatei. Eine Positivliste beschränkt den Paketinhalt auf Quellcode, Webressourcen, Hilfsskripte und Dokumentation. Laufzeitdaten, Backups, versteckte Verzeichnisse, Symlinks und Geheimnisdateien werden ausgeschlossen. Das Paket enthält eine `package-manifest.json` mit den Quellcode-Prüfsummen.

Modulspezifische externe Werkzeuge und bereits bestehende externe Hilfsskripte werden nicht vom laufenden Server kopiert. Zusätzliche Dienste über die jeweiligen Modul-Installer einrichten. Bestehende Git-Updatefunktionen ersetzen keine Debian-Paketupdates.

## Portauswahl ab Paketrevision 0.12-2

Bei `sudo apt install ./Server_Manager.deb` fragt debconf nach dem gewünschten TCP-Port (1–65535, Vorgabe 9877). Bereits belegte Ports werden abgewiesen; der eigene laufende Server-Manager-Port ist bei einem Update zulässig. Der gewählte Port wird dauerhaft in `/etc/server-manager/server-manager.env` gespeichert. Updates übernehmen den vorhandenen Port als Vorgabe.

Für eine unbeaufsichtigte Erstinstallation auf einem neuen Server vorher vorbelegen:

    printf 'server-manager server-manager/port string 9988\n' | sudo debconf-set-selections
    sudo DEBIAN_FRONTEND=noninteractive apt install ./Server_Manager.deb

Ohne freie Portvorgabe meldet die Paketkonfiguration einen Fehler, statt einen fremden Dienst zu verdrängen. Bei grafischen Installationsprogrammen ohne Eingabedialog denselben Weg verwenden. Nachträglich: `sudo dpkg-reconfigure server-manager` oder Einstellungen → Server & Modulpfade → Webport ändern. Die Oberfläche prüft den Port, speichert ihn und startet nur den Server Manager neu; sie zeigt anschließend den Link zur neuen Adresse.

Interne Backup-/Update-Timer lesen die zentrale Portdatei auch dann, wenn ältere Units noch `--port 9877` enthalten. Eine vom Web-&-Sicherheit-Modul angelegte Login-Fail2ban-Regel wird angepasst und geprüft. Fremde Login-Regeln müssen vor einer Portänderung manuell geprüft werden. Eigene Router-, Firewall- und Reverseproxy-Regeln sind separat anzupassen.
