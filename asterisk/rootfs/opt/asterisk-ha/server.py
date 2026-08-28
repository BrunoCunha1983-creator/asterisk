#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, re

from backend import CONF, PBX, SEC, ast, load_json, save_json, token, render_managed, run, usb_ports
from ui import INDEX
from sipcord import ensure_sipcord_state, render_sipcord, augment_index
from ha_state import build_snapshot

INDEX = augment_index(INDEX)


def normalize_ht503_legacy_trunks(data):
    """Remove an old provider-style HT503 trunk when dedicated FXO mode is enabled.

    v0.1.4 represented a local HT503 as a provider trunk, which generated an
    outbound REGISTER and caused SIP 405 responses. Only remove a legacy
    trunk when BOTH its server and username match the enabled HT503 settings.
    This avoids touching unrelated provider trunks.
    """
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
    data, removed_ht503 = normalize_ht503_legacy_trunks(data)
    return data, sipcord_changed, removed_ht503


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
    results = []
    for command in ('pjsip reload', 'dialplan reload', 'voicemail reload'):
        result = ast(command)
        results.append(f'$ {command}\n{result["output"]}')
    if old.get('gsm_dongles', []) != new.get('gsm_dongles', []):
        result = ast('module reload chan_dongle.so')
        results.append(f'$ module reload chan_dongle.so\n{result["output"]}')
    return '\n'.join(results)


class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def sendj(self,obj,code=200):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b)
    def body(self):
        try: return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0') or 0)) or b'{}')
        except Exception: return {}
    def do_GET(self):
        u=urlparse(self.path); path=u.path.rstrip('/') or '/'; q=parse_qs(u.query)
        if path=='/':
            b=INDEX.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',len(b)); self.end_headers(); self.wfile.write(b); return
        if path=='/api/status':
            v=ast('core show version'); ch=ast('core show channels count'); m=re.search(r'(\d+) active channel',ch['output'])
            self.sendj({'running':v['ok'],'version':v['output'].strip(),'channels':int(m.group(1)) if m else 0}); return
        if path=='/api/ha-state':
            try:
                self.sendj(build_snapshot(ast, load_pbx_state()))
            except Exception as e:
                self.sendj({'online':False,'error':str(e)},500)
            return
        if path=='/api/pbx': self.sendj(load_pbx_state()); return
        if path=='/api/usb': self.sendj(usb_ports()); return
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
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.conf',n) or not (CONF/n).exists(): self.sendj({'error':'invalid file'},404); return
            self.sendj({'name':n,'content':(CONF/n).read_text(errors='ignore')}); return
        if path=='/api/logs': self.sendj(run('tail -n 600 /var/log/asterisk/full 2>/dev/null || tail -n 600 /var/log/asterisk/messages 2>/dev/null')); return
        if path=='/api/diagnostics': self.sendj({'modules':ast('module show like res_ari')['output']+'\n'+ast('module show like chan_dongle')['output'],'pjsip':ast('pjsip show transports')['output']+'\n'+ast('pjsip show contacts')['output'],'dongle':ast('dongle show devices')['output'],'usb':run('lsusb; echo; ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null')['output']}); return
        if path=='/api/credentials': self.sendj(load_json(SEC,{})); return
        self.sendj({'error':'not found'},404)
    def do_POST(self):
        u=urlparse(self.path); data=self.body()
        if u.path.rstrip('/')=='/api/pbx':
            try:
                if not isinstance(data,dict): raise ValueError('object required')
                old=load_json(PBX,{})
                data, sipcord_changed, removed = normalize_pbx(data)
                save_json(PBX,data)
                out=apply_pbx(old,data)
                self.sendj({'ok':True,'reload':out,'removed_legacy_trunks':removed,'sipcord_migrated':sipcord_changed})
            except Exception as e: self.sendj({'ok':False,'error':str(e)},400)
            return
        if u.path.rstrip('/')=='/api/action':
            action=data.get('action','')
            if action=='cli':
                c=str(data.get('command','')); allowed=('core reload','pjsip reload','module reload chan_dongle.so','dialplan reload','voicemail reload','queue reload all')
                if c not in allowed: self.sendj({'ok':False,'output':'Command not allowed'},403); return
                self.sendj(ast(c)); return
            if action=='dongle_show': self.sendj(ast('dongle show devices')); return
            if action in ('sms','ussd'):
                dev=token(data.get('device',''))
                if action=='sms':
                    num=re.sub(r'[^0-9+#*]','',str(data.get('number',''))); msg=str(data.get('message','')).replace('\n',' ').replace('"','').strip()[:500]
                    self.sendj(ast(f'dongle sms {dev} {num} {msg}')); return
                code=re.sub(r'[^0-9*#+]','',str(data.get('code',''))); self.sendj(ast(f'dongle ussd {dev} {code}')); return
            self.sendj({'ok':False,'output':'Unknown action'},400); return
        self.sendj({'error':'not found'},404)
    def do_PUT(self):
        u=urlparse(self.path); q=parse_qs(u.query); data=self.body()
        if u.path.rstrip('/')=='/api/file':
            n=(q.get('name') or [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.conf',n) or not (CONF/n).exists(): self.sendj({'ok':False,'error':'invalid file'},400); return
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
        self.sendj({'error':'not found'},404)


if __name__=='__main__':
    startup=load_pbx_state()
    render_managed(startup)
    render_sipcord(CONF,startup)
    ThreadingHTTPServer(('0.0.0.0',8099),H).serve_forever()
