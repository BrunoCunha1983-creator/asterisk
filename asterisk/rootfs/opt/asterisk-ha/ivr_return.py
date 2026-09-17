#!/usr/bin/env python3
import re
from pathlib import Path

CALL_ACTIONS = {'return_ivr', 'voicemail', 'ivr_fallback', 'hangup'}
ACTION_FIELDS = (
    ('on_reject', 'return_ivr'),
    ('on_chanunavail', 'return_ivr'),
    ('on_noanswer', 'voicemail'),
    ('on_busy', 'voicemail'),
    ('on_congestion', 'voicemail'),
    ('on_answer', 'hangup'),
    ('on_other', 'voicemail'),
)


def _clean_id(value, default='main'):
    out = re.sub(r'[^0-9A-Za-z_-]', '', str(value or '').strip()).lower()
    return out or default


def _number(value, default=''):
    out = re.sub(r'[^0-9*#+]', '', str(value or '').strip())
    return out or default


def _call_action(value, default):
    value = str(value or '').strip().lower()
    return value if value in CALL_ACTIONS else default


def _capture_actions(data):
    captured = {}
    if not isinstance(data, dict):
        return captured
    for ivr in data.get('ivrs') or []:
        if not isinstance(ivr, dict):
            continue
        ivr_id = _clean_id(ivr.get('id'))
        for opt in ivr.get('options') or []:
            if not isinstance(opt, dict):
                continue
            digit = str(opt.get('digit') or '').strip()
            if digit not in tuple('0123456789') + ('*', '#'):
                continue
            values = {}
            for field, default in ACTION_FIELDS:
                values[field] = _call_action(opt.get(field), default)
            captured[(ivr_id, digit)] = values
    return captured


def _restore_actions(data, captured):
    changed = False
    if not isinstance(data, dict):
        return changed
    for ivr in data.get('ivrs') or []:
        if not isinstance(ivr, dict):
            continue
        ivr_id = _clean_id(ivr.get('id'))
        for opt in ivr.get('options') or []:
            if not isinstance(opt, dict):
                continue
            digit = str(opt.get('digit') or '').strip()
            saved = captured.get((ivr_id, digit), {})
            for field, default in ACTION_FIELDS:
                value = _call_action(saved.get(field), default)
                if opt.get(field) != value:
                    opt[field] = value
                    changed = True
    return changed


def _action_lines(label, action, ivr_id, number):
    action = _call_action(action, 'voicemail')
    if action == 'return_ivr':
        return [f' same => n({label}),Goto(ivr-{ivr_id},s,menu)']
    if action == 'ivr_fallback':
        return [f' same => n({label}),Goto(ivr-{ivr_id},fallback,1)']
    if action == 'hangup':
        return [f' same => n({label}),Hangup()']
    return [
        f' same => n({label}),VoiceMail({number}@default,u)',
        ' same => n,Hangup()',
    ]


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
                    ' same => n,GotoIf($["${HANGUPCAUSE}"="21"]?act_reject)',
                    ' same => n,GotoIf($["${DIALSTATUS}"="CHANUNAVAIL"]?act_chanunavail)',
                    ' same => n,GotoIf($["${DIALSTATUS}"="NOANSWER"]?act_noanswer)',
                    ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?act_busy)',
                    ' same => n,GotoIf($["${DIALSTATUS}"="CONGESTION"]?act_congestion)',
                    ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?act_answer)',
                    ' same => n,Goto(act_other)',
                ]
                action_map = {
                    'act_reject': option.get('on_reject'),
                    'act_chanunavail': option.get('on_chanunavail'),
                    'act_noanswer': option.get('on_noanswer'),
                    'act_busy': option.get('on_busy'),
                    'act_congestion': option.get('on_congestion'),
                    'act_answer': option.get('on_answer'),
                    'act_other': option.get('on_other'),
                }
                defaults = dict(ACTION_FIELDS)
                for label, value in action_map.items():
                    field = 'on_' + label[4:]
                    lines.extend(_action_lines(label, _call_action(value, defaults[field]), ivr_id, number))
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


