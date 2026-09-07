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
  try{ports=await api('api/usb')}catch(e){}
  let ami=st.ami||{};
  let serialPorts=(ports||[]).filter(p=>String(p.device||'').includes('/dev/tty'));
  let portOpts=serialPorts.map(p=>`<option value="${esc(p.device)}" ${String(cfg.port||'')===String(p.device||'')?'selected':''}>${esc(p.device)} ${esc(p.id_vendor||'')} ${esc(p.id_model||'')}</option>`).join('');
  if(cfg.port&&!serialPorts.some(p=>String(p.device)===String(cfg.port))) portOpts=`<option selected>${esc(cfg.port)}</option>`+portOpts;
  let sms=(st.recent_sms||[]).map(m=>`<div class=item><b>${esc(m.from||'Desconhecido')}</b><div class=sub>${esc(m.stamp||'')}</div><div>${esc(m.text||'')}</div></div>`).join('')||'<div class=sub>Sem SMS recebidos nesta sessão.</div>';
  let audioWarn=st.audio_available?'':'<div class=note><b>⚠ Voz ainda sem caminho físico de áudio.</b> Esta placa está a comunicar por UART/USB-TTL, que transporta AT, SMS e sinalização de chamadas, mas não transporta o áudio. O software fica pronto para controlo GSM/SMS; para voz SIP↔GSM é necessário um caminho físico de áudio da placa.</div>';
  a.innerHTML=`<div class=card><h2>SIM800C — GSM / Voz / SMS / AMI</h2>${audioWarn}
    <div class=grid>
      <div class=card><div class=sub>Ligação série</div><div class="big ${st.connected?'ok':'bad'}">${st.connected?'LIGADO':'DESLIGADO'}</div><div class=sub>${esc(st.port||cfg.port||'')}</div></div>
      <div class=card><div class=sub>SIM</div><div class=big>${esc(st.sim||'unknown')}</div></div>
      <div class=card><div class=sub>Rede GSM</div><div class=big>${esc(st.registration||'unknown')}</div><div class=sub>${esc(st.operator||'')}</div></div>
      <div class=card><div class=sub>Sinal</div><div class=big>${st.rssi==null?'—':esc(st.rssi)+'/31'}</div><div class=sub>${st.signal_dbm==null?'':esc(st.signal_dbm)+' dBm'}</div></div>
      <div class=card><div class=sub>Chamada</div><div class=big>${esc(st.call_state||'idle')}</div><div class=sub>${esc(st.caller||'')}</div></div>
      <div class=card><div class=sub>AMI bridge</div><div class="big ${ami.connected?'ok':'bad'}">${ami.connected?'ONLINE':'OFFLINE'}</div><div class=sub>${esc(ami.username||'homeassistant')}@${esc(ami.host||'127.0.0.1')}:${esc(ami.port||5038)}</div></div>
    </div>
    ${st.last_error?`<div class=note><b>Erro SIM800C:</b> ${esc(st.last_error)}</div>`:''}
    ${ami.error?`<div class=note><b>Erro AMI:</b> ${esc(ami.error)}</div>`:''}
    <h3>Configuração</h3><div class=row>
      <div><label>Ativar SIM800C</label><select id=s8en><option value=0 ${cfg.enabled?'':'selected'}>Não</option><option value=1 ${cfg.enabled?'selected':''}>Sim</option></select></div>
      <div><label>Porta série</label><select id=s8port>${portOpts||`<option>${esc(cfg.port||'/dev/ttyUSB0')}</option>`}</select></div>
      <div><label>Baud rate</label><select id=s8baud>${[9600,19200,38400,57600,115200].map(v=>`<option ${Number(cfg.baudrate||115200)===v?'selected':''}>${v}</option>`).join('')}</select></div>
      <div><label>Prefixo saída GSM</label><input id=s8pre value="${esc(cfg.outbound_prefix||'7')}"></div>
      <div><label>Destino chamadas recebidas</label><input id=s8target value="${esc(cfg.incoming_target||'800')}" placeholder="800"></div>
    </div>
    <div class=actions><button class="btn primary" onclick=saveSIM800C()>Guardar</button><button class=btn onclick="sim800cAction('init')">Inicializar modem</button><button class=btn onclick="sim800cAction('refresh')">Atualizar estado</button></div>
    <h3>AMI — Asterisk Manager Interface</h3>
    <div class=note>O SIM800C usa o AMI interno já existente no add-on em <b>${esc(ami.host||'127.0.0.1')}:${esc(ami.port||5038)}</b>. A password AMI não é exposta nesta página. As ações SIM800C publicam eventos <code>UserEvent: SIM800C</code> no Asterisk.</div>
    <div class=actions><button class=btn onclick="sim800cAction('ami_test')">Testar AMI</button><button class=btn onclick="sim800cAction('ami_publish')">Publicar estado no AMI</button></div>
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
  if(action==='ami_test') alert(r.connected?'AMI ONLINE':'AMI OFFLINE: '+(r.error||''));
  else if(!r.ok&&r.output) alert(r.output); else if(r.warning) alert(r.warning);
  await sim800c(E('#app'));
}
'''
        index = index.replace('</script>', js + '\n</script>', 1)
    return index
