# Apps verwalten

Die App-Übersicht enthält ausschließlich erkannte, vollständig installierte und eingeblendete Apps. Ein gestoppter Dienst bleibt installiert. Nicht prüfbare oder teilweise vorhandene Installationen bleiben unter „Apps verwalten“ sichtbar.

Installation, Deinstallation und Sichtbarkeit werden unter `/apps/manage` verwaltet. Der bisherige Katalog-Link leitet dorthin weiter. App-Karten enthalten keinen Installer mehr. Neu registrierte Container-Apps werden erst nach erfolgreicher Installation eingeblendet.

„Nur ausblenden“ ändert ausschließlich die Anzeige. „Deinstallieren“ zeigt zunächst einen aktuellen Plan und verlangt eine Bestätigung. Der Hintergrundauftrag prüft den Plan erneut. Container eines eindeutig zugeordneten Compose-Projekts werden gemeinsam entfernt, einschließlich Datenbank-Containern; Volumes, Bind-Mounts, Images und Compose-Dateien bleiben erhalten. Flüchtige Inhalte der Container werden entfernt. Die Containerkonfiguration wird geschützt für „Wieder installieren“ aufbewahrt.

ComfyUI und OSCam: Der bekannte Dienst wird beendet/deaktiviert; Programm und Dienstdatei werden auf demselben Dateisystem aufbewahrt. Tvheadend: Paketentfernung ohne Purge oder Autoremove, nur wenn APT keine zusätzlichen Pakete entfernen würde. Eine Wiederinstallation verwendet die aufbewahrten Daten.

Der laufende Server Manager, gemeinsame Mount-Werkzeuge und die vorhandene native Nextcloud haben keine automatische Deinstallation. Die Oberfläche nennt die Gründe; Ausblenden bleibt möglich. Nextcloud als eigenständiger Docker-Stack wird unterstützt.

Die geschützten Wiederherstellungsdaten liegen unter `/var/lib/server-manager/app-lifecycle`. Unvollständige Deinstallationen werden nicht als erfolgreich behandelt und sperren die automatische Neuinstallation bis zur Prüfung. App-Aufträge nutzen den vorhandenen serialisierten Installer-Worker und Schlafblocker. Keine produktive App wird beim Ausrollen dieser UI-Änderung installiert oder entfernt.
