#!/usr/bin/env python3
import ipaddress
import json
import re
import socket
import time
import urllib.request
from pathlib import Path

OPTIONS = Path('/data/options.json')
F2B_DIR = Path('/etc/fail2ban')
DATA_DIR = Path('/data/fail2ban')
ASTERISK_LOG = Path('/var/log/asterisk/full')
NAT_STATUS = Path('/config/state/nat.json')
PBX = Path('/config/state/pbx.json')
SELF_STATE = DATA_DIR / 'self-public-ip.json'


def _load_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else ({} if default is None else default)
    except Exception:
        return {} if default is None else default


def _load_options(path=OPTIONS):
    return _load_json(path, {})


def _bounded(value, default, low, high):
    try:
        value = int(value)
    except Exception:
        value = default
    return max(low, min(high, value))


def _public_ip(value):
    try:
        ip = ipaddress.ip_address(str(value or '').strip())
    except Exception:
        return None
    return str(ip) if ip.is_global else None


def _resolve_public(value):
    value = str(value or '').strip()
    value = re.sub(r'^https?://', '', value, flags=re.I).split('/')[0].strip()
    if not value:
        return None
    literal = _public_ip(value)
    if literal:
        return literal
    host = value
    if host.startswith('[') and ']' in host:
        host = host[1:host.index(']')]
    elif host.count(':') == 1:
        host = host.rsplit(':', 1)[0]
    try:
        for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            ip = _public_ip(info[4][0])
            if ip:
                return ip
    except Exception:
        pass
    return None


def _save_self_ip(ip, source):
    if not ip:
        return
    try:
        SELF_STATE.parent.mkdir(parents=True, exist_ok=True)
        SELF_STATE.write_text(json.dumps({
            'ip': ip,
            'source': source,
            'updated_at': int(time.time()),
        }, indent=2))
    except Exception:
        pass


def _detect_self_public_ip():
    # Fresh scan first. This is deliberate: nat.json may contain yesterday's WAN
    # address after an ISP reconnect, and Fail2ban must start with today's IP.
    for url in ('https://api.ipify.org', 'https://checkip.amazonaws.com'):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Asterisk-HA/0.2.40'})
            with urllib.request.urlopen(req, timeout=3) as response:
                ip = _public_ip(response.read(128).decode('ascii', 'ignore').strip())
            if ip:
                _save_self_ip(ip, url)
                return ip, url
        except Exception:
            continue

    nat = _load_json(NAT_STATUS, {})
    ip = _resolve_public(nat.get('external_address'))
    if ip:
        _save_self_ip(ip, 'nat.json')
        return ip, 'nat.json'

    pbx = _load_json(PBX, {})
    network = pbx.get('network') or {}
    if isinstance(network, dict):
        ip = _resolve_public(network.get('external_address'))
        if ip:
            _save_self_ip(ip, 'pbx.network.external_address')
            return ip, 'pbx.network.external_address'

    return None, 'unavailable'


