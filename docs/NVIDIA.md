# NVIDIA-Treiber unter Apps

Die eigene NVIDIA-Karte zeigt PCI-Grafikkarten, die über nvidia-smi ermittelten
GPU-Namen, geladene und auf Datenträger installierte Modulversionen, DKMS je
Kernel, Kernel-Header und Secure Boot. Installierte Paketversionen stehen den
Kandidaten der konfigurierten APT-Quellen gegenüber. Das ist kein Vergleich mit
der neuesten NVIDIA-Webseitenversion. Paketlisten lassen sich ausdrücklich
über einen protokollierten Hintergrundauftrag aktualisieren.

Automatische Aktionen sind für Debian 13 vorgesehen:
- Hardwareprüfung: nvidia-detect installieren oder aktualisieren. Installiert
  allein keinen Grafiktreiber. Danach die Verwaltungsseite erneut öffnen.
- Neuinstallation bei eindeutiger nvidia-detect-Empfehlung nvidia-driver.
- Vorhandene nvidia-driver/nvidia-kernel-dkms innerhalb derselben Paketfamilie
  aktualisieren oder inklusive passender Kernel-Header neu installieren.

Jede Paketinstallation benötigt eine einmalige, zehn Minuten gültige Vorschau
und Bestätigung. Die Vorschau zeigt konkrete Versionen und simulierte Änderungen.
Nach dem Aktualisieren der Paketlisten wird der Plan erneut verglichen. Hat sich
etwas geändert, muss eine neue Vorschau erstellt werden. Entfernungen, Downgrades,
fremde Treiberfamilien und erkannte .run-Installationen werden nicht automatisch
übernommen. Paketquellen werden nicht hinzugefügt oder umgeschrieben. Fehlende
Kandidaten müssen über die System-Paketquellen geklärt werden; NVIDIA-Pakete
benötigen die passenden Debian-Komponenten einschließlich non-free.

Laufende GPU-Rechenprozesse sperren Treiberänderungen. Grafische Sitzungen und
andere GPU-Nutzer vor Änderungen beenden. Eine Nutzung, die erst während der
Installation startet, kann nicht ausgeschlossen werden. Bei aktiviertem Secure
Boot muss der DKMS-Schlüssel bereits eingeschrieben sein; unbekannter Status
sperrt die Installation. Der Manager verändert keine Firmware-/MOK-Einstellungen.

Der Manager entlädt keine Treiber, startet keinen Displayserver neu und führt
keinen Systemneustart aus. Debian-Paketskripte können Dienste neu starten;
Updates von Benutzerbibliotheken können laufende Anwendungen beeinflussen.
Aktivierung nach Treiberänderungen durch separat geplanten Neustart. Bei Fehlern
sind Teiländerungen möglich, keine automatische vollständige Rücknahme. Ein
Bestandsbericht wird vor der Aktion im Manager-Zustandsverzeichnis abgelegt.
Alle Aktionen verwenden bestehende APT-Aufträge, Protokolle und Schlafblocker.

Die Treiber selbst werden nicht mitgeliefert. NVIDIA-Komponenten behalten ihre
eigenen, teils proprietären Lizenzbedingungen. GPL-3.0-or-later betrifft den
Manager, nicht die nachinstallierten Treiber.

Referenzen:
- https://wiki.debian.org/NvidiaGraphicsDrivers
- https://packages.debian.org/stable/nvidia-detect
