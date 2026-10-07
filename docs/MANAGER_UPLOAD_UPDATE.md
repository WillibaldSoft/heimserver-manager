# Datei-Upload und Manager-Paketupdate

Unter Daten → Downloads lädt die Dateiauswahl eine einzelne Datei in den in
Einstellungen → Server & Modulpfade festgelegten Download-Hauptordner. Ein gerade
geöffneter Unterordner ändert dieses Ziel nicht. Maximal 512 MiB pro Datei;
vorhandene Namen werden nicht überschrieben. Versteckte Namen, Pfadbestandteile,
Links und Systembereiche sind nicht als Upload-Ziele erlaubt. Die fertige Datei
wird atomar veröffentlicht, erhält den Besitzer/die Gruppe des Hauptordners und
Modus 0640. Ein Abbruch vor Veröffentlichung hinterlässt keine sichtbare Teildatei.

Unter Einstellungen → Manager aktualisieren kann eine DEB (maximal 256 MiB)
hochgeladen werden. Vor der Bestätigung werden Paketname server-manager,
Architektur, Version und SHA256 angezeigt. Ältere Versionen werden abgewiesen;
dieselbe Version kann zur erneuten Installation verwendet werden. Diese Prüfungen
sind keine Signaturprüfung: nur eigene oder vertrauenswürdige Pakete installieren.
DEB-Maintainerskripte werden mit root-Rechten ausgeführt.

Der bestätigte Auftrag läuft in einer eigenen systemd-Unit über die vorhandene
App-Auftragsverwaltung und bleibt bei einem Neustart des Webdienstes aktiv.
Laufende App-, Backup-, APT-, Scanner- und Web-Installationsaufträge blockieren den
Start. APT darf keine Pakete entfernen und behält vorhandene Conffiles. Der
Paketinstaller übernimmt die vorhandene Portkonfiguration.

Vorher werden Programm und Konfiguration als program-config.tar.gz und die
Manager-SQLite-Datenbank mittels SQLite-Backup gesichert. Ablage:
SERVER_MANAGER_STATE/manager-updates/<Upload-ID>/before-update.
Die Sicherung umfasst keine externen App-Daten. Der Auftrag behält sein Protokoll
unter SERVER_MANAGER_STATE/app-installers/jobs/<Auftrag-ID>/install.log.

Nach der Installation werden Paketstatus/Zielversion, Dienststatus und die lokale
Health-URL geprüft. Bei Fehlern bleibt der Auftrag fehlgeschlagen; Paketänderungen
können teilweise erfolgt sein. Es gibt keine automatische Rücknahme. Vor einer
manuellen Wiederherstellung den Dienst stoppen und Ursache/Protokoll prüfen.
Benutzte Pakete und Sicherungen bleiben erhalten; unbenutzte Upload-Vorschauen
werden beim nächsten Upload nach 24 Stunden entfernt. Vorschauen gelten eine
Stunde, gestartete Pakete können nicht ein zweites Mal abgesendet werden.

Die Integrationstests simulieren Paketinstallation und Neustart. Ein echtes
Upgrade auf einer separaten Debian-Testmaschine bleibt der passende Abnahmetest
für eine neue DEB-Version.
