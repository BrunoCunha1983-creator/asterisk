#!/usr/bin/env python3
import re


def ensure_webrtc_state(data):
    """Normalize the optional WebRTC flag on managed PJSIP extensions."""
    if not isinstance(data, dict):
        data = {}
    extensions = data.get('extensions')
    if not isinstance(extensions, list):
        extensions = []
        data['extensions'] = extensions
        return data, True

    changed = False
    for ext in extensions:
        if not isinstance(ext, dict):
            continue
        value = bool(ext.get('webrtc', False))
        if ext.get('webrtc') is not value:
            ext['webrtc'] = value
            changed = True
    return data, changed


def augment_index(index):
    """Add a WebRTC/Lovelace toggle and one-click WebRTC extension creation."""
    replacement = r'''function extensions(a){let x=pbx.extensions||[];a.innerHTML=`<div class=card><h2>Extensões PJSIP</h2><div class=note>Telefones/ATA registam-se normalmente por SIP/UDP. Para o <b>card Lovelace no browser</b>, ativa <b>WebRTC</b>. O Asterisk disponibiliza WebSocket SIP em <code>ws://IP_ASTERISK:8088/ws</code>; quando existem certificados Home Assistant em <code>/ssl</code>, também disponibiliza <code>wss://IP_ASTERISK:8089/ws</code>.</div><div id=elist>${x.map((e,i)=>`<div class=item><div class=row><div><label>Extensão</label><input id=e${i} value="${esc(e.extension)}"></div><div><label>Caller ID</label><input id=c${i} value="${esc(e.callerid)}"></div><div><label>Password SIP</label><input id=s${i} value="${esc(e.secret)}"></div><div><label>PIN Voicemail</label><input id=v${i} value="${esc(e.voicemail_pin||'1234')}"></div><div><label>Contexto</label><input id=x${i} value="${esc(e.context||'from-internal')}"></div><div><label>WebRTC / Lovelace</label><select id=w${i}><option value=0 ${e.webrtc?'':'selected'}>Não</option><option value=1 ${e.webrtc?'selected':''}>Sim</option></select></div></div><button class=btn onclick="delExt(${i})">Remover</button></div>`).join('')}</div><div class=actions><button class=btn onclick=addExt()>+ Extensão</button><button class=btn onclick=addWebRTCExt()>+ Lovelace WebRTC</button><button class="btn primary" onclick=saveExt()>Guardar e aplicar</button></div></div>`}
function addExt(){pbx.extensions=pbx.extensions||[];pbx.extensions.push({extension:String(100+pbx.extensions.length),callerid:'Nova extensão',secret:Math.random().toString(36).slice(2,14),voicemail_pin:'1234',context:'from-internal',webrtc:false});extensions(E('#app'))}
function addWebRTCExt(){pbx.extensions=pbx.extensions||[];let used=new Set(pbx.extensions.map(e=>String(e.extension||'')));let n=201;while(used.has(String(n))&&n<299)n++;pbx.extensions.push({extension:String(n),callerid:'Home Assistant Lovelace',secret:Math.random().toString(36).slice(2,18),voicemail_pin:'1234',context:'from-internal',webrtc:true});extensions(E('#app'))}
function delExt(i){pbx.extensions.splice(i,1);extensions(E('#app'))}
async function saveExt(){pbx.extensions=(pbx.extensions||[]).map((e,i)=>({...e,extension:E('#e'+i).value,callerid:E('#c'+i).value,secret:E('#s'+i).value,voicemail_pin:E('#v'+i).value,context:E('#x'+i).value,webrtc:E('#w'+i).value==='1'}));await savePbx()}
'''
    pattern = r'function extensions\(a\)\{.*?async function saveExt\(\)\{.*?\}\n'
    if re.search(pattern, index, flags=re.S):
        index = re.sub(pattern, lambda _m: replacement, index, count=1, flags=re.S)
    return index
