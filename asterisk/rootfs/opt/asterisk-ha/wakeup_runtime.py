#!/usr/bin/env python3
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STATE = Path('/config/state/wakeup.json')
OPTIONS = Path('/data/options.json')
CONF = '/config/asterisk/asterisk.conf'
HEARTBEAT = Path('/run/asterisk-wakeup-heartbeat')
SOUNDS = Path('/var/lib/asterisk/sounds')
DEFAULT_WAKEUP_SOUND = 'pt_BR/this-is-yr-wakeup-call'
# Asterisk sound packages install the classic English prompt below sounds/en/.
# Use the language-specific path only to verify the file exists. The actual
# wake-up call now runs through the dedicated [wakeup-call] dialplan context,
# which answers, waits for media, tries absolute prompt paths and has a spoken
# core-sounds fallback instead of immediately hanging up on Playback failure.
CLASSIC_WAKEUP_SOUND = 'this-is-yr-wakeup-call'
CLASSIC_WAKEUP_FILE = 'en/this-is-yr-wakeup-call'
SOUND_EXTENSIONS = ('.wav', '.WAV', '.gsm', '.ulaw', '.alaw', '.g722', '.sln', '.sln16')


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _extension(value):
    return re.sub(r'[^0-9]', '', str(value or ''))[:12]


def _time(value):
    raw = str(value or '').strip()
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', raw):
        raise ValueError('hora inválida; usa HH:MM')
    return raw


def _date(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    datetime.strptime(raw, '%Y-%m-%d')
    return raw


def _sound(value):
    raw = str(value or DEFAULT_WAKEUP_SOUND).strip() or DEFAULT_WAKEUP_SOUND
    if not re.fullmatch(r'[0-9A-Za-z_./-]+', raw):
        raise ValueError('som inválido')
    return raw[:160]


def _sound_exists(sound):
    sound = _sound(sound)
    base = SOUNDS / sound
    if base.is_file():
        return True
    return any(Path(str(base) + ext).is_file() for ext in SOUND_EXTENSIONS)


def _classic_sound_available():
    return _sound_exists(CLASSIC_WAKEUP_FILE) or _sound_exists(CLASSIC_WAKEUP_SOUND)


def resolve_wakeup_sound(requested=None):
    """Report the preferred prompt that the dialplan will attempt first."""
    wanted = _sound(requested or DEFAULT_WAKEUP_SOUND)

    if wanted in (CLASSIC_WAKEUP_SOUND, CLASSIC_WAKEUP_FILE):
        return CLASSIC_WAKEUP_SOUND if _classic_sound_available() else 'dialplan-fallback'

    if _sound_exists(wanted):
        return wanted

    if wanted != DEFAULT_WAKEUP_SOUND and _sound_exists(DEFAULT_WAKEUP_SOUND):
        return DEFAULT_WAKEUP_SOUND

    if _classic_sound_available():
        return CLASSIC_WAKEUP_SOUND

    return 'dialplan-fallback'


def normalize_alarm(item, fallback_id=1):
    if not isinstance(item, dict):
        raise ValueError('despertador inválido')
    days = []
    for x in (item.get('days') or []):
        try:
            x = int(x)
            if 0 <= x <= 6 and x not in days:
                days.append(x)
        except Exception:
            pass
    ext = _extension(item.get('extension'))
    if not ext:
        raise ValueError('extensão obrigatória')
    alarm_id = re.sub(r'[^0-9A-Za-z_-]', '', str(item.get('id') or f'alarm{fallback_id}'))[:40] or f'alarm{fallback_id}'
    raw_sound = str(item.get('sound') or '').strip()
    if not raw_sound or raw_sound == 'beep':
        raw_sound = DEFAULT_WAKEUP_SOUND
    return {
        'id': alarm_id,
        'enabled': bool(item.get('enabled', True)),
        'label': re.sub(r'[\r\n]+', ' ', str(item.get('label') or 'Serviço Despertar'))[:80],
        'extension': ext,
        'time': _time(item.get('time') or '07:00'),
        'days': sorted(days),
        'date': _date(item.get('date')),
        'sound': _sound(raw_sound),
        'last_fired': str(item.get('last_fired') or '')[:32],
    }


def load_state():
    raw = _read_json(STATE, {'alarms': [], 'events': []})
    alarms = []
    for i, item in enumerate(raw.get('alarms') or [], start=1):
        try:
            alarms.append(normalize_alarm(item, i))
        except Exception:
            continue
    return {'alarms': alarms, 'events': list(raw.get('events') or [])[-50:]}


def save_alarms(alarms):
    state = load_state()
    normalized = [normalize_alarm(x, i + 1) for i, x in enumerate(alarms or [])]
    ids = set()
    for alarm in normalized:
        base = alarm['id']; candidate = base; n = 2
        while candidate in ids:
            candidate = f'{base}-{n}'; n += 1
        alarm['id'] = candidate; ids.add(candidate)
    state['alarms'] = normalized
    _write_json(STATE, state)
    return state


def _event(state, text):
    state.setdefault('events', []).append({'at': datetime.now().isoformat(timespec='seconds'), 'text': str(text)[:500]})
    state['events'] = state['events'][-50:]


def _asterisk_originate(extension, sound=DEFAULT_WAKEUP_SOUND):
    """Ring the extension, then hand the answered channel to [wakeup-call].

    Using a dialplan extension instead of running Playback directly gives RTP
    time to settle and lets us try multiple prompts plus a guaranteed audible
    fallback before hanging up.
    """
    ext = _extension(extension)
    requested = _sound(sound)
    snd = resolve_wakeup_sound(requested)
    if not ext:
        return {'ok': False, 'output': 'extensão inválida'}
    cmd = ['asterisk', '-C', CONF, '-rx', f'channel originate PJSIP/{ext} extension s@wakeup-call']
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=70)
        return {
            'ok': p.returncode == 0,
            'output': (p.stdout or '')[-4000:],
            'extension': ext,
            'sound': snd,
            'requested_sound': requested,
            'call_mode': 'dialplan:wakeup-call',
        }
    except Exception as e:
        return {
            'ok': False,
            'output': str(e),
            'extension': ext,
            'sound': snd,
            'requested_sound': requested,
            'call_mode': 'dialplan:wakeup-call',
        }


