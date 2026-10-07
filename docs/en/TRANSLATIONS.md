# German and English in the Web Interface

The language selection applies per browser. Business data and saved settings are not translated by the language choice.

## New Surface Texts

- Maintain German original texts and English translations in `locales/en.json`.
  `locales/de.json` unifies previously used English terms in the German display.
- Translate static HTML with `ui_translation.html_literal` **before**
  inserting `.format`, `%` or concatenated user data. Do not send a fully rendered page to a translator afterward.
- Use `ui_translation.text` only for application labels and messages,
  never for device names, file names, database/log keys, or form values.
- Paths, URLs, commands, technical logs, JSON keys, and user data
  remain unchanged. Original diagnostic outputs retain their source language.
- Placeholders, numbers, paths, and technical identifiers must be preserved.
- Consider confirmation dialogs and dynamic error messages as well.
- Keep static browser catalogs under `static/i18n/` synchronized with the catalog.
  Generate them using `python3 tools/build_translations.py`;
  `python3 tools/build_translations.py --check` checks for consistency.
  They are served locally; the running manager does not use an external translation service and therefore requires no language model.

## Checks

`python3 -m unittest tests.test_ui_translation tests.test_i18n`

Also check the release file before publishing. The catalog, translation helper, and both browser files must be included in the package.
