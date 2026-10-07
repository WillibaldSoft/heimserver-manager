HEIMSERVER MANAGER CLIENT – WINDOWS 0.2.2
30. September 2026 – GPL-3.0-or-later (siehe LICENSE)

Für Windows 10 und Windows 11 mit .NET Framework 4.8 oder neuer.
Eine eigenständige Windows-EXE, keine Python-, Bash-, WSL- oder Mono-Installation
auf dem Windows-PC erforderlich. Nicht digital signiert. Vor Ausführung Herkunft
und die mitgelieferte SHA256-Prüfsumme prüfen.

EINRICHTUNG
1. EXE herunterladen und als normaler Windows-Benutzer öffnen.
2. Im Manager unter Netzwerk / Client-Agenten einen eigenen Client für diesen
   Windows-PC anlegen und dessen Einrichtung (.json) herunterladen.
3. In der App „Profil importieren (.json)“ wählen und Angaben kontrollieren.
4. „Statussymbol bei Windows-Anmeldung starten“ nach Wunsch aktiviert lassen.
5. „Agent aktivieren“: Einstellungen speichern, Startmenü/Autostart einrichten
   und regelmäßigen Heartbeat starten. Kein Administrator erforderlich.

„Für Benutzer installieren“ kopiert die EXE nach
%LOCALAPPDATA%\Programs\HeimserverManagerClient\0.2.2 und legt den Startmenüeintrag
an. Mit aktivierter Autostart-Auswahl geschieht dies auch beim Speichern.
Windows kann Autostarts verzögert ausführen oder in Einstellungen / Apps /
Autostart deaktivieren. Das Symbol liegt eventuell im ausgeblendeten Infobereich.

FUNKTIONEN
- Server wecken: Wake-on-LAN, Recovery-Aufruf, beide Methoden oder kein Wecken.
- Server benötigt / freigeben: Bedarf direkt an den Manager melden.
- Wecken und verbinden: wecken, maximal zehn Minuten auf Erreichbarkeit warten,
  danach Serverbedarf melden. Es wird kein Netzlaufwerk eingebunden.
- Zugriff vorbereiten: wecken und warten; keine Dateizugriffsüberwachung.
- Heartbeat alle 60 Sekunden; Erreichbarkeitsprüfung etwa alle 15 Sekunden.
- Drei Betriebsmodi wie beim Linux-Agenten: mit Server starten (automatisches
  Wecken und Bedarf), ohne Server starten, nur auf ausdrücklichen Aufruf wecken.
- Die nächste Heartbeat-Meldung setzt den Bedarf wieder gemäß Betriebsmodus.
- Einstellungen, JSON-Profilimport, Protokoll, abbrechbare Aktionen,
  Statussymbol, Startmenü und Benutzer-Autostart. Zweiter Start öffnet das Fenster
  der vorhandenen Instanz; kein zweiter Heartbeat-Prozess.
- Beim Aufwachen des Windows-PCs wird der Status erneut geprüft.

EINSTELLUNGEN UND TOKEN
Das JSON-Profil hat dasselbe Format wie beim Linux-Desktop-Client. Es enthält
einen persönlichen Agenten-Token: nicht weitergeben. Pro gleichzeitig verwendetem
PC einen eigenen Client im Manager einrichten. Linux-Konfigurationsdateien werden
unter Windows nicht automatisch gesucht oder als Shell-Code ausgeführt.
Gespeicherte Einstellungen liegen unter %LOCALAPPDATA%\HeimserverManagerClient
und werden mit Windows-DPAPI für den aktuellen Benutzer verschlüsselt.
config.dat.bak hält die vorherige verschlüsselte Konfiguration vor. Eine Kopie
dieser Dateien auf einen anderen PC/Benutzer ist kein übertragbares Profil.
Netzwerk- und Recovery-Adressen sowie Token werden nicht ins Protokoll geschrieben.
Die EXE enthält keine persönlichen Serverdaten oder Zugangsdaten.

