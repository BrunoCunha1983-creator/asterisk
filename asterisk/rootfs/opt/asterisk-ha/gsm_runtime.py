#!/usr/bin/env python3
import glob
from pathlib import Path


def device_node_exists(value):
    """Return True only for an existing absolute /dev path.

    Stable /dev/serial/by-id and /dev/serial/by-path symlinks are intentionally
    accepted; Path.exists() follows the symlink to the live tty node.
    """
    raw = str(value or '').strip()
    if not raw or not raw.startswith('/dev/'):
        return False
    try:
        return Path(raw).exists()
    except Exception:
        return False


def _resolved_device(value):
    raw = str(value or '').strip()
    if not raw.startswith('/dev/'):
        return ''
    try:
        return str(Path(raw).resolve())
    except Exception:
        return ''


def _serial_aliases_for(value):
    """Return stable aliases that currently point to the same serial node."""
    real = _resolved_device(value)
    if not real:
        return []
    aliases = []
    for link in glob.glob('/dev/serial/by-id/*') + glob.glob('/dev/serial/by-path/*'):
        try:
            if str(Path(link).resolve()) == real:
                aliases.append(link)
        except Exception:
            continue
    # Prefer hardware identity over topology/path identity.
    return sorted(set(aliases), key=lambda x: (0 if x.startswith('/dev/serial/by-id/') else 1, x))


def stable_device_path(value):
    """Convert a volatile ttyUSB/ttyACM path to a persistent serial alias.

    If no stable alias is available, preserve the exact value supplied by the
    user rather than guessing another tty port.
    """
    raw = str(value or '').strip()
    if not raw:
        return ''

    aliases = _serial_aliases_for(raw)
    if aliases:
        return aliases[0]
    return raw


def normalize_dongle_binding(dongle):
    """Preserve manual port selection and optionally pin it to physical IDs."""
    if not isinstance(dongle, dict):
        return dongle
    out = dict(dongle)
    locked = bool(out.get('lock_ports', True))
    out['lock_ports'] = locked
    if locked:
        out['audio'] = stable_device_path(out.get('audio'))
        out['data'] = stable_device_path(out.get('data'))
    return out


def dongle_is_present(dongle):
    """A chan_dongle modem needs both configured serial device nodes."""
    if not isinstance(dongle, dict):
        return False
    return device_node_exists(dongle.get('audio')) and device_node_exists(dongle.get('data'))


def active_dongles(configured):
    """Exclude absent hardware from Asterisk without changing its selected ports."""
    return [
        normalize_dongle_binding(d)
        for d in (configured or [])
        if isinstance(d, dict) and dongle_is_present(normalize_dongle_binding(d))
    ]


def _key(item):
    if not isinstance(item, dict):
        return ('', '', '')
    return (
        str(item.get('name') or '').strip(),
        str(item.get('audio') or '').strip(),
        str(item.get('data') or '').strip(),
    )


def normalize_gsm_state(data):
    """Keep GSM configuration persistent and pin serial ports to stable IDs.

    The Linux ttyUSB number is not an identity: unplugging another converter or
    rebooting can renumber ttyUSB0/1/2. With lock_ports enabled (the default),
    any currently resolvable tty path is migrated to /dev/serial/by-id (or,
    when unavailable, by-path). The selected interface therefore remains the
    same physical Huawei interface after renumbering.

    Absent configurations are still moved to gsm_profiles so they are preserved
    without pretending the hardware is currently attached. When their stable
    aliases reappear they are restored automatically.
    """
    if not isinstance(data, dict):
        return data, False

    current = [
        normalize_dongle_binding(d)
        for d in (data.get('gsm_dongles') or [])
        if isinstance(d, dict)
    ]
    saved = [
        normalize_dongle_binding(d)
        for d in (data.get('gsm_profiles') or [])
        if isinstance(d, dict)
    ]

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

    changed = (
        active != (data.get('gsm_dongles') or [])
        or profiles != (data.get('gsm_profiles') or [])
        or 'gsm_profiles' not in data
    )
    if not changed:
        return data, False

    out = dict(data)
    out['gsm_dongles'] = active
    out['gsm_profiles'] = profiles
    return out, True
