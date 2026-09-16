#!/usr/bin/env python3


def augment_index(index):
    if 'function securityPage(' in index:
        return index

    js = r'''
if(!tabs.includes('Segurança')) tabs.splice(1,0,'Segurança');
const __asteriskBaseRender=render;
render=async function(){
  if(current==='Segurança'){
    let a=E('#app');
    a.innerHTML='<div class=card>A carregar segurança…</div>';
    return securityPage(a);
  }
  return __asteriskBaseRender();
}
async function securityPage(a){
  let s={};
  try{s=await api('api/security')}catch(e){s={running:false,error:String(e)}}
  let details=s.details||{}, dyn=s.dynamic_whitelist||{};
  let jailRows=(s.jails||[]).map(name=>{
    let j=details[name]||{};
    let ignored=(j.ignoreip||[]);
    return `<div class=item><div class=status-head><b>${esc(name)}</b><span class="status-badge ${j.running===false?'offline':'online'}">${j.running===false?'OFFLINE':'ATIVO'}</span></div><div class=sub>Bans atuais: ${esc(j.currently_banned||0)} · Total bans: ${esc(j.total_banned||0)}</div>${j.banned_ips&&j.banned_ips.length?`<div class=sub>IPs banidos: ${esc(j.banned_ips.join(', '))}</div>`:''}${ignored.length?`<div class=sub><b>Whitelist runtime:</b> ${esc(ignored.join(', '))}</div>`:'<div class=sub><b>Whitelist runtime:</b> sem entradas visíveis</div>'}${j.error?`<pre>${esc(j.error)}</pre>`:''}</div>`;
  }).join('');
  let diag=(!s.running&&s.startup_diagnostics)?`<h3>Diagnóstico de arranque</h3><pre>${esc(s.startup_diagnostics)}</pre>`:'';
  let dynErr=(dyn.errors||[]).length?`<div class=bad><b>Erros:</b><pre>${esc(JSON.stringify(dyn.errors,null,2))}</pre></div>`:'';
  let haVerified=dyn.ha_public_ip_verified||{};
  let haOk=dyn.ha_public_ip&&haVerified['asterisk-pjsip']&&haVerified['asterisk-web'];
  let haBox=`<div class=item><div class=status-head><b>IP público do Home Assistant / PBX</b><span class="status-badge ${haOk?'online':'unknown'}">${haOk?'WHITELIST OK':'A VERIFICAR'}</span></div>
    <div class=sub><b>IP público detetado:</b> ${esc(dyn.ha_public_ip||'—')}</div>
    <div class=sub><b>Fonte:</b> ${esc(dyn.ha_public_ip_source||'—')}</div>
    <div class=sub><b>PJSIP:</b> ${haVerified['asterisk-pjsip']?'autorizado':'não confirmado'}</div>
    <div class=sub><b>Web:</b> ${haVerified['asterisk-web']?'autorizado':'não confirmado'}</div>
    ${(dyn.ha_public_ip_added||[]).length?`<div class=sub><b>Aplicado neste ciclo:</b> ${esc((dyn.ha_public_ip_added||[]).map(x=>`${x.jail}: ${x.ip}`).join(', '))}</div>`:''}
    </div>`;
  let dynBox=`<div class=item><div class=status-head><b>Whitelist dinâmica de extensões remotas</b><span class="status-badge ${(dyn.errors||[]).length?'offline':'online'}">${(dyn.errors||[]).length?'ERRO':'ATIVA'}</span></div>
    <div class=sub><b>Extensões configuradas:</b> ${esc((dyn.configured_extensions||[]).join(', ')||'—')}</div>
    <div class=sub><b>IPs encontrados nos contactos PJSIP:</b> ${esc((dyn.contact_ips||[]).join(', ')||'—')}</div>
    <div class=sub><b>IPs confirmados por registos/autenticações bem-sucedidos:</b> ${esc((dyn.successful_log_ips||[]).join(', ')||'—')}</div>
    <div class=sub><b>IPs que o watcher quer autorizar:</b> ${esc((dyn.desired_dynamic_ips||[]).join(', ')||'—')}</div>
    <div class=sub><b>IPs públicos realmente presentes em ignoreip PJSIP:</b> ${esc((dyn.runtime_ignore_ips||[]).join(', ')||'—')}</div>
    <div class=sub><b>Adicionados e verificados neste ciclo:</b> ${esc((dyn.added_verified||[]).join(', ')||'—')}</div>
    ${dyn.error?`<pre>${esc(dyn.error)}</pre>`:''}${dynErr}</div>`;
  a.innerHTML=`<div class=grid><div class=card><div class=sub>Fail2ban</div><div class="big ${s.running?'ok':'bad'}">${s.running?'ATIVO':'OFFLINE'}</div><div class=sub>${esc(s.error||'')}</div></div><div class=card><div class=sub>Jails</div><div class=big>${(s.jails||[]).length}</div></div><div class=card><div class=sub>IPs banidos agora</div><div class=big>${s.currently_banned||0}</div></div><div class=card><div class=sub>Total de bans</div><div class=big>${s.total_banned||0}</div></div></div><div class=card><h2>Segurança / Fail2ban</h2><div class=note>O IP público atual do próprio Home Assistant/PBX é detetado automaticamente e colocado na whitelist de PJSIP e Web. Os IPs públicos de extensões remotas autenticadas continuam a ser aprendidos separadamente.</div>${haBox}${dynBox}${jailRows||'<div class=item>Sem informação de jails. O diagnóstico de arranque aparece abaixo quando disponível.</div>'}${s.banned_ips&&s.banned_ips.length?`<h3>IPs atualmente bloqueados</h3><pre>${esc(s.banned_ips.join('\n'))}</pre>`:''}${diag}${s.dynamic_whitelist_log?`<h3>Log da whitelist dinâmica</h3><pre>${esc(s.dynamic_whitelist_log)}</pre>`:''}<div class=actions><button class=btn onclick="securityPage(E('#app'))">Atualizar segurança</button></div></div>`;
}
'''
    return index.replace('</script>', js + '</script>', 1)
