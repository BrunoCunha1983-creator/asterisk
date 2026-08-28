#!/usr/bin/env bash
set -euo pipefail
AST_VERSION="22.11.0"
AST_SHA256="3bd5ee040509a3d3cd9b1ba9520c18e6ec0a7e7981ca68c457dcd36ba3c54d94"
BASE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$BASE/.build-standalone}"
OUT="${OUT:-$BASE/dist}"
SRC_URL="https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${AST_VERSION}.tar.gz"
rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"
wget -q "$SRC_URL" -O "$WORK/asterisk.tar.gz"
echo "$AST_SHA256  $WORK/asterisk.tar.gz" | sha256sum -c -
tar -xzf "$WORK/asterisk.tar.gz" -C "$WORK"
ROOT="$WORK/asterisk-${AST_VERSION}"
cp "$BASE/standalone/install-chan-dongle.sh" "$ROOT/install-chan-dongle.sh"
cp "$BASE/standalone/README-CHAN-DONGLE.md" "$ROOT/README-CHAN-DONGLE.md"
mv "$ROOT" "$WORK/asterisk-${AST_VERSION}-chan_dongle"
tar -C "$WORK" -czf "$OUT/asterisk-${AST_VERSION}-with-chan_dongle.tar.gz" "asterisk-${AST_VERSION}-chan_dongle"
sha256sum "$OUT/asterisk-${AST_VERSION}-with-chan_dongle.tar.gz"
