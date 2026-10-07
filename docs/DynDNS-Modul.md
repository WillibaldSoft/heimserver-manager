# DynDNS-Modul und Multi DynDNS v4

Integration auf Grundlage von `multi-dyndns-manager-v3.9.sh` aus
`einem vorhandenen DynDNS-Skript`. Der Shell-Updater wurde als eigenständig
aufrufbarer Python-3-Kern umgesetzt, damit Oberfläche und Zeitplan dieselbe geprüfte
Logik benutzen. Der alte interaktive Manager wird nicht im Webprozess ausgeführt.

## Bedienung

- `/dyndns`: Anbieter, Zustand, letzte Prüfung, letztes bestätigtes Update,
  IP-Adressen, Anbietersperren und nächster Timertermin.
- „Bestehendes Skript übernehmen“ liest die v3-Konfigurationen als reine Daten.
  Die Vorschau enthält keine Geheimnisse. Unverständliche Konfigurationen verhindern
  die Übernahme aller Anbieter, statt einzelne Einträge stillschweigend auszulassen.
- Die Übernahme speichert eine private Sicherung unter
  `/var/lib/server-manager/dyndns/backups/<Zeitstempel>/restore.json`,
  bewahrt Originalkonfigurationen und bestehende Anbietersperren auf und ersetzt
  die vorhandene `multi-dyndns-update.service` / `.timer`-Kombination.
- „Anbieter hinzufügen“ bzw. „Bearbeiten“ verwaltet Host, IP-Modus, Anmeldung,
  Update-URL und Aktivstatus. Leere Passwort- und URL-Felder erhalten gespeicherte
  Werte. Löschen benötigt die Bestätigung im Formular und löscht keinen DNS-Eintrag.
- „IP & DNS prüfen“ ermittelt Adressen und autoritative A/AAAA-Einträge; es sendet
  kein Update an den Anbieter. „Jetzt aktualisieren“ startet den systemd-Dienst und
  beachtet weiterhin Anbietersperren, Strategie und Wiederholungsabstände.
- Zeitplan pausieren/aktivieren steuert den vorhandenen Timer. Ein laufender Update-
  Auftrag wird beim Pausieren nicht abgebrochen.
- Unter „Zeitplan & IP-Ermittlung“ lassen sich Intervall, Strategie, IPv6-Schnittstelle
  und Sperrdauer ändern. Speichern aktiviert den Zeitplan.
- Der Download enthält Python-Kern, Shell-Starter und Anleitung ohne Zugangsdaten.
  Konfiguration erfolgt im Modul; CLI-Aufrufe: `--status`, `--check`, `--run-update`.

## Verbesserungen gegenüber v3.9

Konfiguration wird nicht mehr mit `source` ausgeführt. HTTPS-Anfragen erfolgen im
Python-Prozess ohne Geheimnisse in Prozessargumenten. Statusdateien enthalten keine
URLs, Authentifizierungsheader oder Anbieter-Rohantworten. Zugangsdateien und
Sicherungen werden atomar mit Modus 0600 gespeichert. Browserantworten verwenden
`Cache-Control: no-store`; schreibende Formulare haben CSRF- und Revisionsschutz.

IPv4-only und IPv6-only funktionieren unabhängig voneinander. IPv6 ignoriert private,
Link-Local-, temporäre und nicht verwendbare Adressen. Fehlende optionale Adressen
werden nicht als leere Updateparameter gesendet, um unbeabsichtigtes Löschen oder
Autodetektion der falschen Familie zu vermeiden.

Cache, Versuche, Erfolg und Anbietersperren werden pro Anbieter gespeichert. Ein
Fehler bei Anbieter B verliert nicht den Erfolg von Anbieter A. Nur ausdrücklich
bestätigte Antworten gelten als Erfolg. Unbekannte Antworten werden nicht als OK
klassifiziert. HTTP 429, 911 und bekannte Begrenzungstexte setzen Wartezeiten.

Autoritative DNS-Antworten werden über SOA/NS ermittelt und auf das AA-Flag geprüft;
kein Vergleich nur mit dem Fritzbox-Cache. Nach bestätigtem Update verhindert eine
Wartezeit von mindestens einer Stunde wiederholte Updates wegen DNS-Verzögerungen.
Fehlgeschlagene Versuche verwenden ansteigende Abstände. Eine prozessübergreifende
Dateisperre schützt Konfigurationsänderungen, Prüfung und Updates. Währenddessen
meldet sich DynDNS als Blocker bei Schlaf & Wake.

## Grenzen und Betrieb

Der Dienst benötigt Python 3, iproute2 und dnsutils; keine Paketinstallation aus dem
Webformular. Standardvorlagen: DDNSS (Key/Passwort), INWX, dynv6, DuckDNS. Weitere
v3-GET-Anbieter können mit ihrer HTTPS-URL übernommen werden. Eigene URLs benötigen
eine exakte Erfolgsantwort. Cloudflare war in v3 nur eine unvollständige Platzhalter-
vorlage und wird bewusst nicht als funktionsfähige Record-API importiert.

Direkte A/AAAA-Einträge werden geprüft; CNAME-Ketten, providerspezifische JSON-APIs,
DNSSEC-Verifikation und DNS-Record-Erstellung werden nicht angeboten. Öffentliche
DNS-Propagation ist kein Bestandteil einer positiven Providerantwort. Keine
Router-/Firewalländerungen, keine Änderungen an Apache, Nextcloud oder HA-VMs.

Der neue Zeitplan hat kein OnBootSec und kein sofortiges Nachholen: die Übernahme
löst kein Update aus. Bestehende Anbieter bleiben bis zur Übernahme beim alten
Updater. Die neue Konfiguration liegt unter `/etc/server-manager/dyndns.json`.

## Nachweise

Tests in `tests/test_dyndns.py` verwenden temporäre Konfigurationen und simulierte
Netzwerk-/systemd-Aufrufe. Reale Anbieter-Updates sind keine automatischen Tests.

Anbieterdokumentation:
- https://dyn.ddnss.de/info.php
- https://kb.inwx.com/de-de/8-dyndns/167-einrichtung-synology
- https://dynv6.com/docs/apis
- https://www.duckdns.org/spec.jsp
