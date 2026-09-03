#!/usr/bin/env python3
from pathlib import Path


def device_node_exists(value):
    """Return True only for an existing absolute /dev path."""
    raw = str(value or '').strip()
    if not raw or not raw.startswith('/dev/'):
        return False
    try:
        return Path(raw).exists()
    except Exception:
        return False


def dongle_is_present(dongle):
    """A chan_dongle modem needs both configured serial device nodes."""
    if not isinstance(dongle, dict):
        return False
    return device_node_exists(dongle.get('audio')) and device_node_exists(dongle.get('data'))


def active_dongles(configured):
    """Exclude absent hardware from the Asterisk runtime."""
    return [d for d in (configured or []) if isinstance(d, dict) and dongle_is_present(d)]


def _key(item):
    if not isinstance(item, dict):
        return ('', '', '')
    return (
        str(item.get('name') or '').strip(),
        str(item.get('audio') or '').strip(),
        str(item.get('data') or '').strip(),
    )


def normalize_gsm_state(data):
    """Keep only physically available modems in gsm_dongles.

    Absent configurations are moved to gsm_profiles so they are preserved but
    no longer look like active/configured hardware. If the configured /dev
    nodes later reappear, the profile is restored automatically.
    """
    if not isinstance(data, dict):
        return data, False

    current = [d for d in (data.get('gsm_dongles') or []) if isinstance(d, dict)]
    saved = [d for d in (data.get('gsm_profiles') or []) if isinstance(d, dict)]
    combined = []
    seen = set()
    for item in current + saved:
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        combined.append(dict(item))

    active = []
    profiles = []
    for item in combined:
        if dongle_is_present(item):
            active.append(item)
        else:
            profiles.append(item)

    changed = active != current or profiles != saved or 'gsm_profiles' not in data
    if not changed:
        return data, False

    out = dict(data)
    out['gsm_dongles'] = active
    out['gsm_profiles'] = profiles
    return out, True
