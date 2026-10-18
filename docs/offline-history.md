# Offline-Rückholkopien

Neue serverseitige Rückholkopien liegen im jeweiligen Quellordner unter
`.hsm-history/<UTC-Zeitstempel>-<Kennung>/<Originalname>`.
Originalnamen bleiben vollständig erhalten. Der reservierte `.hsm-`-Präfix
schließt den Ordner von Dateilisten und Synchronisation aus.
SMB-Löschungen und HTTPS-Ersetzungen verschieben den ursprünglichen Dateiknoten:
Eigentümer, Dateirechte und ACLs bleiben erhalten. SMB-Ersetzungen verwenden
weiterhin die geprüfte ACL-Kopie; fehlende Rechte werden nicht umgangen.
Unterordner folgen den Erstellungs- und Vererbungsregeln der jeweiligen Freigabe.
Alte Rückholkopien ohne Namenszuordnung behalten beim Verschieben ihren alten
Namen. Keine automatische Löschung oder Aufbewahrungsfrist.
Linux-Clients müssen die aktualisierte SMB-Komponente laden (vollständig beenden
und neu öffnen). Verfügbar ab Manager 0.13-7 und Linux-Client 0.4.40. Frühere Pakete bleiben unverändert.

