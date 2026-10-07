POWER & RECOVERY API 2.2 – INSTALLATION UND AKTUALISIERUNG

Im Manager: Anwendungen → Apps verwalten → Power & Recovery API.
Auf dem Rechner öffnen, der dauerhaft läuft; nicht auf dem schlafenden Zielserver.
Für einen anderen Rechner dieses ZIP entpacken und als root ausführen:
  sudo python3 /vollstaendiger/Pfad/install.py
Ohne sudo-Mitgliedschaft zuerst su - verwenden. Debian/Mint mit systemd und APT.

Bestandserkennung
Bekannt: alte ipmi-power-api.service mit /opt/ipmi-power-api.py (2.1-stable)
und Manager-Installation 1.0/2.2. Importiert ausschließlich literale Werte per
AST; alter Python-Code wird niemals ausgeführt. Unbekannter Bestand bleibt
unangetastet. Installer erneut ausführen, um Einstellungen/Version zu ändern.
Erkannte Adressen, BMC-Benutzer, Wartezeiten und Kennwort werden übernommen.
Das bisherige Kennwort bleibt bei leerer Eingabe erhalten; es wird nicht angezeigt.
Konkrete lokale LAN-IP und erlaubte Client-IP/Netze ausdrücklich wählen.
Alte Bindung an 0.0.0.0 muss ersetzt werden. Vorhandene URLs auf dieselbe LAN-IP
und denselben Port ausrichten. IP-Freigaben sind keine Benutzeranmeldung.
Nur vertrauenswürdiges LAN/VPN; keine öffentliche Portweiterleitung.

Änderungen gegenüber 2.1-stable
- systemd-Dienst ohne root (DynamicUser), Passwort als geschützte Credential-Datei,
  nicht mehr im Python-Code oder in Prozessargumenten.
- Asynchrone GET/POST /recover und /poweron: 202 bedeutet angenommen, nicht fertig.
  /status oder /summary zeigen recover_active, phase, last_action und last_error.
  Parallel laufender Auftrag ergibt 409. /version und /health bleiben lesend.
- /soft, /reset und /cycle als direkte Endpunkte entfallen.
- Ausschalten/Reset wird bei der Installation niemals zum Zielserver gesendet.
- Bei ausgeschaltetem Ziel: Power on. Eingeschaltet und pingbar: keine Schaltaktion.
  Eingeschaltet ohne Ping: optional Soft. Nach Wartezeit optional ein Reset,
  nur wenn der Zielserver dann weiterhin eingeschaltet und nicht pingbar ist.
- Soft/Reset sind bei Neuinstallation aus. Bei Migration werden die bisherigen
  aktiven Optionen übernommen und zur ausdrücklichen Bestätigung angezeigt.
  Soft kann herunterfahren, Reset kann Datenverlust verursachen. Fehlender Ping
  unterscheidet Standby nicht von Firewall, Netzwerkstörung oder Systemstillstand.
- Ping bestätigt nur den Rechner, nicht Nextcloud oder andere Anwendungen.

Update und Rücksicherung
Laufende Recovery-Aufträge blockieren Änderungen. Während der Migration keine
neuen Recovery-Aufrufe starten. Installiert werden python3-flask, python3-waitress,
ipmitool und iputils-ping. Keine OpenIPMI-Hardware auf dem Dauerläufer nötig.
Geschützte Rücksicherung unter /var/lib/server-manager/power-api-backups.
Bei Startfehlern werden die vorherigen Dateien wiederhergestellt. Pakete bleiben.
Bei Updates bleiben Autostart und laufender/gestoppter Zustand erhalten.
Die alte Quelldatei mit Passwort bleibt ausschließlich in der geschützten Sicherung.

Programm: /opt/server-manager-power-api/power_api.py
Konfiguration: /etc/server-manager-power-api/config.json
Passwort: /etc/server-manager-power-api/ipmi-password
Dienst: ipmi-power-api.service
Status: http://RECOVERY-SERVER:8182/status
Recovery: http://RECOVERY-SERVER:8182/recover
Recovery-URL im Manager unter Einstellungen → Server & Modulpfade → Netzwerk
hinterlegen. Neue Client-JSON-Profile übernehmen die aktive Einstellung.
Home-Assistant-YAML bleibt unter Client-Agenten verfügbar. Keine Router-/DNS-
Änderung und kein Nextcloud-Wake-Proxy Bestandteil dieses Installers.
