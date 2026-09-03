__author__ = 'PMarchant'

import logging
import os

from music21 import converter, stream, tempo

from talkingscores.settings import MEDIA_ROOT
from talkingscoreslib import Music21TalkingScore

logger = logging.getLogger("TSScore")


class MidiHandler:
    """One MIDI file per range of bars, holding every part at its written speed.

    Choosing parts, changing the speed, the metronome click and repeating a range
    all happen in the browser, so a range needs only this one file however it is
    played. Parts are written in score order, which is the order the reading page
    names them in.
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

    def make_midi_file(self, start=None, end=None):
        if not self.score:
            self.score = converter.parse(os.path.join(MEDIA_ROOT, self.folder, self.filename))
        if start is None or end is None:
            measures = self.score.parts[0].getElementsByClass('Measure')
            start, end = measures[0].number, measures[-1].number

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
            # A repeat mark inside an excerpt would play bars the reader is not showing.
            for measure in measures.getElementsByClass(stream.Measure):
                measure.removeByClass('Repeat')
            segment.insert(0, measures)

        if not segment.parts:
            raise ValueError(f"No parts to write for bars {start} to {end}.")

        self.insert_tempos(segment, offset)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Two requests can ask for the same range at once, so the file appears whole or not at all.
        partial_path = f"{path}.{os.getpid()}.partial"
        segment.write('midi', partial_path)
        os.replace(partial_path, path)
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
