# HTTPS-Zugang zum Heimserver Manager

Neue DEB-Erstinstallationen installieren Apache, OpenSSL, Certbot und das
Apache-Plugin für Certbot zusätzlich zu den bisherigen Abhängigkeiten.
Apache stellt die Verbindung zum lokalen Manager-Port her. Andere Apache-Websites
werden nicht überschrieben. Fail2ban ist weiterhin optional; es ist keine
Voraussetzung für TLS und kann unter Web & Sicherheit eingerichtet werden.

Bei einer neuen Paketinstallation wird `<rechnername>` vorgeschlagen und ein privater HTTPS-VHost auf Port 443 mit lokaler Zertifizierungsstelle angelegt. Der Manager-HTTP-Port ist ausschließlich auf 127.0.0.1 gebunden. Schlägt HTTPS fehl, Apache und Ports am Server-Terminal prüfen und `sudo dpkg --configure server-manager` wiederholen. Es gibt keinen externen HTTP-Ersatzzugang. Details unter Einstellungen → HTTPS.

## Privater Zugang

1. Einstellungen → HTTPS öffnen. Hostname, HTTPS-Port und zugelassene Netze prüfen.
2. Einrichtung prüfen und die Vorschau bestätigen.
3. Den Namen im lokalen DNS/Router auf die feste Server-IP legen. Alternativ
   hosts-Dateien auf den Clients verwenden; die Oberfläche zeigt die Pfade.
4. Öffentliches Stammzertifikat herunterladen, Fingerabdruck mit der Ausgabe am
   Server vergleichen und auf den Geräten als vertrauenswürdige CA importieren.
5. HTTPS-Adresse öffnen und Anmeldung, Downloads und Uploads prüfen.
6. Client-Agenten nach dem Zertifikatsimport auf die HTTPS-Adresse umstellen.
   Agenten folgen HTTP-Weiterleitungen nicht automatisch.

Windows kann die CA für den aktuellen Benutzer in „Vertrauenswürdige
Stammzertifizierungsstellen“ aufnehmen. Debian/Mint: CRT nach
`/usr/local/share/ca-certificates/` kopieren und `sudo update-ca-certificates`
ausführen. Browser mit eigenem Zertifikatsspeicher benötigen ggf. eigenen Import.
Private Schlüssel werden nicht zum Download angeboten. Die CA ist pro Server
eindeutig; Hostname/Netze lassen sich später im selben Formular ändern.

Der private VHost erlaubt standardmäßig RFC1918-IPv4, Loopback und private/link-lokale IPv6-Netze. Bei globalem IPv6 im Heimnetz das konkrete LAN-Präfix ergänzen. DNS, Router und Firewall werden nicht automatisch geändert. Das Paket bindet den unverschlüsselten HTTP-Backend-Port nur an 127.0.0.1; Clients verwenden HTTPS. Abweichende manuelle Altinstallationen gesondert prüfen.

## Erneuerung

`server-manager-https-renew.timer` prüft täglich mit bis zu einer Stunde zufälliger
Verzögerung; versäumte Läufe werden nachgeholt. Das Serverzertifikat gilt ein Jahr
und wird bei weniger als 30 Tagen Restlaufzeit erneuert. Apache wird geprüft und
neu geladen. Die lokale CA gilt zehn Jahre und wird nicht automatisch ersetzt;
ein CA-Wechsel muss wegen der Client-Vertrauensstellung geplant werden.

Fehler sind im Dienstjournal sichtbar. Bei Änderungen an Apache werden eigene
Konfigurationsdateien gesichert. Bei fehlgeschlagener Aktivierung werden diese
zurückgesetzt; eine erstmals erzeugte lokale CA bleibt erhalten. Bereits aktive
andere Websites und deren Zertifikate werden nicht geändert.

## Öffentliche Domain später

Einstellungen → HTTPS → „Später: öffentliche Domain und Zertifikat“. Eigenes
Manager-Anmeldepasswort setzen. Domain und optional ein vorhandenes gültiges
Let's-Encrypt-Zertifikat auswählen; sonst E-Mail und Zustimmung zur Ausstellung
angeben. Für HTTP-01 müssen DNS und externe Ports 80/443 auf diesen Server zeigen.
Der neue öffentliche VHost ist zusätzlich zum privaten Zugang vorhanden.
Öffentliche Zertifikate erneuert Certbot mit Apache-Reload-Hook.

Die Vorschau zeigt die Veröffentlichung ausdrücklich an. DNS/Portweiterleitung
werden nicht automatisch eingerichtet. Bestehende Domain-VHosts werden nicht
ersetzt; sie sind unter Web & Sicherheit einsehbar und bearbeitbar.

## Proxy und Anmeldung

Der Manager vertraut HTTPS-Metadaten ausschließlich vom lokalen Apache mit hostbezogenem internem Schlüssel. Beliebige X-Forwarded-Header aktivieren kein HTTPS-Vertrauen. HTTPS-Sitzungscookies erhalten Secure. Original-Client-IP und HTTPS-Schema werden für Anmeldung und Formular-Origin-Prüfungen übernommen. Der interne HTTP-Backend-Zugang ist kein freigegebener LAN-Zugang.

Der kurze Rechnername ist nur die Vorgabe bei der Ersteinrichtung. Unter Einstellungen → HTTPS-Zugang kann der private HTTPS-Name später geändert werden. Gespeicherte Namen bleiben bei Updates erhalten. Die Änderung stellt ein neues Serverzertifikat mit der vorhandenen CA aus; sie ändert nicht den Linux-Rechnernamen. DNS-/hosts-Einträge, Lesezeichen und Client-Profile anschließend anpassen.

Privater HTTPS-Zugang ist gleichzeitig über Hostnamen und feste Server-IP möglich. Optionaler IP-Zugang auf eigenem Port (Standard 8443), einstellbar unter HTTPS-Zugang. Das Zertifikat enthält auch die IP; derselbe Netzschutz und dieselbe Anmeldung gelten. Stammzertifikat auf Clients vertrauen. Bei IP-Wechsel die Einstellung anpassen.