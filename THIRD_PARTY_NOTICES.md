# Fremdkomponenten

## Mitgeliefert: Makeself 2.5.0-1 (Debian-Paketstand)

- Pfad: `modules/fotolabor/vendor/makeself/`
- Ursprung: https://makeself.io/ und Debian-Paket `makeself`
- Copyright: 1998–2023 Stéphane Peter und weitere im Quellcode genannte Autoren.
- Lizenz: **GPL-2.0-or-later** (Debian-Bezeichnung: GPL-2+).
- Unveränderte Lizenz- und Urheberhinweise: `COPYING` und `copyright` im obigen Verzeichnis.
- Die Shell-Quellen werden mitgeliefert. Die Projektlizenz ersetzt diese Hinweise nicht.

## Separat installierte Abhängigkeiten und Anwendungen

Python, Flask, Werkzeug, Pillow, libvirt, Waitress und Systemwerkzeuge werden
über die angegebenen Paketabhängigkeiten installiert. Optional installierte
Apps und Zusatzpakete behalten ihre jeweiligen Lizenzen. Ihre Dateien sind
nicht pauschal durch die Projektlizenz dieses Managers erfasst.

Vor Aufnahme weiterer Fremdquellen deren Herkunft, Lizenz und erforderliche
Hinweise dokumentieren. Diese Übersicht ist keine Behauptung, sämtliche
transitiven oder künftig hinzugefügten Abhängigkeiten vollständig zu erfassen.

## Optional heruntergeladen: Digital Devices dddvb

Der Treiber 0.9.41 wird bei ausdrücklich gestarteter Installation aus dem
Hersteller-Repository https://github.com/DigitalDevices/dddvb heruntergeladen.
Er ist kein Bestandteil der Manager-DEB. Seine Quell- und Lizenzdateien werden
unverändert im Treiber-Quellverzeichnis erhalten; die GPL-3.0-or-later-Lizenz
des Managers ersetzt die Lizenz des Treibers nicht.

## Optionale NVIDIA-Treiber

Die NVIDIA-Verwaltung installiert auf ausdrücklichen Auftrag Pakete aus den
konfigurierten Systemquellen. NVIDIA-Treiber und Firmware werden nicht mit dem
Manager ausgeliefert und behalten ihre eigenen, teilweise proprietären
Lizenzbedingungen. Die GPL-3.0-or-later des Managers lizenziert diese Komponenten
nicht um. Maßgeblich sind die Lizenzhinweise der jeweiligen Debian-Pakete.
