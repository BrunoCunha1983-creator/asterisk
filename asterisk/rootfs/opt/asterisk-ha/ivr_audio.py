#!/usr/bin/env python3
from __future__ import annotations

import audioop
import base64
import io
import re
import time
import wave
from pathlib import Path

RECORDINGS = Path('/share/asterisk-ivr')
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
TARGET_RATE = 8000
TARGET_WIDTH = 2


def safe_stem(value: str, default: str = 'ivr-prompt') -> str:
    value = str(value or '').strip()
    if value.startswith('custom/'):
        value = value[7:]
    if value.lower().endswith('.wav'):
        value = value[:-4]
    value = re.sub(r'[^0-9A-Za-z_-]', '-', value).strip('-_').lower()
    return value or default


def managed_sound_id(ivr_id: str) -> str:
    return f'custom/ivr-{safe_stem(ivr_id, "main")}'


def sound_to_stem(sound_id: str, fallback: str = 'ivr-prompt') -> str:
    sound_id = str(sound_id or '').strip()
    if sound_id.startswith('custom/'):
        return safe_stem(sound_id[7:], fallback)
    return safe_stem(fallback, 'ivr-prompt')


def ensure_storage() -> Path:
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    return RECORDINGS


def _decode_base64(value: str) -> bytes:
    value = str(value or '').strip()
    if ',' in value and value.lower().startswith('data:'):
        value = value.split(',', 1)[1]
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError('Ficheiro WAV inválido: base64 incorreto') from exc
    if not raw:
        raise ValueError('Ficheiro WAV vazio')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('Ficheiro WAV demasiado grande (máximo 15 MB)')
    return raw


def normalize_wav(raw: bytes) -> tuple[bytes, dict]:
    """Convert a normal PCM WAV to Asterisk-friendly mono 16-bit 8 kHz WAV."""
    if len(raw) < 12 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        raise ValueError('O ficheiro não é um WAV RIFF válido')

    try:
        with wave.open(io.BytesIO(raw), 'rb') as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames_count = source.getnframes()
            comptype = source.getcomptype()
            frames = source.readframes(frames_count)
    except Exception as exc:
        raise ValueError('Não foi possível ler o WAV') from exc

    if comptype != 'NONE':
        raise ValueError('O upload deve ser WAV PCM sem compressão')
    if channels not in (1, 2):
        raise ValueError('O WAV deve ter 1 ou 2 canais')
    if width not in (1, 2, 3, 4):
        raise ValueError('Profundidade PCM WAV não suportada')
    if rate < 4000 or rate > 192000:
        raise ValueError('Frequência WAV inválida')

    original_seconds = (frames_count / rate) if rate else 0.0
    if original_seconds > 600:
        raise ValueError('A gravação não pode exceder 10 minutos')

    # WAV 8-bit PCM is unsigned; audioop works with signed samples.
    if width == 1:
        frames = audioop.bias(frames, 1, -128)

    if channels == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)
        channels = 1

    if width != TARGET_WIDTH:
        frames = audioop.lin2lin(frames, width, TARGET_WIDTH)
        width = TARGET_WIDTH

    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, width, 1, rate, TARGET_RATE, None)
        rate = TARGET_RATE

    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(TARGET_WIDTH)
        target.setframerate(TARGET_RATE)
        target.writeframes(frames)

    return output.getvalue(), {
        'duration_s': round(original_seconds, 2),
        'sample_rate': TARGET_RATE,
        'channels': 1,
        'sample_width_bits': TARGET_WIDTH * 8,
    }


def save_upload(name: str, data_base64: str) -> dict:
    ensure_storage()
    stem = safe_stem(name)
    raw = _decode_base64(data_base64)
    normalized, info = normalize_wav(raw)
    path = RECORDINGS / f'{stem}.wav'
    tmp = RECORDINGS / f'.{stem}.{int(time.time() * 1000)}.tmp'
    tmp.write_bytes(normalized)
    tmp.replace(path)
    return recording_info(path, info)


def recording_info(path: Path, known: dict | None = None) -> dict:
    known = dict(known or {})
    duration_s = known.get('duration_s')
    sample_rate = known.get('sample_rate')
    channels = known.get('channels')
    width_bits = known.get('sample_width_bits')
    try:
        with wave.open(str(path), 'rb') as wav:
            rate = wav.getframerate()
            frames = wav.getnframes()
            duration_s = round(frames / rate, 2) if rate else None
            sample_rate = rate
            channels = wav.getnchannels()
            width_bits = wav.getsampwidth() * 8
    except Exception:
        pass
    return {
        'name': path.stem,
        'filename': path.name,
        'sound_id': f'custom/{path.stem}',
        'size': path.stat().st_size if path.exists() else 0,
        'duration_s': duration_s,
        'sample_rate': sample_rate,
        'channels': channels,
        'sample_width_bits': width_bits,
        'modified': int(path.stat().st_mtime) if path.exists() else None,
    }


def list_recordings() -> list[dict]:
    ensure_storage()
    return [recording_info(path) for path in sorted(RECORDINGS.glob('*.wav')) if path.is_file()]


def get_recording(name: str) -> tuple[Path, bytes]:
    ensure_storage()
    stem = safe_stem(name)
    path = RECORDINGS / f'{stem}.wav'
    if not path.is_file():
        raise FileNotFoundError(stem)
    return path, path.read_bytes()


def delete_recording(name: str) -> bool:
    ensure_storage()
    stem = safe_stem(name)
    path = RECORDINGS / f'{stem}.wav'
    if not path.exists():
        return False
    path.unlink()
    return True
