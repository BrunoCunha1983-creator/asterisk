#!/usr/bin/env bash
set -euo pipefail
AST_VERSION="${AST_VERSION:-22.11.0}"
DONGLE_REF="${DONGLE_REF:-31eb619600d5ce93237cd440c72db0bc33d7adfe}"
AST_SRC="${AST_SRC:-$(pwd)}"
PREFIX="${PREFIX:-/usr/local}"
WORK="${WORK:-$AST_SRC/.chan_dongle-build}"
mkdir -p "$WORK"
if [ ! -d "$WORK/asterisk-chan-dongle/.git" ]; then
  git clone https://github.com/wdoekes/asterisk-chan-dongle.git "$WORK/asterisk-chan-dongle"
fi
cd "$WORK/asterisk-chan-dongle"
git fetch --all --tags
git checkout "$DONGLE_REF"
./bootstrap
DESTDIR="$PREFIX/lib/asterisk/modules" ./configure \
  --with-asterisk="$AST_SRC/include" \
  --with-astversion="$AST_VERSION"
make -j"$(nproc)"
sudo install -D -m 755 chan_dongle.so "$PREFIX/lib/asterisk/modules/chan_dongle.so"
echo "chan_dongle installed to $PREFIX/lib/asterisk/modules/chan_dongle.so"
