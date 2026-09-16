#!/usr/bin/env python3
import ipaddress
import json
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

PBX = Path('/config/state/pbx.json')
NAT_STATUS = Path('/config/state/nat.json')
OPTIONS = Path('/data/options.json')
STATE = Path('/data/fail2ban/dynamic-ignoreips.json')
STATUS = Path('/data/fail2ban/dynamic-whitelist-status.json')
ASTERISK_LOG = Path('/var/log/asterisk/full')
F2B_SOCKET = '/run/fail2ban/fail2ban.sock'
ASTERISK_CONF = '/config/asterisk/asterisk.conf'
PJSIP_JAIL = 'asterisk-pjsip'
WEB_JAIL = 'asterisk-web'
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
    # Only globally routable addresses are useful as an external HA/PBX IP or
    # as a public remote endpoint address. Private, CGNAT and documentation
    # ranges must never be learned as public Fail2ban exceptions here.
    if not ip.is_global:
        return None
    return str(ip)


def resolve_public(value):
    value = str(value or '').strip()
    value = re.sub(r'^https?://', '', value, flags=re.I).split('/')[0].strip()
    if not value:
        return None
    literal = public_ip(value)
    if literal:
        return literal
    host = value
    if host.startswith('[') and ']' in host:
        host = host[1:host.index(']')]
    elif host.count(':') == 1:
        host = host.rsplit(':', 1)[0]
    try:
        for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            ip = public_ip(info[4][0])
            if ip:
                return ip
    except Exception:
        pass
    return None


def detect_ha_public_ip():
    # Prefer the address already detected by the add-on NAT layer so Fail2ban
    # trusts exactly the public address the PBX is advertising.
    nat = load_json(NAT_STATUS, {})
    ip = resolve_public(nat.get('external_address'))
    if ip:
        return ip, 'nat.json'

    pbx = load_json(PBX, {})
    network = pbx.get('network') or {}
    if isinstance(network, dict):
        ip = resolve_public(network.get('external_address'))
        if ip:
            return ip, 'pbx.network.external_address'

    for url in ('https://api.ipify.org', 'https://checkip.amazonaws.com'):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Asterisk-HA/0.2.39'})
            with urllib.request.urlopen(req, timeout=4) as response:
                ip = public_ip(response.read(128).decode('ascii', 'ignore').strip())
            if ip:
                return ip, url
        except Exception:
            continue
    return None, 'unavailable'


def extract_public_ips(text):
    out = set()
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


def runtime_ignore_ips(jail):
    ok, text = f2b('get', jail, 'ignoreip')
    return extract_public_ips(text) if ok else set(), text.strip()


def banned_ips(jail):
    ok, text = f2b('status', jail)
    if not ok:
        return set()
    m = re.search(r'Banned IP list:\s*(.*)$', text, re.I | re.M)
    return extract_public_ips(m.group(1) if m else '')


def apply_ignore(jail, ip):
    f2b('set', jail, 'unbanip', ip)
    ok, output = f2b('set', jail, 'addignoreip', ip)
    runtime, runtime_raw = runtime_ignore_ips(jail)
    verified = ip in runtime
    return verified, output.strip(), runtime_raw


def static_ignore_contains(ip):
    if not ip:
        return False
    options = load_json(OPTIONS, {})
    raw = str(options.get('fail2ban_ignoreip') or '').replace(',', ' ').split()
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    for item in raw:
        try:
            if addr in ipaddress.ip_network(item, strict=False):
                return True
        except Exception:
            continue
    return False


def sync_ha_public_ip(ha_ip, previous_ha_ip, errors):
    verified = {}
    added = []
    banned_before = {}
    for jail in (PJSIP_JAIL, WEB_JAIL):
        runtime, _ = runtime_ignore_ips(jail)
        banned_before[jail] = sorted(banned_ips(jail))
        if ha_ip and ha_ip not in runtime:
            ok, output, verify_raw = apply_ignore(jail, ha_ip)
            verified[jail] = bool(ok)
            if ok:
                added.append({'jail': jail, 'ip': ha_ip})
                print(f'[SECURITY] Fail2ban HA public-IP whitelist: verified {ha_ip} in {jail}', flush=True)
            else:
                errors.append({'jail': jail, 'ip': ha_ip, 'ha_public_ip_error': output, 'runtime_ignoreip': verify_raw})
        else:
            verified[jail] = bool(ha_ip and ha_ip in runtime)

    # Remove the previous dynamically-managed HA public address after a change,
    # unless the user explicitly placed that address/network in static ignoreip.
    if previous_ha_ip and ha_ip and previous_ha_ip != ha_ip and not static_ignore_contains(previous_ha_ip):
        for jail in (PJSIP_JAIL, WEB_JAIL):
            # In PJSIP keep it if it is still a currently trusted remote endpoint;
            # the remote-IP sync below will manage that case independently.
            f2b('set', jail, 'delignoreip', previous_ha_ip)
            print(f'[SECURITY] Fail2ban HA public-IP whitelist: removed stale {previous_ha_ip} from {jail}', flush=True)

    return verified, added, banned_before


