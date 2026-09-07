#!/usr/bin/env python3
import os
import re
import threading
import time
from collections import deque

try:
    import serial
except Exception:
    serial = None


DEFAULT_SIM800C = {
    'enabled': False,
    'port': '/dev/ttyUSB0',
    'baudrate': 115200,
    'outbound_prefix': '7',
    'incoming_target': '800',
    'audio_mode': 'none',
}


def normalize_sim800c_state(data):
    if not isinstance(data, dict):
        data = {}
    raw = data.get('sim800c')
    if not isinstance(raw, dict):
        raw = {}
        data['sim800c'] = raw
    changed = False
    merged = dict(DEFAULT_SIM800C)
    merged.update(raw)
    merged['enabled'] = bool(merged.get('enabled', False))
    merged['port'] = str(merged.get('port') or '/dev/ttyUSB0').strip()
    try:
        merged['baudrate'] = int(merged.get('baudrate', 115200) or 115200)
    except Exception:
        merged['baudrate'] = 115200
    merged['outbound_prefix'] = re.sub(r'[^0-9*#]', '', str(merged.get('outbound_prefix') or '7')) or '7'
    merged['incoming_target'] = re.sub(r'[^0-9A-Za-z_*#-]', '', str(merged.get('incoming_target') or '800')) or '800'
    merged['audio_mode'] = 'none'
    if merged != raw:
        data['sim800c'] = merged
        changed = True
    return data, changed


