"""One bar of the same music, read once in each style, for the set-up page.

The samples come from the reading engine rather than a written-out table, so
what the set-up page shows a reader is what the style will produce.
"""

import os
from functools import lru_cache

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample_bar.musicxml")


def _sample_for(style):
    from lib.talkingscoreslib import HTMLTalkingScoreFormatter, Music21TalkingScore

    formatter = HTMLTalkingScoreFormatter(
        Music21TalkingScore(SAMPLE_PATH), options={"style": style, "bars_at_a_time": 1})
    # No web path, so the bar is described without a MIDI file being written for it.
    formatter.build()
    bar = formatter.segments[0].instruments[0].parts[0].bars[0]
    # Without the bar label: the sample is one bar, so naming it says nothing.
    return " ".join(line for line in bar.text_lines()[1:] if line)


@lru_cache(maxsize=1)
def style_samples():
    """{style id: the sample bar as that style reads it}."""
    from lib.render_settings import STYLE_IDS

    samples = {}
    for style in STYLE_IDS:
        try:
            samples[style] = _sample_for(style)
        except Exception:
            # A sample is an aid to choosing, so the set-up page still lists the
            # style when the sample cannot be built.
            samples[style] = ""
    return samples
