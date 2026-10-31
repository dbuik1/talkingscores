"""Score a reader's output against the answer for one page.

Two kinds of number per page:

- OMR-NED from musicdiff, the error measure the Sheet Music Benchmark uses:
  edits needed to turn the reader's score into the answer, divided by the
  symbols in both. 0 is perfect, 1 is nothing right. It is given once for
  everything on the page and once for notes and rests alone.
- How many of the answer's dynamics, articulations and lyric syllables the
  reader also found in the same bar, since those are what a talking score
  reads out besides the notes.
"""

import re
import warnings
from collections import Counter
from pathlib import Path

import converter21
import music21 as m21
from musicdiff import _diff_omr_ned_metrics
from musicdiff.detaillevel import DetailLevel

converter21.register()
warnings.filterwarnings("ignore", module=r"music21\..*")

MARKINGS = ("dynamics", "articulations", "lyrics")


def parse(path):
    try:
        score = m21.converter.parse(Path(path), forceSource=True)
    except Exception:
        return None
    if isinstance(score, m21.stream.Opus):
        score = score.scores[0] if score.scores else None
    return score


def omr_ned(predicted, truth, detail):
    if predicted is None or not Path(predicted).exists():
        return 1.0
    try:
        metrics = _diff_omr_ned_metrics(predpath=Path(predicted), gtpath=Path(truth), detail=detail)
    except Exception:
        return 1.0
    return 1.0 if metrics is None else metrics.omr_ned


def _lyric_text(text):
    return re.sub(r"[^\w]", "", text.lower())


def markings(score):
    """Count dynamics, articulations and lyric syllables, keyed by bar position."""
    found = {kind: Counter() for kind in MARKINGS}
    if score is None:
        return found
    for part in score.parts:
        for position, bar in enumerate(part.getElementsByClass(m21.stream.Measure)):
            for dynamic in bar.recurse().getElementsByClass(m21.dynamics.Dynamic):
                found["dynamics"][(position, dynamic.value)] += 1
            for note in bar.recurse().notes:
                for articulation in note.articulations:
                    found["articulations"][(position, type(articulation).__name__)] += 1
                for lyric in note.lyrics:
                    text = _lyric_text(lyric.text or "")
                    if text:
                        found["lyrics"][(position, text)] += 1
    return found


def score_item(predicted, truth):
    row = {
        "omr_ned": omr_ned(predicted, truth, DetailLevel.AllObjects),
        "omr_ned_notes": omr_ned(predicted, truth, DetailLevel.NotesAndRests),
    }
    expected = markings(parse(truth))
    got = markings(parse(predicted)) if predicted and Path(predicted).exists() else markings(None)
    for kind in MARKINGS:
        row[f"{kind}_expected"] = sum(expected[kind].values())
        row[f"{kind}_found"] = sum((expected[kind] & got[kind]).values())
    return row
