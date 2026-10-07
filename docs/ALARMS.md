# Zentrale Alarme

Unter **Alarme** werden ntfy-Versand, Speicher-Schwellwerte und Alarmquellen
verwaltet. Die bisherigen ntfy-Einstellungen bleiben in denselben lokalen
Datenbankeinträgen erhalten. Ein leeres Token-Feld behält den gespeicherten
Token; zum Entfernen gibt es eine eigene Auswahl. Der Token erscheint nicht
im HTML und wird nicht als Prozessargument übergeben. Für externe ntfy-Server
HTTPS verwenden. Weiterleitungen werden beim Versand nicht verfolgt.

Automatischer Versand ist zunächst ausgeschaltet. Speicher/SMART ist als
Quelle vorausgewählt; Sicherungen, DynDNS, Zertifikate und Systemdienste sind
optional. Nur dauerhaft benötigte Dienste auswählen. Die Überwachung liest
bestehende Zustände und startet weder Updates noch Sicherungen oder Reparaturen.

- Speicher: Belegung und SMART-Warnungen aus der Speicherprüfung.
- Sicherungen: fehlende/überfällige erforderliche Backup-Überwachungen und
  Fehler des letzten zentralen Backupauftrags.
- DynDNS: Anbieterfehler oder ausbleibende Prüfungen.
- Zertifikate: Warnung ab 30 Tagen, kritisch ab 7 Tagen oder bei Ungültigkeit.
- Dienste: ausgewählte Dienste fehlen oder sind nicht aktiv.

Das Prüfintervall ist von 1 bis 1440 Minuten einstellbar (Vorgabe: 5).
Die optionale tägliche Erinnerung nutzt die lokale Serverzeit (Vorgabe: 09:00)
und läuft unabhängig vom Intervall, mit bis zu 30 Sekunden Verzögerung. Bei
angehaltenem Manager oder schlafendem Server findet keine Prüfung statt.
Ein externer Ausfallwächter wird dadurch nicht ersetzt.

**Jetzt prüfen (ohne Versand)** aktualisiert die lokale Vorschau.
**Prüfen und fällige Alarme senden** versendet nur fällige Warnungen, sofern
ntfy aktiviert ist. **ntfy-Testmeldung senden** sendet eine Testnachricht.
Diese Aktionen verwenden bereits gespeicherte Einstellungen.

Neue, erneut aufgetretene oder verschärfte Warnungen werden versendet.
Unveränderte Warnungen werden einmal täglich zur eingestellten Uhrzeit
wiederholt. Die Erinnerung ist separat abschaltbar. Nach Unterbrechungen wird
die Erinnerung für den aktuellen Tag nachgeholt, nicht für vergangene Tage.
Erfolgreiche Sendungen sind gespeichert, sodass Neustarts keine Doppelmeldung
auslösen. Eine zuvor deaktivierte Stunden-Erinnerung bleibt deaktiviert. Versandfehler werden frühestens nach
fünf Minuten erneut versucht. Zustände bleiben über Neustarts erhalten.

Speicheralarme enthalten Gerät, Mount-Namen und Mountpunkte zur Zuordnung.
Andere Quellen enthalten standardmäßig nur die betroffene Modulbezeichnung.
Die optionale Detailübertragung kann lokale Pfade oder Domains enthalten.
Zugangsdaten gehören ausschließlich in die lokale Konfiguration, nicht in
Quellcode, Paket oder Dokumentation. Alte Speicher-Links mit `send=1` lösen
keinen Versand mehr aus; die Versandaktionen liegen zentral unter Alarme.
