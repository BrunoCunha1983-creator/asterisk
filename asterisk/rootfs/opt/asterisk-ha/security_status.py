#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import subprocess

SOCKET = '/run/fail2ban/fail2ban.sock'
DATA_DIR = Path('/data/fail2ban')


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


def fail2ban_status():
    if not shutil.which('fail2ban-client'):
        return {'installed': False, 'running': False, 'jails': [], 'currently_banned': 0, 'total_banned': 0, 'banned_ips': []}

    ok, text = _run(['fail2ban-client', '-s', SOCKET, 'status'])
    if not ok:
        diagnostics = '\n'.join(x for x in (
            _tail(DATA_DIR / 'server.log'),
            _tail(DATA_DIR / 'config-test.log'),
            _tail(DATA_DIR / 'setup-error.log'),
        ) if x).strip()
        return {
            'installed': True,
            'running': False,
            'socket': SOCKET,
            'error': text.strip(),
            'startup_diagnostics': diagnostics[-8000:],
            'jails': [],
            'currently_banned': 0,
            'total_banned': 0,
            'banned_ips': [],
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
            details[jail] = {'running': False, 'error': out.strip()}
            continue
        cur = _number(r'Currently banned:\s*(\d+)', out)
        tot = _number(r'Total banned:\s*(\d+)', out)
        ipm = re.search(r'Banned IP list:\s*(.*)$', out, re.I | re.M)
        ips = [x for x in (ipm.group(1).split() if ipm else []) if x]
        current += cur
        total += tot
        banned_ips.extend(ips)
        details[jail] = {'running': True, 'currently_banned': cur, 'total_banned': tot, 'banned_ips': ips}

    return {
        'installed': True,
        'running': True,
        'socket': SOCKET,
        'jails': jails,
        'currently_banned': current,
        'total_banned': total,
        'banned_ips': sorted(set(banned_ips)),
        'details': details,
    }
