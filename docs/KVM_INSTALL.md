# Debian 13: Installation ohne sudo-Gruppe

Ein normales Benutzerkonto bleibt ein normales Konto. Paketinstallation benötigt
Administrationsrechte. Das DEB wird durch APT/dpkg als root installiert; es kann
sich nicht selbst vor dem Start Administratorrechte verschaffen.

Der Paketbau legt deshalb zusätzlich `install_deb.sh` neben das DEB:

    sh install_deb.sh /vollstaendiger/pfad/Heimserver_Manager.deb

Auswahl 2 verwendet `su` und fragt nach dem root-Passwort. Das funktioniert auch,
wenn sudo fehlt oder der Benutzer nicht in der sudo-Gruppe ist. Auswahl 1 ist
für vorhandene sudo-Berechtigungen. Kein Passwort wird im Skript gespeichert;
Auswahl 3 installiert bei Bedarf sudo und nimmt ausschließlich das aufrufende
normale lokale Benutzerkonto in die sudo-Gruppe auf. Dazu ist das root-Passwort
erforderlich. Diese Auswahl erteilt dauerhaft Administratorrechte; vollständig
abmelden und neu anmelden, bevor sudo im Benutzerkonto verwendet wird.
Auswahl 1 und 2 ändern keine Gruppenmitgliedschaften. Alternativ als root
`apt install /vollstaendiger/pfad/Heimserver_Manager.deb` ausführen.
Nach der Installation startet der Manager automatisch als Systemdienst.

# KVM / libvirt

Unter Apps verwalten → KVM / libvirt → Installieren beziehungsweise
KVM / Bridge einrichten gibt es einen geprüften Installationsplan. Installiert
werden QEMU für amd64 oder arm64, passende UEFI-Firmware, libvirt-Systemdienst,
Clients, virt-install, Python-libvirt, dnsmasq-base, bridge-utils und iproute2
sowie deren APT-Abhängigkeiten. VT-x/AMD-V beziehungsweise die entsprechende
Virtualisierungsunterstützung muss im BIOS/UEFI oder Hypervisor verfügbar sein.

Netzwerkoptionen:

- NAT: libvirt-Netz `default`; keine Umstellung der Host-LAN-Verbindung.
- Vorhandene Linux-Bridge: libvirt-Netz `servermgr-lan` darüber einrichten.
- Neue LAN-Bridge: nur über eine freie kabelgebundene Netzkarte ohne IP-Adresse,
  Route, Master oder Konfiguration, mit ifupdown und interfaces.d. Die Bridge
  erhält keine Host-IP; die VMs verwenden das LAN. Bestehende Management-
  Verbindungen benötigen die separate Übernahmeoption (siehe unten). WLAN,
  NetworkManager und systemd-networkd werden nicht migriert.
  Hier zuerst mit der jeweiligen Netzwerkverwaltung eine Bridge einrichten
  und danach die Option für eine vorhandene Bridge wählen.

Optional kann ein normaler lokaler Benutzer den Gruppen libvirt und kvm
hinzugefügt werden. Dies erlaubt die Verwaltung systemweiter VMs; erneute
Anmeldung erforderlich. Es ist keine sudo-Freigabe. Die automatische Entfernung
von KVM ist gesperrt, damit vorhandene VMs und gemeinsam genutzte Dienste
nicht unabsichtlich beeinträchtigt werden. Ausblenden bleibt möglich.

Referenzen: https://wiki.debian.org/KVM und
https://libvirt.org/formatnetwork.html#using-an-existing-host-bridge

## Aktive LAN-Karte übernehmen

Zusätzlich gibt es die Option „Aktive LAN-Karte übernehmen“. Unterstützt sind
überschaubare ifupdown-Konfigurationen mit statischem IPv4/IPv6 oder DHCPv4.
MAC-Adresse, Adressoptionen, Gateway, DNS und explizite DHCP-Clientangaben werden
auf die Bridge übertragen. `auto` und der Networking-Dienst sorgen für Autostart.
DHCP kann trotz gleicher MAC eine andere Adresse vergeben (z. B. andere IAID);
Bestätigung ist nur möglich, wenn die bisherigen IPs und MAC wieder vorhanden sind.

Vor der Änderung werden Konfiguration und Zustand gespeichert. Ein unabhängiger
systemd-Timer stellt nach fünf Minuten ohne Bestätigung zurück. Ein persistenter
Boot-Dienst stellt unbestätigte Konfigurationen auch nach einem Neustart zurück.
Nach erneutem Verbinden im KVM-Installer „Verbindung funktioniert – Bridge behalten“
bestätigen. Erst dann wird das libvirt-Netz servermgr-lan eingerichtet.

Nicht automatisch migriert werden NetworkManager, systemd-networkd, WLAN,
DHCPv6, verteilte/spezielle Include-Strukturen, Netzwerk-Hooks und
schnittstellenspezifische zusätzliche DHCP-Konfiguration. Hier ist eine manuelle
Bridge-Einrichtung mit der vorhandenen Netzwerkverwaltung erforderlich.
Während einer offenen Umstellung keine parallelen Netzwerkänderungen vornehmen.
Die Rücksicherung verringert das Risiko, ersetzt aber keinen lokalen Konsolenzugang.
