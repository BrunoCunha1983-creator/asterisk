#!/usr/bin/env python3
import re


def ensure_ht503_state(data):
    """Add non-destructive FXS metadata to the existing HT503 section."""
    if not isinstance(data, dict):
        data = {}
    changed = False
    ht = data.get('ht503')
    if not isinstance(ht, dict):
        ht = {}
        data['ht503'] = ht
        changed = True

    defaults = {
        'fxs_enabled': False,
        'fxs_extension': '',
        'fxs_local_sip_port': 5062,
    }
    for key, value in defaults.items():
        if key not in ht:
            ht[key] = value
            changed = True

    ht['fxs_enabled'] = bool(ht.get('fxs_enabled', False))
    ht['fxs_extension'] = re.sub(r'[^0-9A-Za-z_*#-]', '', str(ht.get('fxs_extension') or ''))
    try:
        ht['fxs_local_sip_port'] = int(ht.get('fxs_local_sip_port', 5062) or 5062)
    except Exception:
        ht['fxs_local_sip_port'] = 5062
        changed = True

    data['ht503'] = ht
    return data, changed


def validate_ht503_state(data):
    """Ensure an enabled FXS port references a real PJSIP extension."""
    ht = (data or {}).get('ht503') or {}
    if not ht.get('fxs_enabled'):
        return True

    fxs = str(ht.get('fxs_extension') or '').strip()
    if not fxs:
        raise ValueError('HT503 FXS: escolhe ou cria uma extensão')

    extensions = {
        str(e.get('extension') or '').strip()
        for e in ((data or {}).get('extensions') or [])
        if isinstance(e, dict)
    }
    if fxs not in extensions:
        raise ValueError(f'HT503 FXS: a extensão {fxs} não existe')

    fxo_user = str(ht.get('fxo_user') or '').strip()
    if ht.get('enabled') and fxo_user and fxo_user == fxs:
        raise ValueError('HT503: FXS e FXO não podem usar o mesmo utilizador/extensão SIP')
    return True


