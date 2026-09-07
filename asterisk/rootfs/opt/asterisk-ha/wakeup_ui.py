#!/usr/bin/env python3


def augment_index(index):
    if "'Despertador'" not in index:
        if "'Chamadas','AMI','Configuração'" in index:
            index = index.replace("'Chamadas','AMI','Configuração'", "'Chamadas','Despertador','AMI','Configuração'", 1)
        else:
            index = index.replace("'Chamadas','Configuração'", "'Chamadas','Despertador','Configuração'", 1)
        index = index.replace(
            "if(current==='Chamadas') calls(a);",
            "if(current==='Chamadas') calls(a); if(current==='Despertador') wakeup(a);",
            1,
        )
    if 'async function wakeup(a)' in index:
        return index

    js = r'''
const WAKE_DAYS=['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];
const WAKE_DEFAULT_SOUND='ha/wakeup-pt';
async function wakeup(a){
  let st={alarms:[],events:[]};
  try{st=await api('api/wakeup-status')}catch(e){st={alarms:[],events:[],error:String(e)}}
  let exts=(pbx.extensions||[]).map(e=>String(e.extension||'')).filter(Boolean);
  let extOpts=(cur)=>exts.map(x=>`<option value="${esc(x)}" ${String(cur)===x?'selected':''}>${esc(x)}</option>`).join('');
  let rows=(st.alarms||[]).map((x,i)=>{
    let days=WAKE_DAYS.map((d,n)=>`<label><input type=checkbox id=wd${i}_${n} ${x.days&&x.days.includes(n)?'checked':''}> ${d}</label>`).join(' ');
    return `<div class=item>
      <div class=row>
        <div><label>Ativo</label><select id=wen${i}><option value=1 ${x.enabled?'selected':''}>Sim</option><option value=0 ${x.enabled?'':'selected'}>Não</option></select></div>
        <div><label>Nome</label><input id=wlabel${i} value="${esc(x.label||'Serviço Despertar')}"></div>
        <div><label>Extensão</label><select id=wext${i}>${extOpts(x.extension)}${exts.includes(String(x.extension||''))?'':`<option selected>${esc(x.extension||'')}</option>`}</select></div>
        <div><label>Hora</label><input id=wtime${i} type=time value="${esc(x.time||'07:00')}"></div>
        <div><label>Data única (opcional)</label><input id=wdate${i} type=date value="${esc(x.date||'')}"></div>
        <div><label>Gravação</label><input id=wsound${i} value="${esc(x.sound||WAKE_DEFAULT_SOUND)}" placeholder="${WAKE_DEFAULT_SOUND}" readonly></div>
      </div>
      <div class=note><b>Dias recorrentes:</b> ${days}<br><span class=sub>Se definires uma data única, os dias da semana são ignorados e o despertador desativa-se depois de tocar.</span></div>
      <div class=actions><button class=btn onclick="testWake(${i})">▶ Testar chamada + áudio</button><button class=btn onclick="delWake(${i})">Apagar</button></div>
      <div class=sub>Último disparo: ${esc(x.last_fired||'—')}</div>
    </div>`;
  }).join('');
  let promptState=st.bundled_prompt_available
    ? '<span class="ok"><b>PT-PT INCORPORADO</b></span> — mensagem gerada dentro do add-on'
    : (st.classic_prompt_available
      ? '<span class="warn"><b>FALLBACK INGLÊS</b></span> — this-is-yr-wakeup-call'
      : '<span class="bad"><b>SEM FICHEIRO DE VOZ</b></span> — a chamada continua mesmo assim');
  a.innerHTML=`<div class=grid>
    <div class=card><div class=sub>Serviço</div><div class="big ${st.scheduler_online?'ok':'bad'}">${st.scheduler_online?'ONLINE':'OFFLINE'}</div><div class=sub>${esc(st.timezone||'Europe/Lisbon')}</div></div>
    <div class=card><div class=sub>Wakeup Engine</div><div class=big>${esc(st.engine_version||'ANTIGO')}</div><div class=sub>${esc(st.call_mode||'modo antigo')}</div></div>
    <div class=card><div class=sub>Despertadores ativos</div><div class=big>${st.active||0}</div></div>
    <div class=card><div class=sub>Hora do serviço</div><div class=big>${esc((st.now||'').slice(11,16)||'—')}</div></div>
  </div>
  <div class=card><h2>Serviço Despertar — Asterisk</h2>
    <div class=note><b>Motor esperado:</b> <code>0.2.28 / dialplan:wakeup-call</code><br><span class=sub>Esta versão usa áudio PT-PT criado dentro da própria imagem e Playback tolerante a falhas.</span></div>
    <div class=note><b>Gravação padrão:</b> ${promptState}<br><span class=sub>Prompt resolvido: <code>${esc(st.resolved_prompt||'—')}</code></span></div>
    <div class=note>Ao atender: espera cerca de 1 s, gera um tom curto, tenta <code>ha/wakeup-pt</code> e mantém a chamada viva mesmo que um ficheiro de áudio falhe. Por isso uma chamada que volte a desligar exatamente aos ~2 s indica que ainda está a correr uma imagem anterior.</div>
    ${rows||'<div class=item>Nenhum despertador configurado.</div>'}
    <div class=actions><button class=btn onclick=addWake()>+ Chamada de Despertar</button><button class="btn primary" onclick=saveWake()>Guardar</button><button class=btn onclick="wakeup(E('#app'))">Atualizar</button></div>
    <h3>Eventos recentes</h3><pre>${esc((st.events||[]).map(e=>`${e.at||''} ${e.text||''}`).join('\n')||'Sem eventos.')}</pre>
  </div>`;
}
function addWake(){
  api('api/wakeup-status').then(r=>{
    let a=r.alarms||[];
    a.push({id:'alarm'+Date.now(),enabled:true,label:'Serviço Despertar',extension:String((pbx.extensions||[])[0]?.extension||'100'),time:'07:00',days:[0,1,2,3,4],date:'',sound:WAKE_DEFAULT_SOUND});
    renderWakeDraft(a);
  });
}
function renderWakeDraft(a){
  api('api/wakeup-action',{method:'POST',body:JSON.stringify({action:'save',alarms:a})}).then(()=>wakeup(E('#app')));
}
async function saveWake(){
  let st=await api('api/wakeup-status'); let alarms=st.alarms||[];
  alarms=alarms.map((x,i)=>({...x,enabled:E('#wen'+i).value==='1',label:E('#wlabel'+i).value,extension:E('#wext'+i).value,time:E('#wtime'+i).value,date:E('#wdate'+i).value,sound:WAKE_DEFAULT_SOUND,days:WAKE_DAYS.map((_,n)=>n).filter(n=>E('#wd'+i+'_'+n).checked)}));
  let r=await api('api/wakeup-action',{method:'POST',body:JSON.stringify({action:'save',alarms})});
  if(!r.ok) alert(r.output||r.error||'Erro ao guardar');
  await wakeup(E('#app'));
}
async function delWake(i){
  let st=await api('api/wakeup-status'); let alarms=st.alarms||[]; alarms.splice(i,1);
  await api('api/wakeup-action',{method:'POST',body:JSON.stringify({action:'save',alarms})}); await wakeup(E('#app'));
}
async function testWake(i){
  let st=await api('api/wakeup-status'); let x=(st.alarms||[])[i]; if(!x)return;
  let r=await api('api/wakeup-action',{method:'POST',body:JSON.stringify({action:'test',extension:E('#wext'+i).value,sound:WAKE_DEFAULT_SOUND})});
  alert((r.ok?'Chamada iniciada.\n':'ERRO — chamada não iniciada.\n')+
    'Engine: '+(r.engine_version||'ANTIGO')+'\n'+
    'Modo: '+(r.call_mode||'desconhecido')+'\n'+
    'Dialplan pronto: '+(r.dialplan_ready===true?'SIM':r.dialplan_ready===false?'NÃO':'?')+'\n'+
    (r.sound?'Gravação: '+r.sound+'\n':'')+
    (r.output||''));
  await wakeup(E('#app'));
}
'''
    return index.replace('</script>', js + '\n</script>', 1)
