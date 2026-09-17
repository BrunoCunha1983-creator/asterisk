#!/usr/bin/env python3
import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SECRETS = Path('/config/state/secrets.json')
OPTIONS = Path('/data/options.json')


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


class AsteriskARI:
    """Local authenticated health probe for Asterisk REST Interface."""

    def settings(self):
        sec = _load_json(SECRETS, {})
        opt = _load_json(OPTIONS, {})
        return {
            'host': '127.0.0.1',
            'port': int(opt.get('ari_port', 8088) or 8088),
            'username': str(sec.get('ari_user', 'homeassistant') or 'homeassistant'),
            'password': str(sec.get('ari_password', '') or ''),
        }

    def ping(self):
        cfg = self.settings()
        base = {
            'host': cfg['host'],
            'port': cfg['port'],
            'username': cfg['username'],
            'password_exposed': False,
        }
        if not cfg['password']:
            return {**base, 'ok': False, 'error': 'ARI password not initialized'}

        token = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
        url = f"http://{cfg['host']}:{cfg['port']}/ari/asterisk/info"
        req = Request(url, headers={'Authorization': f'Basic {token}', 'Accept': 'application/json'})
        try:
            with urlopen(req, timeout=3) as response:
                body = response.read(1024 * 1024).decode(errors='replace')
                data = json.loads(body) if body else {}
                return {
                    **base,
                    'ok': response.status == 200 and isinstance(data, dict),
                    'http_status': response.status,
                    'asterisk_info': data,
                }
        except HTTPError as exc:
            return {**base, 'ok': False, 'http_status': exc.code, 'error': f'HTTP {exc.code}: {exc.reason}'}
        except URLError as exc:
            return {**base, 'ok': False, 'error': str(exc.reason)}
        except Exception as exc:
            return {**base, 'ok': False, 'error': str(exc)}

    def status(self):
        result = self.ping()
        info = result.get('asterisk_info') if isinstance(result.get('asterisk_info'), dict) else {}
        return {
            'enabled': True,
            'connected': bool(result.get('ok')),
            'host': result.get('host', '127.0.0.1'),
            'port': result.get('port', 8088),
            'username': result.get('username', 'homeassistant'),
            'http_status': result.get('http_status'),
            'asterisk_info': info,
            'error': result.get('error', ''),
            'password_exposed': False,
        }


ARI = AsteriskARI()
