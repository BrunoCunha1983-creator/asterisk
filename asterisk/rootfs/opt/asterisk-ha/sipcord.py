#!/usr/bin/env python3
import re

from ht503 import ensure_ht503_state, augment_index as augment_ht503_index

DEFAULT_SIPCORD = {
    'enabled': False,
    'server': 'bridge-eu1.sipcord.net',
    'port': 5060,
    'username': 'fair-quokka70',
    'password': '',
    'dial_pattern': '_15XX',
}


def esc(v):
    return str(v or '').replace('\\', '\\\\').replace(';', '').replace('\n', ' ').strip()


def token(v, default=''):
    out = re.sub(r'[^0-9A-Za-z_*#-]', '', str(v or ''))
    return out or default


def normalize_pattern(v):
    p = str(v or '_15XX').strip().upper()
    if not p.startswith('_'):
        p = '_' + p
    if not re.fullmatch(r'_[0-9XZN.!*#+\[\]-]+', p):
        return '_15XX'
    return p


def ensure_sipcord_state(data):
    """Add/migrate SIPcord state and normalize shared HT503 metadata."""
    if not isinstance(data, dict):
        data = {}
    data, ht503_changed = ensure_ht503_state(data)
    changed = bool(ht503_changed)
    sc = data.get('sipcord')
    trunks = list(data.get('sip_trunks') or [])

    if not isinstance(sc, dict):
        sc = dict(DEFAULT_SIPCORD)
        for t in trunks:
            server = str(t.get('server', '') or '').strip()
            name = str(t.get('name', '') or '').strip().lower()
            if server.lower().endswith('.sipcord.net') or 'sipcord' in name:
                sc.update({
                    'enabled': True,
                    'server': server or DEFAULT_SIPCORD['server'],
                    'port': int(t.get('port', 5060) or 5060),
                    'username': str(t.get('username', '') or DEFAULT_SIPCORD['username']),
                    'password': str(t.get('password', '') or ''),
                    'dial_pattern': '_15XX',
                })
                break
        data['sipcord'] = sc
        changed = True

    for k, v in DEFAULT_SIPCORD.items():
        if k not in sc:
            sc[k] = v
            changed = True

    sc['server'] = str(sc.get('server') or DEFAULT_SIPCORD['server']).strip()
    sc['username'] = str(sc.get('username') or DEFAULT_SIPCORD['username']).strip()
    sc['password'] = str(sc.get('password') or '')
    sc['port'] = int(sc.get('port', 5060) or 5060)
    sc['dial_pattern'] = normalize_pattern(sc.get('dial_pattern'))

    if sc.get('enabled'):
        keep = []
        for t in trunks:
            server = str(t.get('server', '') or '').strip().lower()
            username = str(t.get('username', '') or '').strip()
            name = str(t.get('name', '') or '').strip().lower()
            same = server == sc['server'].lower() and username == sc['username']
            legacy_sipcord = server.endswith('.sipcord.net') or 'sipcord' in name
            if same or legacy_sipcord:
                changed = True
                continue
            keep.append(t)
        if keep != trunks:
            data['sip_trunks'] = keep

    data['sipcord'] = sc
    return data, changed


def render_sipcord(conf, data):
    """Append SIPcord endpoint/AoR/auth and dial pattern after the base GUI renderer."""
    data, _ = ensure_sipcord_state(data)
    sc = data.get('sipcord') or {}
    if not sc.get('enabled'):
        return

    server = esc(sc.get('server') or DEFAULT_SIPCORD['server'])
    port = int(sc.get('port', 5060) or 5060)
    username = esc(sc.get('username'))
    password = esc(sc.get('password'))
    pattern = normalize_pattern(sc.get('dial_pattern'))

    pjsip = conf / 'pjsip_gui.conf'
    with pjsip.open('a') as f:
        f.write(
            '\n; SIPCORD / DISCORD - STATIC PJSIP TRUNK (NO OUTBOUND REGISTER)\n'
            '[sipcord]\n'
            'type=endpoint\n'
            'transport=transport-udp\n'
            'disallow=all\n'
            'allow=ulaw\n'
            'allow=alaw\n'
            'aors=sipcord\n'
            'outbound_auth=sipcord_auth\n'
            'direct_media=no\n'
            'rtp_symmetric=yes\n'
            'force_rport=yes\n'
            'rewrite_contact=yes\n'
            '; Send comfort-noise RTP regularly so outbound NAT/firewall mappings stay open.\n'
            'rtp_keepalive=5\n'
            '; Give the bridge longer than normal remote extensions before declaring media dead.\n'
            'rtp_timeout=60\n'
            'rtp_timeout_hold=300\n'
            'timers=yes\n'
            'timers_min_se=90\n'
            'timers_sess_expires=180\n'
            '\n[sipcord]\n'
            'type=aor\n'
            f'contact=sip:{server}:{port}\n'
            'qualify_frequency=15\n'
            'qualify_timeout=3.0\n'
            '\n[sipcord_auth]\n'
            'type=auth\n'
            'auth_type=userpass\n'
            f'username={username}\n'
            f'password={password}\n'
        )

    dial = conf / 'extensions_gui.conf'
    with dial.open('a') as f:
        f.write(
            '\n; SIPCORD / DISCORD\n'
            f'exten => {pattern},1,NoOp(SIPcord Discord ${{EXTEN}})\n'
            ' same => n,Dial(PJSIP/${EXTEN}@sipcord,90)\n'
            ' same => n,Hangup()\n'
        )


