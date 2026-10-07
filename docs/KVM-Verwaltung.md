# KVM Verwaltung

Natives Manager-Modul unter `/kvm`, auf Grundlage von `kvm_vm_manager_V8.sh`.

## Funktionen

- Vorhandene libvirt-System-VMs mit Status, CPU, RAM, Firmware, Disks, Netzwerk und Autostart.
- Suche, Detailansicht, SSH-Konsolenbefehl, XML-Download.
- Start, reguläres Herunterfahren, Neustart, Pause/Fortsetzen und separat bestätigtes hartes Ausschalten.
- ISO-Installation einschließlich Rescuezilla-ISO; Vorlagen für Linux Desktop/Server, Windows 11, HAOS, Legacy-Windows und DOS/Windows 98.
- Import von qcow2/raw/img/VMDK als eigenständige qcow2-Kopie. Keine Änderung der Quelldatei.
- Offline-Klon mit neuer UUID/MAC, Offline-Disk-Export nach qcow2/raw.
- Offline-CPU/RAM-Anpassung, ISO-Auswerfen, Autostart; Konfigurationssicherung vor Änderungen.
- Entfernen ausschließlich der VM-Definition mit exakter Namensbestätigung. Disks/NVRAM/TPM werden erhalten.
- Persistente, serialisierte Hintergrundaufträge mit Protokoll in `kvm_jobs` der bestehenden SQLite-DB.
- Zentraler Schlafschutz für aktive VMs, Aufträge und unbekannten KVM-Zustand.

## Grenzen gegenüber V8

Das Shell-Skript wird nicht als Webprozess ausgeführt. Es installiert keine Pakete automatisch und seine Gast-Reparatur-/Benutzeränderungen werden nicht übernommen. Gast-Hostname, feste IP, machine-id und Zugangsdaten eines Klons müssen vor parallelem Betrieb angepasst werden. TPM-/Passthrough-/Dateisystem-Sharing-Klone und komplexe CPU-/NUMA-Konfigurationen werden zur manuellen Bearbeitung abgewiesen. Snapshots werden angezeigt; Änderungen über virt-manager. OVA und VMX vorher separat aufbereiten; VMDK-Import übernimmt nur die ausgewählte Disk. Ein Disk-Export ist kein vollständiges VM-Backup.

Alle Neuinstallationen starten ausgeschaltet; Autostart ist standardmäßig aus. Virtuelle Disk-Kapazität plus Reserve wird vorab gegen freien Speicher geprüft. ISO wird ins neue VM-Verzeichnis kopiert, damit Dateirechte eines Medien-Shares den Start nicht verhindern.

## Betrieb

`qemu:///system`; Daten unter `/VM`; ISO-Vorschläge aus `/VM/iso` und `/srv/iso`. CPU/RAM-Änderungen sichern XML unter `STATE_DIR/kvm-xml-backups` mit Modus 0600. Definitionen ohne Passwortfelder können per UI heruntergeladen werden.

Neustarts unterbrechen laufende Aufträge. Der nächste Start markiert sie als unterbrochen; es gibt keinen automatischen Wiederholungsversuch und keine automatische Löschung von Teilergebnissen. Vor erneutem Auftrag VM-Liste/Zielordner prüfen. Gleichzeitige Änderungen über externe Werkzeuge während eines KVM-Auftrags vermeiden.

Voraussetzungen: python3-libvirt, libvirt-clients, libvirt-daemon-system, qemu-utils, virtinst, ovmf, ggf. swtpm/swtpm-tools. Browserzugriff übernimmt die bestehende Zugangskontrolle des Server Managers. Alle mutierenden Routen verwenden POST und eigene Session-CSRF-Tokens; keine Shell-Interpolation. Host und Benutzer der Konsolenhilfe werden in den Einstellungen konfiguriert.

## Validierung

`python3 -m unittest discover -s tests -p 'test_kvm_manager.py' -v`

Die Tests verwenden simulierte Domains und temporäre Datenbanken; Produktiv-VMs werden weder gestartet noch verändert. Zusätzlich: libvirt-Inventar, XML-Erzeugung mit lokalem virt-install, HTML-Routen und Blocker-Integration prüfen.

Referenzen: https://libvirt.org/python.html · https://www.libvirt.org/manpages/virsh.html · https://virt-manager.org/
