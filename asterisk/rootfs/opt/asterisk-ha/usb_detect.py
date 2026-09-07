#!/usr/bin/env python3
import glob
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


def _run(args, timeout=5):
    try:
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode == 0, p.stdout or ''
    except Exception as e:
        return False, str(e)


def _udev_props(dev):
    ok, output = _run(['udevadm', 'info', '--query=property', f'--name={dev}'], 3)
    props = {}
    if not ok:
        return props
    wanted = {
        'ID_VENDOR', 'ID_MODEL', 'ID_SERIAL_SHORT', 'ID_USB_INTERFACE_NUM',
        'ID_VENDOR_ID', 'ID_MODEL_ID', 'ID_PATH', 'DEVPATH', 'DEVNAME',
    }
    for line in output.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in wanted:
            props[key.lower()] = value
    return props


def _supervisor_hardware():
    """Read HAOS host hardware through the Supervisor API when available."""
    token = os.environ.get('SUPERVISOR_TOKEN', '').strip()
    if not token:
        return [], 'SUPERVISOR_TOKEN unavailable'
    req = Request(
        'http://supervisor/hardware/info',
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
    )
    try:
        with urlopen(req, timeout=4) as response:
            payload = json.loads(response.read().decode(errors='replace'))
        data = payload.get('data') or {}
        serial = []
        raw_serial = data.get('serial') or []
        if isinstance(raw_serial, list):
            serial.extend(str(x) for x in raw_serial if str(x).startswith('/dev/'))

        # Be tolerant of richer/newer hardware models which expose device maps.
        devices = data.get('devices') or []
        if isinstance(devices, dict):
            devices = list(devices.values())
        if isinstance(devices, list):
            for item in devices:
                if not isinstance(item, dict):
                    continue
                subsystem = str(item.get('subsystem') or '').lower()
                path = str(item.get('dev_path') or item.get('path') or item.get('device') or '')
                if path.startswith('/dev/') and (subsystem in ('tty', 'serial') or '/tty' in path):
                    serial.append(path)
        return sorted(set(serial)), ''
    except Exception as e:
        return [], str(e)


def _by_id_map():
    result = {}
    for link in glob.glob('/dev/serial/by-id/*') + glob.glob('/dev/serial/by-path/*'):
        try:
            real = str(Path(link).resolve())
        except Exception:
            continue
        if real.startswith('/dev/'):
            result.setdefault(real, []).append(link)
    return result


def _raw_usb():
    ok, output = _run(['lsusb'], 4)
    devices = []
    if not ok:
        return devices, output.strip()
    rx = re.compile(r'^Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*)$')
    for line in output.splitlines():
        m = rx.match(line.strip())
        if not m:
            continue
        vendor, product = m.group(3).lower(), m.group(4).lower()
        devices.append({
            'device': '',
            'kind': 'raw-usb',
            'raw_usb': True,
            'accessible': True,
            'source': 'lsusb',
            'bus': m.group(1),
            'usb_device': m.group(2),
            'id_vendor_id': vendor,
            'id_model_id': product,
            'usb_id': f'{vendor}:{product}',
            'description': m.group(5).strip(),
            'id_vendor': (m.group(5).strip().split(' ', 1)[0] if m.group(5).strip() else ''),
            'id_model': m.group(5).strip(),
        })
    return devices, ''


def usb_ports():
    """Return serial devices plus raw USB inventory visible to the HA add-on.

    Detection combines the add-on /dev namespace, /dev/serial symlinks, host
    serial paths reported by Home Assistant Supervisor, udev metadata and raw
    /dev/bus/usb enumeration. This makes the UI useful even when HAOS sees a USB
    device but its tty node has not yet been mapped into the add-on.
    """
    by_id = _by_id_map()
    local = set(glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*'))
    supervisor, supervisor_error = _supervisor_hardware()
    candidates = sorted(local | set(supervisor) | set(by_id.keys()))
    out = []

    for dev in candidates:
        if not (dev.startswith('/dev/ttyUSB') or dev.startswith('/dev/ttyACM')):
            continue
        accessible = Path(dev).exists()
        props = _udev_props(dev) if accessible else {}
        item = {
            'device': dev,
            'kind': 'serial',
            'raw_usb': False,
            'accessible': bool(accessible),
            'source': 'local+supervisor' if dev in local and dev in supervisor else ('local' if dev in local else 'supervisor'),
            'by_id': sorted(by_id.get(dev, [])),
        }
        item.update(props)
        vid = str(item.get('id_vendor_id') or '').lower()
        pid = str(item.get('id_model_id') or '').lower()
        if vid and pid:
            item['usb_id'] = f'{vid}:{pid}'
        if not accessible:
            item['note'] = 'HAOS/Supervisor vê esta porta, mas ela ainda não está acessível dentro do add-on. Reinicia o add-on depois do passthrough USB.'
        out.append(item)

    raw, raw_error = _raw_usb()
    serial_ids = {str(x.get('usb_id') or '').lower() for x in out if x.get('usb_id')}
    for item in raw:
        usb_id = str(item.get('usb_id') or '').lower()
        item['has_serial_node'] = usb_id in serial_ids
        if usb_id == '1a86:7523':
            item['role_hint'] = 'SIM800C / adaptador CH340'
            if not item['has_serial_node']:
                item['note'] = 'CH340 visível por USB, mas ainda sem /dev/ttyUSB acessível ao add-on.'
        elif usb_id == '12d1:1505':
            item['role_hint'] = 'Huawei GSM em modo USB inicial/storage'
            item['note'] = 'Huawei 12d1:1505 está visível, mas normalmente ainda não expõe as portas tty do modem antes do mode switch.'
        elif usb_id.startswith('12d1:'):
            item['role_hint'] = 'Huawei GSM'
        out.append(item)

    meta = {
        'supervisor_error': supervisor_error,
        'lsusb_error': raw_error,
        'serial_count': sum(1 for x in out if x.get('kind') == 'serial'),
        'raw_usb_count': sum(1 for x in out if x.get('kind') == 'raw-usb'),
    }
    # Existing callers expect an array. Attach diagnostics to each raw entry only
    # when something failed, preserving backward compatibility with the UI.
    if supervisor_error or raw_error:
        out.append({
            'device': '', 'kind': 'diagnostic', 'raw_usb': False, 'accessible': False,
            'source': 'detector', 'diagnostic': meta,
        })
    return out
