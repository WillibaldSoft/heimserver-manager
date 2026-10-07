# GitHub-Releases

Ein Aufruf baut alle Veröffentlichungsdateien:

```bash
python3 tools/build_release.py --output-root dist
```

Vorher `version.py`, Funktionsübersicht und Versionshistorie aktualisieren.
Die gesamte vorhandene Versionshistorie wird automatisch zu `RELEASE_NOTES.md`,
mit der neuesten Version zuerst. Die Funktionsübersicht muss zusätzlich zur
aktuellen Kopfzeile einen Abschnitt `NEU UND GEÄNDERT IN VERSION <Version>` enthalten.
Vorhandene Releaseordner werden nicht überschrieben. Die Release-Dateiliste
in `packaging/source-manifest.json` ist verbindlich; fehlende Dateien brechen
den Build ab. Optional private Suchbegriffe mit `--forbidden-file` prüfen.
Diese Datei niemals committen. Die heuristische Prüfung ersetzt keine Durchsicht.

Ergebnis: DEB, Einzelprüfsumme, Installer mit Zusatzmodi, Installationshinweise,
Funktionsübersicht, Versionshistorie, Release Notes, Quellarchiv,
Dateimanifest, Komplett-ZIP und SHA256SUMS. Alle Builds verwenden standardmäßig
SOURCE_DATE_EPOCH=0. Bytegleiche Ergebnisse setzen dieselben Buildwerkzeuge voraus.

Für ein neues öffentliches Repository das generierte Quellarchiv als Ausgangspunkt
verwenden. Das bestehende Server-Repository enthält historische Kontextdateien
und persönliche Daten: dessen kompletten Arbeitsbaum oder Git-Verlauf nicht
ungeprüft hochladen. Die Projektlizenz ist GPL-3.0-or-later. `LICENSE`, `LICENSE_NOTICE.md` und
`THIRD_PARTY_NOTICES.md` werden in alle Veröffentlichungspakete aufgenommen. Der Autorenhinweis bleibt erhalten.

Nach Einrichtung des GitHub-Repositorys den geprüften Stand committen und mit
`v<Version>` taggen, beispielsweise `v0.12-42`. Den Tag pushen. Der Workflow
prüft Version und Tag, baut zweimal, vergleicht Prüfsummen und erstellt einen
Release-Entwurf mit allen Dateien. Den Entwurf nach Durchsicht veröffentlichen.
Ein manueller Workflowstart muss ebenfalls auf dem Versionstag erfolgen.
Existierende Releases werden nicht automatisch ersetzt. Der Workflow verwendet
GITHUB_TOKEN mit contents: write; keine separaten persönlichen Tokens nötig.

GitHub erzeugt zusätzlich eigene Source-Code-Archive des vollständigen Tags.
Auch deshalb gehört nur der überprüfte Quellstand in das veröffentlichte Repository.

Dokumentation:
https://cli.github.com/manual/gh_release_create
https://github.com/actions/checkout

## Plattformstatus
Debian 13 ist der reguläre Entwicklungs- und Veröffentlichungsstand.
Linux Mint 22.x bleibt experimentell. Beide Profile getrennt mit --target
bauen. Der Status steht im Paket und im jeweiligen Release-Manifest.
Der Workflow erstellt einen regulären Entwurf; Mint-Assets und Plattformhinweise
bleiben ausdrücklich experimentell gekennzeichnet. Veröffentlichung erst nach
Durchsicht. Versionsnummern werden fortlaufend vergeben, ohne platform-Zusatz.
Version 0.12-47 bleibt unveränderter Sicherungsstand.

## Deutsche und englische Dokumentation
Alle Beschreibungen unter docs sowie README, CHANGELOG und rechtliche Erläuterungen in docs/en pflegen.
Funktionsübersicht, vollständige Versionshistorie und Installationshinweise müssen
in beiden Sprachen dieselbe Version und inhaltlichen Änderungen enthalten.
Der Releasebau prüft docs/en/translation-manifest.json gegen die Quelltexte und
englischen Dateien. Nach jeder Änderung Übersetzung prüfen und Manifest mit
python3 tools/check_documentation.py --refresh aktualisieren. Dieser Befehl
übersetzt nicht automatisch; er bestätigt nur die zuvor geprüfte Zuordnung.
Ein normaler Build bricht bei fehlenden oder veralteten Übersetzungen ab.
Die Pakete werden zusätzlich mit englischen Release Notes und einem
zweisprachigen Dokumentations-ZIP bereitgestellt. Keine persönlichen
Serverwerte in Dokumentation, Manifest oder Quellarchiv aufnehmen.
