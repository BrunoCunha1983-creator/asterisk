# Asterisk 22 para Home Assistant + chan_dongle

Projeto Asterisk para Home Assistant OS/Hass.io e versão standalone, ambos baseados em **Asterisk 22.11.0**.

## 1. Home Assistant Add-on

A pasta [`asterisk/`](asterisk/) contém o Add-on com:

- Asterisk 22.11.0
- PJSIP
- HT503 FXS/FXO
- SIPcord / Discord
- IVR gerido pela GUI
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
- API estruturada para Home Assistant em `/api/ha-state`

O build descarrega exatamente Asterisk 22.11.0 e valida o SHA-256 antes de compilar.

Para instalar como repositório de Add-ons no Home Assistant, use este repositório GitHub e instale **Asterisk 22 PBX + GSM**.

### IVR

No separador **IVR** da interface Web pode criar vários menus de voz. Cada IVR tem:

- ID e nome
- extensão interna de entrada, por exemplo `600`
- prompt/gravação Asterisk, por exemplo `custom/ivr-main`
- timeout e número de tentativas
- som de tecla inválida e timeout
- destino de fallback
- teclas `0-9`, `*` e `#`
- destinos para extensão, outro IVR, voicemail, SIPcord, GSM, HT503/PSTN ou desligar

A extensão de entrada permite reutilizar o IVR em qualquer rota. Exemplo: se o IVR Principal usa a extensão `600`, configure `600` como destino de chamadas recebidas do HT503 ou GSM.

Os prompts são identificadores de som Asterisk sem extensão. Exemplo: um ficheiro instalado como `custom/ivr-main.wav` é configurado na GUI como `custom/ivr-main`.

## 2. Integração Home Assistant / HACS

A pasta [`custom_components/asterisk_pbx/`](custom_components/asterisk_pbx/) contém uma integração própria para apresentar o Asterisk como dispositivo e entidades reais no Home Assistant.

### Instalação pelo HACS

1. Instale/abra o HACS.
2. Adicione este repositório como **Custom repository** do tipo **Integration**.
3. Instale **Asterisk PBX**.
4. Reinicie o Home Assistant.
5. Vá a **Definições → Dispositivos e Serviços → Adicionar integração → Asterisk PBX**.
6. Introduza o IP/hostname do Home Assistant onde o add-on corre e a porta `8099`.

Exemplo:

```text
Host: 192.168.1.139
Porta: 8099
Intervalo: 15
```

### Entidades criadas

O dispositivo **Asterisk PBX** inclui, entre outras:

- PBX online/offline
- versão do Asterisk
- chamadas ativas
- canais ativos
- chamadas processadas
- total de extensões
- extensões registadas/offline
- uma entidade de conectividade por extensão
- estado e RTT do HT503 FXO
- estado e RTT do SIPcord
- total de IVRs e IVRs ativos
- canais atualmente dentro de IVR
- sensor binário global `IVR em utilização`
- uma entidade de atividade por IVR
- trunks SIP
- dongles GSM totais/ligados

A integração usa polling local ao endpoint `/api/ha-state`; não envia credenciais SIP para o Home Assistant.

## 3. Asterisk 22.11.0 + chan_dongle standalone

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

O add-on e a integração Home Assistant são validados por GitHub Actions antes de merge para `main`.
