# Asterisk 22 para Home Assistant + chan_dongle

Projeto Asterisk para Home Assistant OS/Hass.io e versão standalone, ambos baseados em **Asterisk 22.11.0**.

## 1. Home Assistant Add-on

A pasta [`asterisk/`](asterisk/) contém o Add-on com:

- Asterisk 22.11.0
- PJSIP
- AMI
- ARI + WebSocket
- Ingress GUI
- extensões e trunks pela GUI
- filas, ConfBridge, voicemail, gravações/CDR/CEL
- `chan_dongle` opcional
- deteção de `/dev/ttyUSB*` e `/dev/ttyACM*`
- chamadas GSM, SMS e USSD
- acesso USB/UART/udev
- configuração persistente em `addon_config`

O build descarrega exatamente Asterisk 22.11.0 e valida o SHA-256 antes de compilar.

Para instalar como repositório de Add-ons no Home Assistant, use este repositório GitHub e instale **Asterisk 22 PBX + GSM**.

## 2. Asterisk 22.11.0 + chan_dongle standalone

A pasta [`standalone/`](standalone/) contém o instalador do `chan_dongle` e um gerador do pacote standalone:

```bash
./standalone/build-source-package.sh
```

Isto gera `dist/asterisk-22.11.0-with-chan_dongle.tar.gz`.

## Versões fixadas

- Asterisk: `22.11.0`
- SHA-256 source: `3bd5ee040509a3d3cd9b1ba9520c18e6ec0a7e7981ca68c457dcd36ba3c54d94`
- chan_dongle commit: `31eb619600d5ce93237cd440c72db0bc33d7adfe`

## Estado

Versão inicial `0.1.0`. A GUI e geração dos ficheiros de configuração foram validadas localmente. O próximo teste é o build/arranque no Home Assistant OS com modem GSM real.
