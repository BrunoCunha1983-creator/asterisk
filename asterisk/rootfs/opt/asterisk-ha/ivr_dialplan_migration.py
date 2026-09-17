#!/usr/bin/env python3
"""Ensure persistent Asterisk installs load generated IVR contexts.

/config/asterisk/extensions.conf survives add-on upgrades, so installs created
before IVR support may miss the include even though the current image template
contains it. This migration is intentionally idempotent and only adds the
missing include; it never rewrites existing user dialplan content.
"""
import re
from pathlib import Path

EXTENSIONS = Path('/config/asterisk/extensions.conf')
INCLUDE = '#include extensions_ivr_gui.conf'
MARKER = '; IVR CONTEXTS MANAGED BY ASTERISK HA'


def apply():
    if not EXTENSIONS.exists():
        return 'extensions.conf not installed'

    text = EXTENSIONS.read_text(errors='ignore')
    if re.search(r'^\s*#include\s+["\']?extensions_ivr_gui\.conf["\']?\s*$', text, re.I | re.M):
        return 'already present'

    suffix = '' if text.endswith('\n') else '\n'
    EXTENSIONS.write_text(text + suffix + '\n' + MARKER + '\n' + INCLUDE + '\n')
    return 'added'


if __name__ == '__main__':
    print(f'[IVR] persistent dialplan include: {apply()}')
