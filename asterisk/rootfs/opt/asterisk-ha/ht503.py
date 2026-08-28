#!/usr/bin/env python3
import re


def _clean_extension(value):
    return re.sub(r'[^0-9A-Za-z_*#-]', '', str(value or ''))


def ensure_ht503_state(data):
    """Normalize HT503 state and guarantee an enabled FXS has a PJSIP extension.

    The FXS port is still represented by the normal ``extensions`` model, but
    its credentials are mirrored under ``ht503``. This makes the HT503 page a
    first-class configuration source and prevents a state where FXS is enabled
    while no matching PJSIP endpoint exists.
    """
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
        'fxs_callerid': 'HT503 FXS',
        'fxs_secret': '',
        'fxs_voicemail_pin': '1234',
        'fxs_context': 'from-internal',
        'fxs_local_sip_port': 5062,
    }
    for key, value in defaults.items():
        if key not in ht:
            ht[key] = value
            changed = True

    ht['fxs_enabled'] = bool(ht.get('fxs_enabled', False))
    ht['fxs_extension'] = _clean_extension(ht.get('fxs_extension'))
    ht['fxs_callerid'] = str(ht.get('fxs_callerid') or 'HT503 FXS').strip()
    ht['fxs_secret'] = str(ht.get('fxs_secret') or '')
    ht['fxs_voicemail_pin'] = re.sub(r'[^0-9*#]', '', str(ht.get('fxs_voicemail_pin') or '1234')) or '1234'
    ht['fxs_context'] = _clean_extension(ht.get('fxs_context') or 'from-internal') or 'from-internal'
    try:
        ht['fxs_local_sip_port'] = int(ht.get('fxs_local_sip_port', 5062) or 5062)
    except Exception:
        ht['fxs_local_sip_port'] = 5062
        changed = True

    extensions = data.get('extensions')
    if not isinstance(extensions, list):
        extensions = []
        data['extensions'] = extensions
        changed = True

    fxs = ht['fxs_extension']
    ext = None
    if fxs:
        for item in extensions:
            if isinstance(item, dict) and _clean_extension(item.get('extension')) == fxs:
                ext = item
                break

    # Migration: prefer already-working extension values when the new HT503
    # metadata did not yet have explicit values.
    if ext is not None:
        if not ht['fxs_secret'] and str(ext.get('secret') or ''):
            ht['fxs_secret'] = str(ext.get('secret') or '')
            changed = True
        if (not ht['fxs_callerid'] or ht['fxs_callerid'] == 'HT503 FXS') and str(ext.get('callerid') or ''):
            ht['fxs_callerid'] = str(ext.get('callerid') or '')
            changed = True
        if (not ht['fxs_voicemail_pin'] or ht['fxs_voicemail_pin'] == '1234') and str(ext.get('voicemail_pin') or ''):
            ht['fxs_voicemail_pin'] = str(ext.get('voicemail_pin') or '')
            changed = True
        if (not ht['fxs_context'] or ht['fxs_context'] == 'from-internal') and str(ext.get('context') or ''):
            ht['fxs_context'] = str(ext.get('context') or '')
            changed = True

    # If FXS is enabled, make the referenced normal PJSIP extension exist.
    # A blank secret is allowed so the UI stays available and the endpoint is
    # at least identifiable; the GUI warns the user to set the matching secret.
    if ht['fxs_enabled'] and fxs:
        desired = {
            'extension': fxs,
            'callerid': ht['fxs_callerid'],
            'secret': ht['fxs_secret'],
            'voicemail_pin': ht['fxs_voicemail_pin'],
            'context': ht['fxs_context'],
        }
        if ext is None:
            extensions.append(desired)
            ext = extensions[-1]
            changed = True
        else:
            for key, value in desired.items():
                if ext.get(key) != value:
                    ext[key] = value
                    changed = True

    data['extensions'] = extensions
    data['ht503'] = ht
    return data, changed


