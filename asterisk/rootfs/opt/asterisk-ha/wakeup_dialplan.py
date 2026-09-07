#!/usr/bin/env python3
"""Install/update the persistent Asterisk wake-up playback context.

The add-on keeps /config/asterisk across upgrades, so changing only the image
extension template is not enough.  This migration is intentionally idempotent
and runs on every add-on start before Asterisk is launched.
"""
import re
from pathlib import Path

EXTENSIONS = Path('/config/asterisk/extensions.conf')
START = '; WAKEUP CALL CONTEXT MANAGED BY ASTERISK HA\n'
END = '; END WAKEUP CALL CONTEXT MANAGED BY ASTERISK HA\n'

BLOCK = (
    START
    + '[wakeup-call]\n'
    + 'exten => s,1,NoOp(Servico Despertar - reproducao protegida)\n'
    + ' same => n,Answer()\n'
    + ' same => n,Wait(1)\n'
    + '; Short generated tone proves RTP/media is established before speech.\n'
    + ' same => n,PlayTones(950/300)\n'
    + ' same => n,Wait(1)\n'
    + ' same => n,StopPlayTones()\n'
    + '; Try the Portuguese wake-up recording by absolute filesystem path.\n'
    + ' same => n,Playback(/var/lib/asterisk/sounds/pt_BR/this-is-yr-wakeup-call)\n'
    + ' same => n,GotoIf($["${PLAYBACKSTATUS}"="SUCCESS"]?done)\n'
    + '; Deterministic English Extra Sounds fallback, also by absolute path.\n'
    + ' same => n,Set(CHANNEL(language)=en)\n'
    + ' same => n,Playback(/var/lib/asterisk/sounds/en/this-is-yr-wakeup-call)\n'
    + ' same => n,GotoIf($["${PLAYBACKSTATUS}"="SUCCESS"]?done)\n'
    + '; Core-sounds fallback: never silently hang up just because the wake prompt is missing.\n'
    + ' same => n,Playback(hello)\n'
    + ' same => n,SayUnixTime(,,IMp)\n'
    + ' same => n(done),Wait(1)\n'
    + ' same => n,Hangup()\n'
    + END
)


def apply():
    if not EXTENSIONS.exists():
        return False
    text = EXTENSIONS.read_text(errors='ignore')
    text = re.sub(
        r'; WAKEUP CALL CONTEXT MANAGED BY ASTERISK HA\n.*?; END WAKEUP CALL CONTEXT MANAGED BY ASTERISK HA\n?',
        '',
        text,
        flags=re.S,
    ).rstrip()
    EXTENSIONS.write_text(text + '\n\n' + BLOCK)
    return True


if __name__ == '__main__':
    print('[Wakeup] playback dialplan %s' % ('updated' if apply() else 'not installed'))
