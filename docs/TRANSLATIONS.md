# Deutsch und Englisch in der Weboberfläche

Die Sprachwahl gilt pro Browser. Die Geschäftsdaten und gespeicherten
Einstellungen werden durch die Sprachwahl nicht übersetzt.

## Neue Oberflächentexte

- Deutsche Originaltexte und englische Übersetzungen in `locales/en.json` pflegen.
  `locales/de.json` vereinheitlicht bisher englische Begriffe in der deutschen Anzeige.
- Statisches HTML mit `ui_translation.html_literal` übersetzen, **bevor**
  `.format`, `%` oder Verkettung Benutzerdaten einsetzen. Keine vollständig
  gerenderte Seite nachträglich durch einen Übersetzer schicken.
- `ui_translation.text` nur für Anwendungsbeschriftungen und Meldungen verwenden,
  niemals für Gerätenamen, Dateinamen, Datenbank-/Protokollschlüssel oder Formwerte.
- Pfade, URLs, Kommandos, technische Logs, JSON-Schlüssel und Benutzerdaten
  bleiben unverändert. Originale Diagnoseausgaben behalten ihre Herkunftssprache.
- Platzhalter, Zahlen, Pfade und technische Bezeichner müssen erhalten bleiben.
- Bestätigungsdialoge und dynamische Fehlermeldungen ebenfalls berücksichtigen.
- Statische Browser-Kataloge unter `static/i18n/` mit dem Katalog synchron halten.
  Mit `python3 tools/build_translations.py` erzeugen;
  `python3 tools/build_translations.py --check` prüft den Gleichstand.
  Sie werden lokal ausgeliefert; der laufende Manager verwendet keinen
  externen Übersetzungsdienst und benötigt dafür kein Sprachmodell.

## Prüfungen

`python3 -m unittest tests.test_ui_translation tests.test_i18n`

Vor Veröffentlichung außerdem den Release-Dateibestand prüfen. Katalog,
Übersetzungshelfer und beide Browserdateien müssen im Paket enthalten sein.
