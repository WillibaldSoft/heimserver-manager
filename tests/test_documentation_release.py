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
