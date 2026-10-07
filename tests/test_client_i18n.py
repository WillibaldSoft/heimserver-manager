"""Language selection must not change wire/configuration values."""
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT/'client_agent/desktop'
sys.path.insert(0,str(DESKTOP))
import client_i18n as i18n
import core

class ClientLanguageTests(unittest.TestCase):
    def test_desktop_selection(self):
        for code, expected in [('de','de'),('de_DE.UTF-8','de'),('de-AT','de'),('de_CH','de'),('en_US.UTF-8','en'),('fr_FR','en'),('C','en'),('','en')]:
            self.assertEqual(expected,i18n.desktop_language({'LANG':code}))
        self.assertEqual('en',i18n.desktop_language({'LANGUAGE':'fr:de','LANG':'de_DE'}))
        self.assertEqual('de',i18n.desktop_language({'LANGUAGE':'de:en','LANG':'en_US'}))
        self.assertEqual('en',i18n.desktop_language({'LC_ALL':'en_US','LC_MESSAGES':'de_DE'}))
        self.assertEqual('de',i18n.desktop_language({'LC_MESSAGES':'de_DE','LANG':'fr_FR'}))
    def test_display_only(self):
        cfg=dict(core.DEFAULTS,SERVER_URL='https://server.example',TOKEN='test-token',CLIENT_NAME='Eigener Name',CLIENT_MODE='with_server')
        for language in ('de','en'):
            with patch.object(i18n,'LANGUAGE',language):
                self.assertEqual(cfg,core.validate(cfg))
                self.assertEqual('Eigener Name',i18n.tr('Eigener Name'))
                self.assertEqual('with_server',i18n.tr('with_server'))
                self.assertEqual('Speichern' if language=='de' else 'Save',i18n.tr('Speichern'))
    def test_all_marked_literals_have_translations(self):
        catalog=json.loads((DESKTOP/'client_en.json').read_text())
        for path in DESKTOP.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and node.args and isinstance(node.args[0],ast.Constant):
                    self.assertIn(node.args[0].value,catalog,str(path))
    def test_non_german_process_defaults_to_english(self):
        code="import client_i18n;print(client_i18n.tr('Sicherung starten'))"
        for lang in ('en_US.UTF-8','fr_FR.UTF-8','de_DE.UTF-8'):
            env=dict(os.environ,LANG=lang,PYTHONPATH=str(DESKTOP));env.pop('LANGUAGE',None);env.pop('LC_ALL',None);env.pop('LC_MESSAGES',None)
            value=subprocess.check_output([sys.executable,'-c',code],env=env,text=True).strip()
            self.assertEqual('Sicherung starten' if lang.startswith('de') else 'Start backup',value)
    def test_destructive_confirmation_is_stable(self):
        source=(DESKTOP/'system_restore_ui.py').read_text()
        self.assertIn("e.get_text()=='WIEDERHERSTELLEN'",source)
        self.assertIn('WIEDERHERSTELLEN',i18n._CATALOG[' MiB\nSystemdateien und Benutzer werden überschrieben. fstab/crypttab bleiben erhalten. Zusätzliche Zieldateien werden nicht gelöscht. Bootloader vor Neustart prüfen.\nZum Bestätigen WIEDERHERSTELLEN eingeben.'])
