#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '/opt/asterisk-ha')
from wakeup_runtime import DEFAULT_WAKEUP_SOUND, _timezone, load_state, save_alarms


def clean_extension(value):
    return re.sub(r'[^0-9]', '', str(value or ''))[:12]


def parse_hhmm(value):
    raw = re.sub(r'[^0-9]', '', str(value or ''))
    if len(raw) != 4:
        raise ValueError('hora deve ter 4 dígitos HHMM')
    hour = int(raw[:2])
    minute = int(raw[2:])
    if hour > 23 or minute > 59:
        raise ValueError('hora inválida')
    return hour, minute, f'{hour:02d}:{minute:02d}'


def set_alarm(extension, hhmm):
    ext = clean_extension(extension)
    if not ext:
        raise ValueError('extensão inválida')

    hour, minute, time_text = parse_hhmm(hhmm)
    tz, _ = _timezone()
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    alarm_id = f'phone-{ext}'
    state = load_state()
    alarms = [a for a in state.get('alarms', []) if a.get('id') != alarm_id]
    alarms.append({
        'id': alarm_id,
        'enabled': True,
        'label': 'Serviço Despertar (*68)',
        'extension': ext,
        'time': time_text,
        'days': [],
        'date': target.strftime('%Y-%m-%d'),
        'sound': DEFAULT_WAKEUP_SOUND,
        'last_fired': '',
    })
    save_alarms(alarms)
    return {
        'ok': True,
        'action': 'set',
        'extension': ext,
        'time': time_text,
        'date': target.strftime('%Y-%m-%d'),
    }


def cancel_alarm(extension):
    ext = clean_extension(extension)
    if not ext:
        raise ValueError('extensão inválida')
    alarm_id = f'phone-{ext}'
    state = load_state()
    old = state.get('alarms', [])
    alarms = [a for a in old if a.get('id') != alarm_id]
    save_alarms(alarms)
    return {
        'ok': True,
        'action': 'cancel',
        'extension': ext,
        'removed': len(old) - len(alarms),
    }


def main(argv):
    try:
        if len(argv) < 3:
            raise ValueError('uso: wakeup_phone.py set EXT HHMM | cancel EXT')
        action = argv[1]
        if action == 'set':
            if len(argv) < 4:
                raise ValueError('hora em falta')
            result = set_alarm(argv[2], argv[3])
        elif action == 'cancel':
            result = cancel_alarm(argv[2])
        else:
            raise ValueError('ação inválida')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
