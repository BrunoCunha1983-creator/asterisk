#!/usr/bin/env python3
import re
import time


def _int(pattern, text, default=0):
    m = re.search(pattern, text or '', re.I | re.M)
    return int(m.group(1)) if m else default


def _float(value):
    try:
        return float(value)
    except Exception:
        return None


def parse_contacts(text):
    """Parse `pjsip show contacts` into a dict keyed by AoR/endpoint name."""
    contacts = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line.startswith('Contact:'):
            continue
        body = line.split(':', 1)[1].strip()
        parts = body.split()
        if not parts or '/' not in parts[0]:
            continue
        key_uri = parts[0]
        key, uri = key_uri.split('/', 1)
        status = ''
        rtt_ms = None
        for idx, part in enumerate(parts[1:], start=1):
            low = part.lower()
            if low in ('avail', 'available', 'unavail', 'unavailable', 'nonqual', 'unknown'):
                status = part
                if idx + 1 < len(parts):
                    rtt_ms = _float(parts[idx + 1])
                break
        contacts[key] = {
            'uri': uri,
            'status': status or 'unknown',
            'reachable': (status.lower() in ('avail', 'available')) if status else True,
            'rtt_ms': rtt_ms,
            'raw': line,
        }
    return contacts


def parse_dongles(text):
    """Parse a useful subset of `dongle show devices` without relying on exact columns."""
    devices = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(('id ', 'device ', '-----', 'no devices')):
            continue
        if not re.match(r'^[A-Za-z0-9_.-]+\s+', line):
            continue
        parts = line.split()
        name = parts[0]
        if name.lower() in ('device', 'id'):
            continue
        state = parts[2] if len(parts) > 2 else 'unknown'
        rssi = None
        if len(parts) > 3:
            try:
                rssi = int(parts[3])
            except Exception:
                pass
        devices.append({
            'name': name,
            'state': state,
            'connected': state.lower() not in ('notconnected', 'disconnected', 'unknown', 'down'),
            'rssi': rssi,
            'raw': line,
        })
    return devices


def parse_ivr_channels(text):
    """Count live Asterisk channels currently executing inside each IVR context."""
    counts = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or '!' not in line:
            continue
        parts = line.split('!')
        if len(parts) < 2:
            continue
        context = parts[1].strip()
        if not context.startswith('ivr-'):
            continue
        ivr_id = context[4:]
        if ivr_id:
            counts[ivr_id] = counts.get(ivr_id, 0) + 1
    return counts


def _contact_state(enabled, key, contacts):
    contact = contacts.get(key) if key else None
    return {
        'enabled': bool(enabled),
        'user': key,
        'reachable': bool(enabled and contact and contact.get('reachable')),
        'contact': contact.get('uri') if contact else None,
        'status': contact.get('status') if contact else ('disabled' if not enabled else 'unregistered'),
        'rtt_ms': contact.get('rtt_ms') if contact else None,
    }


