#!/usr/bin/env python3
import re

from ivr_audio import managed_sound_id, sound_to_stem

DEFAULT_IVR = {
    'enabled': True,
    'id': 'main',
    'name': 'IVR Principal',
    'extension': '600',
    'prompt': 'custom/ivr-main',
    'timeout': 5,
    'retries': 3,
    'invalid_prompt': 'pbx-invalid',
    'timeout_prompt': '',
    'fallback_type': 'extension',
    'fallback_value': '100',
    'options': [],
}

DEST_TYPES = {'extension', 'ivr', 'voicemail', 'sipcord', 'gsm', 'pstn', 'hangup'}


def _clean_id(value, default='main'):
    out = re.sub(r'[^0-9A-Za-z_-]', '', str(value or '').strip()).lower()
    return out or default


def _number(value, default=''):
    out = re.sub(r'[^0-9*#+]', '', str(value or '').strip())
    return out or default


def _sound(value):
    # Asterisk sound id, without extension: custom/ivr-main, pbx-invalid, etc.
    return re.sub(r'[^0-9A-Za-z_./-]', '', str(value or '').strip())


def _text(value):
    return str(value or '').replace('\n', ' ').replace(';', '').strip()


def _bounded_int(value, default, minimum, maximum):
    try:
        value = int(value)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _dest_type(value):
    value = str(value or 'extension').strip().lower()
    return value if value in DEST_TYPES else 'extension'


def recording_sound_id(ivr):
    """Return the custom sound id used by GUI/telephone recording for an IVR."""
    ivr_id = _clean_id((ivr or {}).get('id'), 'main')
    prompt = _sound((ivr or {}).get('prompt'))
    if prompt.startswith('custom/'):
        return f'custom/{sound_to_stem(prompt, f"ivr-{ivr_id}")}'
    return managed_sound_id(ivr_id)


def recording_code(ivr):
    """Return the internal feature code used to record an IVR prompt."""
    extension = _number((ivr or {}).get('extension'))
    return f'*77{extension}' if extension else ''


def ensure_ivr_state(data):
    """Normalize IVR configuration while preserving user data."""
    if not isinstance(data, dict):
        data = {}
    changed = False
    raw_ivrs = data.get('ivrs')
    if not isinstance(raw_ivrs, list):
        raw_ivrs = []
        data['ivrs'] = raw_ivrs
        changed = True

    normalized = []
    for index, raw in enumerate(raw_ivrs):
        if not isinstance(raw, dict):
            changed = True
            continue
        ivr = dict(DEFAULT_IVR)
        ivr.update(raw)
        ivr['enabled'] = bool(ivr.get('enabled', True))
        ivr['id'] = _clean_id(ivr.get('id'), f'ivr{index + 1}')
        ivr['name'] = _text(ivr.get('name')) or f'IVR {index + 1}'
        ivr['extension'] = _number(ivr.get('extension'), str(600 + index))
        ivr['prompt'] = _sound(ivr.get('prompt'))
        ivr['timeout'] = _bounded_int(ivr.get('timeout'), 5, 1, 30)
        ivr['retries'] = _bounded_int(ivr.get('retries'), 3, 1, 10)
        ivr['invalid_prompt'] = _sound(ivr.get('invalid_prompt'))
        ivr['timeout_prompt'] = _sound(ivr.get('timeout_prompt'))
        ivr['fallback_type'] = _dest_type(ivr.get('fallback_type'))
        ivr['fallback_value'] = _text(ivr.get('fallback_value'))

        options = []
        for opt in (ivr.get('options') or []):
            if not isinstance(opt, dict):
                changed = True
                continue
            digit = str(opt.get('digit') or '').strip()
            if digit not in tuple('0123456789') + ('*', '#'):
                changed = True
                continue
            options.append({
                'digit': digit,
                'label': _text(opt.get('label')),
                'type': _dest_type(opt.get('type')),
                'value': _text(opt.get('value')),
            })
        ivr['options'] = options
        normalized.append(ivr)

    if normalized != raw_ivrs:
        data['ivrs'] = normalized
        changed = True
    return data, changed


