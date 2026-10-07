# Fotoshow im Fotolabor

Aufruf: Fotolabor → Fotoshow erstellen (`/fotolabor/fotoshow`). Grundlage ist das bereitgestellte Skript `Fotoshow erstellen.sh`.

1. Quellordner im Fotolabor durch Anklicken öffnen und mit Checkbox bzw. „Diesen Ordner auswählen“ hinzufügen. Mehrere Ordner können kombiniert werden. „Gesamtes Fotolabor“ ist ausdrücklich auswählbar.
2. Unterordner optional einschalten; Dateinamen, Sekunden pro Bild (0,1–3600), Zufallsreihenfolge und Bildanpassung wählen.
3. Im Hintergrund erstellen. Die Auftragsseite zeigt Erfassung, Kopierfortschritt, Paketbau und Paketprüfung; Abbruch ist möglich.
4. Fertige `.run`-Datei herunterladen. Der Browser bestimmt den lokalen Zielordner. Start auf einem Linux-Desktop: `bash Fotoshow.run` (gewählten Dateinamen verwenden).

Wiedergabe benötigt feh und X11/XWayland. Es wird keine Software ungefragt auf dem Wiedergaberechner installiert. Pfeiltasten wechseln Bilder, Escape beendet die Fotoshow. Das temporär entpackte Paket wird bei normalem Beenden durch makeself entfernt. Ein harter Rechnerabbruch kann temporäre Dateien hinterlassen.

## Dateien und Sicherheit

Nur JPG/JPEG, keine Symlinks. Quellpfade sind auf `/srv/fotolabor` begrenzt und komponentenweise ohne Symlink-Verfolgung geöffnet. Überlappende Auswahl wird anhand relativer Pfade dedupliziert. Namen mit Leerzeichen, Umlauten, Anführungszeichen und Zeilenumbrüchen werden korrekt kopiert. Im Paket erhalten Bilder nummerierte Dateinamen; `Bildliste.json` erhält die Zuordnung zu ursprünglichen relativen Pfaden. Diese Pfade sind somit Bestandteil des heruntergeladenen Pakets.

Die Quellen bleiben unverändert. Beim Kopieren werden Dateityp, Identität, Größe, Zeitstempel und JPEG-Dateianfang geprüft. Das ist keine vollständige Bildintegritätsprüfung; dafür bietet das Fotolabor seine vorhandenen Prüfungen an. Fehler führen zu einem sichtbaren Fehlschlag statt einer unvollständigen Fotoshow.

Maximal 100 ausgewählte Ordner und 100.000 Bilder je Auftrag. Vor dem Kopieren sind mindestens zweimal die Quelldatenmenge plus 256 MiB Reserve nötig. Pakete werden mit niedriger gzip-Kompression erzeugt, mit makeself geprüft und mit SHA-256 dokumentiert.

## Integration

Persistenz: `fotolabor_slideshows` in der bestehenden SQLite-DB. Gemeinsame Sperre `fotolabor.lock` verhindert Überschneidung mit Prüf-/Reparatur-/Löschaufträgen. Zentraler Fotolabor-Blocker verhindert automatischen Schlaf während der Erstellung. Nach Neustart werden unvollständige Aufträge als unterbrochen markiert und deren temporäre Kopien entfernt.

Serverausgabe: `STATE_DIR/fotoshows/<Auftrag>/fotoshow.run`, standardmäßig `/var/lib/server-manager/fotoshows`. Fertige Pakete bleiben für erneute Downloads erhalten. Es gibt keinen automatischen Versand und keine automatische Löschung fertiger Pakete.

Neue Dateien: `slideshow.py`, `slideshow_ui.py`, `vendor/makeself/`, Tests und diese Dokumentation. Kleine Ergänzungen in `plugin.py` und `blocker_provider.py`.

## Paketgenerator

Falls systemweit makeself installiert ist, wird dieser genutzt. Sonst ist unverändert der offizielle Debian-Trixie-Paketinhalt `makeself 2.5.0-1` enthalten, inklusive Copyright und GPL-2-Lizenz. Keine systemweite Paketinstallation erforderlich. Die vom Generator erstellten Archive sind laut dessen Lizenzhinweis nicht automatisch GPL-lizenziert.

Quelle: https://makeself.io/ · feh-Dokumentation: https://man.finalrewind.org/1/feh/

Tests: `python3 -m unittest discover -s tests -p 'test_fotolabor_slideshow.py' -v`. Einschließlich echter Paketerstellung/-prüfung, Extraktion, Download, Sonderzeichen, Path-Traversal-/Symlink-Schutz, Deduplizierung, Abbruch, Sperre und Wiederanlauf. Die Tests verwenden ausschließlich temporäre Testbilder.
