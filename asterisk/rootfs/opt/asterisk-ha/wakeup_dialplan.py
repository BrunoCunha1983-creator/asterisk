#!/usr/bin/env python3
"""Install/update the persistent Asterisk wake-up playback context.

The add-on keeps /config/asterisk across upgrades, so changing only the image
extension template is not enough. This migration is intentionally idempotent
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
    + 'exten => s,1,NoOp(Servico Despertar - engine 0.2.28)\n'
    + ' same => n,Answer()\n'
    + ' same => n,Wait(1)\n'
    + '; Generated tone verifies the channel remains alive before speech.\n'
    + ' same => n,PlayTones(950/300)\n'
    + ' same => n,Wait(1)\n'
    + ' same => n,StopPlayTones()\n'
    + '; Primary prompt is generated and bundled by this add-on itself.\n'
    + '; TryExec is deliberate: a missing/bad audio file must NEVER abort the call.\n'
    + ' same => n,TryExec(Playback(ha/wakeup-pt))\n'
    + ' same => n,NoOp(Wakeup bundled PT playback TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n,GotoIf($["${TRYSTATUS}"="SUCCESS"]?heard)\n'
    + '; Fallback to the packaged Asterisk English Extra Sounds prompt.\n'
    + ' same => n,Set(CHANNEL(language)=en)\n'
    + ' same => n,TryExec(Playback(this-is-yr-wakeup-call))\n'
    + ' same => n,NoOp(Wakeup English playback TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n,GotoIf($["${TRYSTATUS}"="SUCCESS"]?heard)\n'
    + '; Last file fallback. TryExec again prevents an early hangup.\n'
    + ' same => n,TryExec(Playback(hello))\n'
    + ' same => n,NoOp(Wakeup hello playback TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n(heard),Wait(3)\n'
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