BETRIEB / BEENDEN
Fenster schließen minimiert in den Infobereich; Agent und Heartbeat laufen weiter.
Im Symbolmenü „Agent und Statussymbol beenden“ beendet auch den Heartbeat.
Anders als beim Linux-Timer läuft der Windows-Agent im selben Prozess wie das
Statussymbol. Abmeldung beendet diese Benutzersitzung; es ist kein Windows-Dienst.
Nach erneutem Anmelden startet er gemäß Autostart und gespeichertem Betriebsmodus.
Die Anzeige „erreichbar“ allein ist kein Nachweis einer erfolgreichen Anmeldung.
Fehlerhafte Token werden durch den authentifizierten Heartbeat erkannt.

DEAKTIVIERUNG UND ENTFERNEN
„Agent deaktivieren“ stoppt die Meldungen und entfernt den Benutzer-Autostart.
Ein bereits gemeldeter Bedarf läuft gemäß Manager-Ablaufzeit aus; für sofortige
Freigabe vorher „Server freigeben“ wählen. Einstellungen bleiben erhalten.
„Autostart / Startmenü entfernen“ deaktiviert zusätzlich den Startmenüeintrag.
Danach die App über das Symbolmenü beenden. Bei Bedarf Programmordner und separat
den Einstellungsordner im Benutzerprofil löschen. Keine Abhängigkeiten entfernen.
Bei einem späteren Update zuerst die laufende App über das Symbolmenü beenden,
dann die neue EXE öffnen und „Für Benutzer installieren“ wählen.

PRÜFSTAND / GRENZEN
- EXE mit Mono-C#-Compiler für .NET gebaut; keine Mono-Bibliotheken mitgeliefert.
- 15 Kernprüfungen sowie HTTP-Protokollprüfung gegen lokalen Testserver:
  Modi, Profile, Authentifizierung, Wake-Paket, Recovery, Redirect-Schutz, Abbruch.
- Windows-Forms-Fenster und Tray-Komponente unter Mono am Testdisplay geprüft.
- Echter Start auf Windows 10/11, Windows-DPAPI, Startmenü und Autostart dort
  noch nicht live geprüft. Diese erste Windows-Version ist experimentell.
- Wake-on-LAN benötigt passend eingerichtete Netzwerkkarte/Netzwerk; ein
  gesendetes Magic Packet bestätigt keinen erfolgreichen Serverstart.
- Recovery-Dienst bleibt eine separate Einrichtung auf einem erreichbaren Host.
- Bei Netzwerkausfall werden Prüfungen/Heartbeats wiederholt, aber keine beliebigen
  manuellen Aktionen unkontrolliert erneut ausgeführt.

QUELLEN / NACHBAU
Quellcode und build.ps1 liegen im Quellarchiv. Unter Windows mit installiertem
.NET Framework: powershell -File .\build.ps1
Referenzen: Windows Forms, System.Drawing, System.Runtime.Serialization,
System.Security; ausschließlich Windows/.NET-Standardbibliotheken.
Microsoft-Dokumentation:
https://learn.microsoft.com/en-us/dotnet/framework/install/on-windows-and-server
https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata
https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys


NEU IN CLIENT 0.2.2
Eigene Dateibackups und Rücksicherung im Client; Server-Backups nur über erneute
Manager-Administratoranmeldung im Browser. Privates HTTPS mit geprüftem
Stammzertifikat, optionalem Namenseintrag und Administratorfreigabe.
Zuerst im Manager Desktop-Client-Sicherungen einrichten und pro Benutzer ein
eigenes JSON-Profil verwenden. Dateibackups sind keine vollständigen Systemabbilder.
Links, Spezialdateien, ACLs und Betriebssystemzustand werden nicht vollständig gesichert.
Details: docs/CLIENT_BACKUP_ACCESS.md im Manager-Quellpaket.


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
