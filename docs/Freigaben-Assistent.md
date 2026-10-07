# Freigaben: Erstellen, Ändern, Domäne und Client-Dateien

## Bedienung

`/freigaben` zeigt SMB und NFS getrennt, mit Suche, Zugriffsübersicht und Bearbeiten-/Client-Datei-Schaltflächen.

1. **Neue SMB-Freigabe** für Windows, macOS und Linux oder **Neue NFS-Freigabe** für Linux/Unix wählen.
2. Datenordner direkt eingeben oder im Ordnerwähler auswählen. Ein neuer Unterordner kann ausdrücklich angelegt werden.
3. Zugriffsrecht und erlaubte Benutzer/Gruppen (SMB) bzw. Geräte/Netze (NFS) wählen.
4. **Änderung prüfen** erzeugt eine Vorschau. Erst **Jetzt anwenden** aktiviert sie.

Bearbeiten verwendet denselben Assistenten mit vorausgefüllten Werten. „Entfernen“ entfernt nur die Freigabedefinition, niemals Nutzdaten. Der SMB-Netzwerkname bleibt bei einer Bearbeitung stabil.

### Rechte

SMB: „Bisherige Rechte unverändert übernehmen“ erhält vorhandene Lese-/Schreib-/Admin-Ausnahmen. Die explizite Auswahl „Nur Lesen“ oder „Lesen und Schreiben“ ersetzt diese Ausnahmen durch das gewählte einheitliche Recht. Benutzer oder @Gruppen lassen sich per Schaltfläche ergänzen; Domänenbezeichnungen mit Leerzeichen werden in doppelte Anführungszeichen gesetzt, etwa `@"FAMILIE\Domain Users"`.

Bestehende Dateisystemrechte werden nicht rekursiv verändert. Ein neuer SMB-Ordner erhält ACLs für die ausgewählten lokal auflösbaren Konten/Gruppen. Neue NFS-Ordner benötigen eine gemeinsame Linux-Gruppe, deren numerische GID auf den Clients übereinstimmt. Bei Gastzugriff gelten zusätzlich die Samba-Servereinstellungen.

NFS: IP-Adressen und CIDR-Netze werden geprüft; die Oberfläche setzt `ro`/`rw`, `sync`, `no_subtree_check` und die gewählte Root-Zuordnung. Erweiterte bestehende Optionen werden nur nach ausdrücklicher Auswahl ersetzt. Insbesondere kann das bestehende Kerberos-/`sec`-Optionen entfernen; dies wird angezeigt. NFS mit `sec=sys` verwendet Client-UID/GID und wird durch einen AD-Beitritt nicht automatisch Kerberos-geschützt. Das ungültige bisherige `rwx` wird markiert; beim Bearbeiten wird `rw` vorbereitet. Keine automatische Änderung vorhandener Exporte beim Deployment.

## Konfigurationsschutz

- GET-Seiten und Downloads verändern keine Freigaben.
- Alle schreibenden Formularrouten haben Session-CSRF-Schutz.
- Vorschauen sind an die Browser-Sitzung gebunden, einmalig anwendbar und 15 Minuten gültig.
- Vor dem Schreiben müssen die betroffenen Konfigurationsdateien noch exakt zur Vorschau passen.
- Bestehende SMB-Sektionen werden in ihrer Quelldatei bearbeitet; andere Sektionen, unbekannte Optionen und wörtliche Includes bleiben erhalten. Neue Freigaben erhalten eigene Dateien und explizite Einträge in `shares.includes.conf`.
- NFS bearbeitet nur die gewählte Zeile bzw. deren Fortsetzungszeilen in `/etc/exports` oder `/etc/exports.d/*.exports`; Kommentare und andere Regeln bleiben erhalten.
- Vorherige Inhalte werden unter `STATE_DIR/backups/shares/<Zeit>-<ID>/restore.json` gesichert. Auf diesem Server liegt der Bereich unter `/var/lib/server-manager/backups/shares`.
- Samba wird mit `testparm` geprüft und per Reload aktiviert. NFS wird mit `exportfs -ra` aktiviert. Ein Fehler stellt die vorherigen Dateien wieder her und versucht die vorherige Konfiguration neu zu laden; auch ein Fehler bei der Rücknahme wird angezeigt.
- Der zentrale Schlaf-Blocker ist während Prüfung/Aktivierung/Rücknahme aktiv. Gleichzeitige Änderungen werden gesperrt. Ein Server-Manager-Neustart während der Anwendung wird als unterbrochen markiert; Konfiguration/Sicherung dann prüfen.
- Konfigurationswrites benötigen Dateirechte des Dienstkontos. Die vorhandene Installation läuft als root. Ein Sudo-Passwort allein verleiht einem anders eingerichteten Dienst keine direkten Dateischreibrechte.

