# Asterisk 22 PBX + GSM for Home Assistant

Home Assistant App/Add-on containing Asterisk 22.11.0 and an Ingress management UI.

## Main functions

- PJSIP extensions and trunks
- SIP/RTP on the Home Assistant host network
- AMI and ARI enabled with generated credentials
- Active channels/endpoints and diagnostics
- Queue, ConfBridge, voicemail, MixMonitor/recording-ready modules
- CDR/CEL configuration foundation
- Optional Huawei-compatible `chan_dongle`
- USB/UART/udev access without Docker `full_access`
- GSM modem detection, SMS and USSD from the Ingress UI
- Persistent configuration under the app's `addon_config` directory
- `/share/asterisk-recordings` for recordings

## Hardware note

`chan_dongle` depends on the modem exposing serial interfaces usable for voice and AT commands. Many Huawei E-series devices require the correct USB mode/interface layout. The GUI exposes all `/dev/ttyUSB*` and `/dev/ttyACM*` interfaces so audio/data can be selected explicitly.

## First test

1. Install the local app/add-on.
2. Start it and open **Asterisk PBX** from Ingress.
3. Confirm Dashboard reports Asterisk ONLINE.
4. Add a PJSIP extension and save.
5. For GSM, connect the modem, open **GSM / chan_dongle**, inspect the detected USB serial interfaces and create `dongle0`.
