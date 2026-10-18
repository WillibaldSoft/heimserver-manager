# CHANGELOG

Aktuelle Version: **0.13-8** (Beta). Die vollständigen Änderungen stehen in der
[Versionshistorie](docs/Heimserver_Manager_Versionsaenderungen.txt) und in der
[englischen Versionshistorie](docs/en/Home_Server_Manager_Version_History.txt).

## Historischer Grundstand

### Core
- Plugin-Loader
- Modulübersicht
- Projektstatus-Werkzeuge
- Migrationstabelle

### Heimnetz
- IPv4/IPv6-Anzeige
- Gerätebenennung
- Gerätetypen
- Offline-Erkennung beim Scan
- Soft-Delete
- Übernahme als Client-Agent

### Client-Agent
- Token-basierter Agent
- Installer-Download
- Bedarf setzen/löschen
- Server-Control-Blocker

### Server-Control
- Blocker-API
- Tvheadend-Blocker
- Client-Agent-Blocker
- RTC-Anzeige

### TV / Tvheadend
- API-Anbindung
- Streams
- Aufnahmen
- Status-Provider
- Blocker-Provider
- RTC-Aufnahmen

### Sleep
- Sleep-Engine
- Runtime
- Zeitpläne
- Automatik-Schalter
- Dry-Run / echte Ausführung

## 0.13-3 – 11. Oktober 2026 – Beta
- Linux-Client 0.4.36: Vorprüfung der Lesbarkeit für HTTPS-System- und persönliche Sicherungen. Gesperrte Pfade auflisten, nur nach ausdrücklicher Bestätigung für diesen Lauf auslassen und im Inventar dokumentieren. Zusätzliche Lesefehler während der Übertragung bleiben Fehler. Lokale benutzerspezifische Ausnahmen bleiben möglich; keine privaten Ausnahmen im Paket.
- Unvollständige inkrementelle Aufträge im Ablauf anzeigen und nach Bestätigung zurücklegen; vorhandene Blöcke und fertige Stände bleiben erhalten. Neu einlesen und identische Blöcke wiederverwenden. Fremde Geräte, laufende Prüfungen, geänderte Aufträge und Aktivität in den letzten zehn Minuten verhindern die Freigabe. Pausierte Aufträge nicht ersetzen.
- Prüfsummenabschluss im Hintergrund mit Statusabfragen und Prüffortschritt statt langer einzelner HTTP-Anfrage. Erst nach erfolgreicher Prüfung als abgeschlossen markieren. Bei Verbindungsabbruch oder Dienstneustart bleibt der Abschluss unbestätigt; Daten nicht vorschnell verwerfen.
- Persönliches Inventar zeigt den Home-Datenträger und ausgeschlossene Unter-Mounts. Verständliche Lesefehler ohne zusätzlichen Desktop-Absturzbericht.
- Manager und Client gemeinsam aktualisieren; der Manager lädt Änderungen erst nach geprüftem Neustart. Die auftragsgebundene Anmeldung benötigt den neuen laufenden Manager. Bestehende Dienste und Sicherungen werden beim Paketbau nicht verändert. Windows und einfacher Ordner-/USB-Sicherungsmodus erhalten diese Linux-HTTPS-Erweiterungen nicht.

## 0.13-4 – 11. Oktober 2026 – Beta
- Linux-Client 0.4.37: inhaltsabhängige Blockgrenzen für inkrementelle HTTPS-System- und persönliche Sicherungen. Einfügungen und Löschungen verschieben nicht dauerhaft alle folgenden Grenzen. SHA-256-Prüfung und bytegenaue Wiederherstellung bleiben erhalten; kein lokales Zwischenarchiv.
- Beim ersten Lauf nach Umstellung können viele neue Blöcke entstehen; ältere Sicherungen bleiben lesbar und unverändert. Dateien werden weiterhin vollständig eingelesen. Keine Fortsetzung an der früheren Leseposition. Blöcke zwischen 1 und 4 MiB, letzter Block kleiner; maximal 262144 Blöcke pro Stand, daher größenabhängige Kapazitätsgrenze.
- Konfigurierte lokale Offline-Kopien aller normalen Benutzer werden standardmäßig aus neuen gemeinsamen Systemständen ausgeschlossen, auch bei der Größenschätzung. Sichtbare Option zum Mitsichern; erfordert einen neuen Systemstand. Zusätzliche Datenträger weiterhin nur nach eigener Auswahl. Benutzer-Homes bleiben getrennt; vorhandene Systemstände werden nicht verändert.
- Tests für Einfügen, Entfernen, unterschiedliche Leseabschnitte, fehlende Inhaltsmarken, serverseitige Prüfung und Wiederherstellung. Windows, einfacher Ordner-Backupmodus und USB-Assistent unverändert.