def validate_ivrs(data):
    """Reject ambiguous IVR definitions before writing dialplan."""
    ivrs = data.get('ivrs') or []
    ids = set()
    numbers = set()
    endpoint_numbers = {
        str(e.get('extension') or '').strip()
        for e in (data.get('extensions') or [])
        if str(e.get('extension') or '').strip()
    }
    for ivr in ivrs:
        if not ivr.get('enabled', True):
            continue
        ivr_id = _clean_id(ivr.get('id'))
        extension = _number(ivr.get('extension'))
        if ivr_id in ids:
            raise ValueError(f'IVR duplicado: {ivr_id}')
        if extension in numbers:
            raise ValueError(f'Extensão IVR duplicada: {extension}')
        if extension in endpoint_numbers:
            raise ValueError(f'A extensão IVR {extension} já existe como extensão PJSIP')
        ids.add(ivr_id)
        numbers.add(extension)

        digits = set()
        for option in ivr.get('options') or []:
            digit = str(option.get('digit') or '')
            if digit in digits:
                raise ValueError(f'IVR {ivr_id}: tecla {digit} repetida')
            digits.add(digit)
            if option.get('type') == 'ivr' and _clean_id(option.get('value')) == ivr_id:
                raise ValueError(f'IVR {ivr_id}: a tecla {digit} não pode apontar para o próprio IVR')
    return True


def _destination_commands(kind, value, data):
    kind = _dest_type(kind)
    value = _text(value)
    if kind == 'hangup':
        return ['Hangup()']
    if kind == 'ivr':
        return [f'Goto(ivr-{_clean_id(value)},s,1)']
    if kind == 'voicemail':
        number = _number(value, '100')
        return [f'VoiceMail({number}@default,u)', 'Hangup()']
    if kind == 'sipcord':
        number = _number(value)
        return [f'Dial(PJSIP/{number}@sipcord,90)', 'Hangup()']
    if kind == 'gsm':
        number = _number(value)
        dongles = data.get('gsm_dongles') or []
        dongle = _clean_id((dongles[0] or {}).get('name'), 'dongle0') if dongles else 'dongle0'
        return [f'Dial(Dongle/{dongle}/{number},90)', 'Hangup()']
    if kind == 'pstn':
        number = _number(value)
        ht = data.get('ht503') or {}
        user = _clean_id(ht.get('fxo_user'), 'ht503fxo')
        return [f'Dial(PJSIP/{number}@{user},90)', 'Hangup()']
    number = _number(value, '100')
    return [f'Goto(from-internal,{number},1)']


