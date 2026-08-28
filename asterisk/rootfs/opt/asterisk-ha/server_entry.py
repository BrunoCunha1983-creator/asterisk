#!/usr/bin/env python3
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import backend
import server
from ht503 import augment_index as augment_ht503_index, ensure_ht503_state, validate_ht503_state
from dashboard_status import augment_index as augment_dashboard_index
from network import (
    DEFAULT_NETWORK,
    augment_index as augment_network_index,
    detect_local_networks,
    detect_public_address,
    ensure_network_state,
    render_transport_nat,
)


# Apply feature UI layers over the base SIPcord + IVR page.
server.INDEX = augment_network_index(augment_dashboard_index(augment_ht503_index(server.INDEX)))

_base_normalize_pbx = server.normalize_pbx
_base_ast = server.ast
_base_render_managed = server.render_managed
_base_endpoint_lines = backend.endpoint_lines
_current_network = dict(DEFAULT_NETWORK)


def normalize_pbx(data):
    """Extend PBX normalization with HT503 and network/NAT state."""
    data, changed, removed = _base_normalize_pbx(data)
    data, ht_changed = ensure_ht503_state(data)
    validate_ht503_state(data)
    data, net_changed = ensure_network_state(data)
    return data, bool(changed or ht_changed or net_changed), removed


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


def ast_compat(command):
    """Translate the legacy GUI PJSIP reload action to Asterisk 22 syntax."""
    if str(command).strip() != 'pjsip reload':
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
    """Add NAT-safe RTP liveness/session settings to managed PJSIP endpoints."""
    lines = list(_base_endpoint_lines(*args, **kwargs))
    num = str(args[0] if args else kwargs.get('num', '') or '')
    media = _current_network or DEFAULT_NETWORK
    keepalive = int(media.get('rtp_keepalive', 10) or 0)
    timeout = int(media.get('rtp_timeout', 30) or 0)
    timeout_hold = int(media.get('rtp_timeout_hold', 120) or 0)
    timers = bool(media.get('session_timers', True))
    additions = [
        f'rtp_keepalive={keepalive}',
        f'rtp_timeout={timeout}',
        f'rtp_timeout_hold={timeout_hold}',
        f'timers={"yes" if timers else "no"}',
    ]
    if timers:
        additions += ['timers_min_se=90', 'timers_sess_expires=180']

    # Insert before the auth object (the second [endpoint] category).
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
    """Render endpoint media policy and transport NAT addresses together."""
    global _current_network
    data, _ = ensure_network_state(data)
    _current_network = dict(data.get('network') or DEFAULT_NETWORK)
    render_transport_nat(server.CONF, data)
    return _base_render_managed(data)


# backend.render_managed resolves endpoint_lines in backend's module globals.
backend.endpoint_lines = endpoint_lines_compat
server.normalize_pbx = normalize_pbx
server.ast = ast_compat
server.render_managed = render_managed_compat


class H(server.H):
    """Add network discovery to the existing Ingress API."""
    def do_GET(self):
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path == '/api/network-detect':
            self.sendj({
                'external_address': detect_public_address(),
                'local_nets': detect_local_networks(),
            })
            return
        super().do_GET()


if __name__ == '__main__':
    startup = server.load_pbx_state()
    server.render_managed(startup)
    server.render_sipcord(server.CONF, startup)
    server.render_ivrs(server.CONF, startup)
    ThreadingHTTPServer(('0.0.0.0', 8099), H).serve_forever()
