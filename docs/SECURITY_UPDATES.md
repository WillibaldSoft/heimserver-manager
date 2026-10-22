# Automatische Sicherheitsupdates
Unter Anwendungen → Systempakete → Automatische Sicherheitsupdates können Administratoren die Voraussetzungen `unattended-upgrades` und `needrestart` installieren und die Automatik aktivieren oder deaktivieren. Neue Installationen sind standardmäßig inaktiv.

Der systemd-Timer prüft täglich alle zwei Stunden (00, 02, …, 22 Uhr, lokale Serverzeit), mit bis zu fünf Minuten Zufallsverzögerung. Kein Aufwecken. Verpasste Termine werden beim nächsten Start nachgeholt. Sicherungen, Installationen und andere APT-Aufträge verschieben einen Lauf bis zum nächsten Termin. Während eines APT-Auftrags besteht ein Schlafblocker. Deaktivieren unterbricht keine laufende Paketinstallation.

Es werden nur verfügbare Updates aus offiziellen Debian- bzw. Ubuntu-Sicherheitsquellen berücksichtigt; Mint nutzt die Ubuntu-Basis. Dies ist kein vollständiger CVE-Scanner und keine Einstufung ausschließlich kritischer Lücken. Unbekannte Distributionen werden abgewiesen. Container und eigenständig installierte Apps sind nicht enthalten. Paket-Holds und lokale Sperrlisten gelten weiterhin. Keine automatische Paketbereinigung, kein Dist-Upgrade und kein Server-Neustart.

needrestart startet betroffene Dienste automatisch und prüft anschließend erneut im Batch-Modus. Lokale Ausnahmen gelten weiter. Offene Dienste, Sicherheitsupdates und Kernel-/Microcode-Neustarts bleiben sichtbar; ein erfolgreicher Paketlauf garantiert nicht, dass alle Schwachstellen geschlossen sind. Dienstneustarts können bestehende Verbindungen unterbrechen. Andere vorhandene APT-Timer bleiben unverändert.

ntfy verwendet die vorhandene aktivierte Konfiguration unter Alarme. Meldungen betreffen installierte Updates, Fehler und anstehende Neustarts. Unveränderte Warnungen werden unterdrückt; fehlgeschlagener Versand wird beim nächsten Lauf erneut versucht. Ohne Detailfreigabe werden nur Anzahlen übermittelt, keine Paket- oder Dienstnamen. Zugangsdaten und Rohprotokolle werden nicht gesendet. Die Sicherheitsseite zeigt fehlgeschlagenen oder deaktivierten Versand an.

Quellen: https://manpages.debian.org/testing/needrestart/needrestart.1.en.html und https://sources.debian.org/src/unattended-upgrades/2.12/README.md

Diagnose ohne Änderungen: `sudo python3 /opt/server-manager/tools/security/check_run.py`. Die Abschlussprüfung wird anhand des Statusmarkers bzw. der gespeicherten Prüfergebnisse älterer Läufe erkannt; eine fehlende Befehlszeile bedeutet nicht mehr fälschlich, dass keine Prüfung lief.
