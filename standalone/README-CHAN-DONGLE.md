# Asterisk 22.11.0 + chan_dongle

Esta pasta recria a variante standalone do Asterisk 22.11.0 com suporte para instalar `chan_dongle` contra os headers desta versão.

- Asterisk: `22.11.0`
- SHA-256 do source Asterisk: `3bd5ee040509a3d3cd9b1ba9520c18e6ec0a7e7981ca68c457dcd36ba3c54d94`
- `chan_dongle`: `wdoekes/asterisk-chan-dongle`
- commit fixo: `31eb619600d5ce93237cd440c72db0bc33d7adfe`

## Gerar o .tar.gz

```bash
./standalone/build-source-package.sh
```

O pacote é criado em `dist/asterisk-22.11.0-with-chan_dongle.tar.gz`.

## Instalar chan_dongle numa árvore Asterisk 22.11.0

Depois de compilar/instalar o Asterisk normalmente, copie `install-chan-dongle.sh` para a raiz do source Asterisk e execute:

```bash
./install-chan-dongle.sh
```

São necessários `git`, `autoconf`, `automake`, `libtool` e headers de SQLite, além das dependências normais do Asterisk.
