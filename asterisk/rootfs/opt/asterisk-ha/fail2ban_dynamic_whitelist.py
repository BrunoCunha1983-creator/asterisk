#!/usr/bin/env python3
import ipaddress
import json
import re
import subprocess
import time
from pathlib import Path

PBX = Path('/config/state/pbx.json')
STATE = Path('/data/fail2ban/dynamic-ignoreips.json')
F2B_SOCKET = '/run/fail2ban/fail2ban.sock'
ASTERISK_CONF = '/config/asterisk/asterisk.conf'
JAIL = 'asterisk-pjsip'
POLL_SECONDS = 60


def run(args, timeout=8):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout or ''
    except Exception as exc:
        return False, str(exc)


def load_json(path, default):
    try:
        value = json.loads(Path(path).read_text())
        return value
    except Exception:
        return default


def save_state(ips):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({'ips': sorted(ips)}, indent=2))


def public_ip(value):
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except Exception:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return None
    return str(ip)


def configured_extensions():
    data = load_json(PBX, {})
    out = set()
    for item in (data.get('extensions') or []):
        if not isinstance(item, dict):
            continue
        ext = str(item.get('extension') or '').strip()
        if ext:
            out.add(ext)
    return out


def contact_ip(uri):
    uri = str(uri or '').strip()
    # Handles sip:user@1.2.3.4:5060, sip:1.2.3.4:5060 and bracketed IPv6.
    m = re.search(r'@\[([^]]+)\]|@([^;:>\s]+)|sip:\[([^]]+)\]|sip:([^;:@>\s]+)', uri, re.I)
    if not m:
        return None
    host = next((g for g in m.groups() if g), '')
    return public_ip(host)


def active_remote_extension_ips():
    extensions = configured_extensions()
    if not extensions:
        return set()
    ok, text = run(['asterisk', '-C', ASTERISK_CONF, '-rx', 'pjsip show contacts'])
    if not ok:
        return set()
    result = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith('Contact:'):
            continue
        body = line.split(':', 1)[1].strip()
        parts = body.split()
        if not parts or '/' not in parts[0]:
            continue
        key, uri = parts[0].split('/', 1)
        if key not in extensions:
            continue
        ip = contact_ip(uri)
        if ip:
            result.add(ip)
    return result


def f2b(*args):
    return run(['fail2ban-client', '-s', F2B_SOCKET, *args])


def sync_once(previous):
    current = active_remote_extension_ips()

    for ip in sorted(current - previous):
        # A newly learned legitimate endpoint may still carry an old ban from a
        # previous public address/authentication incident. Unban before ignoring.
        f2b('set', JAIL, 'unbanip', ip)
        ok, out = f2b('set', JAIL, 'addignoreip', ip)
        if ok:
            print(f'[SECURITY] Fail2ban auto-whitelist: added remote extension IP {ip}', flush=True)
        else:
            print(f'[SECURITY] Fail2ban auto-whitelist: failed to add {ip}: {out.strip()}', flush=True)

    for ip in sorted(previous - current):
        ok, out = f2b('set', JAIL, 'delignoreip', ip)
        if ok:
            print(f'[SECURITY] Fail2ban auto-whitelist: removed stale remote extension IP {ip}', flush=True)
        else:
            # If Fail2ban restarted, its runtime ignore list may no longer contain
            # the previous address. That is harmless; still drop it from our state.
            print(f'[SECURITY] Fail2ban auto-whitelist: stale IP {ip} no longer active', flush=True)

    save_state(current)
    return current


def main():
    previous = set(load_json(STATE, {}).get('ips') or [])
    print('[SECURITY] Fail2ban dynamic remote-IP whitelist watcher started', flush=True)
    while True:
        ok, _ = f2b('ping')
        if ok:
            previous = sync_once(previous)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
