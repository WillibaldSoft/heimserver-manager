"""Shared presentation only: responsive layout and progressive navigation/table helpers."""
import json

CSS = r'''
:root{color-scheme:dark;--layout-gap:16px}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{max-width:1680px;margin:0 auto;padding:clamp(12px,2.3vw,28px);line-height:1.5}
main,.card,.grid,.grid>*{min-width:0}
.card{overflow-wrap:anywhere}
.grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:var(--layout-gap)}
.grid>.card{margin-bottom:0}
h1{font-size:clamp(1.45rem,2.4vw,2rem);line-height:1.2;margin:0 0 18px;overflow-wrap:anywhere}
h2{font-size:1.3rem;line-height:1.3}h3{font-size:1.1rem;line-height:1.35}
p{margin:12px 0}li+li{margin-top:4px}
.app-brand{display:inline-block;color:#cbd5e1;font-size:.85rem;margin-bottom:6px}
button,input,select,textarea{font:inherit}
button,.btn,.pill,input[type=submit],input[type=button]{min-height:44px;max-width:100%;padding:10px 14px;line-height:1.35;white-space:normal;overflow-wrap:anywhere;vertical-align:middle;cursor:pointer}
button,input[type=submit],input[type=button]{background:#374151;color:#f9fafb;border:1px solid #64748b;border-radius:9px}
button:disabled,input:disabled,select:disabled{cursor:not-allowed;opacity:.6}
input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]):not([type=range]):not([type=color]),select,textarea{max-width:100%;min-width:0;min-height:44px;padding:9px 11px;color:#f9fafb;background:#111827;border:1px solid #64748b;border-radius:8px}
input[type=checkbox],input[type=radio]{width:20px;height:20px;max-width:20px;vertical-align:middle;accent-color:#60a5fa}
input[type=file]{white-space:normal}textarea{resize:vertical;line-height:1.5}
label,fieldset,form{max-width:100%;min-width:0}fieldset{border-color:#64748b}
:focus-visible{outline:3px solid #93c5fd;outline-offset:3px}
.main-nav,.sub-nav{gap:6px}.main-nav .btn,.sub-nav .btn{margin:0}
.navigation-panel>summary{display:none;cursor:pointer;font-weight:600;min-height:44px;padding:10px 12px;border:1px solid #64748b;border-radius:8px;background:#273449}
.navigation-panel>summary::marker{color:#93c5fd}
.account-panel{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;margin-top:14px}
.account-toolbar{margin-top:0!important}
.account-notice{order:3;flex-basis:100%;margin:0}
.account-panel .language-selector{margin:0 0 0 auto!important}
.language-selector{flex-wrap:wrap}.language-selector label{display:inline-flex;align-items:center;gap:8px}
pre{max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5;tab-size:4}
code{overflow-wrap:anywhere}img,video,canvas{max-width:100%}
.table-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-color:#64748b #111827}
.table-scroll>table{width:100%}.table-scroll>table.layout-wide{min-width:44rem}
.table-scroll:focus-visible{outline-offset:-3px}
.table-scroll-hint{color:#93c5fd;font-size:.85rem;margin:6px 0}
th,td{padding:10px;line-height:1.45}
.skip-link{position:absolute;left:16px;top:-100px;background:#1d4ed8;color:white;padding:12px;z-index:100}
.skip-link:focus{top:12px}
@media(max-width:700px){
 body{padding:12px;--layout-gap:12px}
 .card{padding:14px;border-radius:12px;margin-bottom:12px}
 .app-header h1{margin-bottom:12px}
 .navigation-panel>summary{display:list-item;list-style-position:inside}
 .navigation-content{padding-top:12px}
 .main-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
 .main-nav .btn{display:flex;align-items:center;justify-content:center;text-align:center}
 .sub-nav{gap:8px}.sub-nav .btn{flex:1 1 130px;text-align:center}
 .grid{grid-template-columns:minmax(0,1fr)!important}
 input,select,textarea{font-size:16px}
 .language-selector{gap:8px!important}
 .account-panel .language-selector{margin-left:0!important}
 .auth-page{padding:12px}.auth-page main{padding:20px;max-width:440px;margin:24px auto}
 .auth-page h1{font-size:1.65rem}
 .table-scroll>table.form-table{display:block;min-width:0}
 .form-table thead{display:none}.form-table tbody{display:block}
 .form-table tr{display:block;border-bottom:1px solid #64748b;padding:12px 0}
 .form-table .form-table-head{display:none}
 .form-table td{display:block;border:0;padding:7px 0;max-width:100%}
 .form-table td::before{content:attr(data-column);display:block;color:#cbd5e1;font-weight:600;margin-bottom:5px}
 .form-table td[data-column=""]::before{display:none}
 .form-table input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.form-table select,.form-table textarea{width:100%!important}
 #epg-scroll{max-height:70svh}
 #epg-scroll .epg-table{width:calc(var(--epg-width) + 120px)}
 #epg-scroll .epg-table th:first-child{width:120px;min-width:120px}
}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
'''

def script(table_label):
    return '''<script>
(()=>{
 const panel=document.querySelector('.navigation-panel');
 if(panel){
   const small=window.matchMedia('(max-width:700px)');
   const adapt=()=>{panel.open=!small.matches;};
   adapt();small.addEventListener('change',adapt);
 }
 document.querySelectorAll('main table').forEach(table=>{
   // Preserve EPG's two-axis scroller and sticky channel/time headings.
   if(table.closest('#epg-scroll,.epg-scroll'))return;
   let parent=table.parentElement;
   const overflow=getComputedStyle(parent).overflowX;
   let wrapper=parent;
   if(!['auto','scroll'].includes(overflow)){
     wrapper=document.createElement('div');table.before(wrapper);wrapper.append(table);
   }
   wrapper.classList.add('table-scroll');
   wrapper.setAttribute('role','region');wrapper.setAttribute('aria-label',TABLE_LABEL);
   const cells=table.rows[0]?.cells;
   if(cells&&Array.from(cells).reduce((n,c)=>n+c.colSpan,0)>3)table.classList.add('layout-wide');
   if(cells&&Array.from(cells).some(c=>c.tagName==='TH')&&table.querySelector('input:not([type=hidden]),select,textarea')&&
      Array.from(table.rows).every(row=>row.cells.length===cells.length&&Array.from(row.cells).every(c=>c.colSpan===1&&c.rowSpan===1))){
     table.classList.add('form-table');table.rows[0].classList.add('form-table-head');
     Array.from(table.rows).slice(1).forEach(row=>Array.from(row.cells).forEach((cell,i)=>cell.dataset.column=cells[i].textContent.trim()));
   }
   const hint=document.createElement('p');hint.className='table-scroll-hint';hint.textContent='↔ '+TABLE_LABEL;
   if(wrapper===parent)table.before(hint);else wrapper.before(hint);
   const focus=()=>{const wide=wrapper.scrollWidth>wrapper.clientWidth+1;hint.hidden=!wide;if(wide)wrapper.tabIndex=0;else wrapper.removeAttribute('tabindex');};
   focus();if(window.ResizeObserver)new ResizeObserver(focus).observe(wrapper);
 });
})();
</script>'''.replace('TABLE_LABEL',json.dumps(table_label).replace('<','\\u003c'))
