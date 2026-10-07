# Downloads

Daten → Downloads stellt Dateien des konfigurierten Hauptordners einschließlich Unterordnern für angemeldete Server-Manager-Benutzer bereit. Hauptordner: Einstellungen → Server & Modulpfade → Downloads. Standard: `/srv/server-manager/downloads`. Den vorhandenen Datenordner auswählen, Änderungen prüfen und über die Einstellungsseite aktivieren. Es werden keine vorhandenen Datenordner automatisch freigegeben, erstellt oder kopiert.

Ordnernavigation, Breadcrumbs, Suche im aktuellen Ordner, Dateigröße, Änderungsdatum und 100 Einträge pro Seite. Einzelne Dateien werden als Download gestreamt; HTTP Range unterstützt Fortsetzungen. Keine Upload-, Änderungs- oder Löschfunktion. Versteckte Dateien und Pfadbestandteile, symbolische Links, Hardlinks und Spezialdateien werden nicht angeboten. Verzeichniszugriffe öffnen jede Pfadkomponente ohne Symlink-Folgen; eine nachträgliche Pfadersetzung lenkt eine bereits geöffnete Übertragung nicht um.

Downloads benötigen die bestehende Anmeldung. Dies ist keine öffentliche Dateifreigabe und keine Benutzer-/Gruppenrechteverwaltung. Alle angemeldeten Server-Manager-Benutzer können die angebotenen Dateien lesen. Der Dienst liest mit seinen eigenen Dateirechten. Hauptordner daher gezielt auf den bereitzustellenden Datenbestand beschränken.

Während laufender Dateiübertragungen melden sich Downloads als Schlafblocker und verhindern den Neustart über die Pfadeinstellungen. Änderungen des Hauptordners folgen dem bestehenden Vormerkungs-/Neustartablauf.
