# Installer-Plan

Der spätere Installer reproduziert den Server Manager ausschließlich aus Repository + Migrationen.

## Schritte

1. Pakete installieren
2. Benutzer/Gruppe anlegen
3. Projekt nach `/opt/server-manager` kopieren
4. `/etc/server-manager` anlegen
5. `/var/lib/server-manager` anlegen
6. Konfigurationsdateien erzeugen
7. Migrationen ausführen
8. systemd-Service installieren
9. Service starten
10. Projektstatus ausgeben

## Keine Patch-Skripte

Patch-Skripte aus der Entwicklung sind nicht Teil des Installers.
