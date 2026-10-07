# Code- und Auslieferungsprüfung

Prüfstand: 2026-09-25, Heimserver Manager V0.12.

## Bereinigungen und Fehlerkorrekturen

- Neutrale Vorgaben für Benutzer, LAN, SSH, Scanner, App- und Sicherungspfade. Hostwerte gehören ausschließlich in die lokale Konfiguration. Keine persönlichen Benutzer oder gerätespezifischen Scannerkennungen als Auslieferungsstandard.
- Öffentliche Anbieter-URLs und neutrale Dokumentationsbeispiele bleiben enthalten. Historische Mountnamen in der Backup-Kompatibilitätslogik bezeichnen unterstützte Verzeichnisstrukturen, keine Zugangsdaten.
- Explizite Release-Dateiliste in `packaging/source-manifest.json`. Nicht gelistete Dateien werden weder ins Debian-Paket noch in das Server-Installerarchiv aufgenommen. Neue Quelldateien müssen bewusst in die Liste aufgenommen werden.
- Veraltete, versionierte `.bak`-Quellkopien entfernt. Laufzeitdaten, Git-Historie, lokale Konfiguration, Logs, Datenbanken und Snapshotordner gehören nicht in Releases.
- Quellarchive mit neutralem Eigentümer und Zeitstempel. Standard-App-Installerdownloads nutzen portable Profilpfade statt lokaler Hostpfade.
- Tvheadend-Erstkonfiguration mit echten Zeilenumbrüchen und konfigurierbarem Konfigurationsverzeichnis.
- Speichern des TV-Aufwachvorlaufs nur per POST und CSRF-Prüfung; ungültige Minutenwerte liefern eine verständliche 400-Antwort statt eines Serverfehlers.
- Aufnahmelisten werden vollständig seitenweise geladen; eine unvollständige Liste gibt keine Löschung frei.
- SSH-Anwesenheitsprüfung verwendet lokale SSH-Verbindungen statt einer festen Hostadresse.
- Veraltete Tests an Anmeldung und portable Installationspfade angepasst; Fotolabor-Testzustände voneinander isoliert.

## Prüfung

- Gesamte vorhandene Suite einschließlich neuer Regressionen: 508 Tests erfolgreich.
- Python-Syntaxprüfung und Syntaxprüfung der sechs Shellskripte.
- Debian-Testpaket gebaut und entpackt, nicht installiert.
- Release-Dateien auf private Schlüssel, bekannte Tokenformate und Zugangsdaten in URLs geprüft; keine Treffer.
- Standard-App-Installationsarchive auf Pfade und neutrale Eigentümerdaten geprüft.
- Bestehende lokale Pfade vor Umstellung explizit gesichert; beim Rollout Vergleich mit unverändertem Konfigurationsstand.

`python3 tools/privacy_check.py` ist eine heuristische zusätzliche Kontrolle, keine Garantie. Mit `--forbidden-file /geschuetzter/pfad` kann eine **nicht versionierte** Liste eigener Hostnamen, Benutzer oder Adressen geprüft werden. Treffer geben nur Dateinamen und Regelarten aus.

## Grenzen und Veröffentlichung

Kein vollständiger Penetrationstest und keine Garantie, dass jede Hardwarekombination funktioniert. Echte Neuinstallationen, Restore auf leere Datenträger, Ausschalten/Aufwecken, Zertifikatsausstellung, Paketupgrades und Aufnahme-Löschungen wurden nicht auf dem Produktivserver zum Test ausgelöst. Solche Abläufe benötigen zusätzliche Tests auf einem entbehrlichen System.

Die alte Git-Historie und bereits früher erzeugte Pakete werden durch diese Bereinigung nicht rückwirkend anonymisiert. Für Weitergabe ausschließlich neu gebaute, geprüfte Release-Artefakte oder einen bereinigten Quellstand verwenden. Git-Historie vor öffentlicher Freigabe separat prüfen; sie wird nicht automatisch umgeschrieben.

Absichtlich personenbezogene Betriebsexporte (z. B. Client-Backuppakete mit Identitätszuordnung oder eigene Nextcloud-Domainkonfigurationen) sind keine öffentlichen Installationspakete und müssen privat bleiben. Die vom Administrator gewählte Erstanmeldung bleibt erhalten; vor externer Erreichbarkeit ein eigenes Passwort setzen.
