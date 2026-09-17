#!/usr/bin/env python3
"""Shared GSM priority controls layered over the separate USB/GSM and SIM800C tabs."""


def augment_index(index):
    if 'async function gsmSharedSaveExplicit()' in index:
        return index

    js = r'''
/* GSM gateway policy v2.
   USB/GSM and SIM800C remain separate tabs. Saving either tab makes that
   backend preferred for both SMS and USSD. These controls also allow the two
   priorities to be adjusted independently afterwards. */
function gsmSharedConfig(){
  let s=pbx.gsm_shared||{};
  let legacy=['usb_gsm','sim800'].includes(String(s.preferred_gateway||''))?String(s.preferred_gateway):'usb_gsm';
  let sms=['usb_gsm','sim800'].includes(String(s.sms_preferred||''))?String(s.sms_preferred):legacy;
  let ussd=['usb_gsm','sim800'].includes(String(s.ussd_preferred||''))?String(s.ussd_preferred):legacy;
  return {sms_preferred:sms,ussd_preferred:ussd,fallback:s.fallback!==false,schema_version:2};
}
function gsmSharedGatewayLabel(value){
  return value==='sim800'?'SIM800':'USB/GSM';
}
function gsmSharedOptions(selected){
  return `<option value="usb_gsm" ${selected==='usb_gsm'?'selected':''}>USB/GSM (chan_dongle)</option><option value="sim800" ${selected==='sim800'?'selected':''}>SIM800</option>`;
}
function gsmSharedDecorate(a,tabGateway){
  if(!a||!a.firstElementChild) return;
  let s=gsmSharedConfig();
  let activeSms=s.sms_preferred===tabGateway;
  let activeUssd=s.ussd_preferred===tabGateway;
  let box=document.createElement('div');
  box.className='note';
  box.innerHTML=`<b>Prioridade GSM partilhada</b><br>
    <span class=sub>Ao guardares esta aba, ${esc(gsmSharedGatewayLabel(tabGateway))} passa a prioridade para SMS e USSD. Também podes separar as prioridades aqui.</span>
    <div class=row>
      <div><label>Prioridade SMS</label><select id=gsmSmsPreferred>${gsmSharedOptions(s.sms_preferred)}</select></div>
      <div><label>Prioridade USSD</label><select id=gsmUssdPreferred>${gsmSharedOptions(s.ussd_preferred)}</select></div>
      <div><label>Fallback para a outra interface</label><select id=gsmSharedFallback><option value=1 ${s.fallback?'selected':''}>Sim</option><option value=0 ${s.fallback?'':'selected'}>Não</option></select></div>
    </div>
    <div class=sub>Esta aba é prioridade: SMS ${activeSms?'✓':'—'} · USSD ${activeUssd?'✓':'—'}</div>
    <div class=actions><button class=btn onclick="gsmSharedSaveExplicit()">Guardar prioridades GSM</button></div>`;
  a.firstElementChild.insertBefore(box,a.firstElementChild.children[1]||null);
}
function gsmSharedSavePreference(gateway){
  let fallback=E('#gsmSharedFallback');
  let old=gsmSharedConfig();
  pbx.gsm_shared={
    ...(pbx.gsm_shared||{}),
    schema_version:2,
    sms_preferred:gateway,
    ussd_preferred:gateway,
    preferred_gateway:gateway,
    fallback:fallback?fallback.value==='1':old.fallback
  };
}
async function gsmSharedSaveExplicit(){
  let old=gsmSharedConfig();
  let sms=E('#gsmSmsPreferred');
  let ussd=E('#gsmUssdPreferred');
  let fallback=E('#gsmSharedFallback');
  pbx.gsm_shared={
    ...(pbx.gsm_shared||{}),
    schema_version:2,
    sms_preferred:sms?sms.value:old.sms_preferred,
    ussd_preferred:ussd?ussd.value:old.ussd_preferred,
    preferred_gateway:sms?sms.value:old.sms_preferred,
    fallback:fallback?fallback.value==='1':old.fallback
  };
  await savePbx();
}
'''

    return index.replace('</script>', js + '\n</script>', 1)
