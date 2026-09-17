#!/usr/bin/env python3
import re
from pathlib import Path


def _clean_id(value, default='main'):
    out = re.sub(r'[^0-9A-Za-z_-]', '', str(value or '').strip()).lower()
    return out or default


def _number(value, default=''):
    out = re.sub(r'[^0-9*#+]', '', str(value or '').strip())
    return out or default


def patch_generated_ivrs(conf, data):
    path = Path(conf) / 'extensions_ivr_gui.conf'
    if not path.exists():
        return {'changed': False, 'patched': 0, 'missing': []}

    text = path.read_text(errors='ignore')
    original = text
    patched = 0
    missing = []

    for ivr in (data or {}).get('ivrs') or []:
        if not isinstance(ivr, dict) or not ivr.get('enabled', True):
            continue
        ivr_id = _clean_id(ivr.get('id'))
        for option in ivr.get('options') or []:
            if not isinstance(option, dict):
                continue
            if str(option.get('type') or 'extension').strip().lower() != 'extension':
                continue
            digit = str(option.get('digit') or '').strip()
            number = _number(option.get('value'))
            if digit not in tuple('0123456789') + ('*', '#') or not number:
                continue

            pattern = re.compile(
                rf'(?m)^(exten => {re.escape(digit)},1,NoOp\(IVR {re.escape(ivr_id)} option [^\n]*\)\n)'
                rf' same => n,Goto\(from-internal,{re.escape(number)},1\)\n?'
            )

            def replacement(match):
                lines = [
                    match.group(1).rstrip('\n'),
                    f' same => n,Dial(PJSIP/{number},45)',
                    f' same => n,NoOp(IVR {ivr_id} destination {number}: DIALSTATUS=${{DIALSTATUS}} HANGUPCAUSE=${{HANGUPCAUSE}})',
                    # An unavailable endpoint must return to the IVR so the
                    # caller can immediately choose another destination.
                    ' same => n,GotoIf($["${DIALSTATUS}"="CHANUNAVAIL"]?return-menu)',
                    # Q.850 cause 21 = Call Rejected. Explicit rejection also
                    # returns to the IVR. NOANSWER/BUSY/CONGESTION continue to
                    # the selected extension voicemail.
                    ' same => n,GotoIf($["${HANGUPCAUSE}"="21"]?return-menu)',
                    # If the call was answered, never fall through to voicemail
                    # when the bridge ends normally.
                    ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
                    f' same => n,VoiceMail({number}@default,u)',
                    ' same => n,Hangup()',
                    f' same => n(return-menu),Goto(ivr-{ivr_id},s,menu)',
                    ' same => n(done),Hangup()',
                ]
                return '\n'.join(lines) + '\n'

            text, count = pattern.subn(replacement, text, count=1)
            if count:
                patched += 1
            else:
                marker = f'exten => {digit},1,NoOp(IVR {ivr_id} option '
                if marker in text and f'Dial(PJSIP/{number},45)' in text:
                    continue
                missing.append(f'{ivr_id}:{digit}->{number}')

    changed = text != original
    if changed:
        path.write_text(text.rstrip() + '\n')
    return {'changed': changed, 'patched': patched, 'missing': missing}


def install(server_module):
    if getattr(server_module, '_ivr_return_to_menu_installed', False):
        return
    original = server_module.render_ivrs

    def render_ivrs_with_return(conf, data):
        result = original(conf, data)
        try:
            info = patch_generated_ivrs(conf, data)
            if info['patched']:
                print(f"[IVR] reject/CHANUNAVAIL return-to-menu enabled for {info['patched']} extension option(s)")
            if info['missing']:
                print('[IVR] WARNING return-to-menu not applied: ' + ', '.join(info['missing']))
        except Exception as exc:
            print(f'[IVR] WARNING return-to-menu patch failed: {exc}')
        return result

    server_module.render_ivrs = render_ivrs_with_return
    server_module._ivr_return_to_menu_installed = True
