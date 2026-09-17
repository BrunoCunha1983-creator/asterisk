#!/usr/bin/env python3
"""Keep SIPcord PJSIP auth references internally consistent.

Asterisk does not keep a usable auth object when the configured password is
empty. Older rendering always wrote outbound_auth=sipcord_auth, which leaves the
endpoint pointing at a missing auth object and makes every outbound Dial fail
before it can reach the bridge. With a password, normal SIP digest auth is kept.
Without one, render a valid unauthenticated static trunk and let the remote bridge
accept or reject it normally.
"""
from pathlib import Path
import re


def _strip_section(text, section):
    lines = text.splitlines()
    out = []
    skipping = False
    target = str(section or '').strip().lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            name = stripped[1:-1].strip().lower()
            skipping = name == target
            if skipping:
                continue
        if not skipping:
            out.append(line)
    return '\n'.join(out).rstrip() + '\n'


def _repair_rendered_sipcord(conf, data):
    sc = (data or {}).get('sipcord') or {}
    if not sc.get('enabled'):
        return {'enabled': False, 'auth': False, 'changed': False}

    password = str(sc.get('password') or '')
    path = Path(conf) / 'pjsip_gui.conf'
    if not path.exists():
        return {'enabled': True, 'auth': bool(password), 'changed': False, 'error': 'pjsip_gui.conf missing'}

    text = path.read_text(errors='ignore')
    original = text
    if not password:
        text = re.sub(
            r'(?mi)^\s*outbound_auth\s*=\s*sipcord_auth\s*\n?',
            '',
            text,
        )
        text = _strip_section(text, 'sipcord_auth')

    changed = text != original
    if changed:
        path.write_text(text)
    return {'enabled': True, 'auth': bool(password), 'changed': changed}


def install(server_module):
    if getattr(server_module, '_sipcord_auth_runtime_installed', False):
        return

    original = server_module.render_sipcord

    def render_sipcord_safe(conf, data):
        result = original(conf, data)
        try:
            info = _repair_rendered_sipcord(conf, data)
            if info.get('enabled'):
                mode = 'digest-auth' if info.get('auth') else 'no-auth (password empty)'
                print(f'[SIPcord] outbound auth mode: {mode}')
        except Exception as exc:
            print(f'[SIPcord] WARNING auth consistency repair failed: {exc}')
        return result

    server_module.render_sipcord = render_sipcord_safe
    server_module._sipcord_auth_runtime_installed = True
