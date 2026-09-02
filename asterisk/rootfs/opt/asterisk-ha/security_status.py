#!/usr/bin/env python3
import re
import shutil
import subprocess


def _run(args, timeout=4):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout or ''
    except Exception as exc:
        return False, str(exc)


def _number(pattern, text, default=0):
    m = re.search(pattern, text or '', re.I | re.M)
    return int(m.group(1)) if m else default


def fail2ban_status():
    if not shutil.which('fail2ban-client'):
        return {'installed': False, 'running': False, 'jails': [], 'currently_banned': 0, 'total_banned': 0, 'banned_ips': []}

    ok, text = _run(['fail2ban-client', 'status'])
    if not ok:
        return {'installed': True, 'running': False, 'error': text.strip(), 'jails': [], 'currently_banned': 0, 'total_banned': 0, 'banned_ips': []}

    m = re.search(r'Jail list:\s*(.*)$', text, re.I | re.M)
    jails = [x.strip() for x in (m.group(1).split(',') if m else []) if x.strip()]
    current = 0
    total = 0
    banned_ips = []
    details = {}
    for jail in jails:
        good, out = _run(['fail2ban-client', 'status', jail])
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
        'jails': jails,
        'currently_banned': current,
        'total_banned': total,
        'banned_ips': sorted(set(banned_ips)),
        'details': details,
    }