def validate_ht503_state(data):
    """Validate the relationship between the two independent HT503 ports."""
    ht = (data or {}).get('ht503') or {}
    if not ht.get('fxs_enabled'):
        return True

    fxs = _clean_extension(ht.get('fxs_extension'))
    if not fxs:
        raise ValueError('HT503 FXS: escolhe ou cria uma extensão')

    fxo_user = _clean_extension(ht.get('fxo_user'))
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
  let fxsSecret=String(fe.secret??h.fxs_secret??'');
  a.innerHTML=`<div class=card><h2>Grandstream HT503 — FXS + FXO</h2>
  <div class=note>O HT503 tem duas portas independentes. <b>FXS</b> liga o telefone analógico e funciona como uma extensão PJSIP normal. <b>FXO</b> liga a linha telefónica exterior e também se regista no Asterisk. Nenhuma das duas necessita de <code>type=registration</code> outbound no Asterisk.</div>

  <div class=item><h3>☎ FXS — telefone analógico</h3>
  <div class=note>No HT503 FXS: Primary SIP Server = IP deste Asterisk; SIP User ID / Authenticate ID = extensão abaixo; SIP Registration = Yes. Ao ativar FXS, esta página garante automaticamente que a extensão PJSIP correspondente existe.</div>
  ${h.fxs_enabled&&!fxsSecret?'<div class=note><b>⚠ Falta a Password SIP da FXS.</b> O endpoint é criado, mas o HT503 não conseguirá autenticar até esta password ser igual ao Authenticate Password configurado na porta FXS.</div>':''}
  <div class=row>
    <div><label>Ativar FXS</label><select id=hfxsen><option value=0 ${h.fxs_enabled?'':'selected'}>Não</option><option value=1 ${h.fxs_enabled?'selected':''}>Sim</option></select></div>
    <div><label>Usar extensão existente</label><select id=hfxssel onchange="loadHTFXS(this.value)">${extopts}</select></div>
    <div><label>Extensão / SIP User ID</label><input id=hfxsnum value="${esc(fnum)}" placeholder="200"></div>
    <div><label>Caller ID</label><input id=hfxscid value="${esc(fe.callerid||h.fxs_callerid||'HT503 FXS')}"></div>
    <div><label>Password SIP / Authenticate Password</label><input id=hfxssec type=password value="${esc(fxsSecret)}"></div>
    <div><label>PIN Voicemail</label><input id=hfxsvm value="${esc(fe.voicemail_pin||h.fxs_voicemail_pin||'1234')}"></div>
    <div><label>Contexto</label><input id=hfxsctx value="${esc(fe.context||h.fxs_context||'from-internal')}"></div>
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
        index = re.sub(
            pattern,
            lambda _m: new_ht503 + '\nasync function saveHT()',
            index,
            count=1,
            flags=re.S,
        )

    new_save = r'''async function saveHT(){
  let old=pbx.ht503||{};
  let fxsEnabled=E('#hfxsen').value==='1';
  let fxsNum=E('#hfxsnum').value.trim();
  let fxsCaller=E('#hfxscid').value;
  let fxsSecret=E('#hfxssec').value;
  let fxsVm=E('#hfxsvm').value;
  let fxsContext=E('#hfxsctx').value||'from-internal';
  let fxoEnabled=E('#hen').value==='1';
  let fxoUser=E('#huser').value.trim();
  if(fxsEnabled&&!fxsNum){alert('Escolhe ou cria a extensão FXS.');return}
  if(fxsEnabled&&!fxsSecret){if(!confirm('A FXS está sem Password SIP. O endpoint será criado mas o HT503 não conseguirá autenticar. Guardar na mesma?'))return}
  if(fxsEnabled&&fxoEnabled&&fxsNum===fxoUser){alert('FXS e FXO têm de usar utilizadores SIP diferentes.');return}
  if(fxsNum){
    pbx.extensions=pbx.extensions||[];
    let oldNum=String(old.fxs_extension||'');
    let idx=pbx.extensions.findIndex(e=>String(e.extension||'')===fxsNum);
    let oldIdx=pbx.extensions.findIndex(e=>String(e.extension||'')===oldNum);
    let values={extension:fxsNum,callerid:fxsCaller,secret:fxsSecret,voicemail_pin:fxsVm,context:fxsContext};
    if(idx>=0) pbx.extensions[idx]={...pbx.extensions[idx],...values};
    else if(oldIdx>=0) pbx.extensions[oldIdx]={...pbx.extensions[oldIdx],...values};
    else pbx.extensions.push(values);
  }
  pbx.ht503={...old,
    fxs_enabled:fxsEnabled,fxs_extension:fxsNum,fxs_callerid:fxsCaller,fxs_secret:fxsSecret,fxs_voicemail_pin:fxsVm,fxs_context:fxsContext,fxs_local_sip_port:+E('#hfxsport').value,
    enabled:fxoEnabled,device_ip:E('#hip').value,fxo_user:fxoUser,fxo_secret:E('#hsec').value,callerid:E('#hcid').value,incoming_target:E('#htarget').value,outbound_prefix:E('#hpre').value,local_sip_port:+E('#hport').value};
  await savePbx();
}'''
    index = re.sub(
        r'async function saveHT\(\)\{[^\n]*\}',
        lambda _m: new_save,
        index,
        count=1,
    )
    return index
