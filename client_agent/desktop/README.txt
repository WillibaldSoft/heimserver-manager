HEIMSERVER MANAGER CLIENT – Desktop-App 0.2.2

Debian 13 / LMDE 7 / Linux Mint 22.x, grafische Benutzersitzung mit systemd.
Installation: sudo apt install ./Heimserver_Manager_Client_0.2.2_all.deb
Danach im Startmenü „Heimserver Manager Client“ öffnen.

Im Manager unter Netzwerk / Client-Agenten das Desktop-Profil des passenden
Clients herunterladen. In der App „Profil importieren“, Angaben prüfen,
„Speichern“ und „Agent aktivieren / übernehmen“ auswählen. Das Profil enthält
DEN PERSÖNLICHEN AGENTEN-TOKEN: nicht teilen oder öffentlich ablegen.
Das allgemeine DEB enthält keine Serveradresse und keine Zugangsdaten.

Vorhandene Konfiguration: ~/.config/server-manager-client/config
Die App liest sie als Daten, ohne Shell-Code auszuführen. Komplexe individuell
angepasste Shell-Konfigurationen werden nicht übernommen; JSON-Profil nutzen.
Bei Übernahme werden vorhandene systemd-Benutzer-Units und die Konfiguration
unter ~/.local/state/heimserver-manager-client/before-... gesichert.
Die bestehenden Unitnamen bleiben erhalten. Es wird kein zweiter Agent gestartet.

Funktionen: Einstellungen, Server wecken, Serverbedarf melden, Server freigeben,
Wecken und verbinden, Zugriff vorbereiten, Status, Protokoll, Benutzer-Autostart.
Betriebsmodi: mit Server, ohne Server, expliziter Wake-on-access-Aufruf.
Wecken über Recovery-URL, Wake-on-LAN, beide Methoden oder gar nicht.
Die Aktionen und Heartbeats stammen aus dem vorhandenen Manager-Client-Skript.
Wake-on-access überwacht KEINE Dateizugriffe automatisch; die Aktion muss
gezielt aufgerufen werden. Einmalige Bedarf/Freigabe-Meldungen werden beim
nächsten Heartbeat wieder durch den eingestellten Betriebsmodus überschrieben.

Der Timer läuft nach Benutzeranmeldung, auch bei geschlossenem Fenster.
Kein systemweiter root-Agent und keine Änderungen an sudo-Gruppen.
Statussymbol: Ayatana AppIndicator; je nach Desktop muss die Anzeige von
Statussymbolen unterstützt/aktiviert sein. GNOME kann eine Erweiterung benötigen.
Grünes Symbol bedeutet Server erreichbar, nicht Token erfolgreich geprüft.
Ein Desktop-Ende kann auch die systemd-Benutzersitzung beenden.

Deaktivieren: in der App „Agent deaktivieren“. Vor Deinstallation empfohlen.
Paket entfernen: sudo apt remove heimserver-manager-client
Persönliche Konfiguration und Sicherungen bleiben erhalten. Paketinstallation
aktiviert keinen Agenten und startet keine Weckaktion ohne Benutzereinrichtung.

Grenzen: keine automatische Mount-Verwaltung, keine neue Home-Assistant- oder
IPMI-Serverinstallation. Diese bleiben eigene Manager-Funktionen. Wiederholtes
Wecken kann dauern. Vor einem produktiven Einsatz auf dem jeweiligen Desktop
Statussymbol, Anmeldung, Netzwerkwechsel und Schlafverhalten prüfen.

Client-Version 0.1.1 – 30. September 2026
Startfehler behoben: Die GTK-Startfunktion wurde durch eine Aktionsmethode
überschrieben. Fensteraufbau und Programmstart am GTK-Testdisplay geprüft.
Ein vorhandenes 0.1.0-Paket durch Installation dieser DEB aktualisieren.
Benutzereinstellungen bleiben erhalten.

Client-Version 0.2.2 – 30. September 2026
Statussymbol startet bei grafischer Benutzeranmeldung automatisch, sobald die
Client-Konfiguration vorhanden ist – auch bei bisherigen Skript-Clients.
Ohne Konfiguration bleibt der automatische Start still. Der Agent wird dadurch
nicht aktiviert und keine Weckaktion ausgeführt. Manuelles Öffnen bleibt möglich.
„Agent deaktivieren“ schaltet auch den Symbol-Autostart für diesen Benutzer ab.
„Agent aktivieren / übernehmen“ aktiviert ihn wieder.