def build_snapshot(ast, pbx_data):
    """Return a stable JSON-ready snapshot for the Home Assistant integration."""
    version_r = ast('core show version')
    channels_r = ast('core show channels count')
    channels_concise_r = ast('core show channels concise')
    contacts_r = ast('pjsip show contacts')
    dongle_r = ast('dongle show devices')

    version_text = (version_r.get('output') or '').strip()
    channels_text = channels_r.get('output') or ''
    contacts = parse_contacts(contacts_r.get('output') or '')
    dongles = parse_dongles(dongle_r.get('output') or '')
    ivr_channel_counts = parse_ivr_channels(channels_concise_r.get('output') or '')

    extensions = []
    for ext in (pbx_data.get('extensions') or []):
        number = str(ext.get('extension') or '').strip()
        if not number:
            continue
        c = contacts.get(number)
        extensions.append({
            'extension': number,
            'callerid': str(ext.get('callerid') or number),
            'registered': bool(c and c.get('reachable')),
            'contact': c.get('uri') if c else None,
            'status': c.get('status') if c else 'unregistered',
            'rtt_ms': c.get('rtt_ms') if c else None,
        })

    ht = pbx_data.get('ht503') or {}
    fxo_user = str(ht.get('fxo_user') or '').strip()
    fxs_extension = str(ht.get('fxs_extension') or '').strip()
    fxo = _contact_state(bool(ht.get('enabled')), fxo_user, contacts)
    fxs = _contact_state(bool(ht.get('fxs_enabled')), fxs_extension, contacts)
    fxs['extension'] = fxs_extension
    fxs['local_sip_port'] = int(ht.get('fxs_local_sip_port', 5062) or 5062)
    fxo['local_sip_port'] = int(ht.get('local_sip_port', 5064) or 5064)

    # Keep the original top-level FXO fields for backwards compatibility while
    # also exposing explicit nested FXS and FXO objects.
    ht503 = {
        'enabled': fxo['enabled'],
        'user': fxo_user,
        'device_ip': str(ht.get('device_ip') or ''),
        'reachable': fxo['reachable'],
        'contact': fxo['contact'],
        'status': fxo['status'],
        'rtt_ms': fxo['rtt_ms'],
        'fxs_enabled': fxs['enabled'],
        'fxs_extension': fxs_extension,
        'fxs_reachable': fxs['reachable'],
        'fxo': fxo,
        'fxs': fxs,
    }

    sc = pbx_data.get('sipcord') or {}
    sc_contact = contacts.get('sipcord')
    sipcord = {
        'enabled': bool(sc.get('enabled')),
        'server': str(sc.get('server') or ''),
        'port': int(sc.get('port', 5060) or 5060),
        'username': str(sc.get('username') or ''),
        'dial_pattern': str(sc.get('dial_pattern') or ''),
        'reachable': bool(sc.get('enabled') and sc_contact and sc_contact.get('reachable')),
        'contact': sc_contact.get('uri') if sc_contact else None,
        'status': sc_contact.get('status') if sc_contact else ('disabled' if not sc.get('enabled') else 'unknown'),
        'rtt_ms': sc_contact.get('rtt_ms') if sc_contact else None,
    }

    ivrs = []
    for raw in (pbx_data.get('ivrs') or []):
        ivr_id = str(raw.get('id') or '').strip()
        if not ivr_id:
            continue
        active_channels = int(ivr_channel_counts.get(ivr_id, 0))
        ivrs.append({
            'id': ivr_id,
            'name': str(raw.get('name') or ivr_id),
            'extension': str(raw.get('extension') or ''),
            'enabled': bool(raw.get('enabled', True)),
            'prompt': str(raw.get('prompt') or ''),
            'options_count': len(raw.get('options') or []),
            'active_channels': active_channels,
            'active': active_channels > 0,
        })

    registered = sum(1 for e in extensions if e['registered'])
    ivrs_enabled = sum(1 for i in ivrs if i['enabled'])
    ivr_active_channels = sum(i['active_channels'] for i in ivrs)
    return {
        'online': bool(version_r.get('ok')),
        'version': version_text,
        'active_channels': _int(r'(\d+)\s+active channel', channels_text),
        'active_calls': _int(r'(\d+)\s+active call', channels_text),
        'calls_processed': _int(r'(\d+)\s+calls? processed', channels_text),
        'extensions_total': len(extensions),
        'extensions_registered': registered,
        'extensions_unregistered': max(0, len(extensions) - registered),
        'extensions': extensions,
        'ht503': ht503,
        'sipcord': sipcord,
        'ivrs_total': len(ivrs),
        'ivrs_enabled': ivrs_enabled,
        'ivr_active_channels': ivr_active_channels,
        'ivr_in_use': ivr_active_channels > 0,
        'ivrs': ivrs,
        'sip_trunks_total': len(pbx_data.get('sip_trunks') or []),
        'gsm_dongles_total': len(dongles),
        'gsm_dongles_connected': sum(1 for d in dongles if d['connected']),
        'gsm_dongles': dongles,
        'updated_at': int(time.time()),
    }
