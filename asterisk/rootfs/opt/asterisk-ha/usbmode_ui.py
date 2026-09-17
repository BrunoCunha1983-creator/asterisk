#!/usr/bin/env python3
"""Merge USB/modem tooling into the GSM/chan_dongle page.

The old UI exposed USB discovery/mode-switch and chan_dongle configuration as
separate tabs even though they are one workflow. This layer runs after gsm_ui
and folds the USB tools into that page without changing the GSM backend.
"""


def augment_index(index):
    # Remove the legacy standalone tab/dispatcher if an older UI layer inserted
    # them, then rename the remaining GSM page to describe the unified workflow.
    index = index.replace("'USB / Modems',", "", 1)
    index = index.replace(",'USB / Modems'", "", 1)
    index = index.replace(
        "if(current==='USB / Modems') usbmodems(a); ",
        "",
        1,
    )
    index = index.replace("'GSM / chan_dongle'", "'USB / GSM'", 1)
    index = index.replace(
        "if(current==='GSM / chan_dongle') gsm(a);",
        "if(current==='USB / GSM') gsm(a);",
        1,
    )

    # Use the richer usb-tools endpoint as the one hardware scan for this page.
    # It already contains the same serial/raw USB inventory plus modeswitch state.
    old_scan = """  let ports=[];\n  try{ports=await api('api/usb')}catch(e){ports=[]}\n  let h={};"""
    new_scan = """  let usb={devices:[]};\n  try{usb=await api('api/usb-tools-status')}catch(e){usb={devices:[],error:String(e)}}\n  let ports=usb.devices||[];\n  let h={};"""
    if old_scan in index:
        index = index.replace(old_scan, new_scan, 1)

    # Converting between stable IDs and ttyUSBx must work in both directions.
    old_canonical = """function gsmCanonicalPort(value,locked){\n  value=String(value||'');\n  if(!locked) return value;\n  let p=gsmPortForValue(value);\n  return p?gsmStablePath(p):value;\n}"""
    new_canonical = """function gsmCanonicalPort(value,locked){\n  value=String(value||'');\n  let p=gsmPortForValue(value);\n  if(!p) return value;\n  return locked?gsmStablePath(p):String(p.device||value);\n}"""
    if old_canonical in index:
        index = index.replace(old_canonical, new_canonical, 1)

    helpers = r'''
function gsmCaptureForm(){
  let list=pbx.gsm_dongles||[];
  if(!list.length || !E('#dn0')) return;
  pbx.gsm_dongles=list.map((d,i)=>{
    if(!E('#dn'+i)) return d;
    let locked=E('#dl'+i).value==='1';
    return Object.assign({},d,{
      name:E('#dn'+i).value,
      phone_number:E('#dnum'+i).value.trim(),
      audio:gsmCanonicalPort(E('#da'+i).value,locked),
      data:gsmCanonicalPort(E('#dd'+i).value,locked),
      context:E('#dc'+i).value,
      group:+E('#dg'+i).value,
      rxgain:+E('#dr'+i).value,
      txgain:+E('#dt'+i).value,
      lock_ports:locked
    });
  });
}
async function gsmLockChange(){
  gsmCaptureForm();
  await gsm(E('#app'));
}
async function switchHuawei1505Unified(){
  if(!confirm('Executar usb_modeswitch no Huawei 12d1:1505? O PID USB vai mudar e um passthrough Proxmox preso a 12d1:1505 pode perder o modem.')) return;
  try{
    let r=await api('api/usb-action',{method:'POST',body:JSON.stringify({action:'switch_huawei_1505'})});
    let msg=(r.output||'')+(r.warning?'\n\n'+r.warning:'')+(r.new_huawei_ids&&r.new_huawei_ids.length?'\n\nNovo PID: '+r.new_huawei_ids.join(', '):'');
    alert(msg||JSON.stringify(r));
  }catch(e){
    alert('Falha no mode-switch: '+String(e));
  }
  await gsm(E('#app'));
}
'''
    if 'function gsmCaptureForm()' not in index and 'async function gsm(a){' in index:
        index = index.replace('async function gsm(a){', helpers + '\nasync function gsm(a){', 1)

    # Changing lock mode used to redraw from pbx.json and discard unsaved edits.
    index = index.replace(
        "onchange=\"gsm(E('#app'))\"",
        'onchange="gsmLockChange()"',
    )
    index = index.replace(
        "function addDongle(){\n  let i=",
        "function addDongle(){\n  gsmCaptureForm();\n  let i=",
        1,
    )
    index = index.replace(
        "function addHuaweiDongle(){\n  pbx.gsm_dongles=pbx.gsm_dongles||[];",
        "function addHuaweiDongle(){\n  gsmCaptureForm();\n  pbx.gsm_dongles=pbx.gsm_dongles||[];",
        1,
    )

    # Add unified USB/modeswitch status variables beside the existing Huawei
    # detection. Diagnostic entries from HAOS/Supervisor are surfaced too.
    old_huawei = """  let huawei1505=rawUsb.find(p=>String(p.usb_id||'').toLowerCase()==='12d1:1505');"""
    new_huawei = """  let huawei1505=rawUsb.find(p=>String(p.usb_id||'').toLowerCase()==='12d1:1505');\n  let diagnostics=(ports||[]).filter(p=>p.kind==='diagnostic');\n  let diagnosticNote=diagnostics.length?`<div class=note><b>Diagnóstico USB:</b> ${esc(JSON.stringify(diagnostics.map(x=>x.diagnostic||{})))}</div>`:'';\n  let canModeSwitch=!!(usb.huawei_1505_present&&usb.usb_modeswitch_installed&&usb.config_12d1_1505);\n  let modeButton=usb.huawei_1505_present?`<button class=\"btn ${canModeSwitch?'primary':''}\" ${canModeSwitch?'':'disabled'} onclick=\"switchHuawei1505Unified()\">Mudar Huawei 12d1:1505 para modo modem</button>`:'';"""
    if old_huawei in index:
        index = index.replace(old_huawei, new_huawei, 1)

    old_warn = """  let huaweiWarn=huawei1505?'<div class=note><b>Huawei detetado como 12d1:1505.</b> O USB chegou à VM, mas está no modo inicial/storage e ainda pode não criar as portas tty do modem. Não faço mode-switch automático porque o PID muda e um passthrough Proxmox preso a 12d1:1505 pode perder o dispositivo após a mudança.</div>':'';"""
    new_warn = """  let huaweiWarn=huawei1505?'<div class=note><b>Huawei detetado como 12d1:1505.</b> Está no modo inicial/storage. Podes executar o mode-switch manualmente nesta mesma página; atenção que o PID USB muda e um passthrough Proxmox preso ao PID pode perder o dispositivo.</div>':'';"""
    if old_warn in index:
        index = index.replace(old_warn, new_warn, 1)

    # Fold the old USB status cards and action into the GSM page itself.
    old_heading = '<div class=card><h2>chan_dongle / GSM</h2>'
    new_heading = '''<div class=card><h2>USB / Modems + GSM / chan_dongle</h2><div class=grid><div class=card><div class=sub>usb_modeswitch</div><div class="big ${usb.usb_modeswitch_installed?'ok':'bad'}">${usb.usb_modeswitch_installed?'INSTALADO':'AUSENTE'}</div></div><div class=card><div class=sub>Perfil Huawei 12d1:1505</div><div class="big ${usb.config_12d1_1505?'ok':'bad'}">${usb.config_12d1_1505?'OK':'FALTA'}</div></div><div class=card><div class=sub>Huawei 12d1:1505</div><div class="big ${usb.huawei_1505_present?'warn':'ok'}">${usb.huawei_1505_present?'MODO INICIAL':'NÃO DETETADO'}</div></div></div>'''
    if old_heading in index:
        index = index.replace(old_heading, new_heading, 1)

    old_actions = '''<div class=actions><button class=btn onclick="gsm(E('#app'))">Redetetar USB</button><button class=btn onclick="dongleShow()">Estado chan_dongle</button></div>'''
    new_actions = '''<div class=actions><button class=btn onclick="gsmCaptureForm();gsm(E('#app'))">Redetetar USB</button>${modeButton}<button class=btn onclick="dongleShow()">Estado chan_dongle</button></div>${diagnosticNote}'''
    if old_actions in index:
        index = index.replace(old_actions, new_actions, 1)

    return index
