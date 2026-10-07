# VM-Backup und Wiederherstellung

In KVM → VM-Details → **Backup erstellen** eine regulär heruntergefahrene VM sichern.
Während der gesamten Sicherung ausgeschaltet lassen, auch in externen Verwaltungsprogrammen.
KVM-Aufträge und Uploads werden serialisiert; laufende Übertragungen und Aufträge blockieren den Server-Schlaf.
Unter **Backup & Wiederherstellung** bzw. im abgeschlossenen Auftrag das Paket herunterladen.

Speicherziel ist `system_backup_root/kvm`; der Basisordner ist unter Einstellungen → Server & Modulpfade änderbar.
Ein Paket enthält die ursprüngliche Domain-XML, alle lokalen Disk-Images als komprimierte RAW-Daten,
vorhandenen RAW-UEFI-NVRAM und den unverschlüsselten emulierten TPM-2.0-Zustand.
SHA-256-Prüfsummen prüfen die Integrität, nicht die Vertrauenswürdigkeit der Herkunft.
Backups enthalten private Gastdaten und müssen entsprechend geschützt aufbewahrt werden.

Nicht enthalten: RAM-/Managed-Save-Zustand, ISO-Medien, Snapshot-Historie, Host-Software und Netzwerkkonfiguration.
Gesicherte Festplatten enthalten das installierte Gastsystem mit Programmen, Einstellungen und Daten.
Host-Geräte/USB-Passthrough, Host-Dateisystemfreigaben, Netzwerk-/Blockdisks, verkettete oder verschlüsselte Images,
verschlüsselte/physische TPMs und unbekannte Konfigurationselemente werden explizit abgewiesen.
Damit werden solche VMs nicht irreführend als vollständig gesichert gemeldet.

## Wiederherstellen

1. Auf dem Zielserver den KVM-Installer ausführen (einschließlich qemu-utils, UEFI, swtpm/swtpm-tools).
2. Im Installer **VM-Backup hochladen / wiederherstellen** wählen oder KVM → Backup & Wiederherstellung öffnen.
3. Paket und freien VM-Namen angeben; Netzwerk übernehmen oder alle Adapter auf eine vorhandene Bridge/ein libvirt-Netz umstellen.
4. Upload bis zum Ende im Browser geöffnet lassen. Danach Archivprüfung und Wiederherstellung unter Aufträge verfolgen.
5. Neue ausgeschaltete VM prüfen und bewusst starten.

Vorhandene VMs/Ordner werden nicht überschrieben. Wiederherstellung erstellt eine neue UUID und neue MAC-Adressen,
deaktiviert Autostart, leert CD-Laufwerke und bindet die Grafikkonsole nur an localhost.
Die übrige unterstützte virtuelle Hardware bleibt erhalten. Lokale Emulatorpfade und Sicherheitslabels werden
von libvirt neu ermittelt. Firmwaredateien müssen auf dem Zielhost vorhanden sein; keine automatische Ersetzung
unbekannter Machine-/CPU-/Firmware-Versionen. Eine neue VM-Identität kann eine erneute Windows-Aktivierung oder
BitLocker-Wiederherstellung erfordern. Gast-IP, Hostname, Konten und machine-id bleiben im Dateisystem unverändert.
Original und Wiederherstellung nicht ungeprüft parallel im gleichen Netzwerk starten.

Upload in 4-MiB-Blöcken, höchstens 1 TiB komprimiert; ausgepackte Gesamtgröße höchstens 16 TiB.
Mindestens 2 GiB Speicherreserve; Sicherung prüft konservativ zweimal die virtuelle Disk-Gesamtgröße,
Wiederherstellung die ausgepackte Gesamtgröße. RAW-Dateien werden sparse gespeichert.
Der Upload verfällt nach 30 Minuten ohne Aktivität; Neustart verwirft angefangene Uploads.
Bei normalem Fehler werden temporäre Dateien entfernt. Nach Prozessabbruch können `.build-*`,
`.restore-*` und `.partial` übrig bleiben: Auftragsprotokoll und Verzeichnis vor manuellem Entfernen prüfen.
Erfolgreiche Server-Backups werden nicht automatisch gelöscht oder rotiert.

## Technische Schutzmaßnahmen

Nur normale USTAR/GNU-Dateieinträge mit exakt erwarteten Namen, Größen und Hashes werden verarbeitet.
Keine Links, Traversal, PAX-Erweiterungen oder automatische Archivextraktion. Hochgeladene Disks werden immer
explizit als RAW behandelt; fremde qcow2-Header können keine Host-Dateien als Backing-Datei öffnen.
XML verwendet eine Positivliste; Pfade werden ersetzt, Firmwarepfade auf installierte System-Firmware begrenzt,
libvirt prüft die endgültige Definition gegen sein Schema. VM-Start erfolgt nie automatisch.
