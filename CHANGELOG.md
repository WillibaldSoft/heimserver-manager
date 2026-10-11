# CHANGELOG

Aktuelle Version: **0.13-3** (Beta). Die vollständigen Änderungen stehen in der
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
