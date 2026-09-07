#!/usr/bin/env python3
import json
import re
import socket
from pathlib import Path

SECRETS = Path('/config/state/secrets.json')
OPTIONS = Path('/data/options.json')


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _clean_key(value):
    return re.sub(r'[^0-9A-Za-z_-]', '', str(value or ''))[:64]


def _clean_value(value):
    return re.sub(r'[\r\n]+', ' ', str(value if value is not None else ''))[:1000]


class LocalAMI:
    """Small AMI client used internally by the SIM800C gateway.

    It reuses the add-on's generated AMI account from /config/state/secrets.json.
    The password is never returned by status/API responses.
    """

    def settings(self):
        sec = _load_json(SECRETS, {})
        opt = _load_json(OPTIONS, {})
        return {
            'host': '127.0.0.1',
            'port': int(opt.get('ami_port', 5038) or 5038),
            'username': str(sec.get('ami_user', 'homeassistant') or 'homeassistant'),
            'password': str(sec.get('ami_password', '') or ''),
        }

    @staticmethod
    def _recv_frame(sock, timeout=3.0):
        sock.settimeout(timeout)
        data = bytearray()
        while b'\r\n\r\n' not in data and len(data) < 1024 * 1024:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        return data.decode(errors='replace')

    @staticmethod
    def _send_action(sock, fields):
        payload = ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n'
        sock.sendall(payload.encode())

    def action(self, action, fields=None):
        cfg = self.settings()
        if not cfg['password']:
            return {'ok': False, 'error': 'AMI password not initialized', 'host': cfg['host'], 'port': cfg['port'], 'username': cfg['username']}
        try:
            with socket.create_connection((cfg['host'], cfg['port']), timeout=3) as sock:
                banner = self._recv_frame(sock)
                self._send_action(sock, {
                    'Action': 'Login',
                    'Username': cfg['username'],
                    'Secret': cfg['password'],
                    'Events': 'off',
                })
                login = self._recv_frame(sock)
                if 'Response: Success' not in login:
                    return {'ok': False, 'error': 'AMI login failed', 'response': login[-2000:], 'host': cfg['host'], 'port': cfg['port'], 'username': cfg['username']}
                payload = {'Action': str(action)}
                for key, value in (fields or {}).items():
                    key = _clean_key(key)
                    if key:
                        payload[key] = _clean_value(value)
                self._send_action(sock, payload)
                response = self._recv_frame(sock)
                try:
                    self._send_action(sock, {'Action': 'Logoff'})
                except Exception:
                    pass
                ok = 'Response: Success' in response or str(action).lower() == 'userevent'
                return {
                    'ok': bool(ok),
                    'response': response[-4000:],
                    'banner': banner.strip()[:200],
                    'host': cfg['host'],
                    'port': cfg['port'],
                    'username': cfg['username'],
                }
        except Exception as e:
            return {'ok': False, 'error': str(e), 'host': cfg['host'], 'port': cfg['port'], 'username': cfg['username']}

    def status(self):
        result = self.action('Ping')
        return {
            'enabled': True,
            'connected': bool(result.get('ok')),
            'host': result.get('host', '127.0.0.1'),
            'port': result.get('port', 5038),
            'username': result.get('username', 'homeassistant'),
            'error': result.get('error', ''),
            'response': result.get('response', ''),
            'password_exposed': False,
        }

    def user_event(self, name, fields=None):
        payload = {'UserEvent': _clean_key(name) or 'SIM800C'}
        payload.update(fields or {})
        return self.action('UserEvent', payload)


SIM800C_AMI = LocalAMI()