def augment_index(index):
    if 'function ivrCallActionOptions(selected)' not in index:
        needle = "function ivrDigitOptions(selected){\n  return ['0','1','2','3','4','5','6','7','8','9','*','#'].map(x=>`<option ${selected===x?'selected':''}>${x}</option>`).join('');\n}\n"
        addition = needle + """function ivrCallActionOptions(selected){
  const opts=[['return_ivr','Voltar ao IVR'],['voicemail','Voicemail da extensão'],['ivr_fallback','Destino final do IVR'],['hangup','Desligar']];
  return opts.map(x=>`<option value=\"${x[0]}\" ${selected===x[0]?'selected':''}>${x[1]}</option>`).join('');
}
"""
        index = index.replace(needle, addition)

    old_capture = """    let options=(v.options||[]).map((o,j)=>({digit:E(`#ivrdigit${i}_${j}`).value,label:E(`#ivrlabel${i}_${j}`).value,type:E(`#ivrtype${i}_${j}`).value,value:E(`#ivrvalue${i}_${j}`).value}));
"""
    new_capture = """    let options=(v.options||[]).map((o,j)=>{
      const cv=(suffix,def)=>{let e=E(`#ivr${suffix}${i}_${j}`);return e?e.value:(o[suffix]||def)};
      return {digit:E(`#ivrdigit${i}_${j}`).value,label:E(`#ivrlabel${i}_${j}`).value,type:E(`#ivrtype${i}_${j}`).value,value:E(`#ivrvalue${i}_${j}`).value,
        on_reject:cv('on_reject','return_ivr'),on_chanunavail:cv('on_chanunavail','return_ivr'),on_noanswer:cv('on_noanswer','voicemail'),
        on_busy:cv('on_busy','voicemail'),on_congestion:cv('on_congestion','voicemail'),on_answer:cv('on_answer','hangup'),on_other:cv('on_other','voicemail')};
    });
"""
    index = index.replace(old_capture, new_capture)

    old_row = """  ${(v.options||[]).map((o,j)=>`<div class=row><div><label>Tecla</label><select id=ivrdigit${i}_${j}>${ivrDigitOptions(o.digit)}</select></div><div><label>Descrição</label><input id=ivrlabel${i}_${j} value=\"${esc(o.label||'')}\"></div><div><label>Tipo de destino</label><select id=ivrtype${i}_${j}>${ivrDestOptions(o.type||'extension')}</select></div><div><label>Destino</label><input id=ivrvalue${i}_${j} value=\"${esc(o.value||'')}\"></div><div><label>&nbsp;</label><button class=btn onclick=\"delIVROpt(${i},${j})\">Remover tecla</button></div></div>`).join('')}
"""
    new_row = """  ${(v.options||[]).map((o,j)=>`<div class=item><div class=row><div><label>Tecla</label><select id=ivrdigit${i}_${j}>${ivrDigitOptions(o.digit)}</select></div><div><label>Descrição</label><input id=ivrlabel${i}_${j} value=\"${esc(o.label||'')}\"></div><div><label>Tipo de destino</label><select id=ivrtype${i}_${j}>${ivrDestOptions(o.type||'extension')}</select></div><div><label>Destino</label><input id=ivrvalue${i}_${j} value=\"${esc(o.value||'')}\"></div><div><label>&nbsp;</label><button class=btn onclick=\"delIVROpt(${i},${j})\">Remover tecla</button></div></div>
  <div class=sub>Comportamento após chamar a extensão (usado quando o tipo é Extensão)</div><div class=row>
    <div><label>Recusada</label><select id=ivron_reject${i}_${j}>${ivrCallActionOptions(o.on_reject||'return_ivr')}</select></div>
    <div><label>CHANUNAVAIL</label><select id=ivron_chanunavail${i}_${j}>${ivrCallActionOptions(o.on_chanunavail||'return_ivr')}</select></div>
    <div><label>Não atende</label><select id=ivron_noanswer${i}_${j}>${ivrCallActionOptions(o.on_noanswer||'voicemail')}</select></div>
    <div><label>Ocupado</label><select id=ivron_busy${i}_${j}>${ivrCallActionOptions(o.on_busy||'voicemail')}</select></div>
    <div><label>Congestion</label><select id=ivron_congestion${i}_${j}>${ivrCallActionOptions(o.on_congestion||'voicemail')}</select></div>
    <div><label>Após chamada atendida</label><select id=ivron_answer${i}_${j}>${ivrCallActionOptions(o.on_answer||'hangup')}</select></div>
    <div><label>Outro resultado</label><select id=ivron_other${i}_${j}>${ivrCallActionOptions(o.on_other||'voicemail')}</select></div>
  </div></div>`).join('')}
"""
    index = index.replace(old_row, new_row)

    old_add = """function addIVROpt(i){captureIVRs();pbx.ivrs[i].options=pbx.ivrs[i].options||[];pbx.ivrs[i].options.push({digit:'1',label:'',type:'extension',value:'100'});ivrs(E('#app'))}
"""
    new_add = """function addIVROpt(i){captureIVRs();pbx.ivrs[i].options=pbx.ivrs[i].options||[];pbx.ivrs[i].options.push({digit:'1',label:'',type:'extension',value:'100',on_reject:'return_ivr',on_chanunavail:'return_ivr',on_noanswer:'voicemail',on_busy:'voicemail',on_congestion:'voicemail',on_answer:'hangup',on_other:'voicemail'});ivrs(E('#app'))}
"""
    index = index.replace(old_add, new_add)
    return index


def install(server_module):
    if getattr(server_module, '_ivr_return_to_menu_installed', False):
        return

    original_normalize = server_module.normalize_pbx
    original_render = server_module.render_ivrs

    def normalize_pbx_with_call_actions(data):
        captured = _capture_actions(data)
        normalized, changed, removed = original_normalize(data)
        action_changed = _restore_actions(normalized, captured)
        return normalized, bool(changed or action_changed), removed

    def render_ivrs_with_return(conf, data):
        result = original_render(conf, data)
        try:
            info = patch_generated_ivrs(conf, data)
            if info['patched']:
                print(f"[IVR] configurable call-result routing enabled for {info['patched']} extension option(s)")
            if info['missing']:
                print('[IVR] WARNING result routing not applied: ' + ', '.join(info['missing']))
        except Exception as exc:
            print(f'[IVR] WARNING result routing patch failed: {exc}')
        return result

    server_module.normalize_pbx = normalize_pbx_with_call_actions
    server_module.render_ivrs = render_ivrs_with_return
    server_module.INDEX = augment_index(server_module.INDEX)
    server_module._ivr_return_to_menu_installed = True
