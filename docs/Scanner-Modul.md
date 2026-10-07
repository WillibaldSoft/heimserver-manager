# Scanner-Modul

`/scanner` verwaltet die vorhandene Flask-Scanner-API aus `/opt/scanner-api/scan_api.py` und `scanner-api.service`. Grundlage ist das bestehende Skript mit PDF-, Schnell-PDF-, JPG- und TIFF-Scan-Sessions. Die Home-Assistant-Endpunkte `/pdfscan`, `/quickscan`, `/jpgscan`, `/tiffscan`, `/finish`, `/cancel` und `/status` bleiben erhalten. Es wird durch Verwaltungsprüfungen kein Scan ausgelöst.

## Einstellungen

- Feste Scanner-IPv4, Port, eSCL-/WSD-Protokoll und Pfad; alternativ bestehende SANE-Gerätekennung mit automatischer Erkennung.
- API-Bind-Adresse und API-Port (bisher 0.0.0.0:8181).
- Ausgabeordner und bestehender Linux-Dienstbenutzer. Der Sitzungsordner bleibt `/var/lib/scansession`.
- Für die feste Scanner-IP wird ausschließlich ein eigenes SANE-Profil unter `/etc/scanner-api/sane` verwendet. Die systemweite SANE-Konfiguration wird nicht ersetzt.
- Der Dienst erhält seine Einstellungen über eine eigene systemd-Ergänzung und `/etc/scanner-api/server-manager.env`.

Auf neuen Servern Scanneradresse, Gerätekennung, Dienstbenutzer und Ausgabeordner vor der Installation konfigurieren.

## Installation und Änderungen

Die Installation läuft in einer separaten systemd-Unit mit maximal 30 Minuten Laufzeit. Nur fehlende Pakete werden installiert: python3, python3-flask, sane-utils, sane-airscan, img2pdf. Vorhandene Scans werden nicht gelöscht. OCR ist nicht implementiert.

Eine aktive Session oder ein belegter Scan-Lock verhindert die Übernahme. Verwaltete Dateien werden im jeweiligen Auftrag unter `/var/lib/server-manager/scanner/jobs/<ID>/backup` gesichert; `backup-files.json` ordnet die Sicherungen ihren Zielpfaden zu. Bei einer fehlgeschlagenen API-Neustartprüfung werden Dateien und vorheriger Betriebszustand wiederhergestellt. Ein harter Prozess-/Hostabbruch kann eine manuelle Wiederherstellung aus dieser Sicherung erfordern; unterbrochene Aufträge werden sichtbar markiert. Paketinstallationen werden nicht automatisch zurückgerollt.

Abweichende, außerhalb des Moduls geänderte API-Skripte werden nicht überschrieben. Konfigurationsänderungen und Installer sind CSRF-geschützt und prüfen die Konfigurationsrevision. Laufende Installationen und offene Scan-Sessions melden einen Schlafblocker.

## Prüfungen und Home Assistant

API-Status, API-Konfiguration, TCP-Erreichbarkeit des Scanners und SANE-Erkennung sind getrennte Ergebnisse. Dies ist kein physischer Scan-Test. Änderungen des Dienstbenutzers prüfen dessen Schreibrecht auf den Ausgabeordner. Home-Assistant-YAML kann angezeigt und heruntergeladen werden; bestehende rest/rest_command-Abschnitte müssen zusammengeführt werden. Bei Änderung des API-Ports oder der Bind-Adresse die Clients entsprechend anpassen.

Referenz: https://github.com/alexpevzner/sane-airscan/blob/master/airscan.conf
