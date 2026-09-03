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
    """Keep configuration persistent while excluding absent hardware from runtime."""
    return [d for d in (configured or []) if isinstance(d, dict) and dongle_is_present(d)]
