# Modulauswahl pro Server

Unter **Einstellungen → Modulauswahl** können Heimnetz/Anwesenheit/Client-Agenten und das TV-Modul gewählt werden.
Nach der Anmeldung zeigt die Übersicht einen Einrichtungshinweis, solange für diese Installation noch keine Auswahl gespeichert wurde.
Die Auswahl liegt ausschließlich lokal in `/etc/server-manager/modules.json` (bzw. dem konfigurierten Konfigurationsordner).

- Hauptserver: Heimnetz & Anwesenheit bei Bedarf eingeschaltet lassen.
- Nebenserver: abschalten, wenn ein anderer Server die Geräte bereits überwacht.
- Abgeschaltete Heimnetzüberwachung sendet keine neuen Scans, nimmt keine Client-Agent-Meldungen an (HTTP 503) und liefert keine zugehörigen Schlafblocker.
  Gespeicherte Geräte, Agenten und bisherige Presence-Einstellungen bleiben erhalten. Ein bereits laufender Einzeltest kann kurz auslaufen.
- DynDNS und Virtuelle Maschinen sind eigenständige Hauptbereiche. Bei deaktivierter Heimnetzüberwachung wird Netzwerk aus Hauptnavigation und Übersicht ausgeblendet.
- TV automatisch: nur einblenden und überwachen, wenn TVHeadend lokal vorhanden oder eine Verbindung eingerichtet ist.
- TV aktiv: bewusst konfigurierte Überwachung; Verbindungsfehler schützen weiterhin vor dem Einschlafen.
- TV deaktiviert: Bereich ausblenden, TV-Schlafblocker und TV-Weckkandidaten abschalten. Der TVHeadend-Dienst selbst bleibt unverändert.

LAN-Schnittstelle und IPv4-Netz können explizit gesetzt werden. Ohne Vorgabe wird die eindeutige aktive IPv4-Standardroute ausgewertet.
Vorhandene explizite `lan_network`-Werte aus Server & Modulpfade bleiben erhalten; die Modulauswahl kann sie für die Überwachung überschreiben.
Docker-, TAP-, libvirt- und vergleichbare virtuelle Schnittstellen werden nicht automatisch ausgewählt.
Bei uneindeutiger Erkennung eine LAN-Schnittstelle und ein IPv4-Netz mit höchstens 4096 Adressen angeben.
Die Erkennung ändert weder IP-Adresse noch Bridge, Route oder Netzwerkkonfiguration des Betriebssystems.
