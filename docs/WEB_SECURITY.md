# Web & Sicherheit

Unter Server → Web & Sicherheit stehen Apache, Zertifikate und Fail2ban. Statusabfragen verändern keine Konfiguration. Installer & Einrichtung enthält getrennte Installer für Apache, Certbot und Fail2ban. Jeder Installer ist als eigenständige Python-Datei für Debian/Ubuntu herunterladbar:

    python3 installer-apache.py --check
    sudo python3 installer-apache.py --install

Den tatsächlichen Downloadnamen verwenden. Ohne --install wird ausschließlich geprüft. Bestehende Pakete werden nicht gezielt aktualisiert; fehlende Pakete können zusätzliche Abhängigkeiten installieren. Dienste werden nach Konfigurationsprüfung aktiviert und gestartet. Belegte Webports verhindern die Erstinstallation von Apache.

Änderungen benötigen eine Vorschau und Bestätigung. Aufträge laufen unter systemd, protokollieren ihren Status und blockieren automatischen Schlaf. Geänderte Ausgangskonfigurationen erfordern eine neue Vorschau. Konfigurationssicherungen liegen im jeweiligen Auftragsordner unter dem konfigurierten State-Verzeichnis/web-security/jobs.

Zertifikate werden anhand öffentlicher Zertifikatsdateien geprüft. HTTPS-Ziele werden explizit hinterlegt: Domain, Port, optional direkte Verbindungs-IP und lokaler Zertifikatsname. Die Prüfung verwendet Domainname/SNI und prüft die Zertifikatskette. Ein Fingerprint-Vergleich zeigt, ob der Dienst das lokale Zertifikat tatsächlich ausliefert. DNS, NAT und Firewall können externe Prüfungen vom Server aus beeinflussen.

Die Erstinstallation eines Zertifikats benötigt eine bestehende Apache-Website, öffentlich passendes DNS und Erreichbarkeit auf Port 80. Bestehende Zertifikate verwenden ihre gespeicherte Certbot-Erneuerungskonfiguration. Ein Erneuerungstest kann vorhandene Pre-/Post-Hooks ausführen. Der Status eines aktiven Timers allein beweist keine erfolgreiche Erneuerung.

Der optionale Server-Manager-Login-Schutz protokolliert ausschließlich die direkte Verbindungs-IP bei Fehlversuchen. Die eigene Fail2ban-Regel sperrt nach fünf Versuchen in zehn Minuten für 15 Minuten den konfigurierten Server-Manager-Port. Loopback ist ausgenommen. Hinter einem Reverseproxy muss die Regel an dessen Zugriffspfad angepasst werden; beliebige Forwarded-Header werden nicht vertraut. Vorhandene Jails bleiben bestehen. Die Regel wird erst nach ausdrücklicher Einrichtung aktiviert.

## Einzelne Zertifikate verwalten

In der Zertifikatsübersicht führt „Zertifikat für Domain installieren“ direkt zur Einrichtung. Ein Domainname ergibt ein eigenes Zertifikat; optional eingegebene weitere Namen teilen dieses Zertifikat.

„Löschen …“ prüft zunächst Verweise in tatsächlich eingebundenen Apache-Dateien, nginx, Postfix, Dovecot, HAProxy, lokalen systemd-Units, Certbot-Erneuerungshooks und gespeicherten HTTPS-Zielen. Gefundene Verwendungen sperren die Löschung. Externe Kopien und beliebige Anwendungen können nicht vollständig automatisch erkannt werden.

Nach Eingabe des vollständigen Zertifikatsnamens folgt eine Vorschau. Erst deren Bestätigung startet `certbot delete --non-interactive --cert-name NAME`. Direkt davor werden Verwendung und Ausgangsstand erneut geprüft. Gelöscht wird die ganze Certbot-Zertifikatsgruppe einschließlich privatem Schlüssel, lokalen Versionen und Erneuerungskonfiguration; bei mehreren Domains sind alle betroffen. DNS, Website-Dateien und externe Kopien bleiben erhalten. Die Aktion ist kein Widerruf und legt keine zusätzliche Kopie des privaten Schlüssels an.

Referenz: https://eff-certbot.readthedocs.io/en/stable/using.html#safely-deleting-certificates

## Apache-Dateien bearbeiten

Die Verwendungsanzeige verlinkt reguläre `sites-available/*.conf` in einen angemeldeten Admin-Editor. „Aktiv/Deaktiviert“ steuert den zugehörigen Link in `sites-enabled`. Die Vorschau zeigt den Textunterschied und den Statuswechsel. Änderungen seit dem Öffnen oder der Vorschau werden zurückgewiesen.

Vor Übernahme werden Inhalt, Rechte und Linkzustand im geschützten Auftragsordner gesichert. Ein fehlgeschlagener Konfigurationstest stellt Original und Aktivierung wieder her. Bei fehlgeschlagenem Reload wird zusätzlich die alte Konfiguration erneut geladen. Deaktivieren betrifft alle VirtualHosts der Datei. Auch inaktive bearbeitete Dateien werden vorübergehend für einen Konfigurationstest eingebunden, ohne sie live zu laden.

Die Zertifikatsprüfung nutzt Apaches `DUMP_INCLUDES`: nicht eingebundene Websites und Sicherungen erscheinen separat und blockieren nicht. Explizit eingebundene Sicherungen bleiben Blocker. Vor Wiederaktivierung einer alten Datei müssen darin enthaltene Zertifikatsverweise noch gültig sein.
