# Fotolabor in Server Manager

Route: `/fotolabor`, Bestand fest: `/srv/fotolabor`.
Registrierung über `modules/fotolabor/plugin.py:register(app, ctx)`. Nutzt
`ctx.page`, `ctx.db`, die vorhandene SQLite-Datenbank und die zentrale Blocker-API.
`app.py` erhält ausschließlich den Navigationseintrag.

## Bedienung

1. Fotolabor öffnen und Werkzeugstatus prüfen.
2. „Vollständige Prüfung starten“. Ergebnisse, Dateitypen, Größe und Fortschritt
   werden gespeichert. Seitenwechsel beendet den Auftrag nicht.
3. Fehlerliste bzw. DNG-Kategorien öffnen; Listen sind auf 100 Zeilen je Seite begrenzt.
   Nach einer abgeschlossenen Prüfung bietet „Defekte Bilder als Textdatei
   herunterladen“ einen UTF-8-Bericht mit allen defekten Bildern, vollständigen
   Pfaden und Fehlergründen. Der Download ist nicht auf die sichtbaren 100 Zeilen
   begrenzt. Er enthält Scanzeit und Anzahl nicht prüfbarer Bilder; diese werden
   nicht mit bestätigten Defekten vermischt. Bei laufenden oder abgebrochenen
   Aufträgen bleibt der Bericht der letzten abgeschlossenen Prüfung verfügbar.
   Pfade mit Steuerzeichen werden zur eindeutigen Darstellung als JSON-String
   ausgegeben. Der Bericht liest ausschließlich gespeicherte Ergebnisse.
4. „DNG-Löschvorschau erstellen“ prüft den vollständigen Bestand und zeigt Anzahl
   und Speichergröße der sicheren DNGs samt XMP. Dabei wird nichts gelöscht.
   Erst die gesonderte Bestätigung mit `ja` startet die gezielte Sicherheitsprüfung
   und Löschung unveränderter, bestätigter Kandidaten. Kein weiterer Gesamtscan.
5. Aufträge können pausiert und fortgesetzt werden. Bereits geprüfte Dateien
   bleiben erhalten; beim Upgrade werden bisher ungeprüfte WebP erneut eingeplant.
   Unterbrochene Löschaufträge benötigen eine neue Vorschau und Bestätigung.
6. Die Scan-Historie erlaubt die Auswahl früherer Ergebnisse. Eine gezielte
   Nachprüfung kombiniert Dateityp, Status und Fehlergruppe. Sie erstellt einen
   eigenen Auftrag und überschreibt den ursprünglichen Bericht nicht.
7. Zusätzlich steht ein Textbericht aller nicht prüfbaren Dateien mit Pfaden,
   Fehlergruppen und Einzelgründen bereit. Beide Downloads sind nach Abschluss
   bzw. fertiger Vorschau verfügbar und enthalten sämtliche passenden Datensätze.

Debian 13:

```sh
sudo apt install jpeginfo pngcheck libtiff-tools libimage-exiftool-perl libraw-bin webp python3-pil
```

Fehlende Programme sperren die betroffenen Prüfungen; jpeginfo und ExifTool sind
für die Bereinigung zwingend. Keine automatische Paketinstallation.

## Prüfungen und Grenzen

- JPEG: `jpeginfo -c`, auch Warnungen verhindern die Löschung.
- PNG: `pngcheck`. Ausschließlich die bekannte zlib-Build-/Laufzeitversionsmeldung
  wird bei Rückgabewert 0 ignoriert; Bildfehler werden nicht ignoriert.
- TIFF: `tiffinfo -D` liest/dekomprimiert alle Bilddaten aller TIFF-Verzeichnisse.
- DNG/RAW: ExifTool plus `dcraw_emu -q 0 -Z -`; Bildausgabe wird verworfen,
  keine konvertierten Dateien werden angelegt. Nicht unterstützte Varianten bzw.
  Decoderwarnungen werden als nicht prüfbar ausgewiesen.
- WebP: `webpinfo -diag` und vollständige Pillow/libwebp-Dekodierung sämtlicher
  Einzelbilder, auch bei Animationen. Decoderfehler gelten als defekt, fehlende
  Unterstützung und Ressourcenlimits als nicht prüfbar.
