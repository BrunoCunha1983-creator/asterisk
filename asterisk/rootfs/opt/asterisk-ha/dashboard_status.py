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
  if(reachable===true) return ['REACHABLE','online'];
  if(reachable===false) return ['UNREACHABLE','offline'];
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
async function dashboard(a){
  let h={};
  try{h=await api('api/ha-state')}catch(e){h={online:false,error:String(e)}}
  let exts=(h.extensions||[]).slice().sort((x,y)=>String(x.extension).localeCompare(String(y.extension),undefined,{numeric:true}));
  let ht=h.ht503||{}, fxs=ht.fxs||{}, fxo=ht.fxo||{}, sc=h.sipcord||{};
  let extCards=exts.length?exts.map(dashboardExtensionCard).join(''):'<div class="status-card"><div class="status-meta">Nenhuma extensão configurada.</div></div>';
  let fxsCard=dashboardStatusCard('HT503 FXS',fxs.enabled,fxs.reachable,fxs.status,[`<b>Extensão:</b> ${esc(fxs.extension||ht.fxs_extension||'—')}`,`<b>Contacto:</b> ${esc(fxs.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(fxs.rtt_ms)}`]);
  let fxoCard=dashboardStatusCard('HT503 FXO',fxo.enabled,fxo.reachable,fxo.status,[`<b>User:</b> ${esc(fxo.user||ht.user||'—')}`,`<b>Contacto:</b> ${esc(fxo.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(fxo.rtt_ms)}`]);
  let scCard=dashboardStatusCard('SIPcord / Discord',sc.enabled,sc.reachable,sc.status,[`<b>Servidor:</b> ${esc(sc.server||'—')}${sc.port?':'+esc(sc.port):''}`,`<b>Contacto:</b> ${esc(sc.contact||'sem contacto')}`,`<b>RTT:</b> ${dashboardRtt(sc.rtt_ms)}`,`<b>Padrão:</b> ${esc(sc.dial_pattern||'—')}`]);
  a.innerHTML=`
  <div class=grid>
    <div class=card><div class=sub>Asterisk</div><div class="big ${h.online?'ok':'bad'}">${h.online?'ONLINE':'OFFLINE'}</div><pre>${esc(h.version||h.error||'')}</pre></div>
    <div class=card><div class=sub>Canais ativos</div><div class=big>${h.active_channels||0}</div><div class=sub>Chamadas ativas: ${h.active_calls||0}</div></div>
    <div class=card><div class=sub>Extensões</div><div class=big>${h.extensions_registered||0}/${h.extensions_total||0}</div><div class=sub>Reachable / configuradas</div></div>
    <div class=card><div class=sub>IVR</div><div class=big>${h.ivrs_enabled||0}</div><div class=sub>Canais em IVR: ${h.ivr_active_channels||0}</div></div>
    <div class=card><div class=sub>Dongles GSM</div><div class=big>${h.gsm_dongles_connected||0}/${h.gsm_dongles_total||0}</div><div class=sub>Ligados / detetados</div></div>
  </div>
  <div class="card status-section"><h2>Extensões PJSIP</h2><div class=status-summary><span class=pill>Reachable: ${h.extensions_registered||0}</span><span class=pill>Offline: ${h.extensions_unregistered||0}</span><span class=pill>Total: ${h.extensions_total||0}</span></div><div class=status-grid>${extCards}</div></div>
  <div class="card status-section"><h2>Grandstream HT503</h2><div class=status-grid>${fxsCard}${fxoCard}</div></div>
  <div class="card status-section"><h2>SIPcord</h2><div class=status-grid>${scCard}</div></div>
  <div class=actions><button class="btn primary" onclick="cmd('core reload')">Reload Asterisk</button><button class=btn onclick="cmd('pjsip reload')">Reload PJSIP</button><button class=btn onclick="cmd('module reload chan_dongle.so')">Reload chan_dongle</button><button class=btn onclick="dashboard(E('#app'))">Atualizar estados</button></div>`;
  clearTimeout(window.__asteriskDashboardTimer);
  if(current==='Dashboard') window.__asteriskDashboardTimer=setTimeout(()=>{if(current==='Dashboard') dashboard(E('#app'))},15000);
}
'''

    index = index.replace('</head>', css + '</head>')
    index = index.replace('</script>', js + '</script>', 1)
    return index
