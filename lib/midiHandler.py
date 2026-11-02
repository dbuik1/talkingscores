__author__ = 'PMarchant'

import copy
import logging
import os
import re
import struct
import tempfile

from music21 import duration, note, repeat, stream, tempo

from pathvalidate import sanitize_filename

from talkingscores.settings import MEDIA_ROOT
from talkingscoreslib import Music21TalkingScore, join_split_bars, number_bars_in_order, parse_score

logger = logging.getLogger("TSScore")

# Part of every MIDI file name. A file already written under an older number was
# made by code that sounded different, so it is never served again and the
# cleanup command removes it.
MIDI_FORMAT = 2
# The longest a grace note sounds, in crotchets. Each grace note takes its time
# from the start of the note it decorates, so the bar still adds up.
GRACE_NOTE_LENGTH = 0.125
BAR_TAG = re.compile(r"^ts-bar-(\d+)$")


def safe_media_name(filename):
    """A file name that cannot leave the directory it is joined to."""
    cleaned = sanitize_filename(os.path.basename(filename or ""))
    if not cleaned or cleaned in (".", ".."):
        raise ValueError("The file name is not usable.")
    return cleaned


class MidiHandler:
    """One MIDI file per range of bars, holding every part at its written speed.

    Choosing parts, changing the speed, the metronome click and repeating a range
    all happen in the browser, so a range needs only this one file however it is
    played. Parts are written in score order, which is the order the reading page
    names them in, and a part resting through the range still gets its track so
    the browser can line the tracks up with the parts.
    """

    def __init__(self, request, folder, filename):
        self.request = request
        self.folder = folder
        # Everything the file name reaches is built by joining it onto the media
        # directory, so it is reduced to a bare name here rather than trusting the
        # URL to have kept it inside.
        self.filename = safe_media_name(filename)
        # Set by a caller that has already parsed the score, to save the reparse.
        self.score = None

    def midi_path(self, start, end, repeats=False):
        # A file played with its repeats holds more bars than its range names, so it
        # carries its own mark and is never served for the written range.
        played = "r" if repeats else ""
        return os.path.join(MEDIA_ROOT, self.folder, f"{self.filename}p{MIDI_FORMAT}{played}b{start}e{end}.mid")

    def requested_range(self):
        start = self.request.GET.get("start")
        end = self.request.GET.get("end")
        if start is None or end is None:
            return None, None
        return int(start), int(end)

    def requested_repeats(self):
        return self.request.GET.get("repeats") == "1"

    def get_or_make_midi_file(self):
        start, end = self.requested_range()
        return self.make_midi_file(start, end, repeats=self.requested_repeats())

    def score_bar_range(self):
        measures = self.score.parts[0].getElementsByClass(stream.Measure) if self.score.parts else []
        if not len(measures):
            raise ValueError("The score has no bars to play.")
        return measures[0].number, measures[-1].number

    def make_midi_file(self, start=None, end=None, repeats=False):
        # A range already written is served without reparsing the score.
        if start is not None and end is not None and os.path.exists(self.midi_path(start, end, repeats)):
            return self.midi_path(start, end, repeats)

        if not self.score:
            self.score = parse_score(os.path.join(MEDIA_ROOT, self.folder, self.filename))
        # The page asks for bars by the number they are read under, so the score the
        # audio is cut from has to be counted the same way. A score handed over by a
        # caller has been counted already, and counting it again changes nothing.
        number_bars_in_order(join_split_bars(self.score))
        first_bar, last_bar = self.score_bar_range()
        # A range reaching past the score writes the same file as the range that
        # stops at its last bar, so asking for bars that do not exist adds nothing
        # to the folder.
        start = first_bar if start is None else min(max(start, first_bar), last_bar)
        end = last_bar if end is None else min(max(end, start), last_bar)
        # Repeats are played only through the whole score: a group is played as it
        # is written, so it sounds the bars the reader is looking at.
        repeats = repeats and start == first_bar and end == last_bar

        path = self.midi_path(start, end, repeats)
        if os.path.exists(path):
            return path

        order = playing_order(self.score) if repeats else None
        if order:
            segment, bars = self.performed_score(order)
            offset = 0.0
            # The marks were copied in with the bars, and are laid out again below
            # from the bars' new places.
            for mark in list(segment.recurse().getElementsByClass(tempo.MetronomeMark)):
                mark.activeSite.remove(mark)
            tempo_source = self.performed_tempos(order)
        else:
            segment, bars, offset = self.written_range(start, end)
            tempo_source = self.score

        if not segment.parts:
            raise ValueError(f"No parts to write for bars {start} to {end}.")

        # MusicXML writes a transposing instrument's notes as the player reads them,
        # so a clarinet in B flat would sound a tone too high without this.
        segment.toSoundingPitch(inPlace=True)
        for part in segment.parts:
            shape_grace_notes(part)
        self.insert_tempos(segment, offset, tempo_source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Two requests can ask for the same range at once, so each writes its own
        # file and the last one to finish puts it in place whole.
        handle, partial_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".partial")
        os.close(handle)
        try:
            segment.write('midi', partial_path)
            add_bar_markers(partial_path, bars)
            os.replace(partial_path, path)
        finally:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        logger.info(f"Wrote MIDI for bars {start} to {end}: {path}")
        return path

    def written_range(self, start, end):
        """The bars from start to end of every part, as written, with where each bar starts."""
        segment = stream.Score(id='segment')
        first_measure = self.score.parts[0].measure(start) if self.score.parts else None
        offset = first_measure.offset if first_measure is not None else 0.0
        for part in self.score.parts:
            measures = part.measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature'))
            if measures is None:
                continue
            # Excerpting hands back the score's own bars, so the copy is what gets
            # changed: the MIDI writer follows repeat barlines and marks such as D.C.
            # al Fine, which inside an excerpt would play bars the reader is not
            # showing or fail outright, and the score itself is still described
            # with its repeats.
            measures = copy.deepcopy(measures)
            for measure in measures.getElementsByClass(stream.Measure):
                remove_repeat_marks(measure)
            segment.insert(0, measures)
        bars = []
        if segment.parts:
            for measure in segment.parts[0].getElementsByClass(stream.Measure):
                bars.append((measure.number, float(measure.offset)))
        return segment, bars, offset

    def performed_score(self, order):
        """Every part with its bars laid end to end in the order they are played."""
        segment = stream.Score(id='performance')
        for part in self.score.parts:
            by_number = {}
            for measure in part.getElementsByClass(stream.Measure):
                by_number.setdefault(measure.number, measure)
            played = stream.Part(id=part.id)
            instrument = part.getInstrument(returnDefault=False)
            if instrument is not None:
                played.insert(0, copy.deepcopy(instrument))
            at = 0.0
            for number in order:
                source = by_number.get(number)
                if source is None:
                    continue
                measure = copy.deepcopy(source)
                remove_repeat_marks(measure)
                played.insert(at, measure)
                at += source.duration.quarterLength
            segment.insert(0, played)
        bars = []
        at = 0.0
        lengths = {m.number: m.duration.quarterLength
                   for m in self.score.parts[0].getElementsByClass(stream.Measure)}
        for number in order:
            bars.append((number, at))
            at += lengths.get(number, 0.0)
        return segment, bars

    def performed_tempos(self, order):
        """The score's metronome marks, placed where each falls in the played order."""
        held = stream.Score()
        marks = list(self.score.metronomeMarkBoundaries())
        starts = {m.number: float(m.offset) for m in self.score.parts[0].getElementsByClass(stream.Measure)}
        lengths = {m.number: float(m.duration.quarterLength)
                   for m in self.score.parts[0].getElementsByClass(stream.Measure)}
        at = 0.0
        for number in order:
            bar_start = starts.get(number)
            if bar_start is None:
                continue
            bar_end = bar_start + lengths.get(number, 0.0)
            for mark_start, mark_end, mark in marks:
                if mark_end <= bar_start or mark_start >= bar_end:
                    continue
                # Each bar restates the speed it begins at, so a jump back to an
                # earlier bar picks up that bar's speed rather than the last one heard.
                held.insert(at + max(0.0, mark_start - bar_start), copy.deepcopy(mark))
            at += lengths.get(number, 0.0)
        return held

    def insert_tempos(self, segment, offset_start, source):
        """Carry the source's metronome marks into the excerpt, timed from its first bar."""
        length = segment.duration.quarterLength
        end_of_segment = offset_start + length
        last = None
        for start_offset, end_offset, mark in source.metronomeMarkBoundaries():
            if start_offset >= end_of_segment:
                break
            if end_offset > offset_start:
                number = Music21TalkingScore.fix_tempo_number(tempo=mark).number
                # A mark that began before the excerpt still applies to its first note.
                position = 0.001 if start_offset <= offset_start else start_offset - offset_start
                last = tempo.MetronomeMark(number=number, referent=mark.referent)
                segment.insert(position, last)
        if last is not None and length:
            # The written file ends with the last note, so bars of rests at the end of a
            # range would shorten it. Repeating the closing speed on the final barline
            # puts the end of the range in the file without changing how it sounds.
            segment.insert(length, tempo.MetronomeMark(number=last.number, referent=last.referent))