def augment_index(index):
    """Replace the old FXO-only HT503 page with one unified FXS/FXO page."""
    index = index.replace('HT503 / FXO', 'HT503 FXS / FXO')

    new_ht503 = r'''function htLines(text,key){
  if(!key)return '';
  return String(text||'').split('\n').filter(l=>l.includes(key)).join('\n');
}
async function ht503(a){
  let h=pbx.ht503||{};
  let fnum=String(h.fxs_extension||'');
  let fe=(pbx.extensions||[]).find(e=>String(e.extension||'')===fnum)||{};
  let st=(h.enabled||h.fxs_enabled)?await api('api/ht503-status'):{};
  let all=h.fxs_enabled?await api('api/calls'):{};
  let fxsStatus=htLines(all.endpoints||'',fnum);
  let fxsContact=htLines(st.contacts||'',fnum+'/')||htLines(st.contacts||'','sip:'+fnum+'@');
  let fxoStatus=st.endpoint||'';
  let fxoContact=htLines(st.contacts||'',String(h.fxo_user||'')+'/')||htLines(st.contacts||'','sip:'+String(h.fxo_user||'')+'@');
  let extopts=['<option value="">— escolher/criar —</option>'].concat((pbx.extensions||[]).map(e=>`<option value="${esc(e.extension)}" ${String(e.extension)===fnum?'selected':''}>${esc(e.extension)} — ${esc(e.callerid||'')}</option>`)).join('');
  a.innerHTML=`<div class=card><h2>Grandstream HT503 — FXS + FXO</h2>
  <div class=note>O HT503 tem duas portas independentes. <b>FXS</b> liga o telefone analógico e funciona como uma extensão PJSIP normal. <b>FXO</b> liga a linha telefónica exterior e também se regista no Asterisk. Nenhuma das duas necessita de <code>type=registration</code> outbound no Asterisk.</div>

  <div class=item><h3>☎ FXS — telefone analógico</h3>
  <div class=note>No HT503 FXS: Primary SIP Server = IP deste Asterisk; SIP User ID / Authenticate ID = extensão abaixo; SIP Registration = Yes. A configuração é guardada também em <b>Extensões</b>, por isso voicemail e chamadas internas continuam normais.</div>
  <div class=row>
    <div><label>Ativar FXS</label><select id=hfxsen><option value=0 ${h.fxs_enabled?'':'selected'}>Não</option><option value=1 ${h.fxs_enabled?'selected':''}>Sim</option></select></div>
    <div><label>Usar extensão existente</label><select id=hfxssel onchange="loadHTFXS(this.value)">${extopts}</select></div>
    <div><label>Extensão / SIP User ID</label><input id=hfxsnum value="${esc(fnum)}" placeholder="200"></div>
    <div><label>Caller ID</label><input id=hfxscid value="${esc(fe.callerid||'HT503 FXS')}"></div>
    <div><label>Password SIP</label><input id=hfxssec type=password value="${esc(fe.secret||'')}"></div>
    <div><label>PIN Voicemail</label><input id=hfxsvm value="${esc(fe.voicemail_pin||'1234')}"></div>
    <div><label>Contexto</label><input id=hfxsctx value="${esc(fe.context||'from-internal')}"></div>
    <div><label>Porta SIP local FXS (informativo)</label><input id=hfxsport value="${esc(h.fxs_local_sip_port||5062)}"></div>
  </div>
  ${h.fxs_enabled?`<h4>Estado FXS</h4><pre>${esc(fxsStatus||'Sem endpoint/contacto FXS visível neste momento')}\n${esc(fxsContact||'')}</pre>`:''}
  </div>

  <div class=item><h3>☎ FXO — linha exterior / PSTN</h3>
  <div class=note>No HT503 FXO: Primary SIP Server = IP deste Asterisk; SIP User ID e Authenticate ID = o utilizador abaixo; SIP Registration = Yes. O HT503 regista-se <b>no Asterisk</b>.</div>
  <div class=row>
    <div><label>Ativar FXO</label><select id=hen><option value=0 ${h.enabled?'':'selected'}>Não</option><option value=1 ${h.enabled?'selected':''}>Sim</option></select></div>
    <div><label>IP do HT503</label><input id=hip value="${esc(h.device_ip||'')}" placeholder="192.168.1.253"></div>
    <div><label>Utilizador FXO / SIP User ID</label><input id=huser value="${esc(h.fxo_user||'ht503fxo')}"></div>
    <div><label>Password / Authenticate Password</label><input id=hsec type=password value="${esc(h.fxo_secret||'')}"></div>
    <div><label>Caller ID</label><input id=hcid value="${esc(h.callerid||'Exterior')}"></div>
    <div><label>Destino das chamadas PSTN</label><input id=htarget value="${esc(h.incoming_target||'100')}" placeholder="100 ou 600 (IVR)"></div>
    <div><label>Prefixo para chamadas PSTN</label><input id=hpre value="${esc(h.outbound_prefix||'8')}"></div>
    <div><label>Porta SIP local FXO (informativo)</label><input id=hport value="${esc(h.local_sip_port||5064)}"></div>
  </div>
  ${h.enabled?`<h4>Estado FXO</h4><pre>${esc(fxoStatus||'Sem endpoint FXO visível neste momento')}\n${esc(fxoContact||'')}</pre>`:''}
  </div>

  <div class=actions><button class="btn primary" onclick=saveHT()>Guardar FXS + FXO</button><button class=btn onclick=ht503(E('#app'))>Atualizar estado</button></div>
  ${(h.enabled||h.fxs_enabled)?`<h3>Contactos PJSIP</h3><pre>${esc(st.contacts||'')}</pre>`:''}</div>`;
}
function loadHTFXS(num){
  let e=(pbx.extensions||[]).find(x=>String(x.extension||'')===String(num||''));
  if(!e)return;
  E('#hfxsnum').value=e.extension||'';
  E('#hfxscid').value=e.callerid||'';
  E('#hfxssec').value=e.secret||'';
  E('#hfxsvm').value=e.voicemail_pin||'1234';
  E('#hfxsctx').value=e.context||'from-internal';
}
'''

    pattern = r'async function ht503\(a\)\{.*?\}\nasync function saveHT\(\)'
    if re.search(pattern, index, flags=re.S):
        index = re.sub(pattern, new_ht503 + '\nasync function saveHT()', index, count=1, flags=re.S)

    new_save = r'''async function saveHT(){
  let old=pbx.ht503||{};
  let fxsEnabled=E('#hfxsen').value==='1';
  let fxsNum=E('#hfxsnum').value.trim();
  let fxoEnabled=E('#hen').value==='1';
  let fxoUser=E('#huser').value.trim();
  if(fxsEnabled&&!fxsNum){alert('Escolhe ou cria a extensão FXS.');return}
  if(fxsEnabled&&fxoEnabled&&fxsNum===fxoUser){alert('FXS e FXO têm de usar utilizadores SIP diferentes.');return}
  if(fxsNum){
    pbx.extensions=pbx.extensions||[];
    let oldNum=String(old.fxs_extension||'');
    let idx=pbx.extensions.findIndex(e=>String(e.extension||'')===fxsNum);
    let oldIdx=pbx.extensions.findIndex(e=>String(e.extension||'')===oldNum);
    let values={extension:fxsNum,callerid:E('#hfxscid').value,secret:E('#hfxssec').value,voicemail_pin:E('#hfxsvm').value,context:E('#hfxsctx').value||'from-internal'};
    if(idx>=0) pbx.extensions[idx]={...pbx.extensions[idx],...values};
    else if(oldIdx>=0) pbx.extensions[oldIdx]={...pbx.extensions[oldIdx],...values};
    else pbx.extensions.push(values);
  }
  pbx.ht503={...old,
    fxs_enabled:fxsEnabled,fxs_extension:fxsNum,fxs_local_sip_port:+E('#hfxsport').value,
    enabled:fxoEnabled,device_ip:E('#hip').value,fxo_user:fxoUser,fxo_secret:E('#hsec').value,callerid:E('#hcid').value,incoming_target:E('#htarget').value,outbound_prefix:E('#hpre').value,local_sip_port:+E('#hport').value};
  await savePbx();
}'''
    index = re.sub(r'async function saveHT\(\)\{[^\n]*\}', new_save, index, count=1)
    return index
