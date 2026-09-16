#!/usr/bin/env python3
from pathlib import Path
import json
import re
import shutil
import subprocess

SOCKET = '/run/fail2ban/fail2ban.sock'
DATA_DIR = Path('/data/fail2ban')
DYNAMIC_STATUS = DATA_DIR / 'dynamic-whitelist-status.json'


def _run(args, timeout=4):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout or ''
    except Exception as exc:
        return False, str(exc)


def _number(pattern, text, default=0):
    m = re.search(pattern, text or '', re.I | re.M)
    return int(m.group(1)) if m else default


def _tail(path, limit=5000):
    try:
        text = Path(path).read_text(errors='ignore')
        return text[-limit:]
    except Exception:
        return ''


def _json(path, default):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else default
    except Exception:
        return default


def _ignoreip(jail):
    ok, text = _run(['fail2ban-client', '-s', SOCKET, 'get', jail, 'ignoreip'])
    if not ok:
        return {'ok': False, 'raw': text.strip(), 'entries': []}
    # Keep Fail2ban's exact textual entries for the UI; unlike the watcher this
    # also includes private networks and CIDRs from the static configuration.
    entries = []
    for token in re.findall(r'(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?|(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?:/\d{1,3})?', text):
        if token not in entries:
            entries.append(token)
    return {'ok': True, 'raw': text.strip(), 'entries': entries}


def fail2ban_status():
    dynamic = _json(DYNAMIC_STATUS, {})
    if not shutil.which('fail2ban-client'):
        return {'installed': False, 'running': False, 'jails': [], 'currently_banned': 0, 'total_banned': 0, 'banned_ips': [], 'dynamic_whitelist': dynamic}

    ok, text = _run(['fail2ban-client', '-s', SOCKET, 'status'])
    if not ok:
        diagnostics = '\n'.join(x for x in (
            _tail(DATA_DIR / 'server.log'),
            _tail(DATA_DIR / 'config-test.log'),
            _tail(DATA_DIR / 'setup-error.log'),
            _tail(DATA_DIR / 'dynamic-whitelist.log'),
        ) if x).strip()
        return {
            'installed': True,
            'running': False,
            'socket': SOCKET,
            'error': text.strip(),
            'startup_diagnostics': diagnostics[-12000:],
            'jails': [],
            'currently_banned': 0,
            'total_banned': 0,
            'banned_ips': [],
            'dynamic_whitelist': dynamic,
        }

    m = re.search(r'Jail list:\s*(.*)$', text, re.I | re.M)
    jails = [x.strip() for x in (m.group(1).split(',') if m else []) if x.strip()]
    current = 0
    total = 0
    banned_ips = []
    details = {}
    for jail in jails:
        good, out = _run(['fail2ban-client', '-s', SOCKET, 'status', jail])
        if not good:
            details[jail] = {'running': False, 'error': out.strip(), 'ignoreip': []}
            continue
        cur = _number(r'Currently banned:\s*(\d+)', out)
        tot = _number(r'Total banned:\s*(\d+)', out)
        ipm = re.search(r'Banned IP list:\s*(.*)$', out, re.I | re.M)
        ips = [x for x in (ipm.group(1).split() if ipm else []) if x]
        ignore = _ignoreip(jail)
        current += cur
        total += tot
        banned_ips.extend(ips)
        details[jail] = {
            'running': True,
            'currently_banned': cur,
            'total_banned': tot,
            'banned_ips': ips,
            'ignoreip': ignore.get('entries') or [],
            'ignoreip_raw': ignore.get('raw') or '',
            'ignoreip_ok': bool(ignore.get('ok')),
        }

    return {
        'installed': True,
        'running': True,
        'socket': SOCKET,
        'jails': jails,
        'currently_banned': current,
        'total_banned': total,
        'banned_ips': sorted(set(banned_ips)),
        'details': details,
        'dynamic_whitelist': dynamic,
        'dynamic_whitelist_log': _tail(DATA_DIR / 'dynamic-whitelist.log', 12000),
    }
