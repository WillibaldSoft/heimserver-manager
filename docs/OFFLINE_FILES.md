# Offline-Dateien (Beta)

Unter **Netzwerk → Client-Agenten → Offline-Dateien · Freigaben** gibt der
Manager-Administrator einen bestehenden Datenordner für ausgewählte gekoppelte
Benutzer und Geräte frei. Alte, ungekoppelte Token reichen nicht. Der Manager
grenzt die nutzbaren Ordner ein; zusätzliche Dateirechte erteilt er nicht.
SMB-/NFS-Regeln und Linux-Dateirechte des gekoppelten Systembenutzers werden geprüft.
Dateivorgänge laufen mit dessen UID und Gruppen in einem getrennten Prozess.
Entfernen einer Freigabe verhindert weitere Zugriffe, löscht aber keine lokalen Kopien.

Im Linux-Client ab 0.4.8 bzw. Windows-Client ab 0.2.10 **Offline-Dateien** öffnen,
Freigaben laden und einen eigenen lokalen Unterordner auswählen. Nicht direkt ein
Netzlaufwerk oder das gesamte Benutzerverzeichnis verwenden. Standard: nur vom
Server herunterladen, manuell starten, keine Löschweitergabe und kein Aufwecken.
HTTPS mit geprüfter Zertifikatskette ist erforderlich.

Optional lassen sich beide Richtungen, Löschweitergabe, Aufwecken vor dem Abgleich,
ein Minutenintervall und das lokale Speicherlimit einstellen. Das Intervall läuft
nur, solange der Client einschließlich Statussymbol läuft; keine Weckversuche,
wenn die Aufweckoption ausgeschaltet ist. Unter Ausschließen relative Datei- oder
Ordnernamen durch Komma trennen, etwa `Videos,Entwuerfe/gross.bin`. Keine Platzhalter.
Ausschlüsse entfernen keine vorhandenen lokalen Dateien.

Der Abgleich vergleicht SHA-256 mit dem letzten bestätigten Stand. Nur geänderte
Dateien werden übertragen, jeweils vollständig, ohne lokales Gesamtarchiv. Nach
einem Abbruch werden bereits bestätigte Dateien nicht erneut übertragen; eine
unterbrochene einzelne Datei beginnt erneut. Kein blockweiser Delta-Abgleich.
Während des Abgleichs hält eine erneuerte, befristete Sperre den Server wach.

Gleichzeitig geänderte Dateien bleiben auf beiden Seiten unverändert; der Client
meldet die betroffenen Pfade. Beide Fassungen zunächst getrennt sichern, dann
bewusst angleichen und erneut synchronisieren. Keine automatische Konfliktauflösung.
Erst wenn beide Seiten denselben Inhalt haben, wird die neue gemeinsame Basis bestätigt.
Neue, unterschiedliche Dateien mit gleichem Namen werden ebenso als Konflikt behandelt.

Ersetzte und gelöschte Serverdateien bleiben als `.hsm-history-*` im jeweiligen
Quellordner erhalten. Der Administrator kann sie bei angehaltenem Abgleich
zurückkopieren. Lokale frühere Dateien liegen unter `.hsm-recovery` im gewählten
Offline-Ordner; versteckte Dateien im Dateimanager anzeigen. Nicht benötigte
Rückholstände manuell entfernen. Sie verfallen nicht automatisch und zählen zum
lokalen Speicherverbrauch. Synchronisierung ersetzt keine unabhängige Sicherung.

Grenzen: höchstens 5000 reguläre Dateien pro Ordner ohne feste Dateigrößengrenze. Keine
Links, Spezialdateien, leeren Ordner, verschachtelten Mounts oder nicht portablen
Dateinamen. Windows-Verknüpfungen/Junctions und Hardlinks werden abgelehnt. Änderungen
an Systemdateien, Datenbanken und geöffneten Anwendungsdaten sind nicht geeignet.
Für konsistente Dokumente Anwendungen vor dem Abgleich schließen. Gleichzeitige
Änderungen durch andere Programme werden soweit erkennbar abgelehnt; das Modul
stellt keine globale Dateisperre für SMB oder lokale Programme bereit.

