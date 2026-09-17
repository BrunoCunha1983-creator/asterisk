#!/usr/bin/env python3
"""Keep persistent IVR dialplan/audio safe across add-on upgrades.

Older installs may miss the generated IVR include because extensions.conf is
persistent. IVRs can also reference custom/... prompts before a recording was
created. On each start this migration:
- adds the missing IVR include idempotently;
- generates a PT-PT fallback WAV only when a configured custom prompt is absent;
- never overwrites an existing custom recording.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import wave
from pathlib import Path

EXTENSIONS = Path('/config/asterisk/extensions.conf')
PBX = Path('/config/state/pbx.json')
IVR_AUDIO = Path('/share/asterisk-ivr')
AUTO_STATE = Path('/data/ivr-auto-fallbacks.json')
INCLUDE = '#include extensions_ivr_gui.conf'
MARKER = '; IVR CONTEXTS MANAGED BY ASTERISK HA'


def ensure_include():
    if not EXTENSIONS.exists():
        return 'extensions.conf not installed'

    text = EXTENSIONS.read_text(errors='ignore')
    if re.search(r'^\s*#include\s+["\']?extensions_ivr_gui\.conf["\']?\s*$', text, re.I | re.M):
        return 'already present'

    suffix = '' if text.endswith('\n') else '\n'
    EXTENSIONS.write_text(text + suffix + '\n' + MARKER + '\n' + INCLUDE + '\n')
    return 'added'


def safe_stem(value, default='ivr-prompt'):
    value = str(value or '').strip()
    if value.startswith('custom/'):
        value = value[7:]
    if value.lower().endswith('.wav'):
        value = value[:-4]
    value = re.sub(r'[^0-9A-Za-z_-]', '-', value).strip('-_').lower()
    return value or default


def clean_text(value):
    return re.sub(r'\s+', ' ', str(value or '')).replace(';', ',').strip()


def digit_speech(value):
    names = {
        '0': 'zero', '1': 'um', '2': 'dois', '3': 'três', '4': 'quatro',
        '5': 'cinco', '6': 'seis', '7': 'sete', '8': 'oito', '9': 'nove',
        '*': 'asterisco', '#': 'cardinal',
    }
    return names.get(str(value or '').strip(), clean_text(value) or 'opção')


def fallback_text(ivr):
    name = clean_text((ivr or {}).get('name'))
    parts = ['Bem-vindo.']
    if name:
        parts.append(f'Está no menu {name}.')
    options = []
    for option in (ivr or {}).get('options') or []:
        if not isinstance(option, dict):
            continue
        digit = str(option.get('digit') or '').strip()
        if digit not in tuple('0123456789') + ('*', '#'):
            continue
        label = clean_text(option.get('label'))
        if label:
            options.append(f'Para {label}, prima {digit_speech(digit)}.')
        else:
            options.append(f'Para a opção {digit_speech(digit)}, prima {digit_speech(digit)}.')
    if options:
        parts.extend(options)
    else:
        parts.append('Selecione uma opção no teclado.')
    parts.append('Se não fizer nenhuma escolha, aguarde.')
    return ' '.join(parts)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def file_sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def valid_telephony_wav(path):
    try:
        with wave.open(str(path), 'rb') as wav:
            return (
                wav.getnchannels() == 1
                and wav.getsampwidth() == 2
                and wav.getframerate() == 8000
                and wav.getnframes() > 0
            )
    except Exception:
        return False


def generate_wav(path, text):
    IVR_AUDIO.mkdir(parents=True, exist_ok=True)
    source = Path('/tmp/ivr-auto-fallback-source.wav')
    target = path.with_name(f'.{path.stem}.auto.tmp.wav')
    try:
        subprocess.run(
            ['espeak-ng', '-v', 'pt-pt', '-s', '145', '-w', str(source), text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        subprocess.run(
            ['sox', str(source), '-r', '8000', '-c', '1', '-b', '16', str(target)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        if not valid_telephony_wav(target):
            raise RuntimeError('generated WAV has invalid telephony format')
        target.replace(path)
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def ensure_fallback_audio():
    data = load_json(PBX, {})
    ivrs = data.get('ivrs') if isinstance(data, dict) else []
    if not isinstance(ivrs, list):
        return {'generated': [], 'preserved': [], 'errors': []}

    state = load_json(AUTO_STATE, {})
    if not isinstance(state, dict):
        state = {}

    generated = []
    preserved = []
    errors = []
    active_stems = set()

    for ivr in ivrs:
        if not isinstance(ivr, dict) or not ivr.get('enabled', True):
            continue
        prompt = str(ivr.get('prompt') or '').strip()
        if not prompt.startswith('custom/'):
            continue

        stem = safe_stem(prompt)
        active_stems.add(stem)
        path = IVR_AUDIO / f'{stem}.wav'
        text = fallback_text(ivr)
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        previous = state.get(stem) if isinstance(state.get(stem), dict) else None

        if path.exists():
            current_hash = file_sha256(path)
            if not previous:
                preserved.append(stem)
                continue
            if current_hash != str(previous.get('file_sha256') or ''):
                # A user recording/upload replaced the auto fallback. Stop managing it.
                state.pop(stem, None)
                preserved.append(stem)
                continue
            if text_hash == str(previous.get('text_sha256') or '') and valid_telephony_wav(path):
                preserved.append(stem)
                continue

        try:
            generate_wav(path, text)
            state[stem] = {
                'sound_id': f'custom/{stem}',
                'text_sha256': text_hash,
                'file_sha256': file_sha256(path),
                'auto_generated': True,
            }
            generated.append(stem)
        except Exception as exc:
            errors.append(f'{stem}: {exc}')

    # Remove only orphaned files that are still byte-for-byte our own generated fallback.
    for stem in list(state):
        if stem in active_stems:
            continue
        meta = state.get(stem)
        path = IVR_AUDIO / f'{stem}.wav'
        try:
            if isinstance(meta, dict) and path.exists():
                expected = str(meta.get('file_sha256') or '')
                if expected and file_sha256(path) == expected:
                    path.unlink()
        except Exception:
            pass
        state.pop(stem, None)

    AUTO_STATE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return {'generated': generated, 'preserved': preserved, 'errors': errors}


if __name__ == '__main__':
    print(f'[IVR] persistent dialplan include: {ensure_include()}')
    result = ensure_fallback_audio()
    for stem in result['generated']:
        print(f'[IVR] fallback PT-PT gerado: custom/{stem}')
    for error in result['errors']:
        print(f'[IVR] AVISO fallback: {error}')