NEU IN CLIENT 0.2.2
Eigene Dateibackups und Rücksicherung im Client; Server-Backups nur über erneute
Manager-Administratoranmeldung im Browser. Privates HTTPS mit geprüftem
Stammzertifikat, optionalem Namenseintrag und Administratorfreigabe.
Zuerst im Manager Desktop-Client-Sicherungen einrichten und pro Benutzer ein
eigenes JSON-Profil verwenden. Dateibackups sind keine vollständigen Systemabbilder.
Links, Spezialdateien, ACLs und Betriebssystemzustand werden nicht vollständig gesichert.
Details: docs/CLIENT_BACKUP_ACCESS.md im Manager-Quellpaket.

CLIENT 0.3.4 – BENUTZERANMELDUNG (3. Oktober 2026)
- Im Client „Am Manager anmelden / eigene Sicherungen“ wählen.
- Administrator: Einstellungen → Manager-Benutzer → Linux-Konto freigeben,
  Rolle Benutzer und Bereich Eigene Client-Sicherungen auswählen.
- Anmeldung mit Linux-Passwort über geprüftes HTTPS. Passwort und Sitzung
  werden nicht auf Festplatte gespeichert; nach Neustart erneut anmelden.
- Benutzer dürfen eigene Sicherungen starten und wiederherstellen.
  Nur Lesen darf eigene vorhandene Sicherungen wiederherstellen.
- Konto-Sicherungen sind von alten Agenten-Sicherungen getrennt. Alte Stände
  bleiben im bisherigen Profil erreichbar; Profile nicht miteinander teilen.
- Server-Backups bleiben Administratoren vorbehalten. Rechteentzug oder
  Sitzungsablauf beendet den Zugriff; kein automatischer Rückfall auf Tokens.
- Das bestehende JSON-Profil wird weiterhin für Serveradresse, HTTPS und
  Agentenfunktionen benötigt. USB-Sicherungen bleiben offline möglich.
- Vollständige Linux-Systemrücksicherung weiterhin nur im Live-System;
  normale Benutzer erhalten dadurch keine lokalen Administratorrechte.
- Diese Erweiterung betrifft die Linux-DEB. Windows-EXE unverändert.

Client 0.3.5 – HTTPS-Proxy-Korrektur (3. Oktober 2026)
- Konto-Sicherungsanfragen verwenden den Sitzungstoken statt eines
  HTTPS-Origin-Vergleichs mit dem internen HTTP-Backend.
- Ablauf, fehlende Rechte und Anfrageprüfung werden getrennt erklärt.
- Server-Erweiterung und Client 0.3.5 gemeinsam aktualisieren.

Client 0.3.6 – Sicherungswege unterscheiden (3. Oktober 2026)
- Direkte HTTPS-Systemsicherung an erster Stelle; ohne Ordnerauswahl.
- USB/NFS-Assistent ausdrücklich beschriftet und vor Start erklärt.
- HTTPS-Protokoll kennzeichnet den gewählten Übertragungsweg.


Entwicklungsstand 4. Oktober 2026 – Linux-Client 0.4.0
- HTTPS-Systemstände übertragen nur neue 4-MiB-Blöcke; unveränderte Blöcke
  werden pro Konto/Profil wiederverwendet. Keine lokale Archiv-Zwischenkopie.
  Alle Quelldateien werden erneut gelesen; verschobene Blockgrenzen können
  zusätzliche Übertragung verursachen. Jeder fertige Stand bleibt auswählbar.
- Systemdateien, Programme, Paketquellen, Flatpak/Snap, Benutzer-Homes,
  Desktop, UID/GID, ACLs, Dienste und Konfiguration enthalten; zusätzliche
  lokale Mounts und Netzwerkprofile optional. Offline-Quelle auswählbar.
- Software-/Hardwareinventar und Erfassungsfehler im Archiv dokumentiert.
- HTTPS-Rücksicherung: System oder Komponenten im Live-System; einzelne
  Dateien/Ordner ohne Root in neuen Ordner. Externe Prüfablage erforderlich.
- Gleiche Distribution/Version/Architektur für Systemrestore erforderlich.
  Ziel-fstab/crypttab bleiben erhalten. Keine automatische Partitionierung,
  Bootloaderinstallation, plattformübergreifende Paketmigration oder Löschung
  zusätzlicher Zieldateien. Kein sektorweises Abbild. Laufende Datenbanken/VMs
  vorher stoppen oder offline sichern. Keine Archivverschlüsselung im Ruhezustand.
- Abbruchbereinigung erhält Blöcke fertiger Stände. Konto-/Profiltrennung,
  Prüfsummen und Archivpfade werden geprüft. Windows-EXE unverändert.
- Anleitung: docs/HTTPS_SYSTEM_BACKUP.txt; auch im Clientpaket enthalten.


Entwicklungsstand 4. Oktober 2026 – Benutzer und Gerät koppeln
- Linux-Client 0.4.1 und Windows-Client 0.2.3: eigenes Token und eigener
  Schlafblocker pro Manager-Benutzer, Gerät und lokaler Benutzerkennung.
