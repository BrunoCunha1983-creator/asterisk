#!/usr/bin/env python3
"""Unified GSM gateway API for Home Assistant.

USB/chan_dongle and SIM800C remain separate hardware backends. Home Assistant
talks to one local API and the saved priority decides which backend is tried
first. Automatic fallback is optional.
"""
from urllib.parse import urlparse
import re

from gsm_gateway_ui import augment_index as augment_gsm_gateway_index


GATEWAYS = ('usb_gsm', 'sim800')
DEFAULT_GSM_SHARED = {
    'schema_version': 2,
    'sms_preferred': 'usb_gsm',
    'ussd_preferred': 'usb_gsm',
    'fallback': True,
    'preferred_gateway': 'usb_gsm',
}


def _valid_gateway(value, default='usb_gsm'):
    value = str(value or '').strip().lower()
    return value if value in GATEWAYS else default


def ensure_gsm_shared_state(data):
    if not isinstance(data, dict):
        data = {}
    raw = data.get('gsm_shared')
    if not isinstance(raw, dict):
        raw = {}

    legacy = _valid_gateway(raw.get('preferred_gateway'), 'usb_gsm')
    merged = dict(DEFAULT_GSM_SHARED)
    merged.update(raw)
    merged['sms_preferred'] = _valid_gateway(raw.get('sms_preferred'), legacy)
    merged['ussd_preferred'] = _valid_gateway(raw.get('ussd_preferred'), legacy)
    merged['fallback'] = bool(raw.get('fallback', True))
    merged['schema_version'] = 2
    merged['preferred_gateway'] = merged['sms_preferred']

    changed = merged != raw
    if changed:
        data = dict(data)
        data['gsm_shared'] = merged
    return data, changed


def _result_ok(result):
    if not bool((result or {}).get('ok')):
        return False
    text = str((result or {}).get('output', '') or '').lower()
    failure_markers = (
        'no such command',
        'no such module',
        'not connected',
        'not found',
        'unable to',
        'failed',
        'failure',
        'error',
        'no devices found',
        'not initialized',
    )
    return not any(marker in text for marker in failure_markers)


def _clean_number(value):
    return re.sub(r'[^0-9+]', '', str(value or ''))[:32]


def _clean_ussd(value):
    return re.sub(r'[^0-9*#+]', '', str(value or ''))[:64]


def _clean_message(value):
    text = str(value or '').replace('\x1a', ' ').replace('\r', ' ').replace('\n', ' ')
    # backend.ast() currently invokes a shell. Remove shell expansion characters
    # before the message is passed to the Asterisk CLI.
    for char in ('\\', '"', '$', '`'):
        text = text.replace(char, '')
    return re.sub(r'\s+', ' ', text).strip()[:500]


def _clean_device(value):
    return re.sub(r'[^0-9A-Za-z_-]', '', str(value or ''))[:80]


def _active_usb_devices(pbx):
    out = []
    for item in (pbx.get('gsm_dongles') or []):
        if not isinstance(item, dict):
            continue
        name = _clean_device(item.get('name'))
        if name:
            out.append(name)
    return out


def _order(shared, kind, requested):
    requested = str(requested or 'auto').strip().lower()
    if requested in GATEWAYS:
        return [requested]
    if requested != 'auto':
        raise ValueError('gateway deve ser auto, usb_gsm ou sim800')

    key = 'sms_preferred' if kind == 'sms' else 'ussd_preferred'
    first = _valid_gateway(shared.get(key), 'usb_gsm')
    if not shared.get('fallback', True):
        return [first]
    second = 'sim800' if first == 'usb_gsm' else 'usb_gsm'
    return [first, second]


