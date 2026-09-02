#!/usr/bin/env python3
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import ipaddress
import json, re

from backend import CONF, PBX, SEC, ast, load_json, save_json, token, render_managed, run, usb_ports
from ui import INDEX
from sipcord import ensure_sipcord_state, render_sipcord, augment_index as augment_sipcord_index
from ivr import ensure_ivr_state, validate_ivrs, render_ivrs, augment_index as augment_ivr_index, recording_code, recording_sound_id
from ivr_audio import list_recordings, save_upload, get_recording, delete_recording, sound_to_stem
from ha_state import build_snapshot
from security_status import fail2ban_status

INDEX = augment_ivr_index(augment_sipcord_index(INDEX))
WEB_SECURITY_LOG = Path('/data/fail2ban/pbx-web-security.log')
TRUSTED_WEB_NETWORKS = tuple(ipaddress.ip_network(x) for x in (
    '127.0.0.0/8', '::1/128', '10.0.0.0/8', '172.16.0.0/12',
    '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7', 'fe80::/10',
))


def normalize_ht503_legacy_trunks(data):
    """Remove an old provider-style HT503 trunk when dedicated FXO mode is enabled."""
    if not isinstance(data, dict):
        return data, []
    ht = data.get('ht503', {}) or {}
    if not isinstance(ht, dict) or not ht.get('enabled', False):
        return data, []
    device_ip = str(ht.get('device_ip', '') or '').strip()
    fxo_user = token(ht.get('fxo_user', ''))
    if not device_ip or not fxo_user:
        return data, []
    trunks = data.get('sip_trunks', []) or []
    if not isinstance(trunks, list):
        return data, []
    kept = []
    removed = []
    for trunk in trunks:
        if not isinstance(trunk, dict):
            kept.append(trunk)
            continue
        same_server = str(trunk.get('server', '') or '').strip() == device_ip
        same_user = token(trunk.get('username', '')) == fxo_user
        if same_server and same_user:
            removed.append(str(trunk.get('name', '') or fxo_user))
        else:
            kept.append(trunk)
    if not removed:
        return data, []
    cleaned = dict(data)
    cleaned['sip_trunks'] = kept
    return cleaned, removed


def normalize_pbx(data):
    data, sipcord_changed = ensure_sipcord_state(data)
    data, ivr_changed = ensure_ivr_state(data)
    data, removed_ht503 = normalize_ht503_legacy_trunks(data)
    validate_ivrs(data)
    return data, bool(sipcord_changed or ivr_changed), removed_ht503


def load_pbx_state():
    data = load_json(PBX, {})
    data, changed, removed_ht503 = normalize_pbx(data)
    if changed or removed_ht503:
        save_json(PBX, data)
    return data


def apply_pbx(old, new):
    """Render all managed config before doing targeted reloads."""
    render_managed(new)
    render_sipcord(CONF, new)
    render_ivrs(CONF, new)
    results = []
    for command in ('pjsip reload', 'dialplan reload', 'voicemail reload'):
        result = ast(command)
        results.append(f'$ {command}\n{result["output"]}')
    if old.get('gsm_dongles', []) != new.get('gsm_dongles', []):
        result = ast('module reload chan_dongle.so')
        results.append(f'$ module reload chan_dongle.so\n{result["output"]}')
    return '\n'.join(results)


def _clean_ivr_id(value):
    return re.sub(r'[^0-9A-Za-z_-]', '', str(value or '')).lower()


def _configured_extension(data, extension):
    extension = token(extension)
    return extension if any(token(e.get('extension', '')) == extension for e in (data.get('extensions') or [])) else ''


def _find_ivr(data, ivr_id):
    ivr_id = _clean_ivr_id(ivr_id)
    for ivr in (data.get('ivrs') or []):
        if _clean_ivr_id(ivr.get('id')) == ivr_id:
            return ivr
    return None


def _asterisk_prompt(prompt, ivr):
    prompt = re.sub(r'[^0-9A-Za-z_./-]', '', str(prompt or '').strip())
    if prompt.startswith('custom/'):
        return f'/share/asterisk-ivr/{sound_to_stem(prompt, "ivr-prompt")}'
    if prompt:
        return prompt
    return f'/share/asterisk-ivr/{sound_to_stem(recording_sound_id(ivr), "ivr-prompt")}'


def _safe_log_token(value, default='-'):
    value = re.sub(r'\s+', '_', str(value or default))
    return re.sub(r'[^0-9A-Za-z_./?&=%:+*~-]', '_', value)[:500] or default