Bei fehlendem Zielordner, geändertem Datenträger oder ungültiger Freigabe stoppt der
Abgleich. Der Server bindet die Freigabe an Ordner- und Gerätekennung; nach einem
Wechsel muss der Administrator die Freigabe neu erstellen. Nach Profilwechsel wird
eine neue Abgleichbasis verwendet; abweichende vorhandene Dateien werden nicht
stillschweigend überschrieben. Windows-Bau und Logik unter Mono geprüft; ein Test
auf echtem Windows 10/11 steht noch aus.

## Mehrere Ordner (Linux 0.4.7 / Windows 0.2.9)

Im Manager mehrere absolute Serverpfade zeilenweise eintragen. Alle werden vor
dem Speichern geprüft und als getrennte Freigaben für die ausgewählten Clients
angelegt. Überlappende Pfade werden abgelehnt. Der optionale Name dient bei
mehreren Pfaden als Präfix.

Im Client mehrere Freigaben anhaken und „Ausgewählte Ordner einrichten“ wählen.
Ein gemeinsamer lokaler Basisordner erhält je Freigabe einen eigenen Unterordner;
auch gleichnamige Freigaben bekommen unterschiedliche Ziele. Bereits gespeicherte
Ziele und Einstellungen bleiben erhalten. Neue Abgleiche starten lesend, manuell,
ohne Aufwecken oder Löschweitergabe. Über die Einzelauswahl lassen sie sich ändern.
„Ausgewählte Ordner synchronisieren“ arbeitet die eingerichteten Ordner nacheinander
ab und meldet das Ergebnis je Ordner. Ein Fehler stoppt nicht die übrigen Ordner.

Eingehängte Ordner und direkte Unterordner sind im Manager gemeinsam per Haken auswählbar. Jeder Ordner bleibt eine eigene Freigabe. Neue Freigaben speichern Dateisystem-UUID (oder Netzwerkquelle) und Mountpfad; fehlende oder geänderte Mounts sperren die Synchronisierung. Unter-Mounts separat freigeben. Bestehende Freigaben behalten ihre bisherigen Identitätsprüfungen.

Offline-Ordnerauswahl und Rechte (Linux-Client 0.4.8 / Windows-Client 0.2.10):
Der Manager begrenzt die Auswahl auf Mounts und eingerichtete Freigabeordner. Im Client lassen sich darin beliebig tiefe Unterordner öffnen und mehrere getrennt auswählen.
Neue Freigaben erteilen keine zusätzlichen Schreibrechte. Für jeden Zugriff gelten die SMB-/NFS-Regeln und die Linux-Dateirechte des gekoppelten Systembenutzers; Dateizugriffe laufen in einem separaten Prozess mit dessen UID und Gruppen. Das Notfallkonto ADMIN kann keine Offline-Dateien abrufen. Bestehende Nur-Lesen-Begrenzungen bleiben erhalten.
Grenzen: komplexe SMB-Regeln, Windows-ACLs/VFS, erzwungene Identitäten, NFS-Hostnamen/Wildcards und erweiterte NFS-Identitätsregeln werden nicht geraten, sondern gesperrt. Bei mehreren Freigabearten gilt vorsichtig die Schnittmenge. Unter-Mounts benötigen eine eigene Freigabe. Eigentümer, Modus und POSIX-ACL vorhandener Dateien bleiben erhalten; ist dies unter dem Benutzer nicht möglich, wird die Änderung abgewiesen. Vorhandene lokale Kopien verschwinden bei Rechteentzug nicht automatisch.

- Offline-Dateien: zuerst Benutzer/Client wählen, dann dessen Ordnerzuordnung ändern. Nur Mounts und eingerichtete SMB-/NFS-Freigabeordner auswählbar; keine Verzeichnisauflistung darunter. Andere Clients und bestehende Rechte bleiben erhalten.

Zugriffsdiagnose: Bei zugewiesenen, aber vollständig gesperrten Ordnern meldet die API den Ablehnungsgrund statt einer scheinbar leeren Freigabeliste. Unter Offline-Dateien kann der Administrator die Zugriffsprüfung für den ausgewählten Client aufrufen. Die Prüfung ändert keine Rechte oder Zuordnungen.

Samba-Prüfung: Freigabe-ACL und zusätzliche Windows-Datei-ACLs werden mit Sambas access_check geprüft. Die Prüfung gilt bereits bei der Zuordnung pro Benutzer/Client und erneut beim Dateizugriff. Die Zuordnungsauswahl zeigt ausschließlich zugängliche Ordner des ausgewählten Benutzers. Beim Speichern werden ausgeblendete, nicht mehr zugängliche Zuordnungen dieses Clients entfernt. Unterstützt werden lokale Standalone-Server mit tdbsam, normale Allow-/Deny-ACLs und auflösbare lokale Identitäten; unbekannte Regeln bleiben gesperrt. Der direkte HTTPS-Schreibweg bleibt für Samba-Ordner gesperrt. Ab Linux-Client 0.4.14 ist stattdessen die unten beschriebene zusätzliche SMB-Anmeldung zum Zurückschreiben möglich. Es werden keine Samba-Rechte geändert. Benötigt: python3-samba und sharesec.

Linux-Client 0.4.9 (10.10.2026): Vorhandene SMB-/NFS-Mounts werden erkannt und lassen sich einer Offline-Freigabe zuordnen. Die Übertragung bleibt HTTPS; es werden keine Mounts erzeugt oder geändert. Offline-Ziele innerhalb, oberhalb oder identisch zu bekannten Netzwerk-Mounts werden gesperrt; gespeicherte Mount-Zuordnungen schützen auch bei ausgehängtem Mount. Windows-Client unverändert.

Linux-Client 0.4.10 (10.10.2026): Ein bestehender einfacher SMB-/NFS-fstab-Mount kann nach ausdrücklicher Bestätigung und Administratorfreigabe durch einen Link auf den lokalen Offline-Ordner ersetzt werden. Vorher wird konfliktfrei über HTTPS synchronisiert. Der bisherige Pfad bleibt nutzbar; fstab und Mountverzeichnis werden gesichert. Rückkehr zum Netzwerk-Mount mit Bestätigung möglich, lokale Dateien bleiben erhalten. Keine erzwungene Trennung belegter Mounts. Automounts, eigene Mount-Dienste und beschreibbare Mount-Elternverzeichnisse werden nicht automatisch umgestellt. Samba-Offlinedaten derzeit nur lesend; lokale Änderungen werden nicht zum Server zurückgeschrieben.

Linux-Client 0.4.11 (10.10.2026): Die bestätigte Offline-Umschaltung unterstützt nun eigene systemd-Automount-Units und aus fstab erzeugte Automounts für SMB/NFS. Eine eigene dauerhafte Startbedingung verhindert erneutes Einhängen während des Offline-Betriebs. Originale Units, fstab-Einträge und Autostart bleiben unverändert. Der frühere aktive/inaktive Zustand wird gesichert und beim Rückwechsel wiederhergestellt. Belegte Mounts werden nicht erzwungen getrennt; geänderte Unit-Konfigurationen und übersteuerte Startsperren werden abgewiesen. Vorheriger erfolgreicher konfliktfreier HTTPS-Abgleich, Bestätigung und Administratorfreigabe bleiben erforderlich.

Linux-Client 0.4.12 (10.10.2026): „Mount-Pfad für Offline-Dateien übernehmen“ schlägt automatisch einen separaten lokalen Speicherordner vor. Ein bereits eingerichteter lokaler Ordner wird weiterverwendet; ungültige Netzwerk-Ziele werden abgewiesen. Die Bestätigung zeigt gewohnten Zugriffspfad und lokalen Speicherort, bevor Einstellungen gespeichert, Dateien synchronisiert oder Mounts geändert werden. Danach gelten weiterhin konfliktfreier Abgleich und Administratorfreigabe.

Fehlerkorrektur: Aus security.NTACL gelesene Windows-ACLs werden vor der Samba-Prüfung verlustfrei in einen eigenständigen Security Descriptor umgewandelt. Ein interner Typfehler wird nicht mehr als Rechteverweigerung ausgegeben. Rechtefehler nennen den betroffenen Pfad; der Mount wird bei fehlgeschlagener Synchronisierung nicht ersetzt.

