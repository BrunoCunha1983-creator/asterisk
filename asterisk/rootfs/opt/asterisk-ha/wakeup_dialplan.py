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
    + 'exten => s,1,NoOp(Servico Despertar - engine 0.2.29)\n'
    + ' same => n,Answer()\n'
    + ' same => n,Wait(1)\n'
    + '; Generated tone proves that RTP/media reached the answered channel.\n'
    + ' same => n,PlayTones(950/300)\n'
    + ' same => n,Wait(1)\n'
    + ' same => n,StopPlayTones()\n'
    + '; Primary prompt is generated and bundled by this add-on itself.\n'
    + '; Use an absolute path so language-prefix lookup cannot hide the file.\n'
    + '; TryExec guarantees that a media error never aborts the dialplan.\n'
    + ' same => n,Set(PLAYBACKSTATUS=)\n'
    + ' same => n,TryExec(Playback(/var/lib/asterisk/sounds/ha/wakeup-pt))\n'
    + ' same => n,NoOp(Wakeup bundled PT TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n,GotoIf($["${TRYSTATUS}"!="SUCCESS"]?classic)\n'
    + ' same => n,GotoIf($["${PLAYBACKSTATUS}"="SUCCESS"]?heard:classic)\n'
    + '; Fallback to the packaged Asterisk English Extra Sounds prompt.\n'
    + ' same => n(classic),Set(CHANNEL(language)=en)\n'
    + ' same => n,Set(PLAYBACKSTATUS=)\n'
    + ' same => n,TryExec(Playback(this-is-yr-wakeup-call))\n'
    + ' same => n,NoOp(Wakeup classic TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n,GotoIf($["${TRYSTATUS}"!="SUCCESS"]?hello)\n'
    + ' same => n,GotoIf($["${PLAYBACKSTATUS}"="SUCCESS"]?heard:hello)\n'
    + '; Core-sounds fallback.\n'
    + ' same => n(hello),Set(PLAYBACKSTATUS=)\n'
    + ' same => n,TryExec(Playback(hello))\n'
    + ' same => n,NoOp(Wakeup hello TRYSTATUS=${TRYSTATUS} PLAYBACKSTATUS=${PLAYBACKSTATUS})\n'
    + ' same => n,GotoIf($["${TRYSTATUS}"!="SUCCESS"]?emergency-tone)\n'
    + ' same => n,GotoIf($["${PLAYBACKSTATUS}"="SUCCESS"]?heard:emergency-tone)\n'
    + '; File-independent final fallback: keep the call alive and send an audible tone.\n'
    + ' same => n(emergency-tone),PlayTones(950/300)\n'
    + ' same => n,Wait(2)\n'
    + ' same => n,StopPlayTones()\n'
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