def install(app):
    """Install normalization, UI controls and local GSM REST actions."""
    if getattr(app, '_gsm_gateway_runtime_installed', False):
        return

    app.server.INDEX = augment_gsm_gateway_index(app.server.INDEX)

    base_normalize = app.server.normalize_pbx

    def normalize_pbx(data):
        data, changed, removed = base_normalize(data)
        data, gsm_changed = ensure_gsm_shared_state(data)
        return data, bool(changed or gsm_changed), removed

    app.server.normalize_pbx = normalize_pbx

    def load_state():
        return app.server.load_pbx_state()

    def usb_sms(pbx, number, message, device=''):
        devices = _active_usb_devices(pbx)
        selected = _clean_device(device)
        if selected and selected not in devices:
            return {
                'ok': False, 'gateway': 'usb_gsm', 'device': selected,
                'output': f'Dongle {selected} não está ativo/configurado',
            }
        if not selected:
            selected = devices[0] if devices else ''
        if not selected:
            return {
                'ok': False, 'gateway': 'usb_gsm', 'device': '',
                'output': 'Nenhum modem USB/GSM ativo está configurado',
            }
        result = dict(app.server.ast(
            f'dongle sms {selected} {number} {message}'
        ) or {})
        result['ok'] = _result_ok(result)
        result['gateway'] = 'usb_gsm'
        result['device'] = selected
        return result

    def usb_ussd(pbx, code, device=''):
        devices = _active_usb_devices(pbx)
        selected = _clean_device(device)
        if selected and selected not in devices:
            return {
                'ok': False, 'gateway': 'usb_gsm', 'device': selected,
                'output': f'Dongle {selected} não está ativo/configurado',
            }
        if not selected:
            selected = devices[0] if devices else ''
        if not selected:
            return {
                'ok': False, 'gateway': 'usb_gsm', 'device': '',
                'output': 'Nenhum modem USB/GSM ativo está configurado',
            }
        result = dict(app.server.ast(
            f'dongle ussd {selected} {code}'
        ) or {})
        result['ok'] = _result_ok(result)
        result['gateway'] = 'usb_gsm'
        result['device'] = selected
        return result

    def sim800_sms(pbx, number, message):
        cfg = pbx.get('sim800c') or {}
        if not isinstance(cfg, dict) or not cfg.get('enabled'):
            return {
                'ok': False, 'gateway': 'sim800', 'device': '',
                'output': 'SIM800C está desativado',
            }
        app.SIM800C.configure(cfg)
        result = dict(app.SIM800C.send_sms(number, message) or {})
        result['gateway'] = 'sim800'
        result['device'] = str(cfg.get('port') or 'SIM800C')
        return result

    def sim800_ussd(pbx, code):
        cfg = pbx.get('sim800c') or {}
        if not isinstance(cfg, dict) or not cfg.get('enabled'):
            return {
                'ok': False, 'gateway': 'sim800', 'device': '',
                'output': 'SIM800C está desativado',
            }
        app.SIM800C.configure(cfg)
        result = dict(app.SIM800C.command(
            f'AT+CUSD=1,"{code}",15', timeout=12
        ) or {})
        result['gateway'] = 'sim800'
        result['device'] = str(cfg.get('port') or 'SIM800C')
        return result

    def route(kind, payload):
        pbx = load_state()
        shared = pbx.get('gsm_shared') or DEFAULT_GSM_SHARED
        requested = str(
            payload.get('gateway') or payload.get('source') or 'auto'
        ).strip().lower()
        device = str(payload.get('device') or '').strip()
        attempts = []

        if kind == 'sms':
            number = _clean_number(payload.get('number') or payload.get('to'))
            message = _clean_message(payload.get('message') or payload.get('text'))
            if not number or not message:
                return {
                    'ok': False,
                    'output': 'Número e mensagem são obrigatórios',
                    'attempts': [],
                }
        else:
            code = _clean_ussd(payload.get('code'))
            if not code:
                return {
                    'ok': False,
                    'output': 'Código USSD é obrigatório',
                    'attempts': [],
                }

        for gateway in _order(shared, kind, requested):
            try:
                if kind == 'sms' and gateway == 'usb_gsm':
                    result = usb_sms(pbx, number, message, device)
                elif kind == 'sms':
                    result = sim800_sms(pbx, number, message)
                elif gateway == 'usb_gsm':
                    result = usb_ussd(pbx, code, device)
                else:
                    result = sim800_ussd(pbx, code)
            except Exception as exc:
                result = {
                    'ok': False,
                    'gateway': gateway,
                    'device': '',
                    'output': str(exc),
                }

            attempts.append({
                'gateway': gateway,
                'device': result.get('device', ''),
                'ok': bool(result.get('ok')),
                'output': str(result.get('output') or ''),
            })
            if result.get('ok'):
                out = dict(result)
                out['attempts'] = attempts
                out['preferred'] = shared.get(
                    'sms_preferred' if kind == 'sms' else 'ussd_preferred',
                    'usb_gsm',
                )
                return out

        return {
            'ok': False,
            'gateway': attempts[-1]['gateway'] if attempts else '',
            'output': attempts[-1]['output'] if attempts else 'Nenhum gateway disponível',
            'attempts': attempts,
        }

    base_handler = app.H

    class GSMGatewayHandler(base_handler):
        def do_GET(self):
            path = urlparse(self.path).path.rstrip('/') or '/'
            if path == '/api/gsm/status':
                if not self._guard_web():
                    return
                try:
                    pbx = load_state()
                    shared = pbx.get('gsm_shared') or DEFAULT_GSM_SHARED
                    cfg = pbx.get('sim800c') or {}
                    app.SIM800C.configure(cfg)
                    sim_status = app.SIM800C.status()
                    self.sendj({
                        'ok': True,
                        'shared': shared,
                        'usb_gsm': {
                            'devices': _active_usb_devices(pbx),
                            'configured': len(pbx.get('gsm_dongles') or []),
                        },
                        'sim800': {
                            'enabled': bool(cfg.get('enabled')),
                            'connected': bool(sim_status.get('connected')),
                            'port': str(cfg.get('port') or ''),
                            'registration': sim_status.get('registration', 'unknown'),
                            'operator': sim_status.get('operator', ''),
                        },
                    })
                except Exception as exc:
                    self.sendj({'ok': False, 'error': str(exc)}, 500)
                return
            super().do_GET()

        def do_POST(self):
            path = urlparse(self.path).path.rstrip('/') or '/'
            if path not in (
                '/api/gsm/sms',
                '/api/gsm/ussd',
                '/api/gsm/priority',
            ):
                return super().do_POST()
            if not self._guard_web():
                return

            payload = self.body()
            if not isinstance(payload, dict):
                self.sendj({'ok': False, 'error': 'JSON object required'}, 400)
                return

            try:
                if path == '/api/gsm/sms':
                    result = route('sms', payload)
                    self.sendj(result, 200 if result.get('ok') else 400)
                    return

                if path == '/api/gsm/ussd':
                    result = route('ussd', payload)
                    self.sendj(result, 200 if result.get('ok') else 400)
                    return

                pbx = load_state()
                shared = dict(pbx.get('gsm_shared') or DEFAULT_GSM_SHARED)
                sms = payload.get('sms_preferred', payload.get('sms'))
                ussd = payload.get('ussd_preferred', payload.get('ussd'))
                if sms is not None:
                    sms_value = _valid_gateway(sms, '')
                    if not sms_value:
                        raise ValueError('sms_preferred inválido')
                    shared['sms_preferred'] = sms_value
                if ussd is not None:
                    ussd_value = _valid_gateway(ussd, '')
                    if not ussd_value:
                        raise ValueError('ussd_preferred inválido')
                    shared['ussd_preferred'] = ussd_value
                if 'fallback' in payload:
                    shared['fallback'] = bool(payload.get('fallback'))
                shared['schema_version'] = 2
                shared['preferred_gateway'] = shared.get(
                    'sms_preferred', 'usb_gsm'
                )
                pbx['gsm_shared'] = shared
                app.server.save_json(app.server.PBX, pbx)
                self.sendj({'ok': True, 'shared': shared})
            except ValueError as exc:
                self.sendj({'ok': False, 'error': str(exc)}, 400)
            except Exception as exc:
                self.sendj({'ok': False, 'error': str(exc)}, 500)

    app.H = GSMGatewayHandler
    app._gsm_gateway_runtime_installed = True
