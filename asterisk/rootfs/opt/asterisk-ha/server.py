#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, re

from backend import CONF, PBX, SEC, ast, load_json, save_json, token, apply_managed, render_managed, run, usb_ports
from ui import INDEX

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
        if path=='/api/pbx': self.sendj(load_json(PBX,{})); return
        if path=='/api/usb': self.sendj(usb_ports()); return
        if path=='/api/calls': self.sendj({'channels':ast('core show channels concise')['output'],'endpoints':ast('pjsip show endpoints')['output'],'queues':ast('queue show')['output'],'confbridge':ast('confbridge list')['output']}); return
        if path=='/api/ht503-status':
            h=load_json(PBX,{}).get('ht503',{}) or {}; user=token(h.get('fxo_user','ht503fxo'),'ht503fxo')
            self.sendj({'endpoint':ast(f'pjsip show endpoint {user}')['output'],'contacts':ast('pjsip show contacts')['output']}); return
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
                save_json(PBX,data); out=apply_managed(old,data); self.sendj({'ok':True,'reload':out})
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
    render_managed(load_json(PBX,{}))
    ThreadingHTTPServer(('0.0.0.0',8099),H).serve_forever()
