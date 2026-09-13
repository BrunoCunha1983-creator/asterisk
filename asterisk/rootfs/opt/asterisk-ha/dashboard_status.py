#!/usr/bin/env python3


def augment_index(index):
    """Add live, separated status panels to the Dashboard using /api/ha-state."""
    if 'function dashboardStatusCard(' in index:
        return index

    css = r'''
<style>
.status-section{margin-top:14px}.status-section h2{margin:0 0 10px;font-size:18px}
.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.status-card{background:#111a2b;border:1px solid #334155;border-radius:11px;padding:12px;min-width:0}
.status-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}
.status-title{font-weight:700}.status-badge{font-size:11px;font-weight:700;padding:4px 8px;border-radius:999px;white-space:nowrap}
.status-badge.online{background:#0f5132;color:#7ef0ac}.status-badge.offline{background:#5c1d24;color:#ff9aa2}.status-badge.disabled{background:#5a4510;color:#ffd66b}.status-badge.unknown{background:#263244;color:#cbd5e1}
.status-meta{font-size:12px;color:#9fb0c5;overflow-wrap:anywhere}.status-meta b{color:#dbeafe;font-weight:600}
.status-summary{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 10px}.status-summary .pill{font-weight:600}
</style>
'''

    js = r'''
function dashboardStatusBadge(enabled,reachable,status){
  if(enabled===false) return ['DESATIVADO','disabled'];
  if(reachable===true) return [String(status||'REACHABLE').toUpperCase(),'online'];
  if(reachable===false) return [String(status||'UNREACHABLE').toUpperCase(),'offline'];
  let s=String(status||'').toUpperCase();
  return [s||'SEM ESTADO','unknown'];
}
function dashboardRtt(v){
  return (v===null||v===undefined||v==='')?'—':`${Number(v).toFixed(1)} ms`;
}
function dashboardStatusCard(title,enabled,reachable,status,lines=[]){
  let badge=dashboardStatusBadge(enabled,reachable,status);
  return `<div class="status-card"><div class="status-head"><div class="status-title">${esc(title)}</div><span class="status-badge ${badge[1]}">${esc(badge[0])}</span></div>${lines.filter(Boolean).map(x=>`<div class="status-meta">${x}</div>`).join('')}</div>`;
}
function dashboardExtensionCard(e){
  let contact=e.contact?`<b>Contacto:</b> ${esc(e.contact)}`:'<b>Contacto:</b> sem contacto';
  return dashboardStatusCard(`Extensão ${e.extension}`,true,!!e.registered,e.status,[`<b>Caller ID:</b> ${esc(e.callerid||e.extension)}`,contact,`<b>RTT:</b> ${dashboardRtt(e.rtt_ms)}`]);
}
function dashboardTrunkCard(t){
  let reg=t.registration_status||t.contact_status||'Unknown';
  return dashboardStatusCard(`Trunk ${t.name}`,true,!!t.reachable,reg,[
    `<b>Servidor:</b> ${esc(t.server||'—')}${t.port?':'+esc(t.port):''}`,
    `<b>Utilizador:</b> ${esc(t.username||'—')}`,
    `<b>Registration:</b> ${esc(t.registration_status||'—')}`,
    `<b>Contacto:</b> ${esc(t.contact||'sem contacto')}`,
    `<b>Qualify:</b> ${esc(t.contact_status||'—')} · <b>RTT:</b> ${dashboardRtt(t.rtt_ms)}`,
    `<b>Prefixo:</b> ${esc(t.prefix||'—')}`
  ]);
}
async function dashboard(a){
  let h={}, sec={};
  try{h=await api('api/ha-state')}catch(e){h={online:false,error:String(e)}}
  try{sec=await api('api/security')}catch(e){sec={running:false,error:String(e)}}
  let exts=(h.extensions||[]).slice().sort((x,y)=>String(x.extension).localeCompare(String(y.extension),undefined,{numeric:true}));
  let trunks=(h.sip_trunks||[]).slice().sort((x,y)=>String(x.name).localeCompare(String(y.name)));
  let ht=h.ht503||{}, fxs=ht.fxs||{}, fxo=ht.fxo||{}, sc=h.sipcord||{};
  let extCards=exts.length?exts.map(dashboardExtensionCard).join(''):'<div class="status-card"><div class="status-meta">Nenhuma extensão configurada.</div></div>';
  let trunkCards=trunks.length?trunks.map(dashboardTrunkCard).join(''):'<div class="status-card"><div class="status-meta">Nenhum trunk SIP configurado.</div></div>';
  let fxsCard=dashboardStatusCard('HT503 FXS',fxs.enabled,fxs.reachable,fxs.status,[`<b>Extensão:</b> ${esc(fxs.extension||ht.fxs_extension||'—')}`,`<b>Contacto:</b> ${esc(fxs.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(fxs.rtt_ms)}`]);
  let fxoCard=dashboardStatusCard('HT503 FXO',fxo.enabled,fxo.reachable,fxo.status,[`<b>User:</b> ${esc(fxo.user||ht.user||'—')}`,`<b>Contacto:</b> ${esc(fxo.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(fxo.rtt_ms)}`]);
  let scCard=dashboardStatusCard('SIPcord / Discord',sc.enabled,sc.reachable,sc.status,[`<b>Servidor:</b> ${esc(sc.server||'—')}${sc.port?':'+esc(sc.port):''}`,`<b>Contacto:</b> ${esc(sc.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(sc.rtt_ms)}`,`<b>Padrão:</b> ${esc(sc.dial_pattern||'—')}`]);
  let secCard=dashboardStatusCard('Fail2ban',true,!!sec.running,sec.running?'ativo':'offline',[`<b>Jails:</b> ${esc((sec.jails||[]).join(', ')||'—')}`,`<b>Banidos agora:</b> ${esc(sec.currently_banned||0)}`,`<b>Total de bans:</b> ${esc(sec.total_banned||0)}`,sec.banned_ips&&sec.banned_ips.length?`<b>IPs:</b> ${esc(sec.banned_ips.join(', '))}`:'']);
  a.innerHTML=`
  <div class=grid>
    <div class=card><div class=sub>Asterisk</div><div class="big ${h.online?'ok':'bad'}">${h.online?'ONLINE':'OFFLINE'}</div><pre>${esc(h.version||h.error||'')}</pre></div>
    <div class=card><div class=sub>Canais ativos</div><div class=big>${h.active_channels||0}</div><div class=sub>Chamadas ativas: ${h.active_calls||0}</div></div>
    <div class=card><div class=sub>Extensões</div><div class=big>${h.extensions_registered||0}/${h.extensions_total||0}</div><div class=sub>Reachable / configuradas</div></div>
    <div class=card><div class=sub>Trunks SIP</div><div class=big>${h.sip_trunks_registered||0}/${h.sip_trunks_total||0}</div><div class=sub>Registered / configurados</div></div>
    <div class=card><div class=sub>IVR</div><div class=big>${h.ivrs_enabled||0}</div><div class=sub>Canais em IVR: ${h.ivr_active_channels||0}</div></div>
    <div class=card><div class=sub>GSM configurados</div><div class=big>${h.gsm_dongles_configured||0}</div><div class=sub>Configuração guardada</div></div>
    <div class=card><div class=sub>GSM presentes</div><div class=big>${h.gsm_dongles_total||0}</div><div class=sub>Hardware com portas /dev reais</div></div>
    <div class=card><div class=sub>GSM ausentes</div><div class=big>${h.gsm_dongles_absent||0}</div><div class=sub>Configurados sem hardware</div></div>
    <div class=card><div class=sub>GSM ligados</div><div class=big>${h.gsm_dongles_connected||0}</div><div class=sub>Ativos no chan_dongle</div></div>
    <div class=card><div class=sub>Segurança</div><div class="big ${sec.running?'ok':'bad'}">${sec.running?'PROTEGIDO':'OFFLINE'}</div><div class=sub>Bans ativos: ${sec.currently_banned||0}</div></div>
  </div>
  <div class="card status-section"><h2>Extensões PJSIP</h2><div class=status-summary><span class=pill>Reachable: ${h.extensions_registered||0}</span><span class=pill>Offline: ${h.extensions_unregistered||0}</span><span class=pill>Total: ${h.extensions_total||0}</span></div><div class=status-grid>${extCards}</div></div>
  <div class="card status-section"><h2>Trunks SIP/PJSIP</h2><div class=status-summary><span class=pill>Registered: ${h.sip_trunks_registered||0}</span><span class=pill>Reachable: ${h.sip_trunks_reachable||0}</span><span class=pill>Total: ${h.sip_trunks_total||0}</span></div><div class=status-grid>${trunkCards}</div></div>
  <div class="card status-section"><h2>Segurança</h2><div class=status-grid>${secCard}</div></div>
  <div class="card status-section"><h2>Grandstream HT503</h2><div class=status-grid>${fxsCard}${fxoCard}</div></div>
  <div class="card status-section"><h2>SIPcord</h2><div class=status-grid>${scCard}</div></div>
  <div class=actions><button class="btn primary" onclick="cmd('core reload')">Reload Asterisk</button><button class=btn onclick="cmd('pjsip reload')">Reload PJSIP</button><button class=btn onclick="cmd('module reload chan_dongle.so')">Reload chan_dongle</button><button class=btn onclick="dashboard(E('#app'))">Atualizar estados</button></div>`;
  clearTimeout(window.__asteriskDashboardTimer);
  if(current==='Dashboard') window.__asteriskDashboardTimer=setTimeout(()=>{if(current==='Dashboard') dashboard(E('#app'))},15000);
}

// Override the original configuration-only Trunks page with live runtime state.
async function trunks(a){
  let x=pbx.sip_trunks||[], h={};
  try{h=await api('api/ha-state')}catch(e){h={sip_trunks:[],error:String(e)}}
  let runtime={}; (h.sip_trunks||[]).forEach(t=>runtime[String(t.name||'')]=t);
  a.innerHTML=`<div class=card><h2>Trunks SIP/PJSIP</h2>
    <div class=note>Estado em tempo real: <b>Registration</b> vem de <code>pjsip show registrations</code>; <b>Qualify/RTT</b> vem do contacto PJSIP quando disponível.</div>
    ${x.map((t,i)=>{let s=runtime[String(t.name||'')]||{};let badge=dashboardStatusBadge(true,!!s.reachable,s.registration_status||'SEM ESTADO');return `<div class=item>
      <div class=status-head><b>${esc(t.name||'Trunk')}</b><span class="status-badge ${badge[1]}">${esc(badge[0])}</span></div>
      <div class=row><div><label>Nome</label><input id=tn${i} value="${esc(t.name)}"></div><div><label>Servidor</label><input id=th${i} value="${esc(t.server)}"></div><div><label>Utilizador</label><input id=tu${i} value="${esc(t.username)}"></div><div><label>Password</label><input id=tp${i} value="${esc(t.password)}"></div><div><label>Porta</label><input id=tport${i} value="${esc(t.port||5060)}"></div><div><label>Prefixo saída</label><input id=tpre${i} value="${esc(t.prefix||'0')}"></div></div>
      <div class=status-summary><span class=pill>Registration: ${esc(s.registration_status||'—')}</span><span class=pill>Contacto: ${esc(s.contact_status||'—')}</span><span class=pill>RTT: ${dashboardRtt(s.rtt_ms)}</span></div>
      <div class=sub>${s.contact?'Contacto: '+esc(s.contact):'Sem contacto PJSIP qualificado'}${s.registration_raw?'<br>'+esc(s.registration_raw):''}</div>
      <button class=btn onclick="delTrunk(${i})">Remover</button></div>`}).join('')}
    ${x.length?'':'<div class=item>Nenhum trunk SIP configurado.</div>'}
    <div class=actions><button class=btn onclick=addTrunk()>+ Trunk</button><button class="btn primary" onclick=saveTrunks()>Guardar e aplicar</button><button class=btn onclick="trunks(E('#app'))">Atualizar estados</button></div>
    ${h.error?`<pre>${esc(h.error)}</pre>`:''}</div>`;
}
'''

    index = index.replace('</head>', css + '</head>')
    index = index.replace('</script>', js + '</script>', 1)
    return index
