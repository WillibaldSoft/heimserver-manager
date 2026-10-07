"""Client presentation language; never changes protocol keys or OS locale."""
import json
import os
from pathlib import Path


def desktop_language(environ=None):
    env = os.environ if environ is None else environ
    # LANGUAGE is the desktop message-language preference list, not number format.
    preference = env.get('LANGUAGE') or env.get('LC_ALL') or env.get('LC_MESSAGES') or env.get('LANG') or 'en'
    primary = preference.split(':', 1)[0].split('.', 1)[0].split('@', 1)[0]
    return 'de' if primary.lower().replace('-', '_').split('_', 1)[0] == 'de' else 'en'


LANGUAGE = desktop_language()
_CATALOG = json.loads(Path(__file__).with_name('client_en.json').read_text(encoding='utf-8'))


def tr(message):
    """Translate only an explicit application-authored string before formatting."""
    return message if LANGUAGE == 'de' else _CATALOG.get(message, message)
