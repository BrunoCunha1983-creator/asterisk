#!/usr/bin/env python3
import ipaddress
import json
import re
import subprocess
import time
from pathlib import Path

PBX = Path('/config/state/pbx.json')
STATE = Path('/data/fail2ban/dynamic-ignoreips.json')
STATUS = Path('/data/fail2ban/dynamic-whitelist-status.json')
ASTERISK_LOG = Path('/var/log/asterisk/full')
F2B_SOCKET = '/run/fail2ban/fail2ban.sock'
ASTERISK_CONF = '/config/asterisk/asterisk.conf'
JAIL = 'asterisk-pjsip'
POLL_SECONDS = 60
LOG_LOOKBACK_BYTES = 2 * 1024 * 1024


def run(args, timeout=8):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout or ''
    except Exception as exc:
        return False, str(exc)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json(path, value):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False))
    except Exception:
        pass


def public_ip(value):
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except Exception:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return None
    return str(ip)


def extract_public_ips(text):
    out = set()
    # IPv4 plus ordinary textual IPv6 candidates. Validation is delegated to
    # ipaddress so Fail2ban decorations/labels are harmless.
    candidates = re.findall(r'(?<![0-9A-Fa-f:.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![0-9A-Fa-f:.])', text or '')
    candidates += re.findall(r'(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?:/\d{1,3})?(?![0-9A-Fa-f:])', text or '')
    for candidate in candidates:
        host = candidate.split('/', 1)[0]
        ip = public_ip(host)
        if ip:
            out.add(ip)
    return out


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
    m = re.search(r'@\[([^]]+)\]|@([^;:>\s]+)|sip:\[([^]]+)\]|sip:([^;:@>\s]+)', uri, re.I)
    if not m:
        return None
    host = next((g for g in m.groups() if g), '')
    return public_ip(host)


def contact_remote_ips(extensions):
    ok, text = run(['asterisk', '-C', ASTERISK_CONF, '-rx', 'pjsip show contacts'])
    if not ok:
        return set(), {'ok': False, 'error': text.strip(), 'raw': ''}
    result = set()
    matched = []
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
        matched.append({'extension': key, 'uri': uri, 'public_ip': ip})
        if ip:
            result.add(ip)
    return result, {'ok': True, 'matched': matched, 'raw': text[-12000:]}


def successful_log_ips(extensions):
    if not extensions:
        return set(), []
    try:
        with ASTERISK_LOG.open('rb') as fh:
            try:
                fh.seek(-LOG_LOOKBACK_BYTES, 2)
            except OSError:
                fh.seek(0)
            text = fh.read().decode(errors='ignore')
    except Exception:
        return set(), []

    result = set()
    matches = []
    for raw in text.splitlines():
        low = raw.lower()
        # Only learn from success evidence, never from Failed to authenticate or
        # No matching endpoint messages. This keeps the auto-whitelist from
        # trusting a scanner merely because it guessed an extension number.
        if not any(token in low for token in ('successfulauth', 'added contact', 'created contact', 'registered')):
            continue
        ext = next((e for e in extensions if re.search(r'(?<!\d)' + re.escape(e) + r'(?!\d)', raw)), None)
        if not ext:
            continue
        ips = extract_public_ips(raw)
        for ip in ips:
            result.add(ip)
            matches.append({'extension': ext, 'ip': ip, 'line': raw[-1000:]})
    return result, matches[-50:]


def f2b(*args):
    return run(['fail2ban-client', '-s', F2B_SOCKET, *args])


def runtime_ignore_ips():
    ok, text = f2b('get', JAIL, 'ignoreip')
    return extract_public_ips(text) if ok else set(), text.strip()


def banned_ips():
    ok, text = f2b('status', JAIL)
    if not ok:
        return set()
    m = re.search(r'Banned IP list:\s*(.*)$', text, re.I | re.M)
    return extract_public_ips(m.group(1) if m else '')


def apply_ignore(ip):
    # Remove an existing ban first. addignoreip does not reliably make an
    # already-banned address usable on every Fail2ban/action combination.
    f2b('set', JAIL, 'unbanip', ip)
    ok, output = f2b('set', JAIL, 'addignoreip', ip)
    runtime, runtime_raw = runtime_ignore_ips()
    verified = ip in runtime
    return verified, output.strip(), runtime_raw


def sync_once(previous):
    extensions = configured_extensions()
    contact_ips, contact_diag = contact_remote_ips(extensions)
    log_ips, log_diag = successful_log_ips(extensions)
    current = contact_ips | log_ips
    runtime, runtime_raw = runtime_ignore_ips()
    before_banned = banned_ips()
    errors = []
    added = []

    # Persistently known, previously authenticated addresses are also reapplied
    # after a Fail2ban restart. This closes the race where the firewall comes up
    # before the endpoint has had a chance to refresh its registration.
    desired = current | previous
    for ip in sorted(desired - runtime):
        verified, output, verify_raw = apply_ignore(ip)
        if verified:
            added.append(ip)
            print(f'[SECURITY] Fail2ban auto-whitelist: verified remote extension IP {ip}', flush=True)
        else:
            errors.append({'ip': ip, 'output': output, 'runtime_ignoreip': verify_raw})
            print(f'[SECURITY] Fail2ban auto-whitelist: FAILED verification for {ip}: {output}', flush=True)

    runtime_after, runtime_after_raw = runtime_ignore_ips()

    # Only remove stale dynamic addresses when a different/current successful
    # address exists. If the endpoint is temporarily offline, keep its last
    # authenticated public IP so a normal re-registration is not blocked.
    if current:
        for ip in sorted(previous - current):
            if ip in runtime_after:
                ok, out = f2b('set', JAIL, 'delignoreip', ip)
                if ok:
                    print(f'[SECURITY] Fail2ban auto-whitelist: removed stale remote extension IP {ip}', flush=True)
                elif out.strip():
                    errors.append({'ip': ip, 'remove_error': out.strip()})
        persisted = current
    else:
        persisted = previous

    write_json(STATE, {'ips': sorted(persisted), 'updated_at': int(time.time())})
    write_json(STATUS, {
        'updated_at': int(time.time()),
        'jail': JAIL,
        'configured_extensions': sorted(extensions),
        'contact_ips': sorted(contact_ips),
        'successful_log_ips': sorted(log_ips),
        'desired_dynamic_ips': sorted(desired),
        'runtime_ignore_ips': sorted(runtime_after),
        'banned_before_sync': sorted(before_banned),
        'added_verified': added,
        'errors': errors,
        'contact_diagnostics': contact_diag,
        'successful_log_matches': log_diag,
        'runtime_ignore_raw': runtime_after_raw[-8000:],
    })
    return persisted


def main():
    previous = set(load_json(STATE, {}).get('ips') or [])
    print('[SECURITY] Fail2ban dynamic remote-IP whitelist watcher started', flush=True)
    while True:
        ok, ping = f2b('ping')
        if ok:
            try:
                previous = sync_once(previous)
            except Exception as exc:
                write_json(STATUS, {'updated_at': int(time.time()), 'jail': JAIL, 'error': str(exc)})
                print(f'[SECURITY] Fail2ban auto-whitelist watcher error: {exc}', flush=True)
        else:
            write_json(STATUS, {'updated_at': int(time.time()), 'jail': JAIL, 'error': ping.strip() or 'Fail2ban offline'})
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