def augment_index(index):
    """Inject SIPcord and then upgrade the HT503 page to FXS + FXO."""
    if "'SIPcord / Discord'" not in index:
        index = index.replace(
            "'HT503 / FXO','Trunks SIP'",
            "'HT503 / FXO','SIPcord / Discord','Trunks SIP'",
        )
        index = index.replace(
            "if(current==='HT503 / FXO') ht503(a); if(current==='Trunks SIP')",
            "if(current==='HT503 / FXO') ht503(a); if(current==='SIPcord / Discord') sipcord(a); if(current==='Trunks SIP')",
        )

    if 'function sipcord(a)' not in index:
        js = r'''
async function sipcord(a){
  let s=pbx.sipcord||{enabled:false,server:'bridge-eu1.sipcord.net',port:5060,username:'fair-quokka70',password:'',dial_pattern:'_15XX'};
  let st=s.enabled?await api('api/sipcord-status'):{};
  a.innerHTML=`<div class=card><h2>SIPcord — SIP ↔ Discord</h2>
  <div class=note><b>Ligação correta:</b> trunk PJSIP estático, sem <code>type=registration</code>. O Asterisk envia as chamadas diretamente para o bridge SIPcord e autentica quando o bridge pede credenciais. Por defeito, qualquer extensão <b>15XX</b> vai para o número equivalente configurado no SIPcord.</div>
  <div class=note><b>Áudio / NAT:</b> SIPcord usa G.711 (ulaw/alaw). O trunk envia RTP keepalive de 5 s para manter o mapeamento NAT aberto. Se o endpoint estiver Reachable mas não houver áudio, confirma o encaminhamento UDP da gama RTP do add-on e desativa SIP ALG no router.</div>
  <div class=row>
    <div><label>Ativar SIPcord</label><select id=scen><option value=0 ${s.enabled?'':'selected'}>Não</option><option value=1 ${s.enabled?'selected':''}>Sim</option></select></div>
    <div><label>Servidor bridge</label><input id=scsrv value="${esc(s.server||'bridge-eu1.sipcord.net')}"></div>
    <div><label>Porta SIP</label><input id=scport value="${esc(s.port||5060)}"></div>
    <div><label>Username SIPcord</label><input id=scuser value="${esc(s.username||'fair-quokka70')}"></div>
    <div><label>Password SIPcord</label><input id=scpass type=password value="${esc(s.password||'')}"></div>
    <div><label>Padrão Asterisk</label><input id=scpat value="${esc(s.dial_pattern||'_15XX')}"></div>
  </div>
  <div class=actions><button class="btn primary" onclick=saveSIPcord()>Guardar e aplicar</button><button class=btn onclick=sipcord(E('#app'))>Atualizar estado</button></div>
  ${s.enabled?`<h3>Estado PJSIP</h3><pre>${esc(st.endpoint||'')}\n${esc(st.aor||'')}\n${esc(st.contacts||'')}</pre>`:''}</div>`;
}
async function saveSIPcord(){
  pbx.sipcord={enabled:E('#scen').value==='1',server:E('#scsrv').value,port:+E('#scport').value,username:E('#scuser').value,password:E('#scpass').value,dial_pattern:E('#scpat').value};
  await savePbx();
}
'''
        index = index.replace('function trunks(a){', js + '\nfunction trunks(a){')
    return augment_ht503_index(index)
