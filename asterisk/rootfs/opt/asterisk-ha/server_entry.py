#!/usr/bin/env python3
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import backend
import server
from ht503 import augment_index as augment_ht503_index, ensure_ht503_state, validate_ht503_state
from dashboard_status import augment_index as augment_dashboard_index
from gsm_ui import augment_index as augment_gsm_index
from security_ui import augment_index as augment_security_index
from gsm_runtime import normalize_gsm_state
from webrtc import augment_index as augment_webrtc_index, ensure_webrtc_state
from sim800c_runtime import SIM800C, normalize_sim800c_state
from sim800c_ui import augment_index as augment_sim800c_index
from network import (
    DEFAULT_NETWORK,
    augment_index as augment_network_index,
    detect_local_networks,
    detect_public_address,
    ensure_network_state,
    render_transport_nat,
)


# Apply feature UI layers over the base SIPcord + IVR page.
server.INDEX = augment_sim800c_index(
    augment_security_index(
        augment_gsm_index(
            augment_network_index(
                augment_dashboard_index(
                    augment_webrtc_index(
                        augment_ht503_index(server.INDEX)
                    )
                )
            )
        )
    )
)

_base_normalize_pbx = server.normalize_pbx
_base_ast = server.ast
_base_render_managed = server.render_managed
_base_endpoint_lines = backend.endpoint_lines
_current_network = dict(DEFAULT_NETWORK)
_webrtc_extensions = set()


def normalize_pbx(data):
    """Extend PBX normalization with HT503, WebRTC, SIM800C, network/NAT and GSM state."""
    data, changed, removed = _base_normalize_pbx(data)
    data, ht_changed = ensure_ht503_state(data)
    validate_ht503_state(data)
    data, webrtc_changed = ensure_webrtc_state(data)
    data, sim800_changed = normalize_sim800c_state(data)
    data, net_changed = ensure_network_state(data)
    data, gsm_changed = normalize_gsm_state(data)
    return data, bool(changed or ht_changed or webrtc_changed or sim800_changed or net_changed or gsm_changed), removed


def _reload_failed(result):
    """Detect CLI failures that can still be returned with process exit code 0."""
    output = str((result or {}).get('output', '') or '').lower()
    markers = (
        'no such command',
        'no such module',
        'not found',
        'does not support reload',
        'unable to reload',
        'failed to reload',
    )
    return not bool((result or {}).get('ok')) or any(marker in output for marker in markers)


def _dongle_cli_invalid(result):
    output = str((result or {}).get('output', '') or '').lower()
    markers = (
        'no such command',
        'no such module',
        'command not found',
        'unable to find command',
        'chan_dongle is not loaded',
    )
    return not bool((result or {}).get('ok')) or any(marker in output for marker in markers)


def ast_compat(command):
    """Provide Asterisk 22 CLI compatibility and safe GSM runtime reporting."""
    command = str(command).strip()

    if command == 'dongle show devices':
        result = _base_ast(command)
        try:
            serial_ports = backend.usb_ports()
        except Exception:
            serial_ports = []
        if not serial_ports or _dongle_cli_invalid(result):
            return {'ok': True, 'code': 0, 'output': 'No devices found'}
        return result

    if command != 'pjsip reload':
        return _base_ast(command)

    primary_command = 'module reload res_pjsip.so'
    primary = _base_ast(primary_command)
    if not _reload_failed(primary):
        return {
            'ok': True,
            'code': primary.get('code', 0),
            'output': f'$ {primary_command}\n{primary.get("output", "")}'.rstrip(),
        }

    fallback_command = 'core reload'
    fallback = _base_ast(fallback_command)
    return {
        'ok': bool(fallback.get('ok')),
        'code': fallback.get('code', primary.get('code', -1)),
        'output': (
            f'$ {primary_command}\n{primary.get("output", "")}\n'
            f'Fallback: $ {fallback_command}\n{fallback.get("output", "")}'
        ).rstrip(),
    }


