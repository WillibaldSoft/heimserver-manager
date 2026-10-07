#!/usr/bin/env python3
"""Require reviewed English counterparts for all published project descriptions."""
import argparse,hashlib,json,re
from pathlib import Path
try:from .build_deb import source_files,version
except ImportError:from build_deb import source_files,version

RENAMES={'Heimserver_Manager_Funktionsuebersicht.txt':'Home_Server_Manager_Features.txt','Heimserver_Manager_Versionsaenderungen.txt':'Home_Server_Manager_Version_History.txt'}
ROOT_DOCS=('README.md','CHANGELOG.md','LICENSE_NOTICE.md','THIRD_PARTY_NOTICES.md')
def sources(root):
    published={p for p in source_files(root) if p.suffix in ('.md','.txt') and not p.is_relative_to(root/'docs/en')}
    published.update(p for p in (root/'docs').iterdir() if p.is_file() and p.suffix in ('.md','.txt'))
    published.update(root/name for name in ROOT_DOCS)
    return sorted(published)
def destination(root,source):
    rel=source.relative_to(root)
    if source.parent in (root,root/'docs'):rel=Path(RENAMES.get(source.name,source.name))
    return root/'docs/en'/rel
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def mapping(root):
    return {str(p.relative_to(root)):{'english':str(destination(root,p).relative_to(root)),'source_sha256':digest(p),'english_sha256':digest(destination(root,p))} for p in sources(root)}
def check(root):
    saved=json.loads((root/'docs/en/translation-manifest.json').read_text())
    actual=mapping(root)
    if saved!=actual:raise ValueError('English documentation missing or stale; review translations, then refresh the documentation manifest.')
    current=version(root)
    features=(root/'docs/en/Home_Server_Manager_Features.txt').read_text()
    history=(root/'docs/en/Home_Server_Manager_Version_History.txt').read_text()
    if current not in features.splitlines()[1]:raise ValueError('English feature overview has a different version.')
    versions=re.findall(r'^([0-9]+\.[0-9]+-[0-9][\w.+~]*)\s*[–—-]',history,re.M)
    if not versions or versions[0]!=current:raise ValueError('English version history has a different latest version.')
    return len(actual)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--refresh',action='store_true',help='Record hashes only AFTER translations have been reviewed; does not translate.')
    args=parser.parse_args();root=args.source.resolve()
    if args.refresh:(root/'docs/en/translation-manifest.json').write_text(json.dumps(mapping(root),indent=2,sort_keys=True)+'\n')
    print(str(check(root))+' English documentation files current.')
if __name__=='__main__':main()
