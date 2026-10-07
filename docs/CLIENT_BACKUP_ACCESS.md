# Desktop-Clients: HTTPS und Backup & Recovery

Linux-Client 0.2.2 und Windows-Client 0.2.2 ergänzen die bisherigen Agentenfunktionen.

## Einrichtung im Manager

Unter Daten → Backup & Recovery → Desktop-Clients Sicherungen aktivieren,
Speicherlimit festlegen (Standard 100 GiB pro Client) und den Backup-Datenträger
bestätigen. Die Dateisystem-UUID wird bei jeder Übertragung geprüft. Das Ziel
liegt unter dem einstellbaren zentralen Backupordner in desktop-client-backup.
Die Ablage ist auch bei der externen Gesamtsicherung auswählbar. Bei einer
bereits gespeicherten Quellenauswahl diesen zusätzlichen Bereich überprüfen.

Für jeden Benutzer einen eigenen Eintrag unter Netzwerk → Client-Agenten
anlegen und dessen JSON-Profil herunterladen. Profile enthalten geheime
Client-Tokens: nicht teilen, nicht in Git oder öffentliche Downloads aufnehmen.
Ein Client-Profil entspricht einer Backup-Identität. Wer denselben Token erhält,
kann dieselben Client-Sicherungen lesen. Ein Token ist kein Administratorzugang.
Deaktivierung des Client-Eintrags sperrt die API; Tokenwechsel erhält seine Stände.
Gelöschte Client-Einträge entfernen nicht automatisch die gespeicherten Daten.

## Eigene Dateien sichern und wiederherstellen

Im Client „Eigene Backups / Wiederherstellung“ öffnen, Benutzerordner auswählen
und Sicherung bestätigen. Programme mit geöffneten Dateien vorher schließen.
Das Archiv wird zunächst lokal erzeugt: dafür muss Platz im temporären Ordner
vorhanden sein. Übertragung erfolgt in Abschnitten, anschließend SHA-256-Prüfung
auf dem Server. Erst vollständige Stände erscheinen in der Auswahl.

Unterbrochene Übertragungen lassen sich ausdrücklich verwerfen. Nach 24 Stunden
werden sie bei der nächsten Anfrage dieses Clients bereinigt. Eine Fortsetzung
nach Neustart wird derzeit nicht angeboten. Während Übertragung/Download/Prüfung
wird der Server als benötigt gemeldet. Ein abgebrochener Upload blockiert maximal
noch drei Minuten nach seinem letzten Abschnitt.

Wiederherstellung lädt das Archiv herunter, prüft dessen SHA-256 und legt einen
neuen Ordner an. Bestehende Ziele werden abgelehnt. Fehler können einen Teilstand
im neuen Ziel zurücklassen; dieser wird nicht als erfolgreiche Rücksicherung
bestätigt. Keine automatische Löschung älterer vollständiger Stände, höchstens
500 Stände pro Client; ältere Stände bei Bedarf administrativ archivieren.

Umfang: Dateien, leere Verzeichnisse und Dateiänderungszeiten. Linux stellt
Dateien unter dem aktuellen Benutzer mit eingeschränkten eigenen Rechten her.
Keine vollständige Übernahme von ACLs, Eigentümer-IDs, Hardlinks, Symlinks,
Spezialdateien oder Windows-Registry. Unterordner auf separaten Linux-Mounts und
Windows-Reparse-Points werden ausgelassen. NTFS-Zusatzstreams werden nicht
mitgesichert. Dies ist kein bootfähiges Systemabbild und kein Ersatz für das
vorhandene Live-/Migrationswerkzeug. Windows kann Linux-Dateinamen ablehnen.

## Server-Sicherungen: nur Administrator

„Server-Backup (Administrator)“ öffnet die bestehende Backup-&-Recovery-Seite
im Browser über eine erneute Manager-Anmeldung. Dort bleiben Server-Sicherungen,
Status, externe Gesamtsicherung und vorhandene Wiederherstellungsfunktionen.
Das Administratorpasswort wird weder im Client noch im JSON-Profil gespeichert.
Die Server-Routen akzeptieren keinen normalen Client-Token. Ein lokales
Administratorkonto auf dem Client verleiht keine Manager-Administratorrechte.

## Privates HTTPS

Zuerst im Manager unter Einstellungen → HTTPS-Zugang privaten Hostnamen und
Zertifikat einrichten. Danach ein neues Client-Profil herunterladen/importieren.
Dieses enthält zusätzlich das öffentliche Stammzertifikat, SHA-256-Fingerabdruck,
Hostname und Port. Es enthält niemals den privaten Schlüssel des Zertifikats.

Im Client „Privates HTTPS“ öffnen. Fingerabdruck mit der Manager-Einstellungsseite
vergleichen und Import ausdrücklich bestätigen. Optional eine feste Server-IP
für einen markierten hosts-Eintrag angeben. Leer lassen, wenn lokales DNS den
Namen bereits auflöst. Vorhandene fremde Namenseinträge werden nicht überschrieben.
Linux fragt über Polkit nach Administratorfreigabe; Windows über UAC. Der Import
gilt systemweit und vertraut der privaten Zertifizierungsstelle auch für andere
von ihr signierte Namen. Nur einem selbst verwalteten Stammzertifikat vertrauen.

Anschließend HTTPS-Verbindung prüfen und neue Manager-Adresse übernehmen.
Die Prüfung deaktiviert keine Zertifikatsvalidierung. Eine HTTP-Adresse wird
nicht automatisch umgestellt; HTTP-Backups übertragen Daten unverschlüsselt.
„Eigene Einrichtung entfernen“ entfernt vom Assistenten verwaltete Einträge.
Das kann bestehende HTTPS-Verbindungen unterbrechen. Browser können einen
Neustart oder eine zusätzliche Zertifikatseinrichtung benötigen, wenn sie einen
eigenen Vertrauensspeicher nutzen. Eine Installationsstörung kann Teiländerungen
hinterlassen; dann Meldung prüfen und Einrichtung erneut ausführen oder entfernen.

## Plattformgrenzen

Linux: GTK 3, Ayatana-Statussymbol, OpenSSL, CA-Werkzeuge und Polkit werden als
Paketabhängigkeiten aufgenommen. Startmenüeintrag unter Internet/Netzwerk.
Windows 10/11: .NET Framework 4.8, ohne Python; EXE ist nicht digital signiert.
Windows-Build und Dateiübertragung sind automatisiert getestet; echte Windows-
UAC- und Zertifikatsspeicher-Tests benötigen einen Windows-Rechner. Windows gilt
bis dahin weiterhin als experimentell.

Private HTTPS-Profile unterstützen auch kurze Rechnernamen ohne Domain-Endung.
Öffentliche Zertifikate benötigen weiterhin einen vollständigen Domainnamen.