## Client-Dateien

Je SMB-Freigabe: Windows-PowerShell zum Verbinden eines freien Laufwerksbuchstabens oder Linux-Desktop-Skript zum Öffnen im Dateimanager. Je NFS-Freigabe: Linux-Skript zum Einhängen in einen leeren Ordner; kein automatischer `/etc/fstab`-Eintrag. Servername/IP ist wählbar. Zugangsdaten werden erst am Zielrechner abgefragt. Der bisherige vollständige Linux-Mount-Manager bleibt verfügbar.

## Optionale Domäne

`/freigaben/domain` speichert ein **Einrichtungsprofil**, nicht die aktuelle Serverrolle. Standardmäßig deaktiviert. Es gibt beide Wege:

- **Mitglied einer vorhandenen AD-Domäne:** Server-Datei verwendet realmd mit Samba/Winbind und prüft den Beitritt. Sie sichert die bisherigen Konfigurationsdateien. Der Beitritt wird interaktiv am Zielserver ausgeführt.
- **Neue AD-Domäne:** Server-Datei für eine frische Debian-13-VM bzw. einen eigenen Server. Sie kontrolliert Hostname, vorhandene IP, AD-Datenbank und bestehende SMB-/NFS-Freigaben, bevor eine interaktive Samba-AD-Provisionierung beginnt. Vorhandene Dateiserver werden nicht automatisch konvertiert. DNS, Zeitdienst und AD-Sicherung müssen passend eingerichtet werden. Unterbrochene Provisionierung erfordert Prüfung der Teilergebnisse.

Zusätzlich: Windows- und Linux-Beitrittsdateien sowie ein interaktives AD-Verwaltungsmenü für den eingerichteten DC (Benutzer/Gruppen anzeigen und anlegen, Gruppenmitglied hinzufügen, Passwort setzen). Es gibt keinen direkten Web-Beitritt, keine Passwortspeicherung und keinen automatischen Client-Neustart. Passwörter werden durch die Zielwerkzeuge abgefragt; die Serverdateien ändern Systeme erst nach ihrem manuellen Start und Bestätigung.

Lokale Linux-/Samba-Benutzer bleiben unter Benutzer/Gruppen verwaltbar. Passwortübergabe erfolgt über stdin statt Shell-Interpolation.

## Prüfung

`python3 -m unittest discover -s tests -p test_shares.py -v`

Tests nutzen temporäre Konfigurationen, simulierte Reloads und reale `testparm`-Prüfungen sowie `bash -n` für erzeugte Linux-Dateien. Keine produktiven Freigaben, Konten, Domänen oder Clients werden zu Testzwecken geändert. Ein echter AD-Beitritt, DC-Provisionierung und Windows-Ausführung benötigen eine passende Zielumgebung und sind nicht Teil dieses Tests.

Referenzen: [Debian realm](https://manpages.debian.org/trixie/realmd/realm.8.en.html), [Samba smb.conf](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html), [Samba samba-tool](https://www.samba.org/samba/docs/current/man-html/samba-tool.8.html), [NFS exports](https://manpages.debian.org/trixie/nfs-kernel-server/exports.5.en.html), [Microsoft Add-Computer](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/add-computer).