- JSON-Profil importieren, HTTPS einrichten, am Manager anmelden und
  Benutzer & Gerät koppeln wählen. Linux: im Dialog Eigene Client-Sicherungen;
  Windows: direkt in den Einstellungen. Freigabe Eigene Clients & Sicherungen
  mit Rolle Benutzer oder Administrator erforderlich. Nur Lesen darf nicht koppeln.
- Ein Benutzer an mehreren PCs und mehrere Benutzer an einem PC melden ihren
  Bedarf unabhängig. Freigeben wirkt nur auf den eigenen Eintrag.
- Server-MAC wird im JSON exportiert und bei Kopplung übernommen. Bei vorhandener
  Recovery-Adresse und Server-MAC stehen beide Weckwege im JSON zur Verfügung.
- Gerätekennung wird lokal aus machine-id (Linux) oder MachineGuid (Windows)
  abgeleitet; lokale Benutzerkennung aus UID bzw. SID. Die MAC ist nur Zusatzinfo.
  Ein geändertes System/Benutzerkonto benötigt ggf. erneute Kopplung.
- Neue Tokens sind an diese Kennungen gebunden; kopierte Profile passen nicht
  automatisch zu anderen PCs/Konten. Kein hardwaregestützter Identitätsnachweis:
  Token und Systemzugang weiterhin schützen; Kennungen können nachgeahmt werden.
- Kontosperre, Rechte-/Passwortänderung oder deaktivierter Agent verhindert
  weitere Meldungen. Veralteter Bedarf läuft nach bestehendem Heartbeat-Timeout ab.
- Alte Profile bleiben als Nicht gekoppelt (Altprofil) sichtbar und funktionieren
  unverändert. Nach Umstellung aller Nutzer gemeinsames Altprofil deaktivieren.
  Bestehende Sicherungsablagen werden nicht verschoben; Manager-Konto-Sicherungen
  bleiben unabhängig von der Gerätekopplung. Manager-Abmeldung beendet nur die
  Web-/Backupsitzung; Agent über Agent deaktivieren separat abschalten.
- Windows-Build und Transport geprüft; native Windows-Anmeldung/Registry-SID
  und Oberfläche noch nicht auf einem echten Windows-PC getestet.


Entwicklungsstand 4. Oktober 2026 – Persönliche Client-Einrichtung
- Unter https://SERVER:HTTPS-PORT/clients/setup nach Manager-Anmeldung die
  Linux-DEB, Windows-EXE und ein eigenes Einrichtungsprofil herunterladen.
- Freigabe Eigene Clients & Sicherungen und Rolle Benutzer/Administrator
  erforderlich. Keine Ansicht fremder Profile oder Tokens. Nur Lesen kann
  Programme herunterladen, aber keine neue Gerätekopplung einrichten.
- Profil enthält Serveradresse, Server-MAC, ggf. private Zertifikatsinformationen
  und einen 15 Minuten gültigen Einmalcode. Am Server nur dessen Hash gespeichert.
- Linux 0.4.2 / Windows 0.2.4: Profil importieren, speichern, ggf. privates HTTPS
  nach Fingerabdruckprüfung einrichten; Agent aktivieren tauscht den Code über
  geprüftes HTTPS gegen das eigene Benutzer-Geräte-Token. Keine Passwortspeicherung.
- Jedes neue Profil ersetzt frühere unbenutzte Codes desselben Kontos. Bei Ablauf,
  verlorener Antwort oder fehlgeschlagener lokaler Speicherung neues Profil holen.
  Rechtänderung/Kontosperre verhindert auch die Einlösung vorhandener Codes.
- Startmodus Ohne Server starten, anschließend selbst wählen. Stammzertifikat
  und hosts-Eintrag werden weiterhin nur nach ausdrücklicher Bestätigung geändert.
  Backupanmeldung bleibt separat; persönliche Einrichtung erteilt keine Server-
  Backuprechte. Windows bleibt experimentell, native Windows-Prüfung ausstehend.

Sprache / Language
Deutsch bei deutscher Desktop-Anzeigesprache, sonst Englisch. Auswahl beim
Programmstart; nach Änderung der Desktopsprache den Client neu starten.
Die Sprache im Manager-Browser und das JSON-Profil ändern diese Auswahl nicht.
Neue Client-Version installieren; vorhandene Einstellungen bleiben erhalten.
Eigene Namen, Pfade, technische Protokolle und Ausgaben externer Programme
(einschließlich des USB/NFS-Migrationsskripts) bleiben im Original.

German for a German desktop display language; English for all other languages.
Restart the client after changing the desktop language. Browser language and
JSON profiles do not override this setting. Install the new client release;
existing settings are preserved. Names, paths, technical logs and external
program output (including the USB/NFS migration script) remain unchanged.