Linux-Client 0.4.13 (10.10.2026): Lokale Offline-Ordner direkt im Client anlegen oder übernehmen. Vor dem Speichern und Synchronisieren werden Schreibrechte geprüft; falls erforderlich, gezielte Administratorfreigabe zum Anlegen oder Ändern des Ordnereigentümers. Keine rekursive Rechteänderung, kein Client-Start als root. Netzwerk-Mounts und Systemordner bleiben ausgeschlossen. Bei privilegiertem Anlegen muss der übergeordnete Ordner bereits vorhanden und geschützt sein.

Linux-Client 0.4.14 (10.10.2026): Beide Synchronisationsrichtungen für unterstützte SMB-Freigaben mit zusätzlicher SMB-Anmeldung. Passwort ausschließlich im lokalen Schlüsselbund; HTTPS-Lesezugriffe und vorhandene Manager-Zuordnungen bleiben erforderlich. Samba setzt Schreib- und Vererbungsrechte selbst durch. Bestehende Dateien werden unter Beibehaltung ihres Eigentümers und ihrer ACL aktualisiert; vorheriger Inhalt wird mit geprüften Rechten als Server-Rückholstand gesichert. Unterbrochene Schreibvorgänge können einen unvollständigen Serverstand hinterlassen: lokale Datei und Rückholstand behalten, Konflikt prüfen und bewusst auflösen. Kein automatisches Überschreiben abweichender Fassungen.
Pro Ordner nachträglich änderbar: bei Benutzeranmeldung / Client-Start sowie vor dem Ausschalten synchronisieren. Beim Ausschalten keinen Server wecken; bei Nichterreichbarkeit nach kurzer Prüfung sofort fortfahren. Sonst höchstens 60 Sekunden, zusätzlich begrenzt durch systemd-logind (häufig 5 Sekunden). Der Client muss laufen; erzwungenes Ausschalten wird nicht abgefangen. Fehler und Zeitüberschreitungen bleiben als ausstehend sichtbar. Nächster Start gleicht erneut ab, wenn die Startoption aktiv ist. Neue Paketabhängigkeiten: python3-smbc und libsecret-tools. Windows-Client unverändert.

ACL-Korrektur: Nicht auflösbare Identitäten in erlaubenden Samba-ACL-Einträgen gewähren keine Rechte mehr, blockieren aber unabhängig nachgewiesenen Lesezugriff nicht. Unbekannte verbietende Einträge bleiben gesperrt. Vorhandene Datei- und Freigaberechte werden nicht verändert.

Linux-Client 0.4.15 / Windows-Client 0.2.11 (10.10.2026): Die 256-MiB-Grenze für Offline-Dateien entfällt, auch größere ISO-Dateien sind möglich. Blockweise Übertragung; Speicherlimit, freier Platz, Rechteprüfung und Zeitlimits gelten weiterhin. Temporäre Serverablagen benötigen die Dateigröße plus 512 MiB Reserve. Links und Spezialdateien bleiben ausgeschlossen.

Linux-Client 0.4.16 (10.10.2026): Bei Auswahl eines Netzwerk-Mounts wird der Offline-Zielpfad aus dessen Ordnerstruktur vorgeschlagen: zwischen übergeordnetem Ordner und Mountnamen wird Offline eingefügt. Der Vorschlag bleibt änderbar. Bestehende Zuordnungen werden beim Öffnen beibehalten; vorhandene Dateien werden nicht automatisch verschoben.

Linux-Client 0.4.17 (10.10.2026): Neuer Button „Alle Server-Unterordner aufnehmen“ wählt nach Bestätigung den gesamten zugewiesenen Serverordner und entfernt Ausschlüsse. Dateien in tieferen Unterordnern werden rekursiv synchronisiert. Zielpfad prüfen und speichern; kein unmittelbarer Sync-Start. Rechteprüfung bleibt bestehen; leere Ordner, Links und separate Unter-Mounts werden nicht übernommen.
