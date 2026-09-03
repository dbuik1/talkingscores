__author__ = 'PMarchant'

import copy
import logging
import os
import tempfile

from music21 import converter, stream, tempo

from talkingscores.settings import MEDIA_ROOT
from talkingscoreslib import Music21TalkingScore

logger = logging.getLogger("TSScore")


class MidiHandler:
    """One MIDI file per range of bars, holding every part at its written speed.

    Choosing parts, changing the speed, the metronome click and repeating a range
    all happen in the browser, so a range needs only this one file however it is
    played. Parts are written in score order, which is the order the reading page
    names them in, and a part resting through the range still gets its track so
    the browser can line the tracks up with the parts.
    """

    def __init__(self, request, folder, filename):
        self.queryString = request
        self.folder = folder
        self.filename = filename[:-4] if filename.lower().endswith(".mid") else filename
        # A caller that has already parsed the score passes it in to save the reparse.
        self.score = None

    def midi_path(self, start, end):
        return os.path.join(MEDIA_ROOT, self.folder, f"{self.filename}s{start}e{end}.mid")

    def requested_range(self):
        start = self.queryString.GET.get("start")
        end = self.queryString.GET.get("end")
        if start is None or end is None:
            return None, None
        return int(start), int(end)

    def get_or_make_midi_file(self):
        start, end = self.requested_range()
        return self.make_midi_file(start, end)

    def score_bar_range(self):
        measures = self.score.parts[0].getElementsByClass(stream.Measure) if self.score.parts else []
        if not len(measures):
            raise ValueError("The score has no bars to play.")
        return measures[0].number, measures[-1].number

    def make_midi_file(self, start=None, end=None):
        # A range already written is served without reparsing the score.
        if start is not None and end is not None and os.path.exists(self.midi_path(start, end)):
            return self.midi_path(start, end)

        if not self.score:
            self.score = converter.parse(os.path.join(MEDIA_ROOT, self.folder, self.filename))
        first_bar, last_bar = self.score_bar_range()
        # A range reaching past the score writes the same file as the range that
        # stops at its last bar, so asking for bars that do not exist adds nothing
        # to the folder.
        start = first_bar if start is None else min(max(start, first_bar), last_bar)
        end = last_bar if end is None else min(max(end, start), last_bar)

        path = self.midi_path(start, end)
        if os.path.exists(path):
            return path

        segment = stream.Score(id='segment')
        first_measure = self.score.parts[0].measure(start) if self.score.parts else None
        offset = first_measure.offset if first_measure is not None else 0.0
        for part in self.score.parts:
            measures = part.measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature'))
            if measures is None:
                continue
            # Excerpting hands back the score's own bars, so the copy is what gets
            # stripped: a repeat mark inside an excerpt would play bars the reader
            # is not showing, and the score itself is still described with repeats.
            measures = copy.deepcopy(measures)
            for measure in measures.getElementsByClass(stream.Measure):
                measure.removeByClass('Repeat')
            segment.insert(0, measures)

        if not segment.parts:
            raise ValueError(f"No parts to write for bars {start} to {end}.")

        self.insert_tempos(segment, offset)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Two requests can ask for the same range at once, so each writes its own
        # file and the last one to finish puts it in place whole.
        handle, partial_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".partial")
        os.close(handle)
        try:
            segment.write('midi', partial_path)
            os.replace(partial_path, path)
        finally:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        logger.info(f"Wrote MIDI for bars {start} to {end}: {path}")
        return path

    def insert_tempos(self, segment, offset_start):
        """Carry the score's metronome marks into the excerpt, timed from its first bar."""
        end_of_segment = offset_start + segment.duration.quarterLength
        for start_offset, end_offset, mark in self.score.metronomeMarkBoundaries():
            if start_offset >= end_of_segment:
                return
            if end_offset > offset_start:
                number = Music21TalkingScore.fix_tempo_number(tempo=mark).number
                # A mark that began before the excerpt still applies to its first note.
                position = 0.001 if start_offset <= offset_start else start_offset - offset_start
                segment.insert(position, tempo.MetronomeMark(number=number, referent=mark.referent))
