#!/usr/bin/env python3
"""Self-healing runtime watchdog for chan_dongle.

Keeps GSM profiles tied to stable /dev/serial aliases, restores a saved modem
when its USB ports reappear, regenerates dongle.conf, and asks chan_dongle to
reload only when the effective hardware/configuration changes.
"""
import json
import subprocess
import time
from pathlib import Path

from gsm_runtime import active_dongles, normalize_gsm_state

CONF = Path('/config/asterisk')
PBX = Path('/config/state/pbx.json')
OPTIONS = Path('/data/options.json')
HEARTBEAT = Path('/run/asterisk-dongle-watchdog')
STATUS = Path('/run/asterisk-dongle-watchdog.json')


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def run(args, timeout=15):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, (p.stdout or '')[-8000:]
    except Exception as exc:
        return 99, str(exc)


def ast(command, timeout=15):
    return run(['asterisk', '-C', str(CONF / 'asterisk.conf'), '-rx', command], timeout)


def module_loaded():
    rc, out = ast('module show like chan_dongle.so', 8)
    low = out.lower()
    return rc == 0 and 'chan_dongle.so' in low and ('running' in low or 'loaded' in low)


def render_dongle_conf(dongles):
    lines = [
        '[general]',
        'interval=15',
        '',
        '[defaults]',
        'context=from-dongle',
        'group=0',
        'rxgain=0',
        'txgain=0',
        'autodeletesms=yes',
        'resetdongle=yes',
        'u2diag=-1',
        'usecallingpres=yes',
        'callingpres=allowed_passed_screen',
    ]
    for d in dongles:
        name = ''.join(c for c in str(d.get('name') or '') if c.isalnum() or c in '_-')
        if not name:
            continue
        lines += [
            '', f'[{name}]',
            f'audio={str(d.get("audio") or "").strip()}',
            f'data={str(d.get("data") or "").strip()}',
            f'context={str(d.get("context") or "from-dongle").strip()}',
            f'group={int(d.get("group", 0) or 0)}',
            f'rxgain={int(d.get("rxgain", 0) or 0)}',
            f'txgain={int(d.get("txgain", 0) or 0)}',
            f'autodeletesms={"yes" if d.get("autodeletesms", True) else "no"}',
            f'disablesms={"yes" if d.get("disablesms", False) else "no"}',
        ]
    (CONF / 'dongle.conf').write_text('\n'.join(lines).rstrip() + '\n')


def status_write(**extra):
    payload = {'updated_at': int(time.time()), **extra}
    try:
        write_json_atomic(STATUS, payload)
    except Exception:
        pass


def reconcile(previous_signature=None):
    options = read_json(OPTIONS, {})
    enabled = bool(options.get('chan_dongle', True))
    data = read_json(PBX, {})
    normalized, changed = normalize_gsm_state(data)
    if changed:
        write_json_atomic(PBX, normalized)
        data = normalized

    configured = list(data.get('gsm_dongles') or [])
    live = active_dongles(configured)
    signature = tuple(
        (str(d.get('name') or ''), str(d.get('audio') or ''), str(d.get('data') or ''))
        for d in live
    )

    if not enabled:
        status_write(enabled=False, module_loaded=module_loaded(), active=len(live), action='disabled')
        return signature

    loaded = module_loaded()
    action = 'none'
    details = ''

    # If Asterisk started before the USB device was ready, load the module now.
    if not loaded:
        rc, out = ast('module load chan_dongle.so', 15)
        loaded = module_loaded()
        action = 'module-load'
        details = out

    # Only rewrite/reload when the effective physical binding changed. This
    # avoids needless churn and never tears down active calls every poll cycle.
    if signature != previous_signature or changed:
        render_dongle_conf(live)
        if loaded:
            rc, out = ast('dongle reload when convenient', 15)
            action = 'dongle-reload'
            details = out
        elif live:
            rc, out = ast('module load chan_dongle.so', 15)
            loaded = module_loaded()
            action = 'module-load-after-config'
            details = out

    # A configured/present device can remain stopped after a transient serial
    # error. Starting it is safe; chan_dongle ignores already-running devices.
    if loaded and live:
        rc, shown = ast('dongle show devices', 10)
        low = shown.lower()
        for d in live:
            name = str(d.get('name') or '').strip()
            if not name:
                continue
            row = next((line for line in shown.splitlines() if line.strip().startswith(name + ' ')), '')
            if (not row) or any(word in row.lower() for word in ('notconnected', 'disconnected', 'stopped')):
                rc2, out2 = ast(f'dongle start {name}', 10)
                action = f'dongle-start:{name}'
                details = (details + '\n' + out2).strip()

    status_write(
        enabled=True,
        module_loaded=loaded,
        active=len(live),
        profiles=len(data.get('gsm_profiles') or []),
        bindings=[{'name': d.get('name'), 'audio': d.get('audio'), 'data': d.get('data')} for d in live],
        action=action,
        details=details[-3000:],
    )
    return signature


def main():
    previous = None
    while True:
        try:
            HEARTBEAT.touch()
            previous = reconcile(previous)
        except Exception as exc:
            status_write(enabled=True, module_loaded=False, active=0, action='error', details=str(exc))
        time.sleep(15)


if __name__ == '__main__':
    main()
