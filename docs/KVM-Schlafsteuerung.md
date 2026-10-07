# Schlafsteuerung pro VM

Unter KVM Verwaltung kann die Schlafsteuerung direkt in jeder Tabellenzeile und auf der VM-Detailseite ausgewählt und gespeichert werden. Einstellungen werden anhand der VM-UUID in `kvm_sleep_policy` gespeichert; neue und bisherige VMs verwenden zunächst „Server wach halten“.

- **Server wach halten:** aktive und pausierte VMs melden einen Blocker.
- **Durch Schlaf & Wake herunterfahren:** aktive VMs bleiben Blocker, bis sie ausgeschaltet sind. Bei einem aktiven Suspend-, Hibernate- oder Aus-Zeitplan, eingeschalteter Automatik und echter Ausführung werden nach der Nachlaufzeit reguläre Shutdown-Anfragen gestellt. Andere Blocker verhindern diesen Schritt. Der Hostzustand wird erst nach einer erneuten zentralen Blockerprüfung geändert.
- **Keinen Blocker melden:** diese VM hält den Host nicht wach und erhält keine Shutdown-Anfrage vom KVM-Modul. Der Host kann somit mit aktiver VM schlafen oder ausschalten.

Die Nachlaufzeit wird durch verwaltete VMs nicht ständig verlängert. KVM-Hintergrundaufträge bleiben gesperrt; pro Scheduler-Durchlauf wird höchstens eine neue Shutdown-Anfrage gestartet. Wiederholungen für dieselbe VM erfolgen frühestens nach fünf Minuten. Fehler sind unter KVM → Aufträge sichtbar. Ein nicht reagierender Gast bleibt ein Blocker. Pausierte VMs müssen zuerst manuell fortgesetzt werden. Es gibt kein automatisches hartes Ausschalten.

Der Modus wird vor Ausführung eines eingereihten Shutdown-Auftrags erneut geprüft. Ein Zurückwechseln verhindert noch nicht ausgeführte Anfragen; eine bereits an den Gast gesendete Anfrage kann nicht zurückgenommen werden.

Der separate libvirt-Autostart gilt weiterhin für Host-Neustarts. Es gibt keinen automatischen Neustart heruntergefahrener VMs nach Host-Suspend. Manuelle Hostaktionen werden durch diese Erweiterung nicht zu VM-Zeitplanaktionen.

Tests simulieren VMs und Hostaktionen; Produktiv-VMs werden nicht zu Testzwecken heruntergefahren.
