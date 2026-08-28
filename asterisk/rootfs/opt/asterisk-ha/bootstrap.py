#!/usr/bin/env python3
import json, os, re, secrets
from pathlib import Path

CONF=Path('/config/asterisk'); STATE=Path('/config/state'); OPT=Path('/data/options.json')
STATE.mkdir(parents=True, exist_ok=True)
try: options=json.loads(OPT.read_text())
except Exception: options={}
secfile=STATE/'secrets.json'
if secfile.exists():
    sec=json.loads(secfile.read_text())
else:
    sec={'ami_user':'homeassistant','ami_password':secrets.token_urlsafe(24),
         'ari_user':'homeassistant','ari_password':secrets.token_urlsafe(24)}
    secfile.write_text(json.dumps(sec,indent=2))
    os.chmod(secfile,0o600)

repls={
'__SIP_PORT__':str(options.get('sip_port',5060)), '__TLS_PORT__':str(options.get('tls_port',5061)),
'__AMI_PORT__':str(options.get('ami_port',5038)), '__ARI_PORT__':str(options.get('ari_port',8088)),
'__RTP_START__':str(options.get('rtp_start',10000)), '__RTP_END__':str(options.get('rtp_end',20000)),
'__AMI_USER__':sec['ami_user'],'__AMI_PASSWORD__':sec['ami_password'],
'__ARI_USER__':sec['ari_user'],'__ARI_PASSWORD__':sec['ari_password']}
for p in CONF.glob('*.conf'):
    text=p.read_text(errors='ignore')
    old=text
    for k,v in repls.items(): text=text.replace(k,v)
    if text!=old: p.write_text(text)

# Keep the chan_dongle app option authoritative even on upgrades where the
# persistent modules.conf was created by an older version of the app.
modules=CONF/'modules.conf'
if modules.exists():
    lines=modules.read_text(errors='ignore').splitlines()
    lines=[line for line in lines if not re.match(r'^\s*(?:load|noload)\s*=>\s*chan_dongle\.so\s*$', line, re.I)]
    if not any(re.match(r'^\s*noload\s*=>\s*chan_sip\.so\s*$', line, re.I) for line in lines):
        lines.append('noload => chan_sip.so')
    lines.append(('load' if options.get('chan_dongle', True) else 'noload') + ' => chan_dongle.so')
    modules.write_text('\n'.join(lines).rstrip()+'\n')

# v0.1.4 migration: cdr_csv needs a [csv] section. Preserve any existing CDR
# settings and only append the missing backend configuration.
cdr=CONF/'cdr.conf'
if cdr.exists():
    text=cdr.read_text(errors='ignore')
    if not re.search(r'^\s*\[csv\]\s*$', text, re.I|re.M):
        with cdr.open('a') as f:
            if text and not text.endswith('\n'): f.write('\n')
            f.write('\n[csv]\nusegmtime=no\nloguniqueid=yes\nloguserfield=yes\naccountlogs=yes\nnewcdrcolumns=yes\n')

pbx=STATE/'pbx.json'
if not pbx.exists():
    pbx.write_text(json.dumps({
      'extensions':[{'extension':'100','callerid':'Home Assistant 100','secret':secrets.token_urlsafe(12),'voicemail_pin':'1234','context':'from-internal'}],
      'sip_trunks':[],
      'gsm_dongles':[],
      'routes':{'gsm_prefix':'9','incoming_target':'100'}
    },indent=2))