def test_alarm(extension, sound=DEFAULT_WAKEUP_SOUND):
    return _asterisk_originate(extension, sound)


def _timezone():
    opt = _read_json(OPTIONS, {})
    name = str(opt.get('timezone') or 'Europe/Lisbon')
    try:
        return ZoneInfo(name), name
    except Exception:
        return ZoneInfo('Europe/Lisbon'), 'Europe/Lisbon'


def status():
    state = load_state()
    try:
        age = time.time() - HEARTBEAT.stat().st_mtime
        scheduler_online = age < 35
    except Exception:
        scheduler_online = False
    tz, tz_name = _timezone()
    now = datetime.now(tz)
    classic_available = _classic_sound_available()
    return {
        **state,
        'scheduler_online': scheduler_online,
        'timezone': tz_name,
        'now': now.isoformat(timespec='seconds'),
        'active': sum(1 for x in state['alarms'] if x.get('enabled')),
        'default_prompt': DEFAULT_WAKEUP_SOUND,
        'resolved_prompt': resolve_wakeup_sound(DEFAULT_WAKEUP_SOUND),
        'portuguese_prompt_available': _sound_exists(DEFAULT_WAKEUP_SOUND),
        'classic_prompt_available': classic_available,
        'call_mode': 'dialplan:wakeup-call',
    }


def scheduler_loop():
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            HEARTBEAT.touch()
            state = load_state()
            tz, _ = _timezone()
            now = datetime.now(tz)
            minute_key = now.strftime('%Y-%m-%dT%H:%M')
            changed = False
            for alarm in state['alarms']:
                if not alarm.get('enabled') or alarm.get('time') != now.strftime('%H:%M'):
                    continue
                if alarm.get('date'):
                    if alarm['date'] != now.strftime('%Y-%m-%d'):
                        continue
                elif alarm.get('days') and now.weekday() not in alarm['days']:
                    continue
                if alarm.get('last_fired') == minute_key:
                    continue
                result = _asterisk_originate(alarm['extension'], alarm.get('sound') or DEFAULT_WAKEUP_SOUND)
                alarm['last_fired'] = minute_key
                if alarm.get('date'):
                    alarm['enabled'] = False
                _event(state, f"{alarm['label']} → {alarm['extension']} @ {alarm['time']}: {'OK' if result.get('ok') else 'ERRO'} mode={result.get('call_mode','')} prompt={result.get('sound','')} {result.get('output','')}")
                changed = True
            if changed:
                _write_json(STATE, state)
        except Exception:
            pass
        time.sleep(10)
