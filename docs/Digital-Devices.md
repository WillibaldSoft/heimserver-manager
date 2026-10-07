# Digital Devices · DVB-Treiber

Unter Apps und Apps verwalten führt die Karte zur Digital-Devices-Verwaltung.
Sie zeigt PCI-Karten samt PCI-Revision, geladenen und installierten ddbridge-Treiber,
Kernel-Header, Secure Boot und registrierte DKMS-Stände je Kernel. PCI-Revision
ist keine Firmwareversion; Firmware wird weder geflasht noch automatisch geändert.

Die explizite Versionsprüfung fragt das offizielle GitHub-Release-API ab.
Fehler gelten als unbekannter Stand, nicht als „aktuell“. Neue stabile Releases
werden angezeigt. Automatisch installierbar ist zunächst ausschließlich 0.9.41,
mit festem HTTPS-Download und fest hinterlegter SHA256-Prüfsumme.
Spätere Treiber benötigen eine neue Freigabe im Manager, nicht nur einen neuen Tag.

Installation und Update unterstützen Debian 13 auf erkannter Digital-Devices-PCI-
Hardware. Nach Vorschau und Bestätigung werden DKMS, Build-Werkzeuge und die Header
für den laufenden Kernel installiert. Zwei Modi sind auswählbar: Hersteller-dvb-core
oder Kernel-dvb-core. Letzterer kann Herstellerfunktionen einschränken. Der
Hersteller-dvb-core kann andere DVB-Geräte beeinflussen.

Eine bestehende Zielversion wird nicht überschrieben. Die Reparatur baut aus den
vorhandenen registrierten Quellen neu und behält deren DKMS-Konfiguration.
Ältere registrierte 0.9.x-Stände bis 0.9.40 können auf den geprüften Stand aktualisiert
werden; neuere, unbekannte oder manuell installierte Modulbestände sperren die
automatische Übernahme. Quellordner und ältere DKMS-Registrierungen bleiben erhalten.
Keine automatische Deinstallation. Für bisherige Einstellungen wie fmode bleibt
die vorhandene modprobe-Konfiguration maßgeblich.

Aktionen laufen als persistente Systemd-Aufträge über die vorhandene APT-Verwaltung
mit Protokoll und Schlafblocker. Kernel und Bestand werden vor Ausführung erneut
geprüft. Bei Fehlern können Pakete, Quellen oder DKMS-Dateien bereits geändert sein;
kein vollständiges automatisches Rollback. Inventar und vorhandene dkms.conf werden
vorher unter dem Manager-Datenverzeichnis dddvb/before-* gesichert.

Geladene Treiber werden nicht entladen, Tvheadend wird nicht neu gestartet und der
Server nicht automatisch neu gebootet. Nach Installation ist ein geplanter Neustart
zur Aktivierung vorgesehen. Währenddessen keine neuen manuellen Treiberwechsel
starten. Secure Boot muss entweder deaktiviert sein oder einen von mokutil als
eingeschrieben bestätigten DKMS-Schlüssel besitzen. Ein unklarer Zustand blockiert.
DKMS baut bei künftigen Kernelupdates erneut, soweit Treiber und Kernel kompatibel
sind; Kompatibilität mit beliebigen künftigen Kerneln ist nicht zugesichert.

Der Manager liefert den Treiber nicht in seiner DEB mit. Die heruntergeladenen
Herstellerquellen behalten ihre eigene Lizenz samt Lizenzdateien.

Quellen:
- https://github.com/DigitalDevices/dddvb/releases/tag/0.9.41
- https://support.digital-devices.eu/index.php?article=187
