#!/usr/bin/env python3
import ipaddress
import json
import socket
import urllib.request
from pathlib import Path

STATE = Path('/config/state')
STATUS = STATE / 'nat.json'


def _valid_ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except Exception:
        return ''


def _valid_network(value):
    raw = str(value or '').strip()
    if not raw or raw.lower() == 'auto':
        return ''
    try:
        return str(ipaddress.ip_network(raw, strict=False))
    except Exception:
        return ''


def detect_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 53))
        return _valid_ip(s.getsockname()[0])
    except Exception:
        return ''
    finally:
        s.close()


def detect_public_ip(timeout=4):
    services = (
        'https://api.ipify.org',
        'https://checkip.amazonaws.com',
    )
    for url in services:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Asterisk-HA/0.2.6'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                value = _valid_ip(r.read(128).decode(errors='ignore').strip())
                if value:
                    return value, url
        except Exception:
            continue
    return '', ''


def auto_local_net(local_ip):
    try:
        ip = ipaddress.ip_address(local_ip)
        if ip.version == 4:
            return str(ipaddress.ip_network(f'{ip}/24', strict=False))
    except Exception:
        pass
    return ''


def resolve_nat(options):
    options = options or {}
    local_ip = detect_local_ip()
    local_net = _valid_network(options.get('local_net')) or auto_local_net(local_ip)
    raw_external = str(options.get('external_address', '') or '').strip()
    manual = '' if raw_external.lower() == 'auto' else _valid_ip(raw_external)
    external = manual
    source = 'manual' if manual else ''
    detect_url = ''
    if not external and bool(options.get('nat_auto', True)):
        external, detect_url = detect_public_ip()
        if external:
            source = 'auto'
    return {
        'nat_auto': bool(options.get('nat_auto', True)),
        'local_ip': local_ip,
        'local_net': local_net,
        'external_address': external,
        'external_source': source or 'none',
        'detect_url': detect_url,
        'sip_port': int(options.get('sip_port', 5060) or 5060),
        'rtp_start': int(options.get('rtp_start', 10000) or 10000),
        'rtp_end': int(options.get('rtp_end', 20000) or 20000),
    }


def patch_transport(path, nat):
    path = Path(path)
    text = path.read_text(errors='ignore')
    lines = text.splitlines()
    managed = {
        'external_media_address', 'external_signaling_address',
        'external_signaling_port', 'local_net', 'symmetric_transport'
    }
    out = []
    in_transport = False
    inserted = False

    def add_nat_lines():
        nonlocal inserted
        if inserted:
            return
        external = nat.get('external_address') or ''
        local_net = nat.get('local_net') or ''
        out.append('symmetric_transport=yes')
        if local_net:
            out.append(f'local_net={local_net}')
        if external:
            out.append(f'external_media_address={external}')
            out.append(f'external_signaling_address={external}')
            out.append(f'external_signaling_port={int(nat.get("sip_port", 5060) or 5060)}')
        inserted = True

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_transport:
                add_nat_lines()
            in_transport = stripped.lower() == '[transport-udp]'
            out.append(line)
            continue

        if in_transport and stripped.lower().startswith('#include'):
            add_nat_lines()
            in_transport = False
            out.append(line)
            continue

        if in_transport and '=' in stripped:
            key = stripped.split('=', 1)[0].strip().lower()
            if key in managed:
                continue
        out.append(line)
    if in_transport:
        add_nat_lines()
    path.write_text('\n'.join(out).rstrip() + '\n')


def patch_rtp(path):
    path = Path(path)
    if not path.exists():
        return
    lines = []
    for line in path.read_text(errors='ignore').splitlines():
        stripped = line.strip().lower()
        if stripped == 'stunaddr=':
            continue
        lines.append(line)
    path.write_text('\n'.join(lines).rstrip() + '\n')


def apply_nat(conf_dir, options):
    conf_dir = Path(conf_dir)
    nat = resolve_nat(options)
    patch_transport(conf_dir / 'pjsip.conf', nat)
    patch_rtp(conf_dir / 'rtp.conf')
    STATE.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(nat, indent=2, ensure_ascii=False))
    return nat
