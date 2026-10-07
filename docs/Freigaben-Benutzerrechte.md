# Benutzerrechte pro Freigabe

Aufruf: **Freigaben → Benutzerrechte** (`/freigaben/rechte`).

Die SMB-Matrix zeigt Freigaben in den Zeilen und Benutzer/Gruppen in den Spalten: kein Zugriff, Lesen, Lesen/Schreiben, SMB-Admin oder nicht eindeutig. Ein Klick auf die Freigabe zeigt die Herkunft der Regeln und die POSIX-Rechte des Hauptordners. Ein Klick auf ein Recht öffnet die Änderung für genau dieses Konto. Eine Filterauswahl beschränkt die Übersicht auf einen Benutzer oder eine Gruppe; weitere lokale bzw. Domänenkonten können in der Freigabeansicht ergänzt werden.

Die Auswertung liest `testparm -s`, berücksichtigt Freigabestandards und bekannte NSS-Gruppenmitgliedschaften. `invalid users` hat Vorrang vor Erlaubnissen; `write list` hat Vorrang vor `read list`. Ein leeres `valid users` bedeutet nicht „niemand“, sondern grundsätzlich alle authentifizierten Konten. Dynamische Namen/Netgroups und nicht auflösbare Kontozuordnungen werden nicht als sicherer Zugriff dargestellt. Gruppenspalten zeigen Gruppenregeln, nicht die Summe aller Mitgliedschaften eines Benutzers.

## Änderungen

- **Kein Zugriff:** gezielte Samba-Sperre, auch gegenüber einer Gruppenerlaubnis.
- **Lesen / Lesen und Schreiben:** gezielte Regel. Ein Konflikt mit einer weitergehenden Gruppenregel wird vor Anwendung abgewiesen und erklärt; Gruppenmitgliedschaften werden nicht automatisch verändert.
- **SMB-Admin:** Dateivorgänge als root; zusätzliche Bestätigung erforderlich.
- **Gruppen/Standard:** direkte Regeln entfernen. Die letzte Erlaubnis einer ansonsten eingeschränkten Freigabe darf dabei nicht in eine leere Liste umgewandelt werden, weil das den Zugriff erweitern würde.

Unbeteiligte Regeln und Freigabeoptionen bleiben erhalten. Eine Änderung läuft über die bestehende sitzungsgebundene Vorschau, Konfigurationssicherung, Validierung und Aktivierung. Konfigurationsabhängigkeiten und relevante Gruppenauflösung werden vor dem Schreiben erneut geprüft.

Aktiver Gastzugriff wird gesondert angezeigt: Eine Benutzersperre verhindert keine unabhängige anonyme Anmeldung. Bereits bestehende SMB-Verbindungen sollten nach Rechteänderungen getrennt und neu aufgebaut werden.

## Ordnerrechte und NFS

Optional können die POSIX-Rechte des Hauptordners passend geändert werden. Dies ist keine rekursive Änderung vorhandener Unterordner oder Dateien. Vererbung für künftig neue Inhalte ist separat wählbar. Eine durch `force user/group` erzwungene Dateiidentität wird angezeigt; automatische persönliche ACL-Anpassungen werden dann abgewiesen, außer für die passende erzwungene Gruppe.

NFS zeigt Exportregeln und bietet die gezielte Änderung der Hauptordner-ACL für auflösbare Benutzer/Gruppen. Entscheidend bleibt die numerische UID/GID des Clients; ein schreibgeschützter Export bleibt schreibgeschützt. Ein Gruppen-ACL-Eintrag `---` verhindert keinen Zugriff aus anderen Gruppen. Root-Zugriff kann durch diese ACL-Oberfläche nicht eingeschränkt werden.

ACL-Änderungen wirken auf denselben Ordner auch über andere SMB-/NFS-Freigaben. Die Vorschau nennt diese Freigaben. Vorherige ACLs werden zusätzlich in `acl-before.json` im jeweiligen Freigaben-Sicherungsverzeichnis gespeichert. Fehlgeschlagene Aktivierungen nehmen Konfiguration und ACL zurück. Veränderte Ordneridentitäten oder ACLs machen eine neue Vorschau notwendig. Schreibzugriff nutzt einen ohne Symlink-Verfolgung geöffneten Verzeichnisdeskriptor. Beim Erweitern der ACL-Maske werden bislang maskierte Rechte anderer Einträge nicht versehentlich freigegeben.

Die angezeigte Ordnerprüfung betrifft die POSIX-Rechte der Ordnerwurzel. Authentifizierung, übergeordnete Verzeichnisse, Windows-ACLs, erzwungene Identitäten und Rechte einzelner Dateien können den tatsächlich nutzbaren Zugriff zusätzlich einschränken.

## Validierung

`python3 -m unittest discover -s tests -p 'test_share*.py' -v`

56 Tests: Freigaben-Regressionen, Gruppenauflösung/Prioritäten, Konflikte, letzte Erlaubnis, Adminbestätigung, Gastzugriff, gezielte Änderungen, Formularschutz, Vorschau, echte ACL-Anwendung und Rücknahme, Masken und konkurrierende Änderungen. Produktive Rechte werden durch Tests oder Aktivierung des Moduls nicht geändert.

Referenz: [Samba smb.conf – Zugriffslisten](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html).
