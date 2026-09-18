#!/usr/bin/env python3


def augment_index(index):
    """Add a PBX-wide Asterisk ARI page to the Ingress UI."""
    if "'ARI'" not in index:
        index = index.replace("'AMI','Configuração'", "'AMI','ARI','Configuração'", 1)
        index = index.replace(
            "if(current==='AMI') ami(a); if(current==='Configuração') configs(a);",
            "if(current==='AMI') ami(a); if(current==='ARI') ari(a); if(current==='Configuração') configs(a);",
            1,
        )

    if 'async function ari(a)' not in index:
        js = r'''
async function ari(a){
  let st={};
  try{st=await api('api/ari-status')}catch(e){st={connected:false,error:String(e)}}
  let bi=(st.asterisk_info||{}).build||{};
  let si=(st.asterisk_info||{}).system||{};
  a.innerHTML=`<div class=card><h2>ARI — Asterisk REST Interface</h2>
    <div class=note><b>O ARI pertence ao Asterisk inteiro.</b> É a API REST/WebSocket usada por aplicações para controlar canais, bridges, playbacks e outras funções em tempo real. O teste abaixo usa autenticação local e nunca mostra a password.</div>
    <div class=grid>
      <div class=card><div class=sub>Estado ARI</div><div class="big ${st.connected?'ok':'bad'}">${st.connected?'ONLINE':'OFFLINE'}</div><div class=sub>${st.connected?'REST autenticado':'Teste REST falhou'}</div></div>
      <div class=card><div class=sub>Listener HTTP</div><div class=big>${esc(st.port||8088)}</div><div class=sub>Teste: 127.0.0.1:${esc(st.port||8088)}</div></div>
      <div class=card><div class=sub>Utilizador ARI</div><div class=big>${esc(st.username||'homeassistant')}</div><div class=sub>Password protegida / não apresentada</div></div>
      <div class=card><div class=sub>HTTP interno</div><div class="big ${st.connected?'ok':'bad'}">${esc(st.http_status||'-')}</div><div class=sub>/ari/asterisk/info</div></div>
    </div>
    ${st.error?`<div class=note><b>Erro ARI:</b> ${esc(st.error)}</div>`:''}
    <div class=actions><button class="btn primary" onclick="ari(E('#app'))">Testar / atualizar ARI</button></div>
    <h3>Informação Asterisk via ARI</h3><pre>${esc(JSON.stringify(st.asterisk_info||{},null,2))}</pre>
    <h3>Estado HTTP runtime</h3><pre>${esc(st.http_runtime||'')}</pre>
    <h3>Estado ARI runtime</h3><pre>${esc(st.ari_runtime||'')}</pre>
    <h3>Utilizadores ARI runtime</h3><pre>${esc(st.ari_users||'')}</pre>
    <h3>Módulos necessários ARI</h3><pre>${esc(st.ari_modules||'')}</pre>
    <div class=note><b>Segurança:</b> não encaminhes a porta HTTP/ARI ${esc(st.port||8088)} diretamente para a Internet. Para acesso remoto usa LAN/VPN/Tailscale/reverse proxy autenticado conforme o caso.</div>
  </div>`;
}
'''
        index = index.replace('</script>', js + '\n</script>', 1)
    return index
