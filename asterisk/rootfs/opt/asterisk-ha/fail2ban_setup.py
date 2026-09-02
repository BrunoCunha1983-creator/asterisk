#!/usr/bin/env python3
import json
import re
from pathlib import Path

OPTIONS = Path('/data/options.json')
F2B_DIR = Path('/etc/fail2ban')
DATA_DIR = Path('/data/fail2ban')
ASTERISK_LOG = Path('/var/log/asterisk/full')


def _load_options(path=OPTIONS):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _bounded(value, default, low, high):
    try:
        value = int(value)
    except Exception:
        value = default
    return max(low, min(high, value))


def _ignoreip(value):
    raw = str(value or '').replace(',', ' ').split()
    safe = []
    for item in raw:
        if re.fullmatch(r'[0-9A-Fa-f:.]+(?:/\d{1,3})?', item):
            safe.append(item)
    defaults = ['127.0.0.1/8', '::1', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7']
    for item in defaults:
        if item not in safe:
            safe.append(item)
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
    ignoreip = _ignoreip(options.get('fail2ban_ignoreip'))

    for path in (asterisk_log, data_dir / 'pbx-web-security.log'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    (root / 'fail2ban.local').write_text(
        '[Definition]\n'
        f'logtarget = {data_dir}/fail2ban.log\n'
        f'dbfile = {data_dir}/fail2ban.sqlite3\n'
        'dbpurgeage = 1209600\n'
        'loglevel = INFO\n'
    )

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
    (root / 'jail.d' / 'asterisk-ha.local').write_text(jail)
    return {
        'enabled': enabled,
        'bantime': bantime,
        'findtime': findtime,
        'maxretry': maxretry,
        'web_maxretry': web_maxretry,
        'ignoreip': ignoreip,
        'sip_port': sip_port,
        'tls_port': tls_port,
        'jail_file': str(root / 'jail.d' / 'asterisk-ha.local'),
    }


if __name__ == '__main__':
    print(json.dumps(render(), ensure_ascii=False))