def _ignoreip(value, self_public_ip=None):
    raw = str(value or '').replace(',', ' ').split()
    safe = []
    for item in raw:
        if re.fullmatch(r'[0-9A-Fa-f:.]+(?:/\d{1,3})?', item):
            safe.append(item)
    defaults = ['127.0.0.1/8', '::1', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7']
    for item in defaults:
        if item not in safe:
            safe.append(item)
    if self_public_ip and self_public_ip not in safe:
        safe.append(self_public_ip)
    return ' '.join(safe)


def render(options=None, root=F2B_DIR, data_dir=DATA_DIR, asterisk_log=ASTERISK_LOG):
    options = dict(options or _load_options())
    root = Path(root)
    data_dir = Path(data_dir)
    asterisk_log = Path(asterisk_log)
    data_dir.mkdir(parents=True, exist_ok=True)
    (root / 'jail.d').mkdir(parents=True, exist_ok=True)
    (root / 'filter.d').mkdir(parents=True, exist_ok=True)

    enabled = bool(options.get('fail2ban_enabled', True))
    bantime = _bounded(options.get('fail2ban_bantime'), 3600, 60, 604800)
    findtime = _bounded(options.get('fail2ban_findtime'), 600, 30, 86400)
    maxretry = _bounded(options.get('fail2ban_maxretry'), 5, 2, 50)
    web_maxretry = _bounded(options.get('fail2ban_web_maxretry'), 10, 2, 100)
    sip_port = _bounded(options.get('sip_port'), 5060, 1, 65535)
    tls_port = _bounded(options.get('tls_port'), 5061, 1, 65535)
    self_public_ip, self_public_ip_source = _detect_self_public_ip()
    ignoreip = _ignoreip(options.get('fail2ban_ignoreip'), self_public_ip)

    for path in (asterisk_log, data_dir / 'pbx-web-security.log'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    (root / 'fail2ban.local').write_text(
        '[Definition]\n'
        'allowipv6 = auto\n'
        f'logtarget = {data_dir}/fail2ban.log\n'
        f'dbfile = {data_dir}/fail2ban.sqlite3\n'
        'dbpurgeage = 1209600\n'
        'loglevel = INFO\n'
    )

    # Debian enables the stock sshd jail in jail.d/defaults-debian.conf. This
    # PBX image has no sshd/auth.log, so that unrelated jail makes `fail2ban-client
    # -t` fail before our Asterisk jails can start. A late-sorting local override
    # disables only the distro sshd jail while leaving our PBX jails untouched.
    stock_override = root / 'jail.d' / 'zz-asterisk-ha-disable-stock.local'
    stock_override.write_text('[sshd]\nenabled = false\n')

    (root / 'filter.d' / 'asterisk-ha-pjsip.conf').write_text(r'''[Definition]
# Conservative PJSIP filter: REGISTER authentication failures are banned.
# INVITE "No matching endpoint" is deliberately not banned because a remote
# provider such as SIPcord can legitimately reach Asterisk without a local
# identify rule. Failed INVITE authentication is still protected.
failregex = ^.*Request 'REGISTER' from '.*' failed for '<HOST>(?::\d+)?'.* - (?:Failed to authenticate|No matching endpoint found|Authentication failed).*$
            ^.*Request 'INVITE' from '.*' failed for '<HOST>(?::\d+)?'.* - (?:Failed to authenticate|Authentication failed).*$
            ^.*SecurityEvent="(?:InvalidPassword|ChallengeResponseFailed|InvalidAccountID)".*RemoteAddress="IPV[46]/(?:UDP|TCP|TLS)/<HOST>/\d+".*$
ignoreregex =
''')

    (root / 'filter.d' / 'asterisk-ha-web.conf').write_text(r'''[Definition]
failregex = ^\S+ PBX-WEB client=<HOST> method=\S+ path=\S+ status=(?:403|404|405|413)(?: reason=\S+)?$
ignoreregex =
''')

    jail = f'''[DEFAULT]
ignoreip = {ignoreip}
# Local interface self-detection alone does not know the router's public NAT
# address, so protect it in two layers: startup ignoreip above and a final live
# public-IP check immediately before any prospective ban.
ignoreself = true
ignorecommand = python3 /opt/asterisk-ha/fail2ban_ignore_self.py "<ip>"
backend = polling
usedns = no
bantime = {bantime}
findtime = {findtime}
maxretry = {maxretry}
bantime.increment = true
bantime.factor = 2
bantime.maxtime = 604800
bantime.rndtime = 300

[asterisk-pjsip]
enabled = {'true' if enabled else 'false'}
filter = asterisk-ha-pjsip
logpath = {asterisk_log}
findtime = {findtime}
maxretry = {maxretry}
bantime = {bantime}
action = nftables-multiport[name=asterisk-pjsip-udp, port="{sip_port}", protocol=udp]
         nftables-multiport[name=asterisk-pjsip-tcp, port="{sip_port},{tls_port}", protocol=tcp]

[asterisk-web]
enabled = {'true' if enabled else 'false'}
filter = asterisk-ha-web
logpath = {data_dir}/pbx-web-security.log
findtime = 120
maxretry = {web_maxretry}
bantime = {bantime}
action = nftables-multiport[name=asterisk-web, port="8099", protocol=tcp]
'''
    jail_file = root / 'jail.d' / 'asterisk-ha.local'
    jail_file.write_text(jail)
    return {
        'enabled': enabled,
        'bantime': bantime,
        'findtime': findtime,
        'maxretry': maxretry,
        'web_maxretry': web_maxretry,
        'ignoreip': ignoreip,
        'self_public_ip': self_public_ip,
        'self_public_ip_source': self_public_ip_source,
        'ignorecommand': 'python3 /opt/asterisk-ha/fail2ban_ignore_self.py <ip>',
        'sip_port': sip_port,
        'tls_port': tls_port,
        'jail_file': str(jail_file),
        'stock_override': str(stock_override),
    }


if __name__ == '__main__':
    print(json.dumps(render(), ensure_ascii=False))