def sync_once(previous_remote, previous_ha_ip):
    extensions = configured_extensions()
    contact_ips, contact_diag = contact_remote_ips(extensions)
    log_ips, log_diag = successful_log_ips(extensions)
    current_remote = contact_ips | log_ips
    runtime_pjsip, runtime_pjsip_raw = runtime_ignore_ips(PJSIP_JAIL)
    before_banned_pjsip = banned_ips(PJSIP_JAIL)
    errors = []
    added_remote = []

    desired_remote = current_remote | previous_remote
    for ip in sorted(desired_remote - runtime_pjsip):
        verified, output, verify_raw = apply_ignore(PJSIP_JAIL, ip)
        if verified:
            added_remote.append(ip)
            print(f'[SECURITY] Fail2ban auto-whitelist: verified remote extension IP {ip}', flush=True)
        else:
            errors.append({'jail': PJSIP_JAIL, 'ip': ip, 'output': output, 'runtime_ignoreip': verify_raw})
            print(f'[SECURITY] Fail2ban auto-whitelist: FAILED verification for {ip}: {output}', flush=True)

    runtime_pjsip_after, runtime_pjsip_after_raw = runtime_ignore_ips(PJSIP_JAIL)

    if current_remote:
        for ip in sorted(previous_remote - current_remote):
            if ip in runtime_pjsip_after and not static_ignore_contains(ip):
                ok, out = f2b('set', PJSIP_JAIL, 'delignoreip', ip)
                if ok:
                    print(f'[SECURITY] Fail2ban auto-whitelist: removed stale remote extension IP {ip}', flush=True)
                elif out.strip():
                    errors.append({'jail': PJSIP_JAIL, 'ip': ip, 'remove_error': out.strip()})
        persisted_remote = current_remote
    else:
        persisted_remote = previous_remote

    ha_ip, ha_source = detect_ha_public_ip()
    ha_verified, ha_added, ha_banned_before = sync_ha_public_ip(ha_ip, previous_ha_ip, errors)

    runtime_by_jail = {}
    runtime_raw_by_jail = {}
    for jail in (PJSIP_JAIL, WEB_JAIL):
        ips, raw = runtime_ignore_ips(jail)
        runtime_by_jail[jail] = sorted(ips)
        runtime_raw_by_jail[jail] = raw[-8000:]

    write_json(STATE, {
        'ips': sorted(persisted_remote),
        'remote_ips': sorted(persisted_remote),
        'ha_public_ip': ha_ip or previous_ha_ip,
        'ha_public_ip_source': ha_source,
        'updated_at': int(time.time()),
    })
    write_json(STATUS, {
        'updated_at': int(time.time()),
        'jail': PJSIP_JAIL,
        'configured_extensions': sorted(extensions),
        'contact_ips': sorted(contact_ips),
        'successful_log_ips': sorted(log_ips),
        'desired_dynamic_ips': sorted(desired_remote),
        'runtime_ignore_ips': runtime_by_jail.get(PJSIP_JAIL, []),
        'runtime_ignore_by_jail': runtime_by_jail,
        'banned_before_sync': sorted(before_banned_pjsip),
        'added_verified': added_remote,
        'ha_public_ip': ha_ip,
        'ha_public_ip_source': ha_source,
        'ha_public_ip_previous': previous_ha_ip,
        'ha_public_ip_verified': ha_verified,
        'ha_public_ip_added': ha_added,
        'ha_banned_before_sync': ha_banned_before,
        'errors': errors,
        'contact_diagnostics': contact_diag,
        'successful_log_matches': log_diag,
        'runtime_ignore_raw': runtime_pjsip_after_raw[-8000:],
        'runtime_ignore_raw_by_jail': runtime_raw_by_jail,
    })
    return persisted_remote, (ha_ip or previous_ha_ip)


def main():
    state = load_json(STATE, {})
    previous_remote = set(state.get('remote_ips') or state.get('ips') or [])
    previous_ha_ip = public_ip(state.get('ha_public_ip'))
    print('[SECURITY] Fail2ban dynamic whitelist watcher started', flush=True)
    while True:
        ok, ping = f2b('ping')
        if ok:
            try:
                previous_remote, previous_ha_ip = sync_once(previous_remote, previous_ha_ip)
            except Exception as exc:
                write_json(STATUS, {'updated_at': int(time.time()), 'jail': PJSIP_JAIL, 'error': str(exc)})
                print(f'[SECURITY] Fail2ban dynamic whitelist watcher error: {exc}', flush=True)
        else:
            write_json(STATUS, {'updated_at': int(time.time()), 'jail': PJSIP_JAIL, 'error': ping.strip() or 'Fail2ban offline'})
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
