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

## First test

1. Install/update the app and start it.
2. Open **Asterisk PBX** from Ingress and confirm Dashboard reports Asterisk ONLINE.
3. Add the PJSIP extensions used by your phones and save/apply.
4. For GSM, connect the modem, open **GSM / chan_dongle**, inspect the detected USB serial interfaces and create `dongle0`.
5. In **Diagnóstico**, confirm `chan_dongle.so` is loaded and inspect `dongle show devices`.