class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass

    def _peer_ip(self):
        return str((self.client_address or ('', 0))[0] or '')

    def _trusted_web_peer(self):
        try:
            ip = ipaddress.ip_address(self._peer_ip())
            return any(ip in net for net in TRUSTED_WEB_NETWORKS)
        except Exception:
            return False

    def _audit(self, status, reason):
        try:
            WEB_SECURITY_LOG.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
            path = urlparse(self.path).path or '/'
            line = f'{stamp} PBX-WEB client={_safe_log_token(self._peer_ip())} method={_safe_log_token(self.command)} path={_safe_log_token(path)} status={int(status)} reason={_safe_log_token(reason)}\n'
            with WEB_SECURITY_LOG.open('a') as f:
                f.write(line)
        except Exception:
            pass

    def _guard_web(self):
        # The WebGUI has no independent login screen; authentication is supplied
        # by Home Assistant Ingress. Direct public access must therefore never
        # be treated as an authenticated UI path.
        if self._trusted_web_peer():
            return True
        self._audit(403, 'public-direct-blocked')
        self.sendj({'error':'Direct public WebGUI access is disabled; use Home Assistant Ingress'},403)
        return False

    def sendj(self,obj,code=200):
        b=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',len(b))
        self.end_headers()
        self.wfile.write(b)

    def send_bytes(self, data, content_type='application/octet-stream', code=200, filename=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', len(data))
        if filename:
            self.send_header('Content-Disposition', f'inline; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            length=int(self.headers.get('Content-Length','0') or 0)
            if length > 24 * 1024 * 1024:
                return {'_error':'request too large'}
            return json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            return {}

    def do_GET(self):
        if not self._guard_web(): return
        u=urlparse(self.path); path=u.path.rstrip('/') or '/'; q=parse_qs(u.query)
        if path=='/':
            b=INDEX.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b); return
        if path=='/api/status':
            v=ast('core show version'); ch=ast('core show channels count'); m=re.search(r'(\d+) active channel',ch['output'])
            self.sendj({'running':v['ok'],'version':v['output'].strip(),'channels':int(m.group(1)) if m else 0}); return
        if path=='/api/security': self.sendj(fail2ban_status()); return
        if path=='/api/ha-state':
            try:
                self.sendj(build_snapshot(ast, load_pbx_state()))
            except Exception as e:
                self.sendj({'online':False,'error':str(e)},500)
            return
        if path=='/api/pbx': self.sendj(load_pbx_state()); return
        if path=='/api/usb': self.sendj(usb_ports()); return
        if path=='/api/ivr-recordings':
            try: self.sendj({'recordings':list_recordings()})
            except Exception as e: self.sendj({'recordings':[],'error':str(e)},500)
            return
        if path=='/api/ivr-audio':
            try:
                name=(q.get('name') or [''])[0]
                file_path, raw=get_recording(name)
                self.send_bytes(raw,'audio/wav',200,file_path.name)
            except FileNotFoundError:
                self.sendj({'error':'recording not found'},404)
            except Exception as e:
                self.sendj({'error':str(e)},400)
            return
        if path=='/api/calls': self.sendj({'channels':ast('core show channels concise')['output'],'endpoints':ast('pjsip show endpoints')['output'],'queues':ast('queue show')['output'],'confbridge':ast('confbridge list')['output']}); return
        if path=='/api/ht503-status':
            h=load_pbx_state().get('ht503',{}) or {}; user=token(h.get('fxo_user','ht503fxo'),'ht503fxo')
            self.sendj({'endpoint':ast(f'pjsip show endpoint {user}')['output'],'contacts':ast('pjsip show contacts')['output']}); return
        if path=='/api/sipcord-status':
            s=load_pbx_state().get('sipcord',{}) or {}
            if not s.get('enabled'):
                self.sendj({'endpoint':'SIPcord desativado','aor':'','contacts':''}); return
            self.sendj({'endpoint':ast('pjsip show endpoint sipcord')['output'],'aor':ast('pjsip show aor sipcord')['output'],'contacts':ast('pjsip show contacts')['output']}); return
        if path=='/api/files': self.sendj({'files':sorted([p.name for p in CONF.glob('*.conf')])}); return
        if path=='/api/file':
            n=(q.get('name') or [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.conf',n) or not (CONF/n).exists():
                self._audit(404,'invalid-config-file'); self.sendj({'error':'invalid file'},404); return
            self.sendj({'name':n,'content':(CONF/n).read_text(errors='ignore')}); return
        if path=='/api/logs': self.sendj(run('tail -n 600 /var/log/asterisk/full 2>/dev/null || tail -n 600 /var/log/asterisk/messages 2>/dev/null')); return
        if path=='/api/diagnostics': self.sendj({'modules':ast('module show like res_ari')['output']+'\n'+ast('module show like chan_dongle')['output'],'pjsip':ast('pjsip show transports')['output']+'\n'+ast('pjsip show contacts')['output'],'dongle':ast('dongle show devices')['output'],'usb':run('lsusb; echo; ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null')['output']}); return
        if path=='/api/credentials':
            self._audit(403,'sensitive-endpoint-disabled')
            self.sendj({'error':'Sensitive credentials endpoint disabled'},403); return
        self._audit(404,'not-found'); self.sendj({'error':'not found'},404)

    def do_POST(self):
        if not self._guard_web(): return
        u=urlparse(self.path); data=self.body(); path=u.path.rstrip('/')
        if data.get('_error'):
            self._audit(413,'request-too-large'); self.sendj({'ok':False,'error':'request too large'},413); return
        if path=='/api/pbx':
            try:
                if not isinstance(data,dict): raise ValueError('object required')
                old=load_json(PBX,{})
                data, normalized, removed = normalize_pbx(data)
                save_json(PBX,data)
                out=apply_pbx(old,data)
                self.sendj({'ok':True,'reload':out,'removed_legacy_trunks':removed,'normalized':normalized})
            except Exception as e: self.sendj({'ok':False,'error':str(e)},400)
            return
        if path=='/api/ivr-upload':
            try:
                recording=save_upload(data.get('name',''),data.get('data',''))
                self.sendj({'ok':True,'recording':recording})
            except Exception as e:
                self.sendj({'ok':False,'error':str(e)},400)
            return
        if path=='/api/ivr-delete':
            try:
                deleted=delete_recording(data.get('name',''))
                self.sendj({'ok':True,'deleted':deleted})
            except Exception as e:
                self.sendj({'ok':False,'error':str(e)},400)
            return
        if path=='/api/action':
            action=data.get('action','')
            if action=='cli':
                c=str(data.get('command','')); allowed=('core reload','pjsip reload','module reload chan_dongle.so','dialplan reload','voicemail reload','queue reload all')
                if c not in allowed:
                    self._audit(403,'cli-command-blocked'); self.sendj({'ok':False,'output':'Command not allowed'},403); return
                self.sendj(ast(c)); return
            if action in ('ivr_record','ivr_test'):
                pbx=load_pbx_state()
                ivr=_find_ivr(pbx,data.get('ivr_id',''))
                source=_configured_extension(pbx,data.get('source_extension',''))
                if not ivr or not ivr.get('enabled',True):
                    self.sendj({'ok':False,'output':'IVR não encontrado ou desativado'},404); return
                if not source:
                    self.sendj({'ok':False,'output':'Extensão PJSIP de origem inválida'},400); return
                if action=='ivr_record':
                    code=recording_code(ivr)
                    if not code:
                        self.sendj({'ok':False,'output':'IVR sem extensão de gravação'},400); return
                    result=ast(f'channel originate PJSIP/{source} extension {code}@from-internal')
                    self.sendj({'ok':result['ok'],'output':result['output'],'record_code':code,'sound_id':recording_sound_id(ivr)}); return
                prompt=_asterisk_prompt(ivr.get('prompt'),ivr)
                if not prompt:
                    self.sendj({'ok':False,'output':'IVR sem prompt'},400); return
                result=ast(f'channel originate PJSIP/{source} application Playback {prompt}')
                self.sendj({'ok':result['ok'],'output':result['output'],'prompt':prompt}); return
            if action=='dongle_show': self.sendj(ast('dongle show devices')); return
            if action in ('sms','ussd'):
                dev=token(data.get('device',''))
                if action=='sms':
                    num=re.sub(r'[^0-9+#*]','',str(data.get('number',''))); msg=str(data.get('message','')).replace('\n',' ').replace('"','').strip()[:500]
                    self.sendj(ast(f'dongle sms {dev} {num} {msg}')); return
                code=re.sub(r'[^0-9*#+]','',str(data.get('code',''))); self.sendj(ast(f'dongle ussd {dev} {code}')); return
            self.sendj({'ok':False,'output':'Unknown action'},400); return
        self._audit(404,'not-found'); self.sendj({'error':'not found'},404)

    def do_PUT(self):
        if not self._guard_web(): return
        u=urlparse(self.path); q=parse_qs(u.query); data=self.body()
        if u.path.rstrip('/')=='/api/file':
            n=(q.get('name') or [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.conf',n) or not (CONF/n).exists():
                self._audit(404,'invalid-config-file'); self.sendj({'ok':False,'error':'invalid file'},400); return
            try:
                (CONF/n).write_text(str(data.get('content','')))
                if n.startswith('pjsip'): out=ast('pjsip reload')
                elif n.startswith('extensions'): out=ast('dialplan reload')
                elif n.startswith('voicemail'): out=ast('voicemail reload')
                elif n.startswith('queue'): out=ast('queue reload all')
                elif n=='dongle.conf': out=ast('module reload chan_dongle.so')
                else: out=ast('core reload')
                self.sendj({'ok':True,'reload':out['output']})
            except Exception as e: self.sendj({'ok':False,'error':str(e)},500)
            return
        self._audit(404,'not-found'); self.sendj({'error':'not found'},404)

    def do_DELETE(self):
        if not self._guard_web(): return
        self._audit(405,'method-not-allowed')
        self.sendj({'error':'method not allowed'},405)


if __name__=='__main__':
    WEB_SECURITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    WEB_SECURITY_LOG.touch(exist_ok=True)
    startup=load_pbx_state()
    render_managed(startup)
    render_sipcord(CONF,startup)
    render_ivrs(CONF,startup)
    ThreadingHTTPServer(('0.0.0.0',8099),H).serve_forever()