def remove_repeat_marks(measure):
    """Take out what the MIDI writer would follow as a repeat, leaving the bar to play once."""
    measure.removeByClass('Repeat')
    for mark in list(measure.recurse().getElementsByClass('RepeatExpression')):
        mark.activeSite.remove(mark)


def playing_order(score):
    """The bar numbers in the order the score is played, following its repeats.

    Returns None when the score has no repeats, or when they cannot be followed,
    so the bars are played as written. The first part decides the order and every
    part follows it, because expanding each part on its own can give parts of
    different lengths when one carries a mark the others lack.
    """
    if not score.parts:
        return None
    part = copy.deepcopy(score.parts[0])
    measures = list(part.getElementsByClass(stream.Measure))
    written = [measure.number for measure in measures]
    for measure in measures:
        measure.groups.append(f"ts-bar-{measure.number}")
    try:
        if not repeat.Expander(part).isExpandable():
            return None
        expanded = part.expandRepeats()
    except Exception:
        logger.info("The repeats could not be followed, so the bars play as written.")
        return None
    order = []
    for measure in expanded.getElementsByClass(stream.Measure):
        number = next((int(found.group(1)) for found in map(BAR_TAG.match, measure.groups) if found), None)
        if number is not None:
            order.append(number)
    if not order or order == written:
        return None
    return order


