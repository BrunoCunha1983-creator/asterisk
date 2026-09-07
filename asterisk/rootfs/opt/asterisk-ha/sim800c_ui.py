#!/usr/bin/env python3


def augment_index(index):
    if "'SIM800C'" not in index:
        index = index.replace("'GSM / chan_dongle'", "'SIM800C','GSM / chan_dongle'", 1)
        index = index.replace(
            "if(current==='GSM / chan_dongle') gsm(a);",
            "if(current==='SIM800C') sim800c(a); if(current==='GSM / chan_dongle') gsm(a);",
            1,
        )

    if 'async function sim800c(a)' not in index:
        js = r'''
async function sim800c(a){
  let cfg=pbx.sim800c||{}; let st={}; let ports=[];
  try{st=await api('api/sim800c-status')}catch(e){st={error:String(e)}}
  try{ports=await api('api/usb')}catch(e){ports=[]}
  let serialPorts=(ports||[]).filter(p=>p.kind==='serial'&&p.device);
  let usablePorts=serialPorts.filter(p=>p.accessible!==false);
  let rawUsb=(ports||[]).filter(p=>p.kind==='raw-usb');
  let ch340=rawUsb.find(p=>String(p.usb_id||'').toLowerCase()==='1a86:7523');
  let ch340Serial=serialPorts.find(p=>String(p.usb_id||'').toLowerCase()==='1a86:7523');
  let selected=String(cfg.port||'');
  if((!selected||!usablePorts.some(p=>String(p.device)===selected))&&ch340Serial&&ch340Serial.accessible!==false) selected=String(ch340Serial.device||'');
  let portOpts=usablePorts.map(p=>`<option value="${esc(p.device)}" ${selected===String(p.device||'')?'selected':''}>${esc(p.device)} ${esc(p.id_vendor||'')} ${esc(p.id_model||'')} ${p.usb_id?'['+esc(p.usb_id)+']':''}</option>`).join('');
  if(cfg.port&&!usablePorts.some(p=>String(p.device)===String(cfg.port))) portOpts=`<option selected value="${esc(cfg.port)}">${esc(cfg.port)} (guardada / indisponível)</option>`+portOpts;
  if(!portOpts) portOpts=`<option value="${esc(cfg.port||'/dev/ttyUSB0')}">${esc(cfg.port||'/dev/ttyUSB0')}</option>`;
  let sms=(st.recent_sms||[]).map(m=>`<div class=item><b>${esc(m.from||'Desconhecido')}</b><div class=sub>${esc(m.stamp||'')}</div><div>${esc(m.text||'')}</div></div>`).join('')||'<div class=sub>Sem SMS recebidos nesta sessão.</div>';
  let audioWarn=st.audio_available?'':'<div class=note><b>⚠ Voz ainda sem caminho físico de áudio.</b> UART/USB-TTL transporta AT, SMS e sinalização, mas não o áudio da chamada.</div>';
  let usbNote='';
  if(ch340Serial&&ch340Serial.accessible!==false) usbNote=`<div class=note><b>CH340 / SIM800C detetado.</b> Porta disponível: <code>${esc(ch340Serial.device)}</code>.</div>`;
  else if(ch340) usbNote='<div class=note><b>CH340 1a86:7523 chegou à VM/USB do add-on, mas ainda não existe uma porta ttyUSB acessível.</b> Como o add-on já tem <code>uart: true</code>, reinicia o add-on depois do passthrough e confirma no HAOS se aparece /dev/ttyUSB*.</div>';
  else usbNote='<div class=note><b>CH340 1a86:7523 ainda não foi visto pelo detector.</b> O detector consulta /dev, udev, Supervisor e lsusb.</div>';
  let serialRows=serialPorts.map(p=>`<div class=item><b>${esc(p.device)}</b> <span class=pill>${p.accessible===false?'HAOS apenas':'acessível'}</span><div class=sub>${esc(p.id_vendor||'')} ${esc(p.id_model||'')} ${p.usb_id?'USB '+esc(p.usb_id):''} · ${esc(p.source||'')}</div>${p.note?`<div class=sub>${esc(p.note)}</div>`:''}</div>`).join('')||'<div class=item>Nenhuma porta ttyUSB/ttyACM detetada.</div>';
  a.innerHTML=`<div class=card><h2>SIM800C — GSM / Voz / SMS</h2>${audioWarn}${usbNote}
    <div class=grid>
      <div class=card><div class=sub>Ligação série</div><div class="big ${st.connected?'ok':'bad'}">${st.connected?'LIGADO':'DESLIGADO'}</div><div class=sub>${esc(st.port||cfg.port||'')}</div></div>
      <div class=card><div class=sub>Portas série acessíveis</div><div class=big>${usablePorts.length}</div></div>
      <div class=card><div class=sub>SIM</div><div class=big>${esc(st.sim||'unknown')}</div></div>
      <div class=card><div class=sub>Rede GSM</div><div class=big>${esc(st.registration||'unknown')}</div><div class=sub>${esc(st.operator||'')}</div></div>
      <div class=card><div class=sub>Sinal</div><div class=big>${st.rssi==null?'—':esc(st.rssi)+'/31'}</div><div class=sub>${st.signal_dbm==null?'':esc(st.signal_dbm)+' dBm'}</div></div>
      <div class=card><div class=sub>Chamada</div><div class=big>${esc(st.call_state||'idle')}</div><div class=sub>${esc(st.caller||'')}</div></div>
    </div>
    ${st.last_error?`<div class=note><b>Erro:</b> ${esc(st.last_error)}</div>`:''}
    <div class=actions><button class=btn onclick="sim800c(E('#app'))">Redetetar USB</button></div>
    <details><summary>Diagnóstico de portas série (${serialPorts.length})</summary>${serialRows}</details>
    <h3>Configuração</h3><div class=row>
      <div><label>Ativar SIM800C</label><select id=s8en><option value=0 ${cfg.enabled?'':'selected'}>Não</option><option value=1 ${cfg.enabled?'selected':''}>Sim</option></select></div>
      <div><label>Porta série</label><select id=s8port>${portOpts}</select></div>
      <div><label>Baud rate</label><select id=s8baud>${[9600,19200,38400,57600,115200].map(v=>`<option ${Number(cfg.baudrate||115200)===v?'selected':''}>${v}</option>`).join('')}</select></div>
      <div><label>Prefixo saída GSM</label><input id=s8pre value="${esc(cfg.outbound_prefix||'7')}"></div>
      <div><label>Destino chamadas recebidas</label><input id=s8target value="${esc(cfg.incoming_target||'800')}" placeholder="800"></div>
    </div>
    <div class=actions><button class="btn primary" onclick=saveSIM800C()>Guardar</button><button class=btn onclick="sim800cAction('init')">Inicializar modem</button><button class=btn onclick="sim800cAction('refresh')">Atualizar estado</button></div>
    <h3>Chamadas GSM — controlo</h3><div class=row><div><label>Número</label><input id=s8num placeholder="912345678"></div></div>
    <div class=actions><button class="btn primary" onclick="sim800cAction('dial',{number:E('#s8num').value})">Ligar</button><button class=btn onclick="sim800cAction('answer')">Atender</button><button class=btn onclick="sim800cAction('hangup')">Desligar</button></div>
    <h3>SMS</h3><div class=row><div><label>Número</label><input id=s8smsnum placeholder="+351..."></div><div><label>Mensagem</label><input id=s8smstext placeholder="Mensagem"></div></div>
    <div class=actions><button class="btn primary" onclick="sim800cAction('sms',{number:E('#s8smsnum').value,text:E('#s8smstext').value})">Enviar SMS</button></div>
    <h3>SMS recebidos</h3>${sms}
    <details><summary>Eventos AT recentes</summary><pre>${esc((st.recent_events||[]).map(x=>x.line).join('\n'))}</pre></details>
  </div>`;
}
async function saveSIM800C(){
  pbx.sim800c={...(pbx.sim800c||{}),enabled:E('#s8en').value==='1',port:E('#s8port').value,baudrate:+E('#s8baud').value,outbound_prefix:E('#s8pre').value,incoming_target:E('#s8target').value,audio_mode:'none'};
  await savePbx();
}
async function sim800cAction(action,extra={}){
  let r=await api('api/sim800c-action',{method:'POST',body:JSON.stringify({action,...extra})});
  if(!r.ok&&r.output) alert(r.output); else if(r.warning) alert(r.warning);
  await sim800c(E('#app'));
}
'''
        index = index.replace('</script>', js + '\n</script>', 1)
    return index
