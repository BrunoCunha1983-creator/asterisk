#!/usr/bin/env python3
import shutil
import subprocess
import time
from pathlib import Path

from usb_detect import usb_ports

CONFIG_1505 = Path('/etc/usb_modeswitch.d/12d1:1505')


def _ids(items):
    return sorted({str(x.get('usb_id') or '').lower() for x in (items or []) if x.get('usb_id')})


def status():
    items = usb_ports()
    ids = _ids(items)
    return {
        'usb_modeswitch_installed': bool(shutil.which('usb_modeswitch')),
        'config_12d1_1505': CONFIG_1505.exists(),
        'huawei_1505_present': '12d1:1505' in ids,
        'usb_ids': ids,
        'devices': items,
    }


def switch_huawei_1505():
    before = status()
    if not before['usb_modeswitch_installed']:
        return {'ok': False, 'output': 'usb_modeswitch não está instalado na imagem do add-on', 'before': before}
    if not before['config_12d1_1505']:
        return {'ok': False, 'output': 'falta /etc/usb_modeswitch.d/12d1:1505', 'before': before}
    if not before['huawei_1505_present']:
        return {'ok': False, 'output': 'Huawei 12d1:1505 não está visível dentro do add-on', 'before': before}

    cmd = ['usb_modeswitch', '-I', '-W', '-c', str(CONFIG_1505)]
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25)
        output = (p.stdout or '')[-12000:]
    except Exception as e:
        return {'ok': False, 'output': str(e), 'before': before}

    try:
        subprocess.run(['udevadm', 'settle'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    except Exception:
        pass
    time.sleep(3)
    after = status()
    new_huawei = [x for x in after['usb_ids'] if x.startswith('12d1:') and x != '12d1:1505']
    switched = (not after['huawei_1505_present']) and bool(new_huawei)
    warning = ''
    if not after['huawei_1505_present'] and not new_huawei:
        warning = ('O 12d1:1505 desapareceu após o mode-switch, mas o novo PID Huawei não ficou visível. '
                   'Se o Proxmox estiver configurado com host=12d1:1505, o dispositivo pode ter sido perdido quando mudou de PID. '
                   'Nesse caso usa passthrough pela porta USB física no Proxmox e volta a tentar.')
    elif after['huawei_1505_present']:
        warning = 'O dispositivo continua em 12d1:1505; o mode-switch não se confirmou.'

    return {
        'ok': bool(switched),
        'command_ok': p.returncode == 0,
        'output': output,
        'before': before,
        'after': after,
        'new_huawei_ids': new_huawei,
        'warning': warning,
    }
