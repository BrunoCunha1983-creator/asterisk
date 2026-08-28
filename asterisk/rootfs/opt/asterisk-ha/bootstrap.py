#!/usr/bin/env python3
import json, os, re, secrets
from pathlib import Path

from nat import apply_nat

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
    text=p.read_text(errors='ignore'); old=text
    for k,v in repls.items(): text=text.replace(k,v)
    if text!=old: p.write_text(text)

# Configure PJSIP/RTP NAT after template substitutions. This keeps LAN media on
# the private address while advertising the public address to remote phones.
try:
    nat_state=apply_nat(CONF, options)
    print('[NAT] local_ip=%s local_net=%s external=%s source=%s RTP=%s-%s' % (
        nat_state.get('local_ip',''), nat_state.get('local_net',''),
        nat_state.get('external_address',''), nat_state.get('external_source',''),
        nat_state.get('rtp_start',''), nat_state.get('rtp_end','')))
except Exception as e:
    print(f'[NAT] unable to apply automatic NAT settings: {e}')

modules=CONF/'modules.conf'
if modules.exists():
    lines=modules.read_text(errors='ignore').splitlines()
    lines=[line for line in lines if not re.match(r'^\s*(?:load|noload)\s*=>\s*chan_dongle\.so\s*$', line, re.I)]
    if not any(re.match(r'^\s*noload\s*=>\s*chan_sip\.so\s*$', line, re.I) for line in lines):
        lines.append('noload => chan_sip.so')
    lines.append(('load' if options.get('chan_dongle', True) else 'noload') + ' => chan_dongle.so')
    modules.write_text('\n'.join(lines).rstrip()+'\n')

cdr=CONF/'cdr.conf'
if cdr.exists():
    text=cdr.read_text(errors='ignore')
    if not re.search(r'^\s*\[csv\]\s*$', text, re.I|re.M):
        with cdr.open('a') as f:
            if text and not text.endswith('\n'): f.write('\n')
            f.write('\n[csv]\nusegmtime=no\nloguniqueid=yes\nloguserfield=yes\naccountlogs=yes\nnewcdrcolumns=yes\n')

pbx=STATE/'pbx.json'
def default_ht503():
    return {
      'enabled':False,
      'device_ip':'',
      'fxo_user':'ht503fxo',
      'fxo_secret':secrets.token_urlsafe(12),
      'callerid':'Exterior',
      'incoming_target':'100',
      'outbound_prefix':'8',
      'local_sip_port':5064
    }

if not pbx.exists():
    data={
      'extensions':[{'extension':'100','callerid':'Home Assistant 100','secret':secrets.token_urlsafe(12),'voicemail_pin':'1234','context':'from-internal'}],
      'ht503':default_ht503(),
      'sip_trunks':[],
      'gsm_dongles':[],
      'ivrs':[],
      'routes':{'gsm_prefix':'9','incoming_target':'100'}
    }
    pbx.write_text(json.dumps(data,indent=2))
else:
    # Add new managed sections without deleting existing PBX data.
    try:
        data=json.loads(pbx.read_text())
        changed=False
        if 'ht503' not in data:
            data['ht503']=default_ht503(); changed=True
        if 'ivrs' not in data or not isinstance(data.get('ivrs'), list):
            data['ivrs']=[]; changed=True
        if changed: pbx.write_text(json.dumps(data,indent=2,ensure_ascii=False))
    except Exception:
        pass