def endpoint_lines_compat(*args, **kwargs):
    """Apply RTP/session policy and WebRTC media settings exactly once."""
    lines = list(_base_endpoint_lines(*args, **kwargs))
    num = str(args[0] if args else kwargs.get('num', '') or '')
    media = _current_network or DEFAULT_NETWORK
    is_webrtc = num in _webrtc_extensions

    managed_prefixes = (
        'rtp_keepalive=', 'rtp_timeout=', 'rtp_timeout_hold=',
        'timers=', 'timers_min_se=', 'timers_sess_expires=',
        'webrtc=', 'dtls_auto_generate_cert=', 'ice_support=',
        'media_use_received_transport='
    )
    filtered = []
    for line in lines:
        stripped = str(line).strip().lower()
        if any(stripped.startswith(prefix) for prefix in managed_prefixes):
            continue
        if is_webrtc and stripped == 'transport=transport-udp':
            continue
        filtered.append(line)
    lines = filtered

    keepalive = int(media.get('rtp_keepalive', 15) or 0)
    timeout = int(media.get('rtp_timeout', 30) or 0)
    timeout_hold = int(media.get('rtp_timeout_hold', 300) or 0)
    timers = bool(media.get('session_timers', True))
    additions = [
        f'rtp_keepalive={keepalive}',
        f'rtp_timeout={timeout}',
        f'rtp_timeout_hold={timeout_hold}',
        f'timers={"yes" if timers else "no"}',
    ]
    if timers:
        additions += ['timers_min_se=90', 'timers_sess_expires=180']
    if is_webrtc:
        additions += [
            'webrtc=yes',
            'dtls_auto_generate_cert=yes',
            'ice_support=yes',
            'media_use_received_transport=yes',
        ]

    marker = f'\n[{num}]'
    insert_at = None
    for idx, line in enumerate(lines[1:], start=1):
        if line == marker:
            insert_at = idx
            break
    if insert_at is None:
        insert_at = len(lines)
    return lines[:insert_at] + additions + lines[insert_at:]


def render_managed_compat(data):
    """Render endpoint media policy, WebRTC, SIM800C and transport NAT state together."""
    global _current_network, _webrtc_extensions
    data, _ = ensure_network_state(data)
    data, _ = ensure_webrtc_state(data)
    data, _ = normalize_sim800c_state(data)
    _current_network = dict(data.get('network') or DEFAULT_NETWORK)
    _webrtc_extensions = {
        str(e.get('extension') or '').strip()
        for e in (data.get('extensions') or [])
        if isinstance(e, dict) and e.get('webrtc') and str(e.get('extension') or '').strip()
    }
    SIM800C.configure(data.get('sim800c') or {})
    render_transport_nat(server.CONF, data)
    return _base_render_managed(data)


backend.endpoint_lines = endpoint_lines_compat
server.normalize_pbx = normalize_pbx
server.ast = ast_compat
server.render_managed = render_managed_compat


class H(server.H):
    """Add network discovery and SIM800C control to the existing Ingress API."""
    def do_GET(self):
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path == '/api/network-detect':
            if not self._guard_web():
                return
            self.sendj({
                'external_address': detect_public_address(),
                'local_nets': detect_local_networks(),
            })
            return
        if path == '/api/sim800c-status':
            if not self._guard_web():
                return
            try:
                pbx = server.load_pbx_state()
                SIM800C.configure((pbx.get('sim800c') or {}))
                self.sendj(SIM800C.status())
            except Exception as e:
                self.sendj({'connected': False, 'error': str(e)}, 500)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path != '/api/sim800c-action':
            return super().do_POST()
        if not self._guard_web():
            return
        data = self.body()
        try:
            pbx = server.load_pbx_state()
            SIM800C.configure((pbx.get('sim800c') or {}))
            action = str(data.get('action') or '').strip().lower()
            if action == 'init':
                result = SIM800C.initialize()
            elif action == 'refresh':
                result = {'ok': True, 'status': SIM800C.refresh()}
            elif action == 'dial':
                result = SIM800C.dial(data.get('number', ''))
            elif action == 'answer':
                result = SIM800C.answer()
            elif action == 'hangup':
                result = SIM800C.hangup()
            elif action == 'sms':
                result = SIM800C.send_sms(data.get('number', ''), data.get('text', ''))
            else:
                result = {'ok': False, 'output': 'ação SIM800C desconhecida'}
            self.sendj(result, 200 if result.get('ok') else 400)
        except Exception as e:
            self.sendj({'ok': False, 'output': str(e)}, 500)


if __name__ == '__main__':
    startup = server.load_pbx_state()
    server.render_managed(startup)
    server.render_sipcord(server.CONF, startup)
    server.render_ivrs(server.CONF, startup)
    ThreadingHTTPServer(('0.0.0.0', 8099), H).serve_forever()