def render_ivrs(conf, data):
    """Append IVR entry/recording extensions and write dedicated IVR contexts."""
    data, _ = ensure_ivr_state(data)
    validate_ivrs(data)
    ivrs = [i for i in (data.get('ivrs') or []) if i.get('enabled', True)]

    entry = conf / 'extensions_gui.conf'
    if ivrs:
        with entry.open('a') as f:
            f.write('\n; IVR ENTRY AND RECORDING EXTENSIONS\n')
            for ivr in ivrs:
                ivr_id = _clean_id(ivr.get('id'))
                extension = _number(ivr.get('extension'))
                code = recording_code(ivr)
                record_sound = recording_sound_id(ivr)
                record_stem = sound_to_stem(record_sound, f'ivr-{ivr_id}')
                f.write(f'exten => {extension},1,NoOp(IVR {ivr_id})\n')
                f.write(f' same => n,Goto(ivr-{ivr_id},s,1)\n')
                if code:
                    f.write(f'exten => {code},1,NoOp(Record IVR {ivr_id} prompt)\n')
                    f.write(' same => n,Answer()\n')
                    # Record() beeps before recording. # terminates; 3 s silence or 120 s max.
                    f.write(f' same => n,Record(/share/asterisk-ivr/{record_stem}.wav,3,120,k)\n')
                    f.write(' same => n,Playback(beep)\n')
                    f.write(' same => n,Hangup()\n')

    out = ['; AUTO-GENERATED BY ASTERISK HA GUI - IVR']
    for ivr in ivrs:
        ivr_id = _clean_id(ivr.get('id'))
        name = _text(ivr.get('name'))
        prompt = _sound(ivr.get('prompt'))
        timeout = _bounded_int(ivr.get('timeout'), 5, 1, 30)
        retries = _bounded_int(ivr.get('retries'), 3, 1, 10)
        invalid_prompt = _sound(ivr.get('invalid_prompt'))
        timeout_prompt = _sound(ivr.get('timeout_prompt'))

        out += [
            '', f'[ivr-{ivr_id}]',
            f'exten => s,1,NoOp(IVR {name})',
            ' same => n,Answer()',
            ' same => n,Set(IVR_ATTEMPT=0)',
            ' same => n(menu),Set(TIMEOUT(digit)=3)',
            f' same => n,Set(TIMEOUT(response)={timeout})',
        ]
        if prompt:
            out.append(f' same => n,Background({prompt})')
        out += [f' same => n,WaitExten({timeout})', ' same => n,Goto(t,1)']

        for option in ivr.get('options') or []:
            digit = str(option.get('digit'))
            label = _text(option.get('label')) or digit
            out += [f'exten => {digit},1,NoOp(IVR {ivr_id} option {label})']
            for command in _destination_commands(option.get('type'), option.get('value'), data):
                out.append(f' same => n,{command}')

        out += ['exten => i,1,Set(IVR_ATTEMPT=$[${IVR_ATTEMPT}+1])']
        if invalid_prompt:
            out.append(f' same => n,Playback({invalid_prompt})')
        out += [
            f' same => n,GotoIf($[${{IVR_ATTEMPT}} < {retries}]?s,menu)',
            ' same => n,Goto(fallback,1)',
            'exten => t,1,Set(IVR_ATTEMPT=$[${IVR_ATTEMPT}+1])',
        ]
        if timeout_prompt:
            out.append(f' same => n,Playback({timeout_prompt})')
        out += [
            f' same => n,GotoIf($[${{IVR_ATTEMPT}} < {retries}]?s,menu)',
            ' same => n,Goto(fallback,1)',
            'exten => fallback,1,NoOp(IVR fallback)',
        ]
        for command in _destination_commands(ivr.get('fallback_type'), ivr.get('fallback_value'), data):
            out.append(f' same => n,{command}')

    (conf / 'extensions_ivr_gui.conf').write_text('\n'.join(out).rstrip() + '\n')


