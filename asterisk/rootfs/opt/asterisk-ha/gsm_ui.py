#!/usr/bin/env python3

# server.py imports usb_ports directly from backend before feature UI modules are
# loaded. Patch both references here so /api/usb and Asterisk GSM diagnostics use
# the same HAOS/Supervisor-aware detector.
import backend
import server
from usb_detect import usb_ports as detect_usb_ports

backend.usb_ports = detect_usb_ports
server.usb_ports = detect_usb_ports


def augment_index(index):
    if 'function gsmRuntimeState(' in index:
        return index

    js = r'''
let GSM_SERIAL_PORTS=[];
function gsmRuntimeState(item){
  if(!item) return ['AUSENTE','bad'];
  if(item.connected) return ['LIGADO','ok'];
  if(item.present) return ['PRESENTE','warn'];
  return ['AUSENTE','bad'];
}
function gsmAliases(p){
  let a=[];
  if(p&&p.device) a.push(String(p.device));
  (p&&p.by_id||[]).forEach(x=>{if(x&&!a.includes(String(x)))a.push(String(x))});
  return a;
}
function gsmStablePath(p){
  let a=gsmAliases(p);
  return a.find(x=>x.startsWith('/dev/serial/by-id/')) || a.find(x=>x.startsWith('/dev/serial/by-path/')) || String((p&&p.device)||'');
}
function gsmPortForValue(value){
  value=String(value||'');
  return GSM_SERIAL_PORTS.find(p=>gsmAliases(p).includes(value));
}
function gsmCanonicalPort(value,locked){
  value=String(value||'');
  if(!locked) return value;
  let p=gsmPortForValue(value);
  return p?gsmStablePath(p):value;
}
function gsmPortOptions(current,locked){
  let cur=gsmCanonicalPort(current,locked);
  let values=[];
  let rows=GSM_SERIAL_PORTS.map(p=>{
    let val=locked?gsmStablePath(p):String(p.device||'');
    if(values.includes(val)) return '';
    values.push(val);
    let stable=gsmStablePath(p);
    let label=locked&&stable!==String(p.device||'')
      ? `${stable} → ${p.device}`
      : `${p.device} ${p.id_vendor||''} ${p.id_model||''} ${p.usb_id?'['+p.usb_id+']':''} IF:${p.id_usb_interface_num||''}`;
    return `<option value="${esc(val)}" ${val===cur?'selected':''}>${esc(label)}</option>`;
  }).join('');
  if(cur && !values.includes(cur)) rows=`<option value="${esc(cur)}" selected>${esc(cur)}</option>`+rows;
  if(!cur) rows=`<option value="" selected>— selecionar porta —</option>`+rows;
  return rows;
}
function gsmResolvedLabel(value){
  let p=gsmPortForValue(value);
  if(!p) return String(value||'—');
  let stable=gsmStablePath(p);
  return stable!==String(p.device||'')?`${stable} → ${p.device}`:String(p.device||'—');
}
async function gsm(a){
  let ports=[];
  try{ports=await api('api/usb')}catch(e){ports=[]}
  let h={};
  try{h=await api('api/ha-state')}catch(e){h={gsm_dongles:[]}}
  let x=pbx.gsm_dongles||[];
  let profiles=pbx.gsm_profiles||[];
  let live={};
  (h.gsm_dongles||[]).forEach(d=>{live[String(d.name||'')]=d});
  let serialPorts=(ports||[]).filter(p=>p.kind==='serial'&&p.device);
  let usablePorts=serialPorts.filter(p=>p.accessible!==false);
  GSM_SERIAL_PORTS=usablePorts;
  let rawUsb=(ports||[]).filter(p=>p.kind==='raw-usb');
  let huawei1505=rawUsb.find(p=>String(p.usb_id||'').toLowerCase()==='12d1:1505');
  let rows=x.map((d,i)=>{
    let state=live[String(d.name||'')];
    let badge=gsmRuntimeState(state);
    let detail=state&&state.present_nodes&&state.present_nodes.length?state.present_nodes.join(', '):'sem portas /dev presentes';
    let locked=d.lock_ports!==false;
    let audio=gsmCanonicalPort(d.audio||'',locked);
    let data=gsmCanonicalPort(d.data||'',locked);
    return `<div class=item>
      <div class=status-head><b>${esc(d.name||('dongle'+i))}</b>
        <span class="status-badge ${badge[1]==='ok'?'online':badge[1]==='warn'?'disabled':'offline'}">${badge[0]}</span>
        <span class="pill">${locked?'PORTAS FIXAS':'TTY MANUAL'}</span>
      </div>
      <div class=sub>${esc(detail)}</div>
      <div class=note><b>Ligação persistente:</b><br>Áudio: ${esc(gsmResolvedLabel(audio))}<br>Dados/AT: ${esc(gsmResolvedLabel(data))}</div>
      <div class=row>
        <div><label>Nome</label><input id=dn${i} value="${esc(d.name)}"></div>
        <div><label>Fixar portas por ID físico</label><select id=dl${i} onchange="gsm(E('#app'))"><option value=1 ${locked?'selected':''}>Sim — recomendado</option><option value=0 ${locked?'':'selected'}>Não — usar ttyUSBx</option></select></div>
        <div><label>Áudio</label><select id=da${i}>${gsmPortOptions(audio,locked)}</select></div>
        <div><label>Dados/AT</label><select id=dd${i}>${gsmPortOptions(data,locked)}</select></div>
        <div><label>Contexto</label><input id=dc${i} value="${esc(d.context||'from-dongle')}"></div>
        <div><label>Grupo</label><input id=dg${i} value="${esc(d.group||0)}"></div>
        <div><label>RX gain</label><input id=dr${i} value="${esc(d.rxgain||0)}"></div>
        <div><label>TX gain</label><input id=dt${i} value="${esc(d.txgain||0)}"></div>
      </div>
      <button class=btn onclick="delDongle(${i})">Remover configuração</button>
    </div>`;
  }).join('');
  let profileRows=profiles.map((d,i)=>`<div class=item><b>${esc(d.name||('perfil'+i))}</b><div class=sub>Perfil guardado — sem hardware presente</div><div class=sub>Áudio: ${esc(d.audio||'—')} · Dados/AT: ${esc(d.data||'—')}</div><button class=btn onclick="delGsmProfile(${i})">Apagar perfil</button></div>`).join('');
  let serialRows=serialPorts.map(p=>{
    let stable=gsmStablePath(p);
    return `<div class=item><b>${esc(p.device)}</b> <span class="pill">${p.accessible===false?'HAOS apenas':'acessível'}</span>${stable&&stable!==p.device?'<span class="pill">ID ESTÁVEL</span>':''}<div class=sub>${esc(p.id_vendor||'')} ${esc(p.id_model||'')} ${p.usb_id?'USB '+esc(p.usb_id):''} · origem: ${esc(p.source||'')}</div>${stable&&stable!==p.device?`<div class=sub><b>Fixar como:</b> ${esc(stable)}</div>`:''}${p.by_id&&p.by_id.length?`<div class=sub>${esc(p.by_id.join(' · '))}</div>`:''}${p.note?`<div class=sub>${esc(p.note)}</div>`:''}</div>`;
  }).join('')||'<div class=item>Nenhuma porta ttyUSB/ttyACM encontrada.</div>';
  let rawRows=rawUsb.map(p=>`<div class=item><b>${esc(p.usb_id||'USB')}</b> ${p.role_hint?`<span class=pill>${esc(p.role_hint)}</span>`:''}<div class=sub>${esc(p.description||'')}</div>${p.note?`<div class=sub>${esc(p.note)}</div>`:''}</div>`).join('')||'<div class=item>Nenhum dispositivo USB bruto visível no add-on.</div>';
  let huaweiWarn=huawei1505?'<div class=note><b>Huawei detetado como 12d1:1505.</b> O USB chegou à VM, mas está no modo inicial/storage e ainda pode não criar as portas tty do modem. Não faço mode-switch automático porque o PID muda e um passthrough Proxmox preso a 12d1:1505 pode perder o dispositivo após a mudança.</div>':'';
  a.innerHTML=`<div class=grid><div class=card><div class=sub>Configurados ativos</div><div class=big>${h.gsm_dongles_configured||0}</div></div><div class=card><div class=sub>Presentes fisicamente</div><div class=big>${h.gsm_dongles_total||0}</div></div><div class=card><div class=sub>Ligados</div><div class=big>${h.gsm_dongles_connected||0}</div></div><div class=card><div class=sub>Portas série acessíveis</div><div class=big>${usablePorts.length}</div></div></div><div class=card><h2>chan_dongle / GSM</h2><div class=note><b>Novo:</b> com “Fixar portas por ID físico = Sim”, Áudio e Dados/AT são guardados em <code>/dev/serial/by-id/...</code>. O número <code>ttyUSBx</code> pode mudar sem trocar a interface da pen configurada.</div>${huaweiWarn}<div class=actions><button class=btn onclick="gsm(E('#app'))">Redetetar USB</button><button class=btn onclick="dongleShow()">Estado chan_dongle</button></div><h3>Portas série</h3>${serialRows}<details><summary>USB bruto visto pelo add-on (${rawUsb.length})</summary>${rawRows}</details><hr>${rows||'<div class=item>Nenhum modem GSM ativo/configurado.</div>'}<div class=actions><button class=btn onclick=addDongle()>+ Dongle</button><button class="btn primary" onclick=saveDongles()>Guardar e aplicar</button></div>${profiles.length?`<hr><h3>Perfis GSM guardados</h3>${profileRows}`:''}<hr><h3>SMS</h3><div class=row><input id=smsdev placeholder=dongle0><input id=smsnum placeholder="+351..."><input id=smstext placeholder="Mensagem"></div><button class=btn onclick=sendSMS()>Enviar SMS</button><h3>USSD</h3><div class=row><input id=ussddev placeholder=dongle0><input id=ussdcode placeholder="*#123#"></div><button class=btn onclick=sendUSSD()>Enviar USSD</button><pre id=gout></pre></div>`;
}
function addDongle(){
  let i=(pbx.gsm_dongles||[]).length;
  pbx.gsm_dongles=pbx.gsm_dongles||[];
  pbx.gsm_dongles.push({name:'dongle'+i,audio:'',data:'',context:'from-dongle',group:0,rxgain:0,txgain:0,lock_ports:true});
  gsm(E('#app'));
}
async function saveDongles(){
  pbx.gsm_dongles=(pbx.gsm_dongles||[]).map((d,i)=>{
    let locked=E('#dl'+i).value==='1';
    return {
      name:E('#dn'+i).value,
      audio:gsmCanonicalPort(E('#da'+i).value,locked),
      data:gsmCanonicalPort(E('#dd'+i).value,locked),
      context:E('#dc'+i).value,
      group:+E('#dg'+i).value,
      rxgain:+E('#dr'+i).value,
      txgain:+E('#dt'+i).value,
      autodeletesms:true,
      disablesms:false,
      lock_ports:locked
    };
  });
  await savePbx();
}
async function delGsmProfile(i){
  pbx.gsm_profiles=pbx.gsm_profiles||[];
  pbx.gsm_profiles.splice(i,1);
  await savePbx();
}
'''
    return index.replace('</script>', js + '</script>', 1)
