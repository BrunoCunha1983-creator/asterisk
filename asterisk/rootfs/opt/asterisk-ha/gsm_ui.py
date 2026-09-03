#!/usr/bin/env python3


def augment_index(index):
    if 'function gsmRuntimeState(' in index:
        return index

    js = r'''
function gsmRuntimeState(item){
  if(!item) return ['AUSENTE','bad'];
  if(item.connected) return ['LIGADO','ok'];
  if(item.present) return ['PRESENTE','warn'];
  return ['AUSENTE','bad'];
}
async function gsm(a){
  let ports=await api('api/usb');
  let h={};
  try{h=await api('api/ha-state')}catch(e){h={gsm_dongles:[]}}
  let x=pbx.gsm_dongles||[];
  let live={};
  (h.gsm_dongles||[]).forEach(d=>{live[String(d.name||'')]=d});
  let opts=ports.map(p=>`<option value="${esc(p.device)}">${esc(p.device)} ${esc(p.id_vendor||'')} ${esc(p.id_model||'')} IF:${esc(p.id_usb_interface_num||'')}</option>`).join('');
  let rows=x.map((d,i)=>{
    let state=live[String(d.name||'')];
    let badge=gsmRuntimeState(state);
    let detail=state&&state.present_nodes&&state.present_nodes.length?state.present_nodes.join(', '):'sem portas /dev presentes';
    return `<div class=item><div class=status-head><b>${esc(d.name||('dongle'+i))}</b><span class="status-badge ${badge[1]==='ok'?'online':badge[1]==='warn'?'disabled':'offline'}">${badge[0]}</span></div><div class=sub>${esc(detail)}</div><div class=row><div><label>Nome</label><input id=dn${i} value="${esc(d.name)}"></div><div><label>Áudio</label><select id=da${i}><option>${esc(d.audio||'')}</option>${opts}</select></div><div><label>Dados/AT</label><select id=dd${i}><option>${esc(d.data||'')}</option>${opts}</select></div><div><label>Contexto</label><input id=dc${i} value="${esc(d.context||'from-dongle')}"></div><div><label>Grupo</label><input id=dg${i} value="${esc(d.group||0)}"></div><div><label>RX gain</label><input id=dr${i} value="${esc(d.rxgain||0)}"></div><div><label>TX gain</label><input id=dt${i} value="${esc(d.txgain||0)}"></div></div><button class=btn onclick="delDongle(${i})">Remover configuração</button></div>`;
  }).join('');
  a.innerHTML=`<div class=grid><div class=card><div class=sub>Configurados</div><div class=big>${h.gsm_dongles_configured||0}</div></div><div class=card><div class=sub>Presentes fisicamente</div><div class=big>${h.gsm_dongles_total||0}</div></div><div class=card><div class=sub>Ausentes</div><div class=big>${h.gsm_dongles_absent||0}</div></div><div class=card><div class=sub>Ligados</div><div class=big>${h.gsm_dongles_connected||0}</div></div></div><div class=card><h2>chan_dongle / GSM</h2><div class=note>Uma configuração guardada não significa que exista um modem. Só entram no <code>dongle.conf</code> e nas rotas GSM os dongles cujas portas de <b>Áudio</b> e <b>Dados/AT</b> existem realmente em <code>/dev</code>.</div><p>Portas seriais detetadas agora: <span class=pill>${ports.length}</span></p><pre>${esc(JSON.stringify(ports,null,2))}</pre>${rows||'<div class=item>Nenhum dongle configurado.</div>'}<div class=actions><button class=btn onclick=addDongle()>+ Dongle</button><button class="btn primary" onclick=saveDongles()>Guardar e aplicar</button><button class=btn onclick="dongleShow()">Estado chan_dongle</button></div><hr><h3>SMS</h3><div class=row><input id=smsdev placeholder=dongle0><input id=smsnum placeholder="+351..."><input id=smstext placeholder="Mensagem"></div><button class=btn onclick=sendSMS()>Enviar SMS</button><h3>USSD</h3><div class=row><input id=ussddev placeholder=dongle0><input id=ussdcode placeholder="*#123#"></div><button class=btn onclick=sendUSSD()>Enviar USSD</button><pre id=gout></pre></div>`;
}
'''
    return index.replace('</script>', js + '</script>', 1)