## 0.13-5 – 11. Oktober 2026 – Beta
- Linux-Client 0.4.38: Sicherungsdialog nach Konto, Umfang, Aktionen und Fortschritt geordnet. Erweiterte Optionen einklappbar; doppelte Dialogöffnung nach Anmeldung behoben. Lange Statusmeldungen separat scrollbar, damit Schaltflächen erreichbar bleiben.
- Breite Scrollleisten erscheinen bei Bedarf und bleiben dann sichtbar. Größere Startfenster für Einstellungen, Offline-Dateien, Sicherung und Wiederherstellung, begrenzt auf die Monitor-Arbeitsfläche.
- Abbruch einer blockbasierten Sicherung erhält übertragene Blöcke für den nächsten inkrementellen Lauf. Alle Quelldateien werden weiterhin gelesen; nur unbekannte Blöcke übertragen. Einfacher Ordner-/ZIP-Modus und USB-Assistent bleiben unverändert.
- Fertige Server-Sicherungen nach Kontoanmeldung gezielt mit Bestätigung löschen. Schutz gemeinsam genutzter Blöcke und von Systemständen, auf die persönliche Sicherungen verweisen. Laufende Downloads sperren den Speicher gegen gleichzeitige Löschung.
- Administratives Werkzeug zur verlustfreien Neuaufteilung vorhandener Blockarchive: Archivgröße, SHA-256 und ID bleiben erhalten. Wartungspause und vorübergehend zusätzlicher Speicher erforderlich. Keine automatische Umstellung oder Löschung bestehender Sicherungen bei Paketinstallation.
- Abgestimmte Sicherungsoberfläche und Sicherungsfunktionen gemeinsam ausgeliefert; Rückfrage zu unvollständigen Übertragungen, Offline-Ausschluss und inhaltsabhängige Blockbildung enthalten.

0.13-6 – 18. Oktober 2026 – Beta
- Linux-Client 0.4.39: verständliche Meldung bei laufender Synchronisation; gemeinsamer Live-Fortschritt automatischer und manueller Abgleiche. Anmeldung & Einrichtung unten, eingeklappt ohne reservierte Leerfläche; kompaktes Hauptfenster.
- SMB-Löschungen behalten die Originaldatei durch Umbenennen innerhalb der Freigabe als Rückholkopie. Eigentümer und Rechte bleiben erhalten; keine Umgehung der Samba-Rechte. Änderungen bestehender Dateien verwenden weiterhin die bisherige ACL-geprüfte Rückholkopie und können bei fehlenden Rechten scheitern.
- Update-Läufe aktualisieren Status und Ergebnis automatisch; Abschlussprüfungen aktualisieren den App-Kartenstatus. Sicherungsvorbereitung fragt nach einem Verbindungsabbruch weiter nach dem Ergebnis, ohne erneut zu starten.
- Laufende App-Updateprüfungen blockieren automatisches Ausschalten; verwaiste Prüfungen nach Manager-Neustart werden erkannt. Open-WebUI-Blocker prüfen Sperren ohne konkurrierende Sperranforderung.
- Direkter Manager-Neustart unter Einstellungen mit bestehender Auftragsprüfung. Sichtbare, kopierbare Client-Download-Adressen mit weiterhin erforderlicher Anmeldung.
- Windows-Client 0.2.12 aus aktuellem Quellstand neu gebaut; weiterhin experimentell. Die neuen GTK-Fenster- und Linux-SMB-Korrekturen sind Linux-spezifisch. Kein nativer Windows-Laufzeittest für diesen Release.

0.13-7 – 18. Oktober 2026 – Beta
- Linux-Client 0.4.40: neue serverseitige Offline-Rückholkopien im versteckten Ordner .hsm-history, nach UTC-Zeitstempel und Kennung geordnet, mit vollständigem Originalnamen.
- History-Ordner bleiben vom Offline-Abgleich ausgeschlossen. SMB-Löschungen und HTTPS-Ersetzungen erhalten den ursprünglichen Dateiknoten mit Eigentümer, Dateirechten und ACLs. SMB-Ersetzungen verwenden weiterhin eine geprüfte ACL-Kopie; fehlende Rechte werden nicht umgangen.
- Alte Rückholkopien bleiben erhalten; keine automatische Migration oder Löschung bei der Installation. Ohne vorhandene Zuordnung lassen sich deren Originalnamen nicht zuverlässig rekonstruieren.
- Windows-Client bleibt unverändert bei 0.2.12 (experimentell). Die neue SMB-Ablage im Client betrifft Linux.

0.13-8 – 18. Oktober 2026 – Beta
- Linux-Client 0.4.41: anklickbarer Software-Download-Link unten links. Die Adresse folgt der eingestellten Manager-Adresse; ohne gültige Adresse bleibt der Beispiel-Link deaktiviert.
- Versionsnummer nur noch im Fenstertitel; doppelte Versionszeile entfernt. Deutsche und englische Beschriftung.
- Enthält die History-Ablage und alle dokumentierten Korrekturen der Zwischenversionen 0.13-4 bis 0.13-7. Windows-Client unverändert 0.2.12 (experimentell).
