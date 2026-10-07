"""Generate bundled UI catalogs. No external service is contacted."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));import ui_translation as ui
code='''\nwindow.hsmTranslate=function(value){
 if(typeof value!=='string')return value;
 const core=value.trim(),direct=window.hsmTranslations[core];
 let translated=direct;
 if(translated===undefined){for(const [expression,pieces] of window.hsmMessagePatterns){const m=core.match(new RegExp('^(?:'+expression+')$','s'));if(m){translated=pieces.map(p=>typeof p==='string'?p:m[p[0]]).join('');break;}}}
 return translated===undefined?value:value.slice(0,value.length-value.trimStart().length)+translated+value.slice(value.trimEnd().length);
};\n'''
import argparse
parser=argparse.ArgumentParser(description='Build local browser translation catalogs.')
parser.add_argument('--check',action='store_true',help='Fail if generated catalogs are out of date.')
args=parser.parse_args()
folder=root/'static/i18n'
if not args.check:folder.mkdir(parents=True,exist_ok=True)
for lang in ('de','en'):
 data=json.dumps(ui.catalog(lang),ensure_ascii=True,separators=(',',':')).replace('<','\\u003c')
 patterns=json.dumps([(r.pattern,p) for r,p in ui.message_patterns(lang)],ensure_ascii=True,separators=(',',':')).replace('<','\\u003c')
 output='/* Local UI translations; no network services. */\nwindow.hsmTranslations='+data+';\nwindow.hsmMessagePatterns='+patterns+';'+code
 path=folder/(lang+'.js')
 if args.check:
  if not path.exists() or path.read_text()!=output:raise SystemExit('Translation asset out of date: '+str(path.relative_to(root)))
 else:path.write_text(output)
print('Translation assets verified.' if args.check else 'Translation assets generated.')