class SIM800CManager:
    """One SIM800C serial-control runtime.

    This manages AT commands, SMS and call signalling. SIM800C UART does not
    carry call audio, therefore voice media stays explicitly unavailable until
    a physical audio path is added to the hardware.
    """

    def __init__(self):
        self._cfg = dict(DEFAULT_SIM800C)
        self._ser = None
        self._lock = threading.RLock()
        self._cmd_lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._responses = deque(maxlen=500)
        self._events = deque(maxlen=100)
        self._sms = deque(maxlen=50)
        self._reader = None
        self._poller = None
        self._stop = threading.Event()
        self._pending_sms_header = None
        self._status = {
            'enabled': False,
            'connected': False,
            'port': '',
            'baudrate': 115200,
            'sim': 'unknown',
            'registration': 'unknown',
            'operator': '',
            'rssi': None,
            'signal_dbm': None,
            'imei': '',
            'call_state': 'idle',
            'caller': '',
            'last_error': '',
            'audio_available': False,
            'audio_note': 'UART/USB-TTL transporta AT/SMS/sinalização, não o áudio da chamada.',
        }

    def configure(self, cfg):
        cfg = dict(DEFAULT_SIM800C, **(cfg or {}))
        cfg['enabled'] = bool(cfg.get('enabled', False))
        cfg['port'] = str(cfg.get('port') or '/dev/ttyUSB0')
        cfg['baudrate'] = int(cfg.get('baudrate', 115200) or 115200)
        with self._lock:
            changed = any(self._cfg.get(k) != cfg.get(k) for k in ('enabled', 'port', 'baudrate'))
            self._cfg = cfg
            self._status['enabled'] = cfg['enabled']
            self._status['port'] = cfg['port']
            self._status['baudrate'] = cfg['baudrate']
        if not cfg['enabled']:
            self.close()
            return
        if changed or not self._is_open():
            self._open()
        self._ensure_threads()

    def _is_open(self):
        with self._lock:
            return bool(self._ser is not None and getattr(self._ser, 'is_open', False))

    def _open(self):
        self.close()
        cfg = dict(self._cfg)
        if serial is None:
            self._set_error('python3-serial não instalado')
            return False
        if not os.path.exists(cfg['port']):
            self._set_error(f'porta série não existe: {cfg["port"]}')
            return False
        try:
            ser = serial.Serial(
                cfg['port'], cfg['baudrate'], timeout=0.25, write_timeout=2,
                rtscts=False, dsrdtr=False, xonxoff=False,
            )
            with self._lock:
                self._ser = ser
                self._status['connected'] = True
                self._status['last_error'] = ''
                self._responses.clear()
            self._ensure_threads()
            time.sleep(0.15)
            return True
        except Exception as e:
            self._set_error(str(e))
            return False

    def close(self):
        with self._lock:
            ser = self._ser
            self._ser = None
            self._status['connected'] = False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _ensure_threads(self):
        if self._reader is None or not self._reader.is_alive():
            self._reader = threading.Thread(target=self._reader_loop, name='sim800c-reader', daemon=True)
            self._reader.start()
        if self._poller is None or not self._poller.is_alive():
            self._poller = threading.Thread(target=self._poll_loop, name='sim800c-poller', daemon=True)
            self._poller.start()

    def _set_error(self, text):
        with self._lock:
            self._status['last_error'] = str(text)
            self._status['connected'] = self._is_open()

    def _reader_loop(self):
        while not self._stop.is_set():
            with self._lock:
                ser = self._ser
            if ser is None or not getattr(ser, 'is_open', False):
                time.sleep(0.3)
                continue
            try:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode(errors='replace').strip('\r\n ')
                if not line:
                    continue
                self._handle_line(line)
            except Exception as e:
                self._set_error(str(e))
                self.close()
                time.sleep(0.5)

    def _handle_line(self, line):
        now = time.time()
        with self._cv:
            self._events.appendleft({'time': now, 'line': line})
            if self._pending_sms_header is not None:
                hdr = self._pending_sms_header
                self._pending_sms_header = None
                m = re.search(r'\+CMT:\s*"([^"]*)"(?:,"[^"]*")?(?:,"([^"]*)")?', hdr)
                self._sms.appendleft({
                    'time': now,
                    'from': m.group(1) if m else '',
                    'stamp': m.group(2) if (m and m.lastindex and m.lastindex >= 2) else '',
                    'text': line,
                })
                self._cv.notify_all()
                return
            if line.startswith('+CMT:'):
                self._pending_sms_header = line
            elif line == 'RING':
                self._status['call_state'] = 'ringing'
            elif line.startswith('+CLIP:'):
                m = re.search(r'"([^"]+)"', line)
                self._status['caller'] = m.group(1) if m else ''
            elif line in ('NO CARRIER', 'BUSY', 'NO ANSWER'):
                self._status['call_state'] = 'idle'
            elif line == 'CONNECT' or line.startswith('VOICE CALL: BEGIN'):
                self._status['call_state'] = 'active'
            self._responses.append(line)
            self._cv.notify_all()

    def _write(self, payload):
        with self._lock:
            ser = self._ser
        if ser is None or not getattr(ser, 'is_open', False):
            if not self._open():
                raise RuntimeError(self._status.get('last_error') or 'SIM800C não ligado')
            with self._lock:
                ser = self._ser
        ser.write(payload)
        ser.flush()

    def command(self, command, timeout=4):
        with self._cmd_lock:
            with self._cv:
                self._responses.clear()
            self._write((str(command).strip() + '\r').encode())
            deadline = time.monotonic() + timeout
            lines = []
            while time.monotonic() < deadline:
                with self._cv:
                    if not self._responses:
                        self._cv.wait(timeout=min(0.25, max(0.0, deadline - time.monotonic())))
                    while self._responses:
                        line = self._responses.popleft()
                        lines.append(line)
                        if line == 'OK':
                            return {'ok': True, 'lines': lines, 'output': '\n'.join(lines)}
                        if line == 'ERROR' or line.startswith('+CME ERROR') or line.startswith('+CMS ERROR'):
                            return {'ok': False, 'lines': lines, 'output': '\n'.join(lines)}
            return {'ok': False, 'lines': lines, 'output': '\n'.join(lines) or 'timeout'}

    def initialize(self):
        results = []
        for cmd in ('AT', 'ATE0', 'AT+CMEE=2', 'AT+CLIP=1', 'AT+CMGF=1', 'AT+CNMI=2,2,0,0,0'):
            results.append((cmd, self.command(cmd)))
        self.refresh()
        return {'ok': all(r['ok'] for _, r in results), 'commands': results, 'status': self.status()}

    def refresh(self):
        queries = {
            'sim': 'AT+CPIN?',
            'registration': 'AT+CREG?',
            'signal': 'AT+CSQ',
            'operator': 'AT+COPS?',
            'imei': 'AT+GSN',
        }
        out = {}
        for key, cmd in queries.items():
            try:
                out[key] = self.command(cmd, timeout=3)
            except Exception as e:
                out[key] = {'ok': False, 'output': str(e), 'lines': []}
        with self._lock:
            sim_text = out['sim'].get('output', '')
            m = re.search(r'\+CPIN:\s*([^\r\n]+)', sim_text)
            if m:
                self._status['sim'] = m.group(1).strip()
            reg_text = out['registration'].get('output', '')
            m = re.search(r'\+CREG:\s*\d+\s*,\s*(\d+)', reg_text)
            if m:
                code = int(m.group(1))
                self._status['registration'] = {
                    0: 'not-registered', 1: 'home', 2: 'searching', 3: 'denied', 4: 'unknown', 5: 'roaming'
                }.get(code, str(code))
            sig_text = out['signal'].get('output', '')
            m = re.search(r'\+CSQ:\s*(\d+)\s*,', sig_text)
            if m:
                rssi = int(m.group(1))
                self._status['rssi'] = None if rssi == 99 else rssi
                self._status['signal_dbm'] = None if rssi == 99 else -113 + (2 * rssi)
            op_text = out['operator'].get('output', '')
            m = re.search(r'\+COPS:.*?"([^"]+)"', op_text)
            if m:
                self._status['operator'] = m.group(1)
            imei_lines = [x for x in out['imei'].get('lines', []) if re.fullmatch(r'\d{14,17}', x)]
            if imei_lines:
                self._status['imei'] = imei_lines[0]
        return self.status()

    def _poll_loop(self):
        while not self._stop.is_set():
            if self._cfg.get('enabled') and self._is_open():
                try:
                    self.refresh()
                except Exception:
                    pass
            self._stop.wait(15)

    def dial(self, number):
        number = re.sub(r'[^0-9+#*]', '', str(number or ''))
        if not number:
            return {'ok': False, 'output': 'número inválido'}
        result = self.command(f'ATD{number};', timeout=5)
        if result['ok']:
            with self._lock:
                self._status['call_state'] = 'dialing'
        result['audio_available'] = False
        result['warning'] = 'Chamada GSM iniciada, mas esta placa sem caminho de áudio não pode ainda transportar voz para o Asterisk.'
        return result

    def answer(self):
        result = self.command('ATA', timeout=5)
        if result['ok']:
            with self._lock:
                self._status['call_state'] = 'active'
        result['audio_available'] = False
        return result

    def hangup(self):
        result = self.command('ATH', timeout=5)
        with self._lock:
            self._status['call_state'] = 'idle'
        return result

    def send_sms(self, number, text):
        number = re.sub(r'[^0-9+]', '', str(number or ''))
        text = str(text or '').replace('\x1a', '').strip()
        if not number or not text:
            return {'ok': False, 'output': 'número e mensagem são obrigatórios'}
        prep = self.command('AT+CMGF=1')
        if not prep.get('ok'):
            return prep
        with self._cmd_lock:
            with self._cv:
                self._responses.clear()
            self._write((f'AT+CMGS="{number}"\r').encode())
            time.sleep(0.6)
            self._write(text.encode(errors='replace') + b'\x1a')
            deadline = time.monotonic() + 20
            lines = []
            while time.monotonic() < deadline:
                with self._cv:
                    if not self._responses:
                        self._cv.wait(timeout=0.5)
                    while self._responses:
                        line = self._responses.popleft()
                        lines.append(line)
                        if line == 'OK':
                            return {'ok': True, 'output': '\n'.join(lines), 'lines': lines}
                        if line == 'ERROR' or line.startswith('+CMS ERROR'):
                            return {'ok': False, 'output': '\n'.join(lines), 'lines': lines}
            return {'ok': False, 'output': '\n'.join(lines) or 'timeout', 'lines': lines}

    def status(self):
        with self._lock:
            out = dict(self._status)
            out['connected'] = self._is_open()
            out['recent_sms'] = list(self._sms)[:20]
            out['recent_events'] = list(self._events)[:30]
            out['config'] = dict(self._cfg)
            return out


SIM800C = SIM800CManager()
