import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import check_documentation as docs
from build_deb import source_files
class DocumentationRelease(unittest.TestCase):
 def test_current_documents_and_client_catalogs_are_packaged(self):
  self.assertGreaterEqual(docs.check(ROOT),50)
  included={str(p.relative_to(ROOT)) for p in source_files(ROOT)}
  for p in docs.sources(ROOT):self.assertIn(str(docs.destination(ROOT,p).relative_to(ROOT)),included)
  for p in ('client_agent/desktop/client_en.json','client_agent/windows/client_en.json','docs/en/translation-manifest.json'):self.assertIn(p,included)
 def test_manifest_detects_stale_translation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'docs/en').mkdir(parents=True)
   (root/'packaging').mkdir();(root/'packaging/source-manifest.json').write_text('[]')
   for name in docs.ROOT_DOCS:(root/name).write_text('source');(root/'docs/en'/name).write_text('english')
   (root/'version.py').write_text('VERSION="1.0-1"')
   (root/'docs/en/translation-manifest.json').write_text(json.dumps(docs.mapping(root)))
   (root/'README.md').write_text('changed source')
   with self.assertRaisesRegex(ValueError,'stale'):docs.check(root)
 def test_reviewed_hashes_do_not_hide_wrong_current_versions(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'docs/en').mkdir(parents=True)
   content={'version.py':'VERSION="0.13-1"',
    'docs/en/translation-manifest.json':'{}',
    'CHANGELOG.md':'# CHANGELOG\n\nAktuelle Version: **0.13-1**\n',
    'docs/en/CHANGELOG.md':'# CHANGELOG\n\nCurrent version: **0.13-1**\n',
    'docs/Heimserver_Manager_Funktionsuebersicht.txt':'Features\nStand: Version 0.13-1 · Datum\n',
    'docs/en/Home_Server_Manager_Features.txt':'Features\nStatus: Version 0.13-1\n',
    'docs/Heimserver_Manager_Versionsaenderungen.txt':'0.13-1 – Datum\n',
    'docs/en/Home_Server_Manager_Version_History.txt':'0.13-1 – Date\n'}
   for name,text in content.items():(root/name).write_text(text)
   with patch.object(docs,'mapping',return_value={}):
    self.assertEqual(0,docs.check(root))
    for name in ('CHANGELOG.md','docs/en/CHANGELOG.md','docs/Heimserver_Manager_Funktionsuebersicht.txt','docs/Heimserver_Manager_Versionsaenderungen.txt'):
     (root/name).write_text(content[name].replace('0.13-1','0.12-64'))
     with self.assertRaises(ValueError,msg=name):docs.check(root)
     (root/name).write_text(content[name])
