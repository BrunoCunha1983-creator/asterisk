# Asterisk 22 PBX + GSM for Home Assistant

Home Assistant App/Add-on containing Asterisk 22.11.0 and an Ingress management UI.

## Main functions

- PJSIP extensions and trunks
- SIP/RTP on the Home Assistant host network
- AMI and ARI enabled with generated credentials
- Active channels/endpoints and diagnostics
- Queue, ConfBridge, voicemail, MixMonitor/recording-ready modules
- CDR CSV and CEL event logging
- Call parking (700, spaces 701-720)
- Optional Huawei-compatible `chan_dongle`, controlled by the app option
- USB/UART/udev access without Docker `full_access`
- GSM modem detection, SMS and USSD from the Ingress UI
- Persistent configuration under the app's `app_config` directory
- `/share/asterisk-recordings` for recordings

## Hardware note

`chan_dongle` depends on the modem exposing serial interfaces usable for voice and AT commands. Many Huawei E-series devices require the correct USB mode/interface layout. The GUI exposes all `/dev/ttyUSB*` and `/dev/ttyACM*` interfaces so audio/data can be selected explicitly.

## Huawei 4G / número do SIM

A partir da versão **0.2.31**, cada perfil GSM pode guardar um **Número associado** (MSISDN) apenas como informação de identificação. O campo é opcional e, para o perfil **Huawei 4G**, fica vazio por defeito até o número real do SIM ser conhecido.

O número associado **não é escrito no `dongle.conf` e não altera o encaminhamento de chamadas**. O `chan_dongle` continua a depender apenas da configuração técnica do modem (portas Áudio e Dados/AT, contexto, grupo e ganhos). A página **GSM / chan_dongle** inclui também o atalho **+ Huawei 4G**, que cria o perfil com o número vazio e com portas fixas por identidade física ativadas.

## First test

1. Install/update the app and start it.
2. Open **Asterisk PBX** from Ingress and confirm Dashboard reports Asterisk ONLINE.
3. Add the PJSIP extensions used by your phones and save/apply.
4. For GSM, connect the modem, open **GSM / chan_dongle**, inspect the detected USB serial interfaces and create `dongle0` or use **+ Huawei 4G**.
5. Leave **Número associado** blank if the SIM number is not yet known, select the correct Audio and Data/AT ports, then save/apply.
6. In **Diagnóstico**, confirm `chan_dongle.so` is loaded and inspect `dongle show devices`.
