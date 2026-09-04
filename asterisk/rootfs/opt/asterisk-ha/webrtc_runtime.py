#!/usr/bin/env python3
from pathlib import Path


PJSIP_START = '; WEBRTC TRANSPORTS MANAGED BY ASTERISK HA'
PJSIP_END = '; END WEBRTC TRANSPORTS MANAGED BY ASTERISK HA'


def _strip_managed_block(text):
    start = text.find(PJSIP_START)
    if start < 0:
        return text
    end = text.find(PJSIP_END, start)
    if end < 0:
        return text[:start].rstrip() + '\n'
    end += len(PJSIP_END)
    return (text[:start] + text[end:]).strip() + '\n'


def patch_pjsip_websocket(path):
    path = Path(path)
    if not path.exists():
        return
    text = _strip_managed_block(path.read_text(errors='ignore')).rstrip()
    block = f'''\n\n{PJSIP_START}
[transport-ws]
type=transport
protocol=ws
bind=0.0.0.0
allow_reload=yes

[transport-wss]
type=transport
protocol=wss
bind=0.0.0.0
allow_reload=yes
{PJSIP_END}\n'''
    path.write_text(text + block)


def patch_http_websocket(path, options):
    path = Path(path)
    if not path.exists():
        return {'ws_port': int(options.get('ari_port', 8088) or 8088), 'wss': False, 'wss_port': int(options.get('webrtc_wss_port', 8089) or 8089)}

    ws_port = int(options.get('ari_port', 8088) or 8088)
    wss_port = int(options.get('webrtc_wss_port', 8089) or 8089)
    cert = Path('/ssl/fullchain.pem')
    key = Path('/ssl/privkey.pem')
    tls_ok = cert.exists() and key.exists()

    managed_keys = {
        'bindaddr', 'bindport', 'websocket_enabled',
        'tlsenable', 'tlsbindaddr', 'tlscertfile', 'tlsprivatekey'
    }
    out = []
    in_general = False
    inserted = False

    def add_lines():
        nonlocal inserted
        if inserted:
            return
        out.extend([
            'enabled=yes',
            'bindaddr=0.0.0.0',
            f'bindport={ws_port}',
            'websocket_enabled=yes',
            f'tlsenable={"yes" if tls_ok else "no"}',
        ])
        if tls_ok:
            out.extend([
                f'tlsbindaddr=0.0.0.0:{wss_port}',
                f'tlscertfile={cert}',
                f'tlsprivatekey={key}',
            ])
        inserted = True

    for line in path.read_text(errors='ignore').splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_general:
                add_lines()
            in_general = stripped.lower() == '[general]'
            out.append(line)
            continue
        if in_general and '=' in stripped:
            key_name = stripped.split('=', 1)[0].strip().lower()
            if key_name == 'enabled' or key_name in managed_keys:
                continue
        out.append(line)
    if in_general:
        add_lines()
    if not any(line.strip().lower() == '[general]' for line in out):
        out = ['[general]'] + out
        inserted = False
        add_lines()
    path.write_text('\n'.join(out).rstrip() + '\n')
    return {'ws_port': ws_port, 'wss': tls_ok, 'wss_port': wss_port}


def apply_webrtc_runtime(conf_dir, options):
    conf_dir = Path(conf_dir)
    patch_pjsip_websocket(conf_dir / 'pjsip.conf')
    return patch_http_websocket(conf_dir / 'http.conf', options or {})
