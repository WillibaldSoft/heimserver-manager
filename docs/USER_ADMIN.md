# Benutzer, Linux-Gruppen und Passwörter

Unter Freigaben & Benutzer → Benutzer → Benutzer bearbeiten die lokalen Konten
verwalten. Einstellungen → Manager-Benutzer verlinkt beim jeweiligen Linux-Konto
auf dieselbe Bearbeitungsseite. Die Übersicht zeigt bestehende Gruppen; die
Bearbeitung zeigt zusätzlich UID/GID, Home, Shell und primäre Gruppe.

Nur Manager-Administratoren dürfen Änderungen ausführen. Vor jeder Änderung das
eigene aktuelle Administratorpasswort bestätigen. Erlaubt sind lokale Konten mit
UID 1000 bis 59999; root und Systemkonten unter UID 1000 sind ausgeschlossen.
UID, primäre Gruppe, Home und Shell werden nicht geändert.

Gruppen einzeln hinzufügen oder entfernen. Andere Mitgliedschaften bleiben
unverändert, auch wenn sie in früheren Auswahllisten nicht sichtbar waren.
Für sudo und weitere Gruppen mit weitreichenden Rechten ist eine ausdrückliche
Bestätigung erforderlich. sudo erlaubt Betriebssystemverwaltung, erteilt aber
keinen Manager-Zugang. Auch docker, disk und ähnliche Gruppen können erhebliche
Rechte gewähren. Bestehende Benutzersitzungen benötigen danach eine Neuanmeldung.
Gleichzeitige Änderungen im Manager werden serialisiert; veraltete Formulare
werden anhand der Benutzerkennung und Mitgliedschaften zurückgewiesen.

Linux-Passwort und SMB-Passwort sind getrennte Aktionen. Jeweils neues Passwort
zweimal eingeben, 8 bis 256 Zeichen ohne Zeilenumbrüche. Linux-Passwortänderungen
betreffen auch freigeschaltete PAM-Anmeldungen im Manager und machen deren
bestehende Sitzungen ungültig. Ein bislang gesperrtes Linux-Passwort kann durch
das Setzen wieder nutzbar werden; SSH-Schlüssel und Ablaufvorgaben bleiben separat.
SMB-Passwortsetzen aktiviert bei Bedarf den Samba-Zugang. Es ändert weder das
Linux-Passwort noch Freigaberechte. NFS besitzt kein eigenes Benutzerpasswort.

Passwörter werden ausschließlich über die Standardeingabe der Systemwerkzeuge
übergeben, nicht als Prozessargument oder Shelltext. Der Manager speichert sie
nicht im Klartext und zeigt sie nicht erneut an. Passwortfehler geben keine
ungefilterten Ausgaben externer Werkzeuge zurück. Die Betriebssystem- bzw.
Samba-Passwortdatenbank speichert weiterhin ihre eigenen geschützten Nachweise.
Die Aktion benötigt passende Dienstrechte sowie chpasswd bzw. smbpasswd;
fehlende Werkzeuge oder Passwortvorgaben werden als nicht bestätigt gemeldet.

Gruppenauswahl: Mitgliedschaften per Häkchen hinzufügen oder entfernen und gemeinsam mit „Gruppen speichern“ übernehmen. Primäre Gruppe geschützt; Administratorpasswort und bei geänderten besonderen Rechten ausdrückliche Bestätigung erforderlich. Veraltete Gruppenauswahl wird abgelehnt.
