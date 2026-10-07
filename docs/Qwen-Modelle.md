# Qwen-Modelle in Open WebUI

Apps → Open WebUI → **Qwen-Modelle** öffnet `/apps/open_webui/models`.
Die Oberfläche verwaltet den lokalen Ollama-Dienst (`127.0.0.1:11434`).
Open WebUI muss denselben Ollama verwenden. Bestehende Verbindungseinstellungen werden nicht verändert.

- Modellfamilien werden live von der offiziellen Ollama-Suche geladen, Varianten samt Größen und Prüfsummen von deren Tag-Seiten. Katalogfehler werden sichtbar angezeigt.
- Installierte Modelle werden über `/api/tags` gelesen. Die veröffentlichte Prüfsumme unterscheidet aktuelle Installationen und Updates desselben Tags. Andere Größen/Generationen bleiben separate Modelle.
- Standardansicht mit einfachen Tags; alle Quantisierungen optional. Cloud-/MLX-Varianten sind ausgeschlossen. Der Download wird vorab durch ein Registry-Manifest mit lokalen Modellgewichten validiert.
- Herunterladen und Installieren erfolgt ausdrücklich per POST mit CSRF-Schutz. GET-Abfragen installieren nichts.
- Ein serieller systemd-Worker verwendet Ollamas `/api/pull` mit Streaming-Fortschritt, abschließender lokaler Modellprüfung und verständlicher Fehleranzeige. Er überlebt Neustarts des Server Managers. Laufzeitlimit: 24 Stunden, Lese-Timeout ohne Fortschrittsdaten: 180 Sekunden.
- Aufträge liegen privat in `/var/lib/server-manager/qwen-models`; verwaiste Aufträge werden als unterbrochen erkannt. Erneutes Installieren kann vorhandene Downloadteile verwenden.
- Ein Schlafblocker bleibt während des Downloads aktiv. Es gibt keine automatische Löschung alter Modelle und keine automatische Auswahl eines Modells für Chats.
- Größen sind Downloadgrößen, keine Zusage für RAM/VRAM-Bedarf oder Laufzeit-Kompatibilität. Ollama meldet fehlenden Speicher bzw. nicht unterstützte Modelle als Fehler.

Quellen: https://ollama.com/search?q=qwen und https://docs.ollama.com/api/pull

## Deinstallation

Installierte Qwen-Modelle besitzen eine Schaltfläche **Deinstallieren**. Die Bestätigungsseite nennt den genauen Modellnamen und verlangt eine ausdrückliche Bestätigung. Die Entfernung erfolgt per CSRF-geschütztem POST über Ollamas DELETE /api/delete. Während eines Modelldownloads wird die Entfernung blockiert; eine geänderte Modell-Prüfsumme verlangt eine neue Bestätigung. Nach der Entfernung wird die lokale Modellliste geprüft. Chats und andere Modellnamen bleiben erhalten; gemeinsam genutzte Modelldaten können den tatsächlich freigegebenen Speicher begrenzen.