- Weitere bekannte Bildformate werden erfasst, jedoch ohne passenden Decoder als
  nicht prüfbar angezeigt. Video-/Nichtbilddateien gehören nicht zur Bildstatistik.
- Ein erfolgreicher Decoderlauf beweist Lesbarkeit zum Prüfzeitpunkt, nicht die
  fotografische Richtigkeit, Vollständigkeit eines Archivs oder Abwesenheit früherer
  unbemerkter Bitänderungen. Es existiert kein historischer Prüfsummenbestand.

Quellen: [Debian tiffinfo](https://manpages.debian.org/trixie/libtiff-tools/tiffinfo.1.en.html),
[Debian jpeginfo](https://manpages.debian.org/trixie/jpeginfo/jpeginfo.1.en.html),
[LibRaw dcraw_emu](https://github.com/LibRaw/LibRaw/blob/master/samples/dcraw_emu.cpp).

## Löschsicherheit

Nur `XMP-xmpMM:HistoryParameters` mit
`converted from image/jpeg to image/dng` bestätigt JPEG-Herkunft. Die Referenzdatei
`/mnt/data/dng-jpeg-checker.sh` war weder lokal noch auf dem Server verfügbar;
die expliziten Sicherheitsanforderungen des Auftrags wurden nativ implementiert.

- Kategorie 2: JPEG gesund. Löschbarkeit verlangt zusätzlich passende Auflösung,
  bestätigte Dateitypen. Hauptmerkmal der Zuordnung ist derselbe exakte Dateistamm
  im selben Ordner. Unterschiede bei DateTimeOriginal/Make/Model sind nur Hinweise.
- Kategorie 3: JPEG fehlt. DNG und XMP bleiben erhalten.
- Kategorie 4: JPEG defekt, unprüfbar oder mehrdeutig. DNG und XMP bleiben erhalten.
- Kategorie 5: andere/RAW-DNGs oder ungeklärte Herkunft. Keine Löschung.

Dateistamm wird exakt verglichen, JPEG-Erweiterungen ohne Beachtung der Großschreibung.
Mehrere JPEG-Kandidaten schützen das DNG. Das DNG selbst kann von LibRaw nicht
unterstützt werden und trotzdem nach eindeutigem Herkunfts- und gesundem
JPEG-Nachweis ein Kandidat sein; diese Fälle bleiben in der Integritätsliste sichtbar.

Unmittelbar vor Löschung: erneute JPEG-Dekodierung, Herkunfts-/Auflösungsprüfung, offene
Dateideskriptoren, Inode-/Größen-/Zeitstempel- und SHA-256-Vergleich. Keine Symlinks
werden verfolgt, auch nicht in übergeordneten Pfadkomponenten. Werkzeuge erhalten
Dateideskriptoren statt Shell-Zeichenketten. JPG/JPEG sind niemals Löschziele.
`.dng.xmp` und gleichnamige `.xmp` werden nur mit zugehörigem freigegebenen DNG
entfernt. Möglicherweise mit einem weiteren RAW/DNG geteilte XMP schützen das Paket.

Während der Bereinigung dürfen keine anderen Programme den Bestand bearbeiten.
POSIX bietet keine atomare Transaktion über DNG/JPEG/XMP und fremde Schreibprozesse.
Bei einem Fehler nach DNG-Löschung können XMP zurückbleiben; das Audit zeigt
Einzelaktionen und Teilfehler. Es gibt keinen automatischen Wiederholungsversuch.

## Betrieb und Persistenz

Migration `migrations/0003_fotolabor.sql` wird idempotent bei Pluginregistrierung
angewendet; `0004_fotolabor_resume.sql` ergänzt Auftragsphasen, Filter und
Vorschau-Fingerabdrücke in zwei zusätzlichen Detailtabellen. Beide werden mit SHA-256 in `schema_migrations` vermerkt. Tabellen:
`fotolabor_jobs`, `fotolabor_files`, `fotolabor_audit`. Historische Ergebnisse und
Löschprotokolle bleiben erhalten. Größe/Zähler sind ein Scan-Snapshot; nach einer
Bereinigung für den neuen Bestand nochmals scannen.

Hintergrundthread entsprechend der vorhandenen Manager-Jobarchitektur; kein Vollscan
im HTTP-Request. Prozessübergreifende `flock`-Sperre verhindert konkurrierende Jobs.
Der zentrale Blocker besteht ab `queued` bis zum Abschluss/Abbruch. Bei einem
Dienstneustart werden verwaiste Aufträge als unterbrochen markiert, niemals
automatisch fortgesetzt. Über die Oberfläche lassen sich Prüfungen fortsetzen;
die fertige Vorschau hält keinen Schlafblocker. Das bestehende systemd-Service beendet seine Kindprozesse mit.
Ein nicht initialisierbares Modul blockiert die Schlafentscheidung konservativ.

## Tests

```sh
python3 -m py_compile app.py modules/blocker_api/registry.py modules/fotolabor/*.py
python3 -m unittest discover -s tests -p 'test_fotolabor*.py' -v
git diff --check
```

Alle Testbilder und Testlöschungen liegen ausschließlich in temporären Ordnern.
Echte Decoderprüfungen benötigen zusätzlich Pillow für die Testbildgenerierung
(`python3-pil`); für vollständige WebP-Prüfungen ist Pillow auch im Betrieb erforderlich.

Bekannte Hinweise zu MicrosoftPhoto-Namensraum, ausgelassenen großen Arrays und
veraltetem IPTCDigest verhindern die Paarzuordnung nicht allein. Erforderliche
Herkunft und Abmessungen müssen trotzdem nachgewiesen sein; optionale EXIF-Abweichungen werden seit 13.09.2026 nur als Hinweise behandelt.
Andere ExifTool-Warnungen und Fehler bleiben sperrend. Integritätswarnungen des
DNG bleiben unabhängig von seiner Löschbarkeit sichtbar.

## Duplikatsuche

Unter `/fotolabor/duplicates` startet eine gesonderte, rein lesende Suche im festen
Bildbestand. Dateigröße filtert Kandidaten, SHA-256 vergleicht vollständige Inhalte.
Dateinamen und Unterordner dürfen abweichen. Visuelle Ähnlichkeit oder umkodierte
Bilder werden nicht erkannt. Es gibt keine Duplikat-Löschaktion.

Der vorhandene Fotolabor-Worker, zentrale Schlafblocker und die Auftragsperre
werden wiederverwendet. Parallel zu einer laufenden Bildprüfung ist der Start
gesperrt. Pause/Fortsetzen erhält Ergebnisse. Migration 0005 speichert Hashes
getrennt von Integritätsbefunden; Inhaltsvergleich erzeugt kein Bild-OK.

Gruppen sind seitenweise abrufbar und nach Abschluss vollständig als Textdatei
herunterladbar. Symlinks werden nicht verfolgt, unlesbare oder während des Lesens
veränderte Dateien bleiben ausgeschlossen. Hardlinks erscheinen mit Anzahl der
unterschiedlichen Dateiobjekte. Ergebnisse gelten zum Lesezeitpunkt; spätere
Änderungen erfordern eine neue Suche. Es wird kein freigebbarer Speicher garantiert.

Bei Integritätsprüfungen und Bereinigungsvorschauen werden offene DNGs vor den
übrigen Formaten abgearbeitet, damit große WebP-Vorschaubestände ihre Zuordnung
nicht verzögern. Die Kategorieübersicht weist noch ungeprüfte DNGs separat aus.

## Automatische JPEG-Metadatenreparatur

Migration 0006 protokolliert Reparaturfälle. Bei normalen Prüfungen und Vorschauen
werden JPEGs mit erfolgreich dekodierten Bilddaten auf ExifTool-Metadatenhinweise
untersucht. Die Reparatur baut Metadaten ausschließlich in einer separaten Kopie
neu auf. Ausgaben liegen in privaten `fotolabor-repair-*`-Ordnern im Manager-State-Ordner,
außerhalb des Bildbestands; kein Original wird ersetzt. Im Löschlauf finden keine
Reparaturversuche statt. ExifTool, jpeginfo und Pillow werden benötigt.

Erfolg erfordert fehlerfreie erneute JPEG- und Metadatenprüfung sowie identische
Pixel, Farbprofile und Orientierung. Sonstige Metadaten können entfallen. Kopien
werden unter `/fotolabor/repairs` mit Grund und Download angezeigt; eine Sichtkontrolle
bleibt erforderlich. Beschädigte Bilddaten und andere Formate werden nicht automatisch
repariert. Alle erfassten Reparaturfälle schützen das zugehörige DNG dauerhaft.
Bereits abgearbeitete JPEGs benötigen eine gezielte Nachprüfung zur Kandidatenauswahl.

## Archiv, Teilprüfung, Planung und Wiederherstellung (Migration 0007)

`/fotolabor/tools` bietet relative Ordnerauswahl, Ausschlüsse (ein Pfad pro Zeile),
Vollprüfung, schnelle Prüfung neuer/geänderter Dateien und reine Prüfsummenkontrolle.
Scope und Lastoptionen werden je Auftrag gespeichert. Löschläufe verwenden ausschließlich die bestätigte Vorschau.
Schonender Betrieb setzt die Priorität des Worker-Threads (und seiner Decoder)
herab und pausiert zwischen Dateien. Optional wartet der Worker oberhalb einer
konfigurierten Systemlast; das ist keine feste CPU-Prozentbegrenzung.

`/fotolabor/archive` zeigt neue, unveränderte und inhaltlich geänderte Dateien.
Erste SHA-256-Werte bleiben erhalten; spätere Werte/Befunde werden separat gespeichert.
Schnellprüfungen übernehmen nur zuvor erfolgreiche Befunde bei identischen
Dateimerkmalen. Sie erkennen keine Bitänderungen bei unveränderten Merkmalen;
regelmäßige Voll-/Prüfsummenprüfungen sind dafür erforderlich. DNG-Paare werden
immer erneut geprüft. Alte Ergebnisse erhalten nicht rückwirkend Prüfsummen.

Zeitpläne werden bewusst zunächst inaktiv angelegt, sofern nicht aktiviert.
Tägliche Startzeit und Wochentage gelten in Server-Ortszeit. Fällige Aufträge warten
bei belegtem Worker; Starts werden transaktional mit der nächsten Fälligkeit
vermerkt. Ein neuer Fotolabor-RTC-Provider liefert Wecktermine an den bestehenden
zentralen RTC-Planer. Vorhandene Schlaf-/Weck-Einstellungen werden nicht verändert.

`/fotolabor/compare` vergleicht zwei abgeschlossene Integritätsprüfungen desselben
Teilbestands: neue Pfade, nicht mehr erfasste Pfade und Statuswechsel, seitenweise.
Reparaturen besitzen einen direkten Original/Kopie-Bildvergleich; kein Austausch.

`/fotolabor/restore` startet eine explizite DNG-Wiederherstellung im selben Worker.
LibRaw entwickelt ein 16-Bit-TIFF und daraus ein JPEG, ausschließlich in privaten
State-Unterordnern. Beide werden vollständig geprüft, zum Download und als Vorschau
angeboten. Farb-/Tonwertentwicklung kann vom historischen JPEG abweichen. Kein
fehlendes Detail wird erfunden; inkompatible DNGs bleiben als Fehler sichtbar.
Wiederherstellungsquellen sind dauerhaft gegen DNG-Bereinigung geschützt.

GIF (alle Frames) und BMP werden mit Pillow vollständig gelesen. HEIC/HEIF/AVIF
werden mit installiertem `heif-convert` (Debian: `libheif-examples`) einschließlich
seiner ausgegebenen Haupt-/Zusatzbilder dekodiert. Fehlende Decoder bleiben
„nicht prüfbar“. LibRaw 0.21.4 deckt die vorhandenen RAW-Endungen ab; nicht unterstützte
Kamera-/DNG-Varianten werden weiterhin nicht als gesund behauptet.


Seit 13.09.2026 gilt auf ausdrücklichen Wunsch die Dateinamen-Zuordnung vorrangig:
abweichende Aufnahmezeiten, Hersteller oder Modelle verhindern bei exaktem Stamm
im selben Ordner keine Freigabe. Eng begrenzte MakerNotes-Diagnosen (Offset,
Herstellerdaten nicht interpretierbar, CanonCameraSettings) sperren die benötigten
Standardmetadaten nicht pauschal. Herkunftseintrag, Dateitypen, Bildabmessungen und
JPEG-Dekodierung bleiben zwingend. Andere Warnungen/Fehler sowie mehrdeutige Paare
bleiben geschützt. Reparatur- und Wiederherstellungsquellen behalten ihren Schutz.
Die Integritätsanzeige des DNG bleibt von der Paarzuordnung getrennt.


Seit 13.09.2026 benötigt die Löschung keinen zweiten Gesamtscan. Sie übernimmt nur
freigegebene Kategorie-2-Pakete mit gespeicherten Vorschau-Fingerabdrücken.
Unmittelbar vor jedem Löschen werden Paketidentität, JPEG-Lesbarkeit, Herkunft,
Auflösung und Reparatur-/Wiederherstellungsschutz erneut geprüft. Neue Dateien
außerhalb der bestätigten Kandidaten werden nicht erfasst oder gelesen. Fortschritt
und Zähler des Löschauftrags beziehen sich auf DNG-Pakete, nicht den Gesamtbestand.


Persistierte Vorschauen tolerieren seit 14.09.2026 eine geänderte Gerätekennung
(st_dev), wie sie nach Neustart/Neueinbindung auftreten kann. Dateinummer, Größe,
Zeitstempel, Paketmitglieder und vollständige SHA-256-Inhalte müssen unverändert
bleiben. Während des eigentlichen Löschens gilt weiterhin die komplette
Dateisystemidentität einschließlich Gerätekennung als Veränderungsschutz.


Gezielte Reparaturaufträge verwenden ausschließlich die JPEG-Reparaturfälle einer
gespeicherten DNG-Vorschau. Bereits vorhandene erfolgreiche Kopien bleiben erhalten
und werden übersprungen. Die Reparatur erhält ICC-Farbprofile ausdrücklich; weiterhin
defekte MakerNotes/XMP/IPTC dürfen nur aus der Kopie entfernt werden. JPEG/MPO wird
einschließlich aller Einzelbilder verglichen. Unlesbare MPO-Zweitbilder bleiben
geschützt. Originale und DNGs werden nicht ersetzt oder zur Löschung freigegeben.


Übernahme und Löschvorbereitung (Migration 0008): Der ausdrückliche Button
„Geprüfte Reparaturen übernehmen“ sichert Originale in privaten
`fotolabor-original-*`-Ordnern im Manager-State-Verzeichnis und ersetzt sie atomar
durch separat erneut geprüfte Reparaturen. SHA-256, alle Bildframes, Farbprofile,
Orientierung, JPEG-/Metadatenprüfung sowie Dateistabilität werden kontrolliert.
Hardlinks bleiben von automatischer Übernahme ausgenommen. Eigentümer, Rechte,
Zeitstempel und erweiterte Attribute werden auf der Ersatzdatei erhalten.
Vorbereitete Übernahmen werden journalisiert und können nach Unterbrechung
abgeglichen werden. Kopien und Originalsicherung bleiben erhalten.

Nur ausdrücklich übernommene, seitdem unveränderte JPEGs dürfen ihren pauschalen
Reparaturschutz verlieren. DNG-Herkunft, gleiche Namen, passende Auflösung,
JPEG-Gesundheit sowie Sidecar-/Wiederherstellungsschutz bleiben maßgeblich.
Die gezielte Löschvorbereitung liest ausschließlich frühere Kategorie-2-Paare
und erzeugt eine neue gespeicherte Vorschau. Sie löscht keine DNGs.


## Gezielte MPF-Vorschaureparatur
Der Button unter Reparaturen bearbeitet ausschließlich gespeicherte MPO-Frame-Fehler. Ein eindeutig vorhandenes nachgestelltes JPEG-Vorschaubild erhält korrigierte MPF-Offsets/Längen. Fehlen nach dem Hauptbild sämtliche Zusatzdaten, wird nur das MPF-APP2-Segment entfernt. Andere Zusatzbilder, unklare Daten und beschädigte Hauptbilder bleiben geschützt. Hauptbildpixel, ICC und Orientierung werden verglichen; alle übrigen Bytes bleiben erhalten. Separate Kopien werden danach über den bestehenden gesicherten Übernahmeauftrag angewandt. Bestehende andere Metadatenwarnungen dürfen bei dieser exakt auf MPF begrenzten Änderung bestehen bleiben. Kein DNG wird automatisch gelöscht.