def shape_grace_notes(part):
    """Give each grace note a short length of its own, taken from the note it leads to.

    A grace note has no written length, and is written to the file as a note that
    stops before it starts, which leaves it sounding through to the end of the range.
    """
    containers = list(part.getElementsByClass(stream.Measure))
    for measure in list(containers):
        containers.extend(measure.getElementsByClass(stream.Voice))
    for container in containers:
        waiting = []
        for element in list(container.getElementsByClass(note.GeneralNote)):
            if element.duration.isGrace:
                waiting.append(element)
                continue
            if not waiting:
                continue
            if isinstance(element, note.Rest):
                for grace in waiting:
                    container.remove(grace)
                waiting = []
                continue
            main_length = element.duration.quarterLength
            each = min(GRACE_NOTE_LENGTH, main_length / (2 * len(waiting))) if main_length else 0
            begins = element.offset
            for index, grace in enumerate(waiting):
                if not each:
                    container.remove(grace)
                    continue
                grace.duration = duration.Duration(each)
                container.setElementOffset(grace, begins + index * each)
            if each:
                container.setElementOffset(element, begins + len(waiting) * each)
                element.duration = duration.Duration(main_length - len(waiting) * each)
            waiting = []
        # A grace note leading into the next bar has nothing here to take time from.
        for grace in waiting:
            container.remove(grace)


def _variable_length(value):
    out = [value & 0x7f]
    value >>= 7
    while value:
        out.insert(0, (value & 0x7f) | 0x80)
        value >>= 7
    return bytes(out)


def add_bar_markers(path, bars):
    """Add a track of markers naming each bar where it starts, as "bar 12".

    The page says each bar number as it is played, and a score played with its
    repeats reaches some bars twice, so the file itself says which bar is which.
    """
    if not bars:
        return
    with open(path, "rb") as midi_file:
        data = bytearray(midi_file.read())
    if data[:4] != b"MThd" or len(data) < 14:
        return
    division = struct.unpack(">H", data[12:14])[0]
    if division & 0x8000 or not division:
        return
    events = bytearray()
    previous = 0
    for number, quarters in bars:
        ticks = int(round(quarters * division))
        text = f"bar {number}".encode("ascii")
        events += _variable_length(max(0, ticks - previous)) + b"\xff\x06" + _variable_length(len(text)) + text
        previous = max(previous, ticks)
    events += b"\x00\xff\x2f\x00"
    tracks = struct.unpack(">H", data[10:12])[0]
    # A single-track file cannot hold a second track, and format 1 reads the same.
    data[8:10] = struct.pack(">H", 1)
    data[10:12] = struct.pack(">H", tracks + 1)
    data += b"MTrk" + struct.pack(">I", len(events)) + events
    with open(path, "wb") as midi_file:
        midi_file.write(data)