def augment_index(index):
    """Inject the IVR manager into the existing Ingress GUI."""
    if "'IVR'" not in index:
        index = index.replace(
            "'SIPcord / Discord','Trunks SIP'",
            "'SIPcord / Discord','IVR','Trunks SIP'",
        )
        index = index.replace(
            "if(current==='SIPcord / Discord') sipcord(a); if(current==='Trunks SIP')",
            "if(current==='SIPcord / Discord') sipcord(a); if(current==='IVR') ivrs(a); if(current==='Trunks SIP')",
        )

    if 'function ivrs(a)' not in index:
        js = r'''
function ivrDestOptions(selected){
  const opts=[['extension','Extensão'],['ivr','Outro IVR'],['voicemail','Voicemail'],['sipcord','SIPcord / Discord'],['gsm','GSM'],['pstn','Linha exterior / HT503'],['hangup','Desligar']];
  return opts.map(x=>`<option value="${x[0]}" ${selected===x[0]?'selected':''}>${x[1]}</option>`).join('');
}
function ivrDigitOptions(selected){
  return ['0','1','2','3','4','5','6','7','8','9','*','#'].map(x=>`<option ${selected===x?'selected':''}>${x}</option>`).join('');
}
function ivrSafeId(value){return String(value||'main').toLowerCase().replace(/[^0-9a-z_-]/g,'')||'main'}
function ivrManagedSound(v){return 'custom/ivr-'+ivrSafeId(v.id)}
function ivrPromptStem(prompt){let p=String(prompt||'');if(!p.startsWith('custom/'))return '';return p.slice(7).replace(/\.wav$/i,'').toLowerCase().replace(/[^0-9a-z_-]/g,'-').replace(/^[-_]+|[-_]+$/g,'')}
function ivrPhoneOptions(selected){let e=pbx.extensions||[];return e.map(x=>`<option value="${esc(x.extension)}" ${String(selected||'')===String(x.extension)?'selected':''}>${esc(x.extension)} · ${esc(x.callerid||'')}</option>`).join('')}
function captureIVRs(){
  if(!document.querySelector('[id^=ivrid]')) return;
  pbx.ivrs=(pbx.ivrs||[]).map((v,i)=>{
    let options=(v.options||[]).map((o,j)=>({digit:E(`#ivrdigit${i}_${j}`).value,label:E(`#ivrlabel${i}_${j}`).value,type:E(`#ivrtype${i}_${j}`).value,value:E(`#ivrvalue${i}_${j}`).value}));
    return {enabled:E('#ivren'+i).value==='1',id:E('#ivrid'+i).value,name:E('#ivrname'+i).value,extension:E('#ivrext'+i).value,prompt:E('#ivrprompt'+i).value,timeout:+E('#ivrtimeout'+i).value,retries:+E('#ivrretries'+i).value,invalid_prompt:E('#ivrinvalid'+i).value,timeout_prompt:E('#ivrtprompt'+i).value,fallback_type:E('#ivrftype'+i).value,fallback_value:E('#ivrfvalue'+i).value,options};
  });
}
async function persistIVRs(){
  captureIVRs();
  let r=await api('api/pbx',{method:'POST',body:JSON.stringify(pbx)});
  if(!r.ok) throw new Error(r.error||'Erro ao guardar IVR');
  pbx=await api('api/pbx');
  return r;
}
async function ivrs(a){
  let x=pbx.ivrs||[];let recordings=[];
  try{let rr=await api('api/ivr-recordings');recordings=rr.recordings||[]}catch(e){}
  const recMap=Object.fromEntries(recordings.map(r=>[r.name,r]));
  const defaultPhone=((pbx.extensions||[])[0]||{}).extension||'';
  a.innerHTML=`<div class=card><h2>IVR — Menu de Voz</h2>
  <div class=note>Cada IVR recebe uma extensão interna própria. Para áudio personalizado usa <code>custom/...</code>. A GUI guarda as gravações em <code>/share/asterisk-ivr</code>, normaliza uploads WAV para mono 16-bit/8 kHz e permite gravar diretamente por um telefone PJSIP.</div>
  ${x.map((v,i)=>{let stem=ivrPromptStem(v.prompt);let rec=stem?recMap[stem]:null;let code='*77'+String(v.extension||'');return `<div class=item><h3>${esc(v.name||v.id||'IVR')}</h3><div class=row>
    <div><label>Ativo</label><select id=ivren${i}><option value=1 ${v.enabled!==false?'selected':''}>Sim</option><option value=0 ${v.enabled===false?'selected':''}>Não</option></select></div>
    <div><label>ID</label><input id=ivrid${i} value="${esc(v.id||'ivr'+(i+1))}"></div>
    <div><label>Nome</label><input id=ivrname${i} value="${esc(v.name||'IVR')}"></div>
    <div><label>Extensão de entrada</label><input id=ivrext${i} value="${esc(v.extension||String(600+i))}"></div>
    <div><label>Prompt / gravação</label><input id=ivrprompt${i} value="${esc(v.prompt||'')}" placeholder="custom/ivr-main"></div>
    <div><label>Timeout (s)</label><input id=ivrtimeout${i} type=number min=1 max=30 value="${esc(v.timeout||5)}"></div>
    <div><label>Tentativas</label><input id=ivrretries${i} type=number min=1 max=10 value="${esc(v.retries||3)}"></div>
    <div><label>Som tecla inválida</label><input id=ivrinvalid${i} value="${esc(v.invalid_prompt||'pbx-invalid')}"></div>
    <div><label>Som timeout</label><input id=ivrtprompt${i} value="${esc(v.timeout_prompt||'')}"></div>
    <div><label>Destino após tentativas</label><select id=ivrftype${i}>${ivrDestOptions(v.fallback_type||'extension')}</select></div>
    <div><label>Valor do destino</label><input id=ivrfvalue${i} value="${esc(v.fallback_value||'100')}"></div>
  </div>
  <h4>Áudio do IVR</h4><div class=row>
    <div><label>Telefone para gravar/testar</label><select id=ivrphone${i}>${ivrPhoneOptions(defaultPhone)}</select></div>
    <div><label>Código manual de gravação</label><input value="${esc(code)}" readonly></div>
    <div><label>Ficheiro atual</label><input value="${rec?esc(rec.filename)+' · '+esc(rec.duration_s||0)+' s':'Sem WAV gerido / som interno'}" readonly></div>
  </div>
  <div class=actions>
    <button class=btn onclick="useManagedIVR(${i})">Usar gravação gerida</button>
    <button class="btn primary" onclick="recordIVR(${i})">☎ Gravar pelo telefone</button>
    <button class=btn onclick="testIVR(${i})">Testar no telefone</button>
    <button class=btn onclick="playIVR(${i})">▶ Ouvir no browser</button>
    <label class=btn>⬆ Upload WAV<input type=file accept="audio/wav,.wav" style="display:none" onchange="uploadIVR(${i},this)"></label>
    ${rec?`<button class=btn onclick="deleteIVRAudio(${i})">Apagar WAV</button>`:''}
  </div>
  ${rec?`<audio controls preload=none src="api/ivr-audio?name=${encodeURIComponent(rec.name)}&v=${rec.modified||0}" style="width:100%;max-width:640px"></audio>`:''}
  <h4>Teclas</h4>
  ${(v.options||[]).map((o,j)=>`<div class=row><div><label>Tecla</label><select id=ivrdigit${i}_${j}>${ivrDigitOptions(o.digit)}</select></div><div><label>Descrição</label><input id=ivrlabel${i}_${j} value="${esc(o.label||'')}"></div><div><label>Tipo de destino</label><select id=ivrtype${i}_${j}>${ivrDestOptions(o.type||'extension')}</select></div><div><label>Destino</label><input id=ivrvalue${i}_${j} value="${esc(o.value||'')}"></div><div><label>&nbsp;</label><button class=btn onclick="delIVROpt(${i},${j})">Remover tecla</button></div></div>`).join('')}
  <div class=actions><button class=btn onclick="addIVROpt(${i})">+ Tecla</button><button class=btn onclick="delIVR(${i})">Remover IVR</button></div></div>`}).join('')}
  <div class=actions><button class=btn onclick=addIVR()>+ IVR</button><button class="btn primary" onclick=saveIVRs()>Guardar e aplicar</button></div>
  <h3>Gravações WAV disponíveis</h3>${recordings.length?recordings.map(r=>`<div class=item><b>${esc(r.sound_id)}</b> · ${esc(r.duration_s||0)} s · ${esc(r.sample_rate||0)} Hz · ${Math.round((r.size||0)/1024)} KB</div>`).join(''):'<div class=sub>Ainda não existem gravações personalizadas.</div>'}</div>`;
}
function addIVR(){captureIVRs();let i=(pbx.ivrs||[]).length;pbx.ivrs=pbx.ivrs||[];pbx.ivrs.push({enabled:true,id:'ivr'+(i+1),name:'Novo IVR',extension:String(600+i),prompt:'custom/ivr-'+(i+1),timeout:5,retries:3,invalid_prompt:'pbx-invalid',timeout_prompt:'',fallback_type:'extension',fallback_value:'100',options:[]});ivrs(E('#app'))}
function delIVR(i){captureIVRs();pbx.ivrs.splice(i,1);ivrs(E('#app'))}
function addIVROpt(i){captureIVRs();pbx.ivrs[i].options=pbx.ivrs[i].options||[];pbx.ivrs[i].options.push({digit:'1',label:'',type:'extension',value:'100'});ivrs(E('#app'))}
function delIVROpt(i,j){captureIVRs();pbx.ivrs[i].options.splice(j,1);ivrs(E('#app'))}
async function saveIVRs(){try{await persistIVRs();alert('IVR guardado e aplicado.');await render()}catch(e){alert(e.message)}}
function useManagedIVR(i){captureIVRs();let v=pbx.ivrs[i];let sound=ivrManagedSound(v);v.prompt=sound;E('#ivrprompt'+i).value=sound}
async function recordIVR(i){
  try{
    captureIVRs();let v=pbx.ivrs[i];let sound=ivrManagedSound(v);v.prompt=sound;E('#ivrprompt'+i).value=sound;
    await persistIVRs();
    let phone=E('#ivrphone'+i)?.value||((pbx.extensions||[])[0]||{}).extension||'';
    if(!phone) throw new Error('Escolhe uma extensão PJSIP para gravar.');
    let r=await api('api/action',{method:'POST',body:JSON.stringify({action:'ivr_record',ivr_id:v.id,source_extension:phone})});
    if(!r.ok) throw new Error(r.output||'Não foi possível iniciar a gravação.');
    alert(`A extensão ${phone} vai tocar. Atende, fala depois do beep e carrega # para terminar. Código manual: *77${v.extension}`);
    setTimeout(()=>ivrs(E('#app')),1500);
  }catch(e){alert(e.message||String(e))}
}
async function testIVR(i){
  try{captureIVRs();let v=pbx.ivrs[i];let phone=E('#ivrphone'+i)?.value||'';if(!phone)throw new Error('Escolhe uma extensão.');let r=await api('api/action',{method:'POST',body:JSON.stringify({action:'ivr_test',ivr_id:v.id,source_extension:phone,prompt:v.prompt})});if(!r.ok)throw new Error(r.output||'Falha no teste.');alert(`A extensão ${phone} vai tocar para reproduzir ${v.prompt}.`)}catch(e){alert(e.message||String(e))}
}
function playIVR(i){captureIVRs();let stem=ivrPromptStem(pbx.ivrs[i].prompt);if(!stem){alert('Este prompt é um som interno do Asterisk. Usa “Testar no telefone”.');return}let audio=new Audio('api/ivr-audio?name='+encodeURIComponent(stem)+'&v='+Date.now());audio.play().catch(()=>alert('Não foi possível reproduzir o WAV.'))}
async function uploadIVR(i,input){
  try{
    let file=input.files&&input.files[0];if(!file)return;if(file.size>15*1024*1024)throw new Error('Máximo 15 MB.');
    captureIVRs();let v=pbx.ivrs[i];let sound=ivrManagedSound(v);let stem=ivrPromptStem(sound);
    let data=await new Promise((resolve,reject)=>{let fr=new FileReader();fr.onload=()=>resolve(fr.result);fr.onerror=()=>reject(new Error('Falha ao ler WAV'));fr.readAsDataURL(file)});
    let r=await api('api/ivr-upload',{method:'POST',body:JSON.stringify({name:stem,data})});if(!r.ok)throw new Error(r.error||'Upload falhou');
    v.prompt=r.recording.sound_id;E('#ivrprompt'+i).value=v.prompt;await persistIVRs();alert(`WAV guardado: ${r.recording.sound_id}`);await ivrs(E('#app'));
  }catch(e){alert(e.message||String(e))}finally{input.value=''}
}
async function deleteIVRAudio(i){
  try{captureIVRs();let v=pbx.ivrs[i];let stem=ivrPromptStem(v.prompt);if(!stem)return;let r=await api('api/ivr-delete',{method:'POST',body:JSON.stringify({name:stem})});if(!r.ok)throw new Error(r.error||'Falha ao apagar');v.prompt='';E('#ivrprompt'+i).value='';await persistIVRs();await ivrs(E('#app'))}catch(e){alert(e.message||String(e))}
}
'''
        index = index.replace('function trunks(a){', js + '\nfunction trunks(a){')
    return index
