#!/usr/bin/env python3
from http.server import ThreadingHTTPServer

import server
from ht503 import augment_index as augment_ht503_index, ensure_ht503_state, validate_ht503_state


# Apply the HT503 UI after the base server has already applied SIPcord + IVR.
server.INDEX = augment_ht503_index(server.INDEX)

_base_normalize_pbx = server.normalize_pbx
_base_ast = server.ast


def normalize_pbx(data):
    """Extend the existing PBX normalizer with HT503 FXS metadata/validation."""
    data, changed, removed = _base_normalize_pbx(data)
    data, ht_changed = ensure_ht503_state(data)
    validate_ht503_state(data)
    return data, bool(changed or ht_changed), removed


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
    """Translate the legacy GUI PJSIP reload action to Asterisk 22 syntax.

    This Asterisk 22 image does not expose the old `pjsip reload` CLI command.
    Reload res_pjsip directly and use a core reload only as a safety fallback.
    All existing callers can keep using the logical `pjsip reload` action.
    """
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


# Functions in server.py resolve globals dynamically, so replacing these module
# attributes also updates requests handled by server.H, including Dashboard,
# managed saves and config-file editor reloads.
server.normalize_pbx = normalize_pbx
server.ast = ast_compat


if __name__ == '__main__':
    startup = server.load_pbx_state()
    server.render_managed(startup)
    server.render_sipcord(server.CONF, startup)
    server.render_ivrs(server.CONF, startup)
    ThreadingHTTPServer(('0.0.0.0', 8099), server.H).serve_forever()
