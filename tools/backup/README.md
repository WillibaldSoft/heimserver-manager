# Server- und Client-Backup

Das Paket enthält keine Zugangsdaten. `client.json` enthält den ursprünglichen
Rechnernamen, den zugeordneten Serverbenutzer und dessen UID/GID zum Vergleich.
Eine Änderung von Konten, Gruppen, UID oder GID findet nicht automatisch statt.

## Voraussetzungen

Linux mit Python 3, GNU tar, findmnt. Für SMB im Desktop: gio und gvfs-backends;
für Live-USB mit root: cifs-utils. Der SMB-Benutzer benötigt Zugriff auf Backup.
Archive enthalten private Dateien und ggf. Schlüssel. SMB-Unterordnerrechte im
Server Manager prüfen; der Backupbereich darf nicht allgemein lesbar sein.

## Jederzeit vom Client sichern

Paket entpacken und als normaler Benutzer `sh install-client.sh` ausführen.
Danach im Anwendungsmenü „Server-Backup – Jetzt sichern“ öffnen. SMB-Zugang wird
bei Bedarf abgefragt. Es läuft kein dauerhafter root-Dienst. Der Start sichert
das eigene Home; kein Vollsystemabbild und keine konsistente Sicherung laufender
Datenbanken. Anwendungen mit wichtigen geöffneten Dateien vorher schließen.
Fehler oder während des Lesens veränderte Dateien ergeben keinen fertigen Stand.

Alternativ im entpackten Ordner:

    python3 backup_client.py identity
    python3 backup_client.py backup

Der letzte Befehl verbindet die konfigurierte SMB-Freigabe. Für eine bereits
verbundene Freigabe `--repository /pfad/zur/Backup-Freigabe` ergänzen.
Die Ablage ist linux-client-backup/RECHNER/BENUTZER/ZEITSTEMPEL.
Jeder Stand ist ein eigenes vollständiges Archiv; alte Stände werden nicht gelöscht.
Bei vollem Ziel bleibt ein `.partial-…`-Ordner, kein gültiger Sicherungsstand.

## Live-USB

Den ursprünglichen Rechner auswählen: das passende Paket im Server Manager laden.
Python-Werkzeug und client.json zusammen auf dem Stick mitnehmen. Das installierte
Linux zunächst über die Laufwerksverwaltung einbinden. Beispiel:

    sudo python3 backup_client.py backup --source /mnt/linux/home/exampleuser
    sudo python3 backup_client.py list
    sudo python3 backup_client.py verify --snapshot /mnt/server-manager-backup/linux-client-backup/RECHNER/exampleuser/STAND
    sudo python3 backup_client.py restore --snapshot /mnt/server-manager-backup/linux-client-backup/RECHNER/exampleuser/STAND --target /mnt/linux/home/exampleuser-wiederhergestellt --preserve-ids

Das Restore-Ziel muss neu sein. `--preserve-ids` erhält die originalen numerischen
Eigentümer und ACLs und benötigt root. Ohne diese Option werden Dateien dem
aufrufenden Benutzer zugeordnet und Original-ACLs nicht übernommen. Vor einer
Übernahme ins endgültige Home die Benutzer- und Gruppen-IDs prüfen; ergänzende
ACL-Benutzer werden nicht pauschal auf einen einzigen Benutzer umgeschrieben.
Ein laufendes Benutzerprofil wird vom neuen Werkzeug nicht überschrieben.

SHA-256 und Archivpfade werden vor der Wiederherstellung geprüft. Das ersetzt
keine Authentizitätssignatur: nur Sicherungen aus vertrauenswürdiger Ablage nutzen.
Das Python-Werkzeug schreibt während seiner Arbeit alle 30 Sekunden ein SMB-
Lebenszeichen. Der Server-Manager verhindert damit geplantes Einschlafen; nach
Verbindungsverlust läuft der Schutz nach drei Minuten aus. Die SMB-Freigabe muss
auf dieselbe zentrale Backupablage zeigen, die in den Einstellungen steht.
Bei direkter Nutzung von migration.sh ohne das Python-Werkzeug den Schlafzeitplan
für die Dauer der Arbeit pausieren.

## Erweitertes V20-Migrationswerkzeug

`migration.sh` ist die bereitgestellte V20-Vorlage mit zusätzlichem lokalen
Arbeitsordner und Rechnertrennung. USB-Modus bleibt verfügbar. Beispiel:

    sudo bash migration.sh --live --source-home /mnt/linux/home/exampleuser --source-user exampleuser --client-id MEIN-PC --storage-dir /mnt/linux/backup-arbeit

Der Arbeitsordner muss schon existieren und auf einem Linux-Dateisystem liegen.
Das V20-Werkzeug nicht direkt auf SMB verwenden: dessen lose Dateien benötigen
POSIX-Rechte. Der erweiterte V20-Ablauf ist interaktiv und nicht identisch mit dem
Home-Archiv des neuen Client-Werkzeugs. Für die Archivübertragung des V20-Arbeitsordners dient:

    sudo python3 backup_client.py migration --live --source /mnt/linux/home/exampleuser --local-user exampleuser --workdir /mnt/linux/backup-arbeit

Nach Beenden des V20-Menüs fragt das Werkzeug, ob der Arbeitsordner als eigener
Migrationsstand auf den Server übertragen werden soll. Zum Wiederherstellen den
Stand mit `restore --preserve-ids` in einen neuen lokalen Linux-Arbeitsordner
entpacken und `migration.sh --storage-dir DIESER_ORDNER --client-id MEIN-PC ...`
starten. Die einzelnen V20-Wiederherstellungsschritte müssen dort ausgewählt werden.
Das Vorlagenskript bleibt ein separates, nicht vollständig end-to-end getestetes
Migrationswerkzeug. Ein Server-Konfigurationsarchiv lässt sich mit `list --server
SERVERNAME` anzeigen und mit `restore --server SERVERNAME --snapshot ... --target
NEUER_ORDNER --preserve-ids` entpacken; es wird niemals automatisch über / kopiert.


## Optional: Client-IDs an den Server angleichen

Im Server Manager das Paket frisch herunterladen, damit die Server-IDs aktuell
sind. Auf dem Client zuerst eine Sicherung erstellen, dann von Live-USB starten.
Das installierte System separat unter /mnt/linux einbinden. Vorschau:

    sudo python3 identity_sync.py --target-root /mnt/linux --local-user exampleuser

Nach Prüfung und vorhandener Sicherung anwenden:

    sudo python3 identity_sync.py --target-root /mnt/linux --local-user exampleuser --apply

Zusätzlich muss ANGLEICHEN eingegeben werden. Das Werkzeug prüft UID-/GID-
Kollisionen und gemeinsam genutzte Primärgruppen. Es passt den ausgewählten
Benutzer, dessen private primäre Gruppe, Dateieigentümer und numerische ACL-
Einträge an. Passwörter und zusätzliche Gruppen werden nicht synchronisiert.
Sicherungen von passwd/group, ACLs und eine Dateiliste werden im Offline-System
unter /var/lib/server-manager-id-before-ZEIT abgelegt. Bei einem erkannten Fehler
versucht das Werkzeug zurückzusetzen; ein Stromausfall ist dadurch nicht abgesichert.
Root und Home müssen in dieser ersten Version auf demselben Dateisystem liegen.
Weitere eingehängte Dateisysteme werden ausdrücklich abgewiesen, damit dort keine
alten IDs unbemerkt zurückbleiben. Eine Online-Umnummerierung ist gesperrt.
