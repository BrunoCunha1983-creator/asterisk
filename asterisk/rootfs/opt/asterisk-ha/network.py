#!/usr/bin/env python3
import ipaddress
import json
import re
import subprocess
import urllib.request
from pathlib import Path


NAT_STATUS = Path('/config/state/nat.json')
DEFAULT_NETWORK = {
    'external_address': '',
    'auto_external': True,
    'local_nets': [],
    'auto_local_nets': True,
    'rtp_keepalive': 15,
    'rtp_timeout': 30,
    'rtp_timeout_hold': 300,
    'session_timers': True,
}


def _clamp_int(value, default, low, high):
    try:
        value = int(value)
    except Exception:
        value = default
    return max(low, min(high, value))


def detect_local_networks():
    """Return private IPv4 networks assigned to the host."""
    found = []
    try:
        p = subprocess.run(
            ['ip', '-o', '-4', 'addr', 'show', 'scope', 'global'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        for line in p.stdout.splitlines():
            m = re.search(r'\binet\s+([0-9.]+/\d+)\b', line)
            if not m:
                continue
            try:
                net = ipaddress.ip_interface(m.group(1)).network
            except ValueError:
                continue
            if net.is_private and not net.is_loopback:
                value = str(net)
                if value not in found:
                    found.append(value)
    except Exception:
        pass
    return found


def detect_public_address():
    """Best-effort public IPv4 discovery, used by auto mode and the GUI."""
    urls = (
        'https://api.ipify.org',
        'https://checkip.amazonaws.com',
    )
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Asterisk-HA/0.2.6'})
            with urllib.request.urlopen(req, timeout=4) as r:
                value = r.read(128).decode('ascii', 'ignore').strip()
            ip = ipaddress.ip_address(value)
            if ip.version == 4 and not ip.is_private:
                return str(ip)
        except Exception:
            continue
    return ''


def _nat_status_external():
    """Reuse the public address already detected by bootstrap/nat.py."""
    try:
        data = json.loads(NAT_STATUS.read_text())
        value = str(data.get('external_address') or '').strip()
        if value:
            ipaddress.ip_address(value)
            return value
    except Exception:
        pass
    return ''


def _normalise_external(value):
    value = str(value or '').strip()
    value = re.sub(r'^https?://', '', value, flags=re.I).split('/')[0].strip()
    if not value:
        return ''
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not re.fullmatch(r'[A-Za-z0-9.-]+', value) or '..' in value or value.startswith('.') or value.endswith('.'):
        raise ValueError('Rede/NAT: endereço público inválido')
    return value


def _normalise_nets(values):
    if isinstance(values, str):
        values = re.split(r'[,;\n ]+', values)
    out = []
    for raw in values or []:
        raw = str(raw or '').strip()
        if not raw:
            continue
        try:
            net = str(ipaddress.ip_network(raw, strict=False))
        except ValueError as exc:
            raise ValueError(f'Rede/NAT: rede local inválida: {raw}') from exc
        if net not in out:
            out.append(net)
    return out


def ensure_network_state(data):
    if not isinstance(data, dict):
        data = {}
    changed = False
    current = data.get('network')
    if not isinstance(current, dict):
        current = {}
        changed = True
    net = dict(DEFAULT_NETWORK)
    net.update(current)

    net['auto_external'] = bool(net.get('auto_external', True))
    net['external_address'] = _normalise_external(net.get('external_address'))
    if net['auto_external']:
        detected = _nat_status_external()
        if not detected and not net['external_address']:
            detected = detect_public_address()
        if detected and detected != net['external_address']:
            net['external_address'] = detected
            changed = True

    net['auto_local_nets'] = bool(net.get('auto_local_nets', True))
    net['local_nets'] = _normalise_nets(net.get('local_nets'))
    if net['auto_local_nets'] and not net['local_nets']:
        detected = detect_local_networks()
        if detected:
            net['local_nets'] = detected
            changed = True
    net['rtp_keepalive'] = _clamp_int(net.get('rtp_keepalive'), 15, 0, 120)
    net['rtp_timeout'] = _clamp_int(net.get('rtp_timeout'), 30, 0, 600)
    net['rtp_timeout_hold'] = _clamp_int(net.get('rtp_timeout_hold'), 300, 0, 1800)
    net['session_timers'] = bool(net.get('session_timers', True))

    if current != net:
        changed = True
    data['network'] = net
    return data, changed


def render_transport_nat(conf, data):
    """Patch the persisted UDP transport with managed NAT address settings."""
    conf = Path(conf)
    p = conf / 'pjsip.conf'
    if not p.exists():
        return False
    data, _ = ensure_network_state(data)
    net = data['network']
    lines = p.read_text(errors='ignore').splitlines()
    out = []
    in_transport = False
    inserted = False

    managed_keys = (
        'external_media_address=', 'external_signaling_address=',
        'external_signaling_port=', 'local_net=', 'symmetric_transport='
    )

    def managed_lines():
        result = ['; NAT MANAGED BY ASTERISK HA GUI', 'symmetric_transport=yes']
        ext = net.get('external_address', '')
        if ext:
            result += [f'external_media_address={ext}', f'external_signaling_address={ext}']
        for local in net.get('local_nets', []):
            result.append(f'local_net={local}')
        return result

    for line in lines:
        stripped = line.strip()
        if re.match(r'^\[transport-udp\]\s*$', stripped, re.I):
            in_transport = True
            inserted = False
            out.append(line)
            continue

        # Includes end the transport body for our purposes. NAT options must be
        # emitted before #include pjsip_gui.conf, otherwise they may attach to
        # the last category parsed from the included file.
        if in_transport and stripped.lower().startswith('#include'):
            if not inserted:
                out.extend(managed_lines())
                inserted = True
            in_transport = False
            out.append(line)
            continue

        if in_transport and re.match(r'^\[[^]]+\]\s*$', stripped):
            if not inserted:
                out.extend(managed_lines())
                inserted = True
            in_transport = False

        if in_transport:
            low = stripped.lower()
            if low == '; nat managed by asterisk ha gui' or any(low.startswith(k) for k in managed_keys):
                continue
            out.append(line)
            if low.startswith('allow_reload=') and not inserted:
                out.extend(managed_lines())
                inserted = True
            continue
        out.append(line)

    if in_transport and not inserted:
        out.extend(managed_lines())
    new = '\n'.join(out).rstrip() + '\n'
    old = p.read_text(errors='ignore')
    if new != old:
        p.write_text(new)
        return True
    return False


def augment_index(index):
    if "'Rede / NAT'" not in index:
        index = index.replace("const tabs=['Dashboard',", "const tabs=['Dashboard','Rede / NAT',", 1)
    if "current==='Rede / NAT'" not in index:
        index = index.replace("if(current==='Dashboard') dashboard(a);", "if(current==='Dashboard') dashboard(a); if(current==='Rede / NAT') networkPage(a);", 1)
    if 'async function networkPage(' in index:
        return index

    js = r'''
async function networkPage(a){
  let n=pbx.network||{};
  let nets=Array.isArray(n.local_nets)?n.local_nets.join('\n'):String(n.local_nets||'');
  a.innerHTML=`<div class=card><h2>Rede / NAT / RTP</h2>
  <div class=note><b>Para extensões fora da LAN:</b> o Asterisk tem de anunciar o endereço público no SDP e o router tem de encaminhar SIP e a gama RTP para este Home Assistant. O timeout RTP também termina chamadas remotas que desapareçam sem enviar BYE.</div>
  <div class=row>
    <div><label>IP público automático</label><select id=netextauto><option value=1 ${n.auto_external!==false?'selected':''}>Sim</option><option value=0 ${n.auto_external===false?'selected':''}>Não</option></select></div>
    <div><label>Endereço público / DDNS</label><input id=netext value="${esc(n.external_address||'')}" placeholder="pbx.exemplo.pt ou IP público"></div>
    <div><label>Detetar redes locais automaticamente</label><select id=netauto><option value=1 ${n.auto_local_nets!==false?'selected':''}>Sim</option><option value=0 ${n.auto_local_nets===false?'selected':''}>Não</option></select></div>
    <div><label>RTP keepalive (s)</label><input id=netkeep type=number min=0 max=120 value="${esc(n.rtp_keepalive??15)}"></div>
    <div><label>RTP timeout chamada (s)</label><input id=nettimeout type=number min=0 max=600 value="${esc(n.rtp_timeout??30)}"></div>
    <div><label>RTP timeout em hold (s)</label><input id=nethold type=number min=0 max=1800 value="${esc(n.rtp_timeout_hold??300)}"></div>
    <div><label>Session timers SIP</label><select id=nettimers><option value=1 ${n.session_timers!==false?'selected':''}>Ativos</option><option value=0 ${n.session_timers===false?'selected':''}>Desativos</option></select></div>
  </div>
  <div><label>Redes locais (uma por linha)</label><textarea id=netlocals style="min-height:110px">${esc(nets)}</textarea></div>
  <div class=note>Router/NAT: encaminha <b>UDP 5060</b> e a gama <b>UDP RTP configurada no add-on</b> (por defeito 10000–20000) para o IP do Home Assistant. Depois de alterar endereço público/rede local, reiniciar o add-on é recomendado.</div>
  <div class=actions><button class="btn primary" onclick=saveNetwork()>Guardar e aplicar</button><button class=btn onclick=detectNetwork()>Detetar IP público/LAN</button></div><pre id=netout></pre></div>`;
}
async function detectNetwork(){
  let r=await api('api/network-detect');
  if(r.external_address)E('#netext').value=r.external_address;
  if((r.local_nets||[]).length)E('#netlocals').value=r.local_nets.join('\n');
  E('#netout').textContent=JSON.stringify(r,null,2);
}
async function saveNetwork(){
  pbx.network={
    ...(pbx.network||{}),
    auto_external:E('#netextauto').value==='1',
    external_address:E('#netext').value.trim(),
    auto_local_nets:E('#netauto').value==='1',
    local_nets:E('#netlocals').value.split(/[,;\n ]+/).filter(Boolean),
    rtp_keepalive:+E('#netkeep').value,
    rtp_timeout:+E('#nettimeout').value,
    rtp_timeout_hold:+E('#nethold').value,
    session_timers:E('#nettimers').value==='1'
  };
  await savePbx();
}
'''
    marker = 'nav();render()'
    pos = index.rfind(marker)
    if pos >= 0:
        index = index[:pos] + js + '\n' + index[pos:]
    return index
