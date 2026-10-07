#!/usr/bin/env python3
"""Build an immutable, allowlisted release directory; never publish or install."""
import argparse,gzip,hashlib,io,json,os,re,shutil,subprocess,tarfile,tempfile,zipfile
from pathlib import Path
from build_deb import build,source_files,version
from platform_check import PROFILES
from privacy_check import scan,RULES
from check_documentation import check as check_documentation

LEGAL=('LICENSE','LICENSE_NOTICE.md','THIRD_PARTY_NOTICES.md')
EXTRA=('.github/workflows/release.yml','.gitignore')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def release(root,output_root,forbidden=(),platform="debian13"):
 if platform not in PROFILES:raise ValueError("Unbekannte Plattform")
 root=root.resolve();check_documentation(root);current=version(root);target=output_root.resolve()/('heimserver-manager-'+current+'-'+platform)
 if target.exists():raise ValueError('Release existiert bereits; neue Version verwenden: '+str(target))
 inventory=json.loads((root/'packaging/source-manifest.json').read_text())
 selected={str(p.relative_to(root)):p for p in source_files(root)}
 missing=set(inventory)-set(selected)
 if missing:raise ValueError('Release-Dateien fehlen oder sind nicht erlaubt: '+', '.join(sorted(missing)))
 for name in EXTRA:
  p=root/name
  if p.is_symlink() or not p.is_file():raise ValueError('Release-Zusatz fehlt: '+name)
  selected[name]=p
 findings=scan(root,forbidden)
 for name in EXTRA:
  text=selected[name].read_text()
  findings += [(name,rule) for rule,pattern in RULES.items() if pattern.search(text)]
  if any(v and v.casefold() in text.casefold() for v in forbidden):findings.append((name,'host-specific-value'))
 if findings:raise ValueError('Datenschutzprüfung: '+repr(findings))
 if any(name not in selected for name in LEGAL):raise ValueError('Lizenzdateien fehlen')
 if 'GPL-3.0-or-later' not in (root/'LICENSE_NOTICE.md').read_text():raise ValueError('Projektlizenz fehlt oder hat sich geändert; Release-Regel prüfen')
 overview=(root/'docs/Heimserver_Manager_Funktionsuebersicht.txt').read_text()
 history=(root/'docs/Heimserver_Manager_Versionsaenderungen.txt').read_text()
 if 'Stand: Version '+current+' ·' not in overview:raise ValueError('Funktionsübersicht hat falsche Version')
 matches=list(re.finditer(r'^\d+(?:\.\d+)*-[0-9][a-zA-Z0-9.+~]* – .+$',history,re.M))
 if not matches or not matches[0].group().startswith(current+' –'):raise ValueError('Versionshistorie hat falschen neuesten Eintrag')
 notes=re.sub(r'^(\d+(?:\.\d+)*-[0-9][a-zA-Z0-9.+~]* – .+)$',r'## \1',history[matches[0].start():].strip(),flags=re.M)+'\n'
 if 'NEU UND GEÄNDERT IN VERSION '+current not in overview:raise ValueError('Funktionsübersicht braucht einen Abschnitt für die aktuelle Version')
 # A fixed epoch makes assets independent of checkout mtimes and Git history.
 epoch=int(os.environ.get('SOURCE_DATE_EPOCH','0'))
 output_root.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.release-',dir=output_root) as temp:
  stage=Path(temp)/target.name;stage.mkdir()
  deb=stage/('Heimserver_Manager_'+current+'_'+({'debian13':'Debian','mint22':'Mint'}[platform])+'.deb');build(root,deb,target=platform)
  actual=subprocess.check_output(['dpkg-deb','-f',str(deb),'Version'],text=True).strip()
  if actual!=current:raise ValueError('DEB-Version stimmt nicht überein')
  for name in ('Heimserver_Manager_Funktionsuebersicht.txt','Heimserver_Manager_Versionsaenderungen.txt'):shutil.copyfile(root/'docs'/name,stage/name)
  (stage/'RELEASE_NOTES.md').write_text('# Heimserver Manager '+current+'\n\nVollständige vorhandene Versionshistorie ab '+matches[-1].group().split(' – ')[0]+'. Neueste Änderungen zuerst.\n\n'+notes)
  shutil.copyfile(root/'docs/RELEASE_INSTALLATION.txt',stage/'INSTALLATION.txt')
  for name in ('Home_Server_Manager_Features.txt','Home_Server_Manager_Version_History.txt'):
   shutil.copyfile(root/'docs/en'/name,stage/name)
  shutil.copyfile(root/'docs/en/RELEASE_INSTALLATION.txt',stage/'INSTALLATION_EN.txt')
  english_history=(root/'docs/en/Home_Server_Manager_Version_History.txt').read_text()
  (stage/'RELEASE_NOTES_EN.md').write_text('# Home Server Manager '+current+'\n\n'+english_history)
  (stage/'PLATFORM_EN.txt').write_text(PROFILES[platform]['label']+'\n'+('Experimental build; not approved for production.' if PROFILES[platform]['experimental'] else 'Regular Debian release.')+'\nDebian packages: Debian 13 only. Mint packages: Mint 22.x/Noble only.\n')
  with zipfile.ZipFile(stage/('Documentation_'+current+'_DE_EN.zip'),'w',compression=zipfile.ZIP_DEFLATED) as docs_zip:
   for name,p in sorted(selected.items()):
    if name.startswith('docs/') or name in ('README.md','CHANGELOG.md'):
     entry=zipfile.ZipInfo(name,(1980,1,1,0,0,0));entry.external_attr=0o100644<<16;entry.compress_type=zipfile.ZIP_DEFLATED;docs_zip.writestr(entry,p.read_bytes())

  (stage/'PLATTFORM.txt').write_text(PROFILES[platform]['label']+'\n'+('Experimenteller Entwicklungsstand. Nicht auf Produktivsystemen freigegeben.' if PROFILES[platform]['experimental'] else 'Regulärer Debian-Stand; experimentelle Debian-Phase beendet.')+'\nDebian-Pakete nur auf Debian 13; Mint-Pakete nur auf Mint 22.x/Noble.\n')
  for name in LEGAL:shutil.copyfile(root/name,stage/name)
  # Export only the package inventory and explicitly listed build metadata.
  # No .git history, local snapshots, databases, runtime state or credentials.
  source=stage/('heimserver-manager-'+current+'-source.tar.gz')
  with source.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=epoch) as gz,tarfile.open(fileobj=gz,mode='w',format=tarfile.GNU_FORMAT) as archive:
   for name,p in sorted(selected.items()):
    info=tarfile.TarInfo('heimserver-manager-'+current+'/'+name);data=p.read_bytes();info.size=len(data);info.mtime=epoch;info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o755 if p.suffix=='.sh' or p.parent.name=='helpers' else 0o644
    archive.addfile(info,io.BytesIO(data))
  metadata={'target_platform':platform,'experimental':PROFILES[platform]['experimental'],'license':'GPL-3.0-or-later','third_party_licenses':{'makeself':'GPL-2.0-or-later'},'version':current,'package':'server-manager','architecture':'all','target_os':PROFILES[platform]['label'],'source_date_epoch':epoch,'source_files':{name:sha(p) for name,p in sorted(selected.items())},'assets':{p.name:sha(p) for p in sorted(stage.iterdir())}}
  (stage/'release-manifest.json').write_text(json.dumps(metadata,indent=2,sort_keys=True)+'\n')
  bundle=stage/('Heimserver_Manager_'+current+'_'+({'debian13':'Debian','mint22':'Mint'}[platform])+'_Komplett.zip')
  with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
   for p in sorted(stage.iterdir()):
    if p==bundle:continue
    info=zipfile.ZipInfo(p.name,date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=(0o100755 if p.suffix=='.sh' else 0o100644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
    archive.writestr(info,p.read_bytes())
  (stage/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(stage.iterdir())))
  stage.rename(target)
 return target

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--output-root',type=Path,default=Path('dist'));parser.add_argument('--forbidden-file',type=Path)
 parser.add_argument('--target',choices=PROFILES,default='debian13')
 args=parser.parse_args();print(release(args.source,args.output_root,args.forbidden_file.read_text().splitlines() if args.forbidden_file else (),args.target))
if __name__=='__main__':main()
