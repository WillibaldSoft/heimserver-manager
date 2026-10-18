"""Visible, copyable client download URLs; no credentials in links."""
import html
from flask import request
from i18n import language

def card():
    english=language()=='en'
    labels=['Client setup (sign-in required)','Linux installer (.deb)','Windows installer (.exe)'] if english else ['Client-Einrichtung (Anmeldung erforderlich)','Linux-Installation (.deb)','Windows-Installation (.exe)']
    paths=['/clients/setup','/clients/desktop/download','/clients/windows/download']
    copy='Copy' if english else 'Kopieren'
    copied='Copied' if english else 'Kopiert'
    fallback='Select and copy the address manually.' if english else 'Adresse markieren und manuell kopieren.'
    body="<div class='card' id='client-download-addresses'><h3>"+('Client download addresses' if english else 'Client-Download-Adressen')+'</h3>'
    for label,path in zip(labels,paths):
        url=html.escape(request.host_url.rstrip('/')+path,quote=True)
        body+="<div style='margin-bottom:12px'><label>"+label+"<input readonly style='width:100%;box-sizing:border-box' value='"+url+"' onclick='this.select()'></label><a class='btn' href='"+url+"'>"+('Open' if english else 'Öffnen')+"</a> <button type='button' class='btn' data-copy-link>"+copy+"</button><span role='status' aria-live='polite'></span></div>"
    body+='</div>'
    return body+'''<script>(()=>{const box=document.getElementById('client-download-addresses');
    box.querySelectorAll('[data-copy-link]').forEach(button=>button.addEventListener('click',async()=>{
      const row=button.parentElement,input=row.querySelector('input'),status=row.querySelector('[role=status]');
      try{await navigator.clipboard.writeText(input.value);status.textContent=__COPIED__;}
      catch(e){input.focus();input.select();status.textContent=__FALLBACK__;}
    }));})();</script>'''.replace('__COPIED__',__import__('json').dumps(copied)).replace('__FALLBACK__',__import__('json').dumps(fallback))
