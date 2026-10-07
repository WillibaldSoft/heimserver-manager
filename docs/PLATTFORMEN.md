# Getrennte Plattformpakete – Debian regulär, Mint experimentell

Die experimentelle Debian-Phase ist nach bestätigtem Updatebetrieb beendet.
Mint bleibt experimentell. v0.12-47 bleibt unveränderter Sicherungsstand. Die produktive Debian-Installation wird durch die
Entwicklung und das Bauen der Testpakete nicht verändert. Keine automatische
Zusammenführung oder Installation. Ein Git-Tag ersetzt keine Datensicherung.

| Paketprofil | Akzeptiertes Betriebssystem | Python-Abhängigkeit |
|---|---|---|
| debian13 | ID=debian, VERSION_ID=13 | >= 3.13 |
| mint22 | ID=linuxmint, VERSION_ID=22 oder 22.x, UBUNTU_CODENAME=noble | >= 3.12 |

ID_LIKE reicht ausdrücklich nicht. LMDE, Ubuntu selbst, Debian 12 sowie
unbekannte Versionen werden blockiert. LMDE benötigt später ein eigenes Profil.
Beide Pakete heißen intern server-manager und tragen dieselbe Entwicklungsversion;
Dateinamen und Releaseverzeichnisse enthalten das Profil. Das Control-Feld
X-Heimserver-Target und package-target.json enthalten die Zielplattform.

## Installationsprüfung

`sh install_deb.sh --check DATEI.deb` prüft ohne Installation die Zielplattform.
Der reguläre Launcher prüft vor APT und vor Zusatzinstallationen. Direktes
`dpkg -i`/`apt install` wird zusätzlich über preinst abgesichert; config und
postinst prüfen ebenfalls. Eine Ablehnung des preinst geschieht vor dem Entpacken
des Managers. APT kann bei direktem Aufruf vorher Abhängigkeiten bearbeiten;
für eine Prüfung vor jeglicher Paketaktion deshalb den Launcher verwenden.

Die neue Web-Updateprüfung lehnt falsche oder fehlende Plattformangaben beim
Upload und vor der Ausführung ab. Ein älterer Manager hat diesen Vorabcheck noch
nicht; das neue DEB prüft seine Plattform dennoch selbst. Alte, bereits verteilte
DEBs werden nicht nachträglich verändert und besitzen diese Sperre nicht.
Root kann Pakete manipulieren; die Sperre schützt vor Verwechslungen und ist
keine Sicherheitsgrenze gegenüber dem Administrator.

## Mint-Testumfang und Grenzen

Der Grundbau unterstützt Python 3.12. Das ist noch keine vollständige Mint-Freigabe.
Debian-spezifische NVIDIA-/dddvb-Installer bleiben auf Mint gesperrt. Treiber dort
über die Mint-Systemverwaltung verwalten, bis eigene Verfahren getestet sind.
Optionale App-Installer müssen einzeln validiert werden. Die Oberfläche zeigt
den experimentellen Zustand. Automatische Schlaf- und RTC-Hintergrundaktionen
sind unter Mint deaktiviert, einschließlich übernommener aktivierter Einstellungen.
Manuelle Energieaktionen sind weiterhin bewusst auslösbare Verwaltungsfunktionen.
Debian behält seinen bisherigen Ablauf.

ACL-Unterstützung hängt vom Ziel-Dateisystem und der Einbindung ab. Mint wird
nicht pauschal als ACL-unfähig behandelt. Vor Freigabetests die Werkzeuge getfacl
und setfacl sowie Lese-/Schreibrechte, Vererbung, Benutzerzuordnung und Samba-Zugriff
auf einem separaten Testverzeichnis auf dem vorgesehenen Laufwerk prüfen.
Bestehende Freigaben niemals pauschal durch eine Testkonfiguration ersetzen.

## Bau und Freigabe

    python3 tools/build_release.py --target debian13 --output-root dist
    python3 tools/build_release.py --target mint22 --output-root dist

Erforderlich vor produktiver Freigabe: echte Debian-13- und Mint-22.x-VMs mit
Neuinstallation, Gegenplattform-Ablehnung, Neustart, Anmeldung, Update und
Deinstallation; danach Samba/ACL-, App- und Desktoptests. DKMS und Secure Boot
zusätzlich auf geeigneter Hardware prüfen. Gemockte Systemkennungen und
extrahierte Paket-Skripte ersetzen keine vollständigen VM-Installationstests.

## KVM ab platform2
KVM-Paketprüfung unterstützt Debian 13 und Mint 22.x/Noble. NAT ist die Vorgabe;
LAN-Karte über das Dropdown wählen, wenn eine LAN-Bridge gewünscht ist.
Die aktive LAN-Übernahme benötigt nach wie vor eine bestätigte Vorschau und
geeignete NetworkManager-/ifupdown-Konfiguration. Paketauflösung wurde auf
Mint 22.3 erfolgreich simuliert. Das ersetzt keinen realen Bridge-/VM-Test.
