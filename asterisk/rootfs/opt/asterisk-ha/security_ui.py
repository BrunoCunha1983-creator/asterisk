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
  let details=s.details||{};
  let jailRows=(s.jails||[]).map(name=>{
    let j=details[name]||{};
    return `<div class=item><div class=status-head><b>${esc(name)}</b><span class="status-badge ${j.running===false?'offline':'online'}">${j.running===false?'OFFLINE':'ATIVO'}</span></div><div class=sub>Bans atuais: ${esc(j.currently_banned||0)} · Total bans: ${esc(j.total_banned||0)}</div>${j.banned_ips&&j.banned_ips.length?`<div class=sub>IPs: ${esc(j.banned_ips.join(', '))}</div>`:''}${j.error?`<pre>${esc(j.error)}</pre>`:''}</div>`;
  }).join('');
  let diag=(!s.running&&s.startup_diagnostics)?`<h3>Diagnóstico de arranque</h3><pre>${esc(s.startup_diagnostics)}</pre>`:'';
  a.innerHTML=`<div class=grid><div class=card><div class=sub>Fail2ban</div><div class="big ${s.running?'ok':'bad'}">${s.running?'ATIVO':'OFFLINE'}</div><div class=sub>${esc(s.error||'')}</div></div><div class=card><div class=sub>Jails</div><div class=big>${(s.jails||[]).length}</div></div><div class=card><div class=sub>IPs banidos agora</div><div class=big>${s.currently_banned||0}</div></div><div class=card><div class=sub>Total de bans</div><div class=big>${s.total_banned||0}</div></div></div><div class=card><h2>Segurança / Fail2ban</h2><div class=note>Proteção automática para brute-force SIP/PJSIP e scans HTTP. Redes privadas/Ingress estão na whitelist por defeito para reduzir o risco de auto-bloqueio.</div>${jailRows||'<div class=item>Sem informação de jails. O diagnóstico de arranque aparece abaixo quando disponível.</div>'}${s.banned_ips&&s.banned_ips.length?`<h3>IPs atualmente bloqueados</h3><pre>${esc(s.banned_ips.join('\n'))}</pre>`:''}${diag}<div class=actions><button class=btn onclick="securityPage(E('#app'))">Atualizar segurança</button></div></div>`;
}
'''
    return index.replace('</script>', js + '</script>', 1)
