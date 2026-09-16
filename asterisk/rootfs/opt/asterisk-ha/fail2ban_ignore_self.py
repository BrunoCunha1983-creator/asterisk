#!/usr/bin/env python3
import ipaddress
import json
import re
import socket
import sys
import time
import urllib.request
from pathlib import Path

NAT_STATUS = Path('/config/state/nat.json')
PBX = Path('/config/state/pbx.json')
DYNAMIC_STATE = Path('/data/fail2ban/dynamic-ignoreips.json')
SELF_STATE = Path('/data/fail2ban/self-public-ip.json')
CACHE_MAX_AGE = 120


def load_json(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_self(ip, source):
    try:
        SELF_STATE.parent.mkdir(parents=True, exist_ok=True)
        SELF_STATE.write_text(json.dumps({
            'ip': ip,
            'source': source,
            'updated_at': int(time.time()),
        }, indent=2))
    except Exception:
        pass


def public_ip(value):
    try:
        ip = ipaddress.ip_address(str(value or '').strip())
    except Exception:
        return None
    return str(ip) if ip.is_global else None


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


def live_public_ip(version):
    urls = (
        ('https://api.ipify.org', 'https://checkip.amazonaws.com')
        if version == 4 else
        ('https://api6.ipify.org',)
    )
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Asterisk-HA/0.2.40'})
            with urllib.request.urlopen(req, timeout=3) as response:
                ip = public_ip(response.read(128).decode('ascii', 'ignore').strip())
            if ip and ipaddress.ip_address(ip).version == version:
                return ip, url
        except Exception:
            continue
    return None, 'live-scan-failed'


def cached_candidates():
    now = int(time.time())
    candidates = []

    state = load_json(SELF_STATE)
    ip = public_ip(state.get('ip'))
    try:
        fresh = now - int(state.get('updated_at') or 0) <= CACHE_MAX_AGE
    except Exception:
        fresh = False
    if ip and fresh:
        candidates.append((ip, 'self-state'))

    state = load_json(DYNAMIC_STATE)
    ip = public_ip(state.get('ha_public_ip'))
    try:
        fresh = now - int(state.get('updated_at') or 0) <= CACHE_MAX_AGE
    except Exception:
        fresh = False
    if ip and fresh:
        candidates.append((ip, 'dynamic-state'))

    nat = load_json(NAT_STATUS)
    ip = resolve_public(nat.get('external_address'))
    if ip:
        candidates.append((ip, 'nat.json'))

    pbx = load_json(PBX)
    network = pbx.get('network') or {}
    if isinstance(network, dict):
        ip = resolve_public(network.get('external_address'))
        if ip:
            candidates.append((ip, 'pbx.network.external_address'))

    return candidates


def main():
    if len(sys.argv) < 2:
        return 1
    candidate = public_ip(sys.argv[1])
    if not candidate:
        return 1

    version = ipaddress.ip_address(candidate).version

    # This runs only when Fail2ban is considering a ban. Make a fresh public-IP
    # check first so a just-changed WAN address cannot be blacklisted while the
    # periodic watcher is still catching up.
    live, source = live_public_ip(version)
    if live:
        save_self(live, source)
        return 0 if live == candidate else 1

    # If public-IP services are temporarily unreachable, fall back to very fresh
    # watcher state and then to the PBX/NAT state. This favours PBX availability
    # without globally disabling Fail2ban.
    for ip, cached_source in cached_candidates():
        if ip == candidate:
            save_self(ip, cached_source)
            return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
