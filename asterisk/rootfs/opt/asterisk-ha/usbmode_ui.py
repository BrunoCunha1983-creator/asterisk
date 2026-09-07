#!/usr/bin/env python3


def augment_index(index):
    if "'USB / Modems'" not in index:
        index = index.replace("'SIM800C','GSM / chan_dongle'", "'USB / Modems','SIM800C','GSM / chan_dongle'", 1)
        index = index.replace(
            "if(current==='SIM800C') sim800c(a);",
            "if(current==='USB / Modems') usbmodems(a); if(current==='SIM800C') sim800c(a);",
            1,
        )
    if 'async function usbmodems(a)' in index:
        return index

    js = r'''
async function usbmodems(a){
  let st={devices:[]};
  try{st=await api('api/usb-tools-status')}catch(e){st={devices:[],error:String(e)}}
  let serial=(st.devices||[]).filter(x=>x.kind==='serial');
  let raw=(st.devices||[]).filter(x=>x.kind==='raw-usb');
  let serialRows=serial.map(p=>`<div class=item><b>${esc(p.device||'')}</b> <span class=pill>${p.accessible===false?'HAOS apenas':'acessível'}</span><div class=sub>${esc(p.usb_id||'')} ${esc(p.id_vendor||'')} ${esc(p.id_model||'')} · ${esc(p.source||'')}</div>${p.by_id&&p.by_id.length?`<div class=sub>${esc(p.by_id.join(' · '))}</div>`:''}${p.note?`<div class=note>${esc(p.note)}</div>`:''}</div>`).join('')||'<div class=item>Sem portas série.</div>';
  let rawRows=raw.map(p=>`<div class=item><b>${esc(p.usb_id||'USB')}</b> ${p.role_hint?`<span class=pill>${esc(p.role_hint)}</span>`:''}<div class=sub>${esc(p.description||'')}</div>${p.note?`<div class=note>${esc(p.note)}</div>`:''}</div>`).join('')||'<div class=item>Sem dispositivos USB brutos.</div>';
  let modeButton=st.huawei_1505_present?`<button class="btn primary" onclick="switchHuawei1505()">Mudar Huawei 12d1:1505 para modo modem</button>`:'';
  a.innerHTML=`<div class=grid>
    <div class=card><div class=sub>usb_modeswitch</div><div class="big ${st.usb_modeswitch_installed?'ok':'bad'}">${st.usb_modeswitch_installed?'INSTALADO':'AUSENTE'}</div></div>
    <div class=card><div class=sub>Config Huawei 12d1:1505</div><div class="big ${st.config_12d1_1505?'ok':'bad'}">${st.config_12d1_1505?'OK':'FALTA'}</div></div>
    <div class=card><div class=sub>Huawei 12d1:1505</div><div class="big ${st.huawei_1505_present?'warn':'ok'}">${st.huawei_1505_present?'MODO INICIAL':'NÃO DETETADO'}</div></div>
  </div>
  <div class=card><h2>USB / Modems</h2>
    <div class=note><b>Mode-switch Huawei:</b> o 12d1:1505 é o modo inicial/storage. O add-on inclui o perfil oficial de switching para os PIDs de destino 140b, 1506 e 150f. Se o Proxmox estiver preso a <code>host=12d1:1505</code>, o USB pode desaparecer da VM quando o PID mudar; o ideal é passthrough pela porta USB física.</div>
    <div class=actions><button class=btn onclick="usbmodems(E('#app'))">Redetetar</button>${modeButton}</div>
    <h3>Portas série</h3>${serialRows}
    <h3>USB bruto</h3>${rawRows}
    <h3>IDs visíveis</h3><pre>${esc((st.usb_ids||[]).join('\n'))}</pre>
    ${st.error?`<div class=note><b>Erro:</b> ${esc(st.error)}</div>`:''}
  </div>`;
}
async function switchHuawei1505(){
  if(!confirm('Executar usb_modeswitch no Huawei 12d1:1505? O PID USB vai mudar e um passthrough Proxmox preso a 12d1:1505 pode perder o modem.'))return;
  let r=await api('api/usb-action',{method:'POST',body:JSON.stringify({action:'switch_huawei_1505'})});
  let msg=(r.output||'')+(r.warning?'\n\n'+r.warning:'')+(r.new_huawei_ids&&r.new_huawei_ids.length?'\n\nNovo PID: '+r.new_huawei_ids.join(', '):'');
  alert(msg||JSON.stringify(r));
  await usbmodems(E('#app'));
}
'''
    return index.replace('</script>', js + '\n</script>', 1)
