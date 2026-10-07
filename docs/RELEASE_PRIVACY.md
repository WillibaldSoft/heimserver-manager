# Veröffentlichung und Datenschutz – Version 0.12-64

Die Veröffentlichung wird aus einer ausdrücklichen Dateiliste gebaut, nicht aus
allen Dateien des laufenden Servers. DEB, Quellarchiv und Komplett-ZIP enthalten
keine lokale Git-Historie, Konfiguration, Datenbank, Sicherung oder Anmeldeprofile.
Die mitgelieferte Datei packaging/debian/server-manager.env ist eine neutrale
Paketvorlage; sie ist keine Kopie einer lokalen .env-Datei.

Vor Freigabe werden Paketinhalt und Quellarchiv auf private Schlüssel,
Tokenformate, Zugangsdaten in URLs und bekannte private Hostwerte geprüft.
Die Prüfung gibt keine gefundenen Geheimnisse aus. Automatische Treffer werden
inhaltlich bewertet: öffentliche DynDNS-Anbieter-URLs, RFC1918-Netzbereiche und
Loopback-Adressen sind technisch erforderlich. Historische Mountnamen im
Migrationsskript dienen der Sicherungs-Kompatibilität und enthalten keine
individuellen Dateiinhalte oder Zugangsdaten. Autorennennung und Lizenzhinweise
sind ausdrücklich für die Veröffentlichung bestimmt.

Englische Beschreibungen werden lokal erstellt und überprüft; der Manager nutzt
im Betrieb keine externe Übersetzungs-API. Sprachkataloge enthalten ausschließlich
Programmtexte. Persönliche Namen, Pfade und technische Ausgaben werden nicht an
einen Übersetzungsdienst gesendet.

Die alte Git-Historie wird nicht rückwirkend bereinigt. Für ein neues öffentliches
Repository ausschließlich das geprüfte Quellarchiv verwenden. Ein lokaler Commit
ist keine Freigabe zum Hochladen der vollständigen bisherigen Git-Historie.
Ältere Pakete bleiben unverändert und müssen vor Weitergabe separat geprüft werden.

Dies ist eine Quell- und Artefaktprüfung, keine Datenschutz-Zertifizierung oder
Garantie für den späteren Betrieb. Betreiber bestimmen selbst Benutzer, Freigaben,
Protokollierung und Aufbewahrung ihrer Daten. Produktive Wiederherstellungen,
Hardwaretreiber und alle Windows-Konfigurationen sind nicht vollständig getestet;
der Windows-Client und der Mint-Zweig bleiben experimentell.
