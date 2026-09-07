#!/usr/bin/env python3


def augment_index(index):
    """Add a PBX-wide Asterisk AMI page to the Ingress UI."""
    if "'AMI'" not in index:
        index = index.replace("'Chamadas','Configuração'", "'Chamadas','AMI','Configuração'", 1)
        index = index.replace(
            "if(current==='Configuração') configs(a);",
            "if(current==='AMI') ami(a); if(current==='Configuração') configs(a);",
            1,
        )

    if 'async function ami(a)' not in index:
        js = r'''
async function ami(a){
  let st={};
  try{st=await api('api/ami-status')}catch(e){st={connected:false,error:String(e)}}
  a.innerHTML=`<div class=card><h2>AMI — Asterisk Manager Interface</h2>
    <div class=note><b>O AMI pertence ao Asterisk inteiro.</b> Não é uma função do SIM800C, HT503 ou de qualquer trunk. Pode ser usado por Home Assistant, aplicações externas e ferramentas de gestão para receber eventos e enviar ações ao PBX.</div>
    <div class=grid>
      <div class=card><div class=sub>Estado AMI</div><div class="big ${st.connected?'ok':'bad'}">${st.connected?'ONLINE':'OFFLINE'}</div><div class=sub>${esc(st.banner||'')}</div></div>
      <div class=card><div class=sub>Listener</div><div class=big>${esc(st.port||5038)}</div><div class=sub>Bind: ${esc(st.bindaddr||'0.0.0.0')}</div></div>
      <div class=card><div class=sub>Utilizador AMI</div><div class=big>${esc(st.username||'homeassistant')}</div><div class=sub>Password protegida / não apresentada</div></div>
      <div class=card><div class=sub>Teste interno</div><div class="big ${st.connected?'ok':'bad'}">${st.connected?'PING OK':'FALHOU'}</div><div class=sub>127.0.0.1:${esc(st.port||5038)}</div></div>
    </div>
    ${st.error?`<div class=note><b>Erro AMI:</b> ${esc(st.error)}</div>`:''}
    <div class=actions><button class="btn primary" onclick="ami(E('#app'))">Testar / atualizar AMI</button></div>
    <h3>Sessões AMI ligadas</h3><pre>${esc(st.connected_sessions||'')}</pre>
    <h3>Definições runtime</h3><pre>${esc(st.manager_settings||'')}</pre>
    <div class=note><b>Segurança:</b> não encaminhes a porta AMI 5038 para a Internet. O acesso remoto deve ser feito por LAN/VPN/Tailscale ou outra rede confiável.</div>
  </div>`;
}
'''
        index = index.replace('</script>', js + '\n</script>', 1)
    return index
