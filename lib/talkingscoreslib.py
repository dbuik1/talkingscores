"""
Talking Scores library: reads a MusicXML file and builds the talking score.

Music21TalkingScore extracts musical facts from the file. HTMLTalkingScoreFormatter
turns those facts into the score page, the text download and the braille download,
using the reading settings stored beside the score.
"""

import copy
import json
import logging
import math
import os
import re
from abc import ABCMeta, abstractmethod
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader
from music21 import converter, duration, environment, key, meter, stream
from music21 import pitch as pitch_module
from music21.stream import makeNotation
from django.conf import settings as django_settings

from lib.braille import text_to_brf
from lib.description import (
    DescriptionBuilder, Fact, InstrumentDescription, ScoreFacts, SegmentDescription,
    clean_colour_map, segments_to_text,
)
from lib.events import TSChord, TSChordSymbol, TSDynamic, TSNote, TSPitch, TSRest, TSUnpitched
from lib.musicAnalyser import MusicAnalyser
from lib.render_settings import RenderSettings
from lib.vocabulary import AMERICAN_DURATIONS, BRITISH_DURATIONS, DOT_WORDS, Vocabulary

us = environment.UserSettings()
us['warnings'] = 0
# music21 caches every parsed score as a pickle and reads those pickles back. In
# a world-writable temporary directory that cache is a way into this process, so
# it is kept beside the scores instead.
_scratch = os.path.join(django_settings.MEDIA_ROOT, "music21")
os.makedirs(_scratch, exist_ok=True)
us['directoryScratch'] = _scratch
logger = logging.getLogger("TSScore")

UNTITLED = "Untitled work"
UNKNOWN_COMPOSER = "Unknown composer"
NOT_GIVEN = "not given"


def mark_tuplet_brackets(measure_stream):
    """Work out where each tuplet begins and ends, for scores that do not say.

    A tuplet is written with a bracket or number over it, but the file need only
    carry the time modification on each note; without a start and a stop nothing
    in the bar is read as a tuplet at all.
    """
    try:
        makeNotation.makeTupletBrackets(measure_stream, inPlace=True)
    except Exception:
        pass


def alter_name(alter):
    """The accidental name for a written alteration, or None if there is not one."""
    try:
        return pitch_module.Accidental(alter or 0).name
    except Exception:
        return None


def get_accidental_steps(num_accidentals):
    """Pitch names, with symbol, that a key signature alters. -2 gives ['B♭', 'E♭']."""
    sharp_order = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
    flat_order = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
    if num_accidentals > 0:
        return [s + '♯' for s in sharp_order[:num_accidentals]]
    if num_accidentals < 0:
        return [f + '♭' for f in flat_order[:abs(num_accidentals)]]
    return []


class TalkingScoreBase(object, metaclass=ABCMeta):
    @abstractmethod
    def get_title(self):
        pass

    @abstractmethod
    def get_composer(self):
        pass


class Music21TalkingScore(TalkingScoreBase):
    """Facts about a MusicXML score, read through music21."""

    def __init__(self, musicxml_filepath, settings=None):
        self.filepath = os.path.realpath(musicxml_filepath)
        self.score = converter.parse(musicxml_filepath)
        self.timeSigs = {}
        self.part_instruments = {}
        self.part_names = {}
        self.selected_instruments = []
        self.unselected_instruments = []
        self.selected_part_names = []
        self.use_settings(settings or RenderSettings())
        super().__init__()

    def use_settings(self, settings):
        self.settings = settings
        self.vocabulary = Vocabulary(settings)

    # Title and composer

    def get_title(self):
        if self.score.metadata.title:
            return self.score.metadata.title
        for tb in self.score.flatten().getElementsByClass('TextBox'):
            if (getattr(tb, 'justify', None) == 'center' and
                    getattr(tb, 'alignVertical', None) == 'top' and
                    (getattr(tb, 'size', 0) or 0) > 18):
                return tb.content
        return UNTITLED

    def get_composer(self):
        if self.score.metadata.composer:
            return self.score.metadata.composer
        for tb in self.score.getElementsByClass('TextBox'):
            if tb.style.justify == 'right':
                return tb.content
        return UNKNOWN_COMPOSER

    # Time, key and tempo

    def get_initial_time_signature(self):
        return self.describe_time_signature(self._get_initial_time_signature_object())

    def describe_time_signature(self, ts):
        if ts is None:
            return NOT_GIVEN
        return " ".join(ts.ratioString.split("/"))

    def get_initial_key_signature(self):
        m1 = self.score.parts[0].measures(1, 1)
        key_signatures = m1.flatten().getElementsByClass('KeySignature')
        ks = key_signatures[0] if key_signatures else key.KeySignature(0)
        return self.describe_key_signature(ks)

    def describe_key_signature(self, ks):
        """For example "B♭ major (2 flats: B♭, E♭)"."""
        m21key = ks.asKey() if isinstance(ks, key.KeySignature) and not isinstance(ks, key.Key) else ks
        tonic = m21key.tonic.name.replace('-', '♭').replace('#', '♯')
        tonic = tonic[0].upper() + tonic[1:]
        mode = m21key.mode
        count = ks.sharps
        if count == 0:
            return f"{tonic} {mode} (no sharps or flats)"
        word = "sharp" if count > 0 else "flat"
        if abs(count) > 1:
            word += "s"
        return f"{tonic} {mode} ({abs(count)} {word}: {', '.join(get_accidental_steps(count))})"

    def get_initial_text_expression(self):
        m1 = self.score.parts[0].measures(1, 1)
        for te in m1.flatten().getElementsByClass('TextExpression'):
            return te.content
        return None

    def get_initial_tempo(self):
        """The tempo mark at the start of the piece, or nothing when the file gives none."""
        marks = self.score.flatten().getElementsByClass('MetronomeMark')
        if not marks:
            return ""
        first_bar = self.score.parts[0].getElementsByClass('Measure')[0].number
        mark = marks[0]
        if mark.measureNumber is not None and mark.measureNumber > first_bar:
            return ""
        return self.describe_tempo(mark)

    @staticmethod
    def fix_tempo_number(tempo):
        """A tempo mark with no number plays at 120, or at its sounding number when given."""
        if tempo.number is None:
            tempo.number = tempo.numberSounding if tempo.numberSounding is not None else 120
        return tempo

    def describe_tempo(self, tempo):
        tempo = self.fix_tempo_number(tempo)
        beats = f"{math.floor(tempo.number)} {self.describe_tempo_referent(tempo)} beats a minute"
        if tempo.text:
            return f"{tempo.text} ({beats})"
        return beats

    def describe_tempo_referent(self, tempo):
        """The beat a metronome mark counts, always as a note name."""
        referent = tempo.referent
        table = AMERICAN_DURATIONS if self.settings.duration_names == 'american' else BRITISH_DURATIONS
        base = table.get(referent.type, referent.type)
        return f"{DOT_WORDS.get(referent.dots, '')} {base}".strip()

    def get_beat_division_options(self):
        """Ways of grouping a bar's events, from the first time signature."""
        ts = self._get_initial_time_signature_object()
        if not ts:
            return []
        options = []
        seen = set()

        def add_option(display, value):
            if value not in seen:
                options.append({'display': display, 'value': value})
                seen.add(value)

        add_option('Whole bar, no beat numbers', 'bar')
        default_name = self._british_name(ts.beatDuration)
        add_option(f"{ts.beatCount} {default_name} beats (usual for this time signature)",
                   f"{ts.beatCount}/{ts.beatDuration.quarterLength}")
        face_value = duration.Duration(4.0 / ts.denominator)
        add_option(f"{ts.numerator} {self._british_name(face_value)} beats",
                   f"{ts.numerator}/{ts.denominator}")
        if ts.numerator % 3 == 0 and ts.numerator > 3:
            compound_count = ts.numerator // 3
            compound_ql = (4.0 / ts.denominator) * 3
            add_option(f"{compound_count} dotted {self._british_name(face_value)} beats",
                       f"{compound_count}/{compound_ql}")
        return options

    @staticmethod
    def _british_name(dur):
        return BRITISH_DURATIONS.get(dur.type, dur.type)

    def _get_initial_time_signature_object(self):
        try:
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            for item in first_measure:
                if isinstance(item, meter.TimeSignature):
                    return item
            time_signatures = self.score.getTimeSignatures()
            return time_signatures[0] if time_signatures else None
        except Exception as exc:
            logger.error(f"Could not find a time signature: {exc}")
            return None

    def beat_quarter_length(self, bar_number):
        """Length of one counted beat in the given bar, in quarter notes."""
        if self.settings.beat_unit:
            return float(self.settings.beat_unit)
        ts = self.timeSigs.get(bar_number) or self._get_initial_time_signature_object()
        if ts is None:
            return 1.0
        return float(ts.beatDuration.quarterLength)

    def get_number_of_bars(self):
        """Counted by bar number, the same way the bars are described."""
        measures = self.score.parts[0].getElementsByClass('Measure')
        if not measures:
            return 0
        return measures[-1].number - measures[0].number + 1

    # Instruments and parts

    def get_instruments(self):
        """Group the score's parts by instrument. Returns the instrument names in order."""
        self.part_instruments = {}
        self.part_names = {}
        instrument_names = []
        ins_count = 1
        # One entry per part, taken from the part itself: an instrument change part
        # way through a part would otherwise count as another part, and the numbers
        # here are read as positions in the score's parts.
        for c, part in enumerate(self.score.parts):
            # A notation program can leave the instrument inside the first bar rather
            # than on the part, and an unnamed part still has to be told from the next.
            instrument = part.getInstrument(recurse=True)
            part_id = instrument.partId or part.id
            if (len(self.part_instruments) == 0 or
                    self.part_instruments[ins_count - 1][3] != part_id):
                part_name = (instrument.partName or "").strip()
                # Notation programs leave "(Inst3)" style names on parts nobody named.
                if not part_name or re.fullmatch(r"\(Inst\d+\)", part_name):
                    part_name = f"Instrument {ins_count} (unnamed)"
                self.part_instruments[ins_count] = [part_name, c, 1, part_id]
                instrument_names.append(part_name)
                ins_count += 1
            else:
                self.part_instruments[ins_count - 1][2] += 1
                self._assign_part_names(c, ins_count - 1)
        logger.debug(f"part instruments = {self.part_instruments}")
        return instrument_names

    def _assign_part_names(self, current_index, instrument_index):
        part_count = self.part_instruments[instrument_index][2]
        if part_count == 2:
            self.part_names[current_index - 1] = "Right hand"
            self.part_names[current_index] = "Left hand"
        elif part_count == 3:
            self.part_names[current_index - 2] = "Part 1"
            self.part_names[current_index - 1] = "Part 2"
            self.part_names[current_index] = "Part 3"
        else:
            self.part_names[current_index] = f"Part {part_count}"

    def part_name(self, ins, part_index):
        """Name of one part of an instrument; the instrument name when it has one part."""
        ins_name = self.part_instruments[ins][0]
        if self.part_instruments[ins][2] == 1:
            return ins_name
        return f"{ins_name} - {self.part_names.get(part_index, f'Part {part_index + 1}')}"

    def compare_parts_with_selected_instruments(self):
        """Work out which instruments are read and which playback options apply."""
        chosen = list(self.settings.instruments or [])
        chosen = [int(i) for i in chosen if str(i).isdigit()]
        if not any(ins in chosen for ins in self.part_instruments):
            chosen = list(self.part_instruments)

        self.selected_instruments = []
        self.unselected_instruments = []
        self.selected_part_names = []

        for ins in self.part_instruments:
            if ins in chosen:
                self.selected_instruments.append(ins)
            else:
                self.unselected_instruments.append(ins)

        for ins in self.selected_instruments:
            first_part_index = self.part_instruments[ins][1]
            part_count = self.part_instruments[ins][2]
            for part_index in range(first_part_index, first_part_index + part_count):
                self.selected_part_names.append(self.part_name(ins, part_index))

        self._configure_playback_options()

    def _configure_playback_options(self):
        settings = self.settings

        if len(self.part_instruments) == 1:
            settings.play_all = False
            settings.play_selected = False
        if len(self.unselected_instruments) == 0:
            settings.play_unselected = False
        if len(self.selected_instruments) == len(self.part_instruments) and settings.play_all:
            settings.play_selected = False
        if len(self.selected_instruments) == 1:
            settings.play_selected = False

    def get_number_of_parts(self):
        self.get_instruments()
        return len(self.part_instruments)

    def get_bar_range(self, range_start, range_end):
        measures = self.score.measures(range_start, range_end)
        bars_for_parts = {}
        for part in measures.parts:
            bars_for_parts.setdefault(part.id, []).extend(part.getElementsByClass('Measure'))
        return bars_for_parts

    # Events

    def _pickup_measure_stream(self, part_index):
        """A copy of the first measure numbered 0, when it is shorter than the bar."""
        part = self.score.parts[part_index]
        all_measures = part.getElementsByClass('Measure')
        measures = stream.Stream()
        if not all_measures:
            return measures
        first_measure = all_measures[0]
        pickup = copy.deepcopy(first_measure)
        pickup.number = 0
        if not pickup.getElementsByClass(meter.TimeSignature):
            ts = self.timeSigs.get(first_measure.number) or self.timeSigs.get(first_measure.number + 1)
            if ts is not None:
                pickup.insert(0, ts)
        measures.append(pickup)
        return measures

    def get_events_for_bar_range(self, start_bar, end_bar, part_index):
        """Events for each bar in the range: {bar: [time point, ...]}."""
        intermediate_events = {}
        if start_bar == 0:
            measures = self._pickup_measure_stream(part_index)
        else:
            measures = self.score.parts[part_index].measures(start_bar, end_bar)
            first = measures.measure(start_bar)
            if (first is not None and not first.getElementsByClass(meter.TimeSignature)
                    and start_bar in self.timeSigs and self.timeSigs[start_bar] is not None):
                first.insert(0, self.timeSigs[start_bar])

        for bar_index in range(start_bar, end_bar + 1):
            if start_bar == 0:
                found = measures.getElementsByClass('Measure')
                measure = found[0] if found else None
            else:
                measure = measures.measure(bar_index)
            if measure is None:
                logger.warning(f'No measure found for bar {bar_index} in part {part_index}')
                continue
            original_number = measure.number
            measure.number = bar_index
            # Accidentals last until the bar line, so each bar starts from the key signature alone.
            state = self._key_signature_alters(measure)
            self.update_events_for_measure(measure, intermediate_events, state=state)
            measure.number = original_number

        if self.settings.dynamics:
            self._add_dynamic_spanners(part_index, start_bar, end_bar, intermediate_events)

        return self._organize_events_by_time_point(intermediate_events, start_bar, end_bar)

    def bar_lengths(self, start_bar, end_bar, part_index):
        """{bar: (written bar length, actual length)} in quarter notes."""
        lengths = {}
        part = self.score.parts[part_index]
        for bar_index in range(start_bar, end_bar + 1):
            if bar_index == 0:
                found = part.getElementsByClass('Measure')
                measure = found[0] if found else None
            else:
                measure = part.measure(bar_index)
            if measure is None:
                continue
            ts = self.timeSigs.get(bar_index) or measure.timeSignature
            written = float(ts.barDuration.quarterLength) if ts is not None else float(measure.duration.quarterLength)
            lengths[bar_index] = (written, float(measure.duration.quarterLength))
        return lengths

    def _add_dynamic_spanners(self, part_index, start_bar, end_bar, intermediate_events):
        names = {'Crescendo': ('Crescendo starts', 'Crescendo ends'),
                 'Diminuendo': ('Diminuendo starts', 'Diminuendo ends')}
        for spanner in self.score.parts[part_index].spanners.stream():
            spanner_type = type(spanner).__name__
            if spanner_type not in names:
                continue
            first = spanner.getFirst()
            last = spanner.getLast()
            if (first is None or last is None or first.measureNumber is None or last.measureNumber is None
                    or first.measureNumber > end_bar or last.measureNumber < start_bar):
                continue
            start_name, end_name = names[spanner_type]
            if first.measureNumber >= start_bar:
                event = TSDynamic(long_name=start_name)
                event.start_offset = first.offset
                event.beat = first.beat
                intermediate_events.setdefault(first.measureNumber, {}).setdefault(
                    first.offset, {}).setdefault(1, []).append(event)
            if last.measureNumber <= end_bar and last is not first:
                # The hairpin closes on its last note, so the ending is read with that note.
                # A wedge the file never closes has nothing to end.
                event = TSDynamic(long_name=end_name)
                event.trailing = True
                event.start_offset = last.offset
                event.beat = last.beat
                intermediate_events.setdefault(last.measureNumber, {}).setdefault(
                    event.start_offset, {}).setdefault(1, []).append(event)

    def _organize_events_by_time_point(self, intermediate_events, start_bar, end_bar):
        final_events_by_bar = {}
        for bar_num in range(start_bar, end_bar + 1):
            if bar_num not in intermediate_events:
                continue
            sorted_time_points = []
            for offset, voices in sorted(intermediate_events[bar_num].items()):
                first_event = next(iter(next(iter(voices.values()))))
                sorted_time_points.append({'offset': offset, 'beat': first_event.beat, 'voices': voices})
            final_events_by_bar[bar_num] = sorted_time_points
        return final_events_by_bar

    def update_events_for_measure(self, measure_stream, events, voice=1, state=None):
        if state is None:
            state = {}
        mark_tuplet_brackets(measure_stream)
        for element in measure_stream.elements:
            event = self._create_event_from_element(element, state)
            if event is None:
                if type(element).__name__ == 'Voice':
                    try:
                        voice_number = int(element.id)
                    except (TypeError, ValueError):
                        voice_number = voice + 1
                    self.update_events_for_measure(element, events, voice_number, state=state)
                continue
            self._set_event_timing_and_duration(event, element)
            events.setdefault(measure_stream.measureNumber, {}) \
                  .setdefault(element.offset, {}) \
                  .setdefault(voice, []) \
                  .append(event)

    @staticmethod
    def _key_signature_alters(measure):
        """{step: alter} for the key signature in force, plus the key itself under "key"."""
        ks = measure.keySignature or measure.getContextByClass(key.KeySignature)
        alters = {}
        if ks is not None:
            alters = {p.step: p.alter for p in ks.alteredPitches}
        state = dict(alters)
        state["key"] = alters
        return state

    @staticmethod
    def _make_pitch(pitch, state):
        accidental = pitch.accidental
        name = accidental.name if accidental is not None else None
        displayed = bool(accidental.displayStatus) if accidental is not None else False
        last_alter = state.get(pitch.step)
        changed = last_alter is None or pitch.alter != last_alter
        state[pitch.step] = pitch.alter
        differs_from_key = (pitch.alter or 0) != state.get("key", {}).get(pitch.step, 0)
        if name is None and differs_from_key:
            # A note carrying an alteration set earlier in the same bar is written
            # without an accidental of its own, so the letter alone would be read
            # as the key signature's version of it.
            name = alter_name(pitch.alter)
        return TSPitch(pitch.step, pitch.octave, pitch.alter, pitch.ps,
                       accidental_name=name, accidental_displayed=displayed,
                       accidental_changed=changed, differs_from_key=differs_from_key)

    def _create_event_from_element(self, element, state):
        element_type = type(element).__name__
        if element_type == 'Note':
            event = TSNote()
            event.pitch = self._make_pitch(element.pitch, state)
            if element.tie:
                event.tie = element.tie.type
            event.expressions = [exp.name for exp in element.expressions if getattr(exp, 'name', None)]
            return event
        if element_type == 'Rest':
            return TSRest()
        if element_type == 'Unpitched':
            return TSUnpitched()
        if element_type == 'ChordSymbol':
            if not self.settings.chord_symbols:
                return None
            return TSChordSymbol(element.figure)
        if element_type == 'Chord':
            event = TSChord()
            event.pitches = []
            for chord_note in element.notes:
                pitch = self._make_pitch(chord_note.pitch, state)
                pitch.tie = chord_note.tie.type if chord_note.tie else None
                event.pitches.append(pitch)
            ties = {pitch.tie for pitch in event.pitches}
            if len(ties) == 1:
                # Every note of the chord is tied the same way, so the tie is read
                # once for the chord rather than after each note.
                event.tie = ties.pop()
                for pitch in event.pitches:
                    pitch.tie = None
            elif element.tie and not ties - {None}:
                event.tie = element.tie.type
            event.expressions = [exp.name for exp in element.expressions if getattr(exp, 'name', None)]
            return event
        if element_type == 'Dynamic':
            if not self.settings.dynamics:
                return None
            return TSDynamic(long_name=element.longName, short_name=element.value)
        return None

    @staticmethod
    def _set_event_timing_and_duration(event, element):
        event.start_offset = element.offset
        event.beat = element.beat
        event.quarter_length = float(element.duration.quarterLength)
        event.duration_type = element.duration.type
        event.dots = element.duration.dots
        event.grace = bool(element.duration.isGrace)
        if element.duration.tuplets:
            tuplet = element.duration.tuplets[0]
            if tuplet.type in ("start", "startStop"):
                event.tuplet_start = (tuplet.fullName, tuplet.tupletActual[0], tuplet.tupletNormal[0])
            if tuplet.type in ("stop", "startStop"):
                event.tuplet_stop = True
        beams = getattr(element, 'beams', None)
        if beams is not None and beams.beamsList:
            beam_type = beams.beamsList[0].type
            if beam_type in ('start', 'stop'):
                event.beam = beam_type

    # Ranges

    def get_rhythm_range(self):
        found = set()
        for note in self.score.flatten().notesAndRests:
            if note.duration.type in BRITISH_DURATIONS:
                found.add(BRITISH_DURATIONS[note.duration.type])
        order = list(BRITISH_DURATIONS.values())
        return sorted(found, key=order.index)

    def get_octave_range(self):
        all_octaves = []
        for element in self.score.flatten().notes:
            all_octaves.extend(p.octave for p in getattr(element, 'pitches', ()) if p.octave is not None)
        if not all_octaves:
            return {'min': 0, 'max': 0}
        return {'min': min(all_octaves), 'max': max(all_octaves)}

    def pitch_range(self, part_index):
        """(lowest, highest) music21 pitches in a part, or (None, None) when it has no notes."""
        lowest = highest = None
        for element in self.score.parts[part_index].flatten().notes:
            # Unpitched percussion has no pitches and takes no part in the range.
            for p in getattr(element, 'pitches', ()):
                if p.ps is None:
                    continue
                if lowest is None or p.ps < lowest.ps:
                    lowest = p
                if highest is None or p.ps > highest.ps:
                    highest = p
        return lowest, highest


# The only colour-map keys that become CSS class names.
PITCH_COLOUR_KEYS = frozenset("abcdefg")
OCTAVE_COLOUR_KEYS = frozenset(("high", "mid", "low"))
RHYTHM_COLOUR_KEYS = frozenset(name.lower().replace(' ', '-') for name in BRITISH_DURATIONS.values())


class HTMLTalkingScoreFormatter:
    """Builds the score page, text and braille from a Music21TalkingScore."""

    def __init__(self, talking_score, options=None):
        self.score = talking_score
        if options is None:
            options = {}
            options_path = self.score.filepath + '.opts'
            try:
                with open(options_path, "r") as options_fh:
                    options = json.load(options_fh)
            except FileNotFoundError:
                logger.warning(f"Options file not found: {options_path}. Using the default settings.")
        self.options = options
        self.settings = RenderSettings.from_options(options)
        self.settings.pitch_colours = clean_colour_map(self.settings.pitch_colours, PITCH_COLOUR_KEYS)
        self.settings.rhythm_colours = clean_colour_map(self.settings.rhythm_colours, RHYTHM_COLOUR_KEYS)
        self.settings.octave_colours = clean_colour_map(self.settings.octave_colours, OCTAVE_COLOUR_KEYS)
        self.score.use_settings(self.settings)
        self.built = False
        self.segments = []
        self.facts = None
        self.time_and_keys = {}
        self.signature_changes = []
        self.music_analyser = None
        self.builder = None

    # Building

    def build(self, output_path="", web_path=""):
        """Read the score once; later renders reuse the result."""
        if self.built:
            return
        self.score.get_instruments()
        self.score.compare_parts_with_selected_instruments()
        self.music_analyser = MusicAnalyser()
        self.music_analyser.setScore(self.score)
        self._process_time_and_key_changes()
        self._setup_measure_time_signatures()
        self.builder = DescriptionBuilder(
            self.settings,
            time_and_keys=self.time_and_keys,
            immediate_repetitions=self.music_analyser.immediate_repetition_contexts,
            detailed_repetitions=self.music_analyser.repetition_in_contexts,
        )
        self.segments = []
        start_bar_for_loop = self._handle_pickup_bar(self.segments)
        self._generate_main_segments(start_bar_for_loop, self.segments)
        self.facts = self._build_facts()
        if web_path and self.segments:
            # The bars the page opens on.
            self._trigger_midi_generation(self.segments[0].start_bar, self.segments[0].end_bar)
        self.built = True

    def generateHTML(self, output_path="", web_path="", download_html_url="", export_theme=None,
                     export_mode=False, download_text_url="", download_braille_url="", options_url=""):
        template = self._setup_template_environment(export_mode=export_mode)
        self.build(output_path, web_path)
        palette = self.builder.palette
        # A downloaded page has no server behind it, so it carries no links back and no player.
        if export_mode:
            download_html_url = download_text_url = download_braille_url = options_url = ""
        return template.render({
            'settings': self.settings,
            'style_name': self.settings.style_name,
            'basic_information': self._get_basic_information(),
            'facts': self.facts,
            'meta_line': self._meta_line(),
            'score_data': self._score_data(web_path, export_mode),
            'music_segments': self.segments,
            'download_html_url': download_html_url,
            'download_text_url': download_text_url,
            'download_braille_url': download_braille_url,
            'options_url': options_url,
            'export_theme': export_theme,
            'export_mode': export_mode,
            'inline_css': (self._read_static("css", "site.css") + self._read_static("css", "score.css")
                           if export_mode else ""),
            'inline_js': self._read_static("js", "score.js") if export_mode else "",
            'static_icon_url': f"{django_settings.STATIC_URL}img/icon.svg",
            'static_site_css_url': f"{django_settings.STATIC_URL}css/site.css",
            'static_css_url': f"{django_settings.STATIC_URL}css/score.css",
            'static_js_url': f"{django_settings.STATIC_URL}js/score.js",
            'static_player_url': f"{django_settings.STATIC_URL}js/player.js",
            'palette_css': palette.css(),
            'colour_root_class': palette.root_class,
        })

    META_LINE_INSTRUMENTS = 4

    def _meta_line(self):
        """Key, time, tempo, the instruments being read and the length, shown under the title."""
        preamble = self._get_preamble()
        items = [preamble['key_signature'], preamble['time_signature']]
        if preamble['tempo']:
            items.append(preamble['tempo'])
        names = []
        for ins in self.score.selected_instruments:
            name = self.score.part_instruments[ins][0]
            if name not in names:
                names.append(name)
        shown = names[:self.META_LINE_INSTRUMENTS]
        if len(names) > len(shown):
            shown.append(f"and {len(names) - len(shown)} more")
        items.extend(shown)
        bars = preamble['number_of_bars']
        items.append("1 bar" if bars == 1 else f"{bars} bars")
        return [item for item in items if item]

    def _playback_parts(self):
        """Every part in the score, named as the reading page names it."""
        parts = []
        for ins, (name, first_part, part_count, part_id) in self.score.part_instruments.items():
            for part_index in range(first_part, first_part + part_count):
                parts.append({
                    'index': part_index,
                    'label': self.score.part_name(ins, part_index),
                    'read': ins in self.score.selected_instruments,
                })
        return parts

    def _playback_voices(self, parts):
        """What the player can be asked for, in the order the choice is offered."""
        settings = self.settings
        every = [part['index'] for part in parts]
        read = [part['index'] for part in parts if part['read']]
        others = [part['index'] for part in parts if not part['read']]
        voices = []
        if settings.play_all:
            voices.append({'parts': every, 'label': "Every instrument"})
        if settings.play_selected and read:
            voices.append({'parts': read, 'label': "The instruments being read"})
        if settings.play_unselected and others:
            voices.append({'parts': others, 'label': "The other instruments"})
        for ins in self.score.selected_instruments:
            name, first_part, part_count, part_id = self.score.part_instruments[ins]
            instrument_parts = list(range(first_part, first_part + part_count))
            voices.append({'parts': instrument_parts, 'label': name})
            if part_count > 1:
                for part_index in instrument_parts:
                    voices.append({'parts': [part_index],
                                   'label': self.score.part_name(ins, part_index)})
        if not voices:
            voices.append({'parts': every, 'label': "Every instrument"})
        return voices

    def _score_data(self, web_path, export_mode):
        """What the reader script needs: the bar range, the grouping and where the audio lives."""
        pickup = next((segment.start_bar for segment in self.segments if segment.is_pickup), None)
        first_bar = self.segments[0].start_bar if self.segments else 1
        last_bar = self.segments[-1].end_bar if self.segments else first_bar
        bars_per_group = max(1, int(self.settings.bars_at_a_time))
        midi = None
        if web_path and not export_mode:
            parts = self._playback_parts()
            midi = {'base': web_path, 'parts': parts, 'voices': self._playback_voices(parts)}
        # A score that is only a pickup bar keeps the go-to range inside the bars that exist.
        first_numbered = min(first_bar + 1, last_bar) if pickup == first_bar else first_bar
        return {
            'key': web_path or self.score.get_title(),
            'firstBar': first_bar,
            'firstNumberedBar': first_numbered,
            'lastBar': last_bar,
            # The total counts numbered bars only, so it agrees with the last bar number.
            'totalBars': max(0, last_bar - first_numbered + 1) if self.segments else 0,
            'pickupBar': pickup,
            'barsPerGroup': bars_per_group,
            'groupSizes': sorted({1, 2, 4, 8, bars_per_group}),
            'midi': midi,
        }

    def render_text(self, output_path="", web_path=""):
        self.build(output_path, web_path)
        return segments_to_text(self.segments, self.facts, title=self.score.get_title(),
                                one_beat_per_line=(self.settings.style == "reference"))

    def render_braille(self, output_path="", web_path=""):
        return text_to_brf(self.render_text(output_path, web_path))

    # Template

    def _setup_template_environment(self, export_mode=False):
        # Titles, composers and part names come from the uploaded file, so every
        # value is escaped unless the template marks it safe.
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)), autoescape=True)
        return env.get_template('talkingscore.html')

    @staticmethod
    def _read_static(kind, name):
        """A static file's text, so a downloaded page can carry its own stylesheet and script."""
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "talkingscoresapp", "static", kind, name)
        try:
            with open(path, "r", encoding="utf-8") as static_file:
                return static_file.read()
        except OSError:
            logger.warning(f"Could not inline {path} into the downloaded page.")
            return ""

    def _get_basic_information(self):
        return {'title': self.score.get_title(), 'composer': self.score.get_composer()}

    def _get_preamble(self):
        return {
            'time_signature': self.score.get_initial_time_signature(),
            'key_signature': self.score.get_initial_key_signature(),
            'tempo': self.score.get_initial_tempo(),
            'number_of_bars': self.score.get_number_of_bars(),
            'number_of_parts': len(self.score.part_instruments),
        }

    # Score structure

    def _get_score_range(self):
        measures = self.score.score.parts[0].getElementsByClass('Measure')
        return measures[0].number, measures[-1].number

    def _process_time_and_key_changes(self):
        """Signature and tempo changes after the first bar, keyed by bar number."""
        self.time_and_keys = {}
        self.signature_changes = []
        part = self.score.score.parts[0]
        first_bar = part.getElementsByClass('Measure')[0].number

        def note(bar, text):
            if bar is None or bar <= first_bar:
                return
            self.time_and_keys.setdefault(bar, []).append(text)
            self.signature_changes.append(f"{text} from bar {bar}")

        for ts in part.flatten().getElementsByClass('TimeSignature'):
            note(ts.measureNumber, f"Time signature {self.score.describe_time_signature(ts)}")
        for ks in part.flatten().getElementsByClass('KeySignature'):
            note(ks.measureNumber, f"Key signature {self.score.describe_key_signature(ks)}")
        for mark in self.score.score.flatten().getElementsByClass('MetronomeMark'):
            note(mark.measureNumber, f"Tempo {self.score.describe_tempo(mark)}")

    def _setup_measure_time_signatures(self):
        self.score.timeSigs = {}
        part = self.score.score.parts[0]
        measures = part.getElementsByClass('Measure')
        first_measure = measures[0]
        initial = first_measure.getTimeSignatures()
        previous_ts = initial[0] if initial else self.score._get_initial_time_signature_object()
        for measure_num in range(first_measure.number, measures[-1].number + 1):
            measure = part.measure(measure_num)
            if measure is not None and measure.getElementsByClass(meter.TimeSignature):
                previous_ts = measure.getElementsByClass(meter.TimeSignature)[0]
            self.score.timeSigs[measure_num] = previous_ts

    def _trigger_midi_generation(self, start_bar, end_bar):
        """Write the audio for one range of bars, so the first press of play waits for nothing."""
        from lib.midiHandler import MidiHandler

        id_hash = os.path.basename(os.path.dirname(self.score.filepath))
        xml_filename = os.path.basename(self.score.filepath)
        try:
            midi_handler = MidiHandler(SimpleNamespace(GET={}), id_hash, xml_filename)
            midi_handler.score = self.score.score
            midi_handler.make_midi_file(start_bar, end_bar)
        except Exception as exc:
            logger.error(f"Failed to write MIDI for bars {start_bar}-{end_bar}: {exc}", exc_info=True)

    def _create_music_segment(self, start_bar, end_bar, is_pickup=False):
        if is_pickup:
            label, anchor = "Pickup bar", "segment-pickup"
        elif start_bar == end_bar:
            label, anchor = f"Bar {start_bar}", f"segment-{start_bar}"
        else:
            label, anchor = f"Bars {start_bar} to {end_bar}", f"segment-{start_bar}"
        segment = SegmentDescription(
            start_bar=start_bar, end_bar=end_bar, label=label, anchor=anchor, is_pickup=is_pickup)
        pickup_bar = start_bar if is_pickup else None
        for ins in self.score.selected_instruments:
            instrument = InstrumentDescription(number=ins, name=self.score.part_instruments[ins][0])
            first_part_index = self.score.part_instruments[ins][1]
            part_count = self.score.part_instruments[ins][2]
            for part_index in range(first_part_index, first_part_index + part_count):
                events = self.score.get_events_for_bar_range(start_bar, end_bar, part_index)
                lengths = self.score.bar_lengths(start_bar, end_bar, part_index)
                beat_lengths = {bar: self.score.beat_quarter_length(bar) for bar in range(start_bar, end_bar + 1)}
                instrument.parts.append(self.builder.build_part(
                    part_index, self.score.part_name(ins, part_index), events, lengths,
                    beat_lengths, pickup_bar=pickup_bar))
            segment.instruments.append(instrument)
        return segment

    def _handle_pickup_bar(self, music_segments):
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        start_bar_for_loop = first_measure.number
        active_ts = first_measure.timeSignature or self.score.timeSigs.get(first_measure.number)
        if active_ts and first_measure.duration.quarterLength < active_ts.barDuration.quarterLength:
            pickup_bar_num = first_measure.number
            self.score.timeSigs[pickup_bar_num] = active_ts
            music_segments.append(self._create_music_segment(
                start_bar=pickup_bar_num, end_bar=pickup_bar_num, is_pickup=True))
            start_bar_for_loop = pickup_bar_num + 1
        return start_bar_for_loop

    def _generate_main_segments(self, start_bar_for_loop, music_segments):
        part = self.score.score.parts[0]
        total_measures = part.getElementsByClass('Measure')[-1].number
        step = max(1, int(self.settings.bars_at_a_time))
        for bar_index in range(start_bar_for_loop, total_measures + 1, step):
            end_bar_index = min(bar_index + step - 1, total_measures)
            if part.measure(bar_index) is None:
                break
            music_segments.append(self._create_music_segment(
                start_bar=bar_index, end_bar=end_bar_index))

    # Facts

    def _build_facts(self):
        facts = ScoreFacts()
        preamble = self._get_preamble()
        facts.piece = [
            Fact("Title", self.score.get_title()),
            Fact("Composer", self.score.get_composer()),
            Fact("Key", preamble['key_signature']),
            Fact("Time signature", preamble['time_signature']),
        ]
        if preamble['tempo']:
            facts.piece.append(Fact("Tempo", preamble['tempo']))
        facts.piece.append(Fact("Bars", str(preamble['number_of_bars'])))
        facts.piece.append(Fact("Instruments", ", ".join(
            self.score.part_instruments[ins][0] for ins in self.score.part_instruments)))
        facts.changes = list(self.signature_changes)

        analyse_index = 0
        for ins in self.score.selected_instruments:
            first_part_index = self.score.part_instruments[ins][1]
            part_count = self.score.part_instruments[ins][2]
            for part_index in range(first_part_index, first_part_index + part_count):
                part_facts = []
                lowest, highest = self.score.pitch_range(part_index)
                if lowest is not None:
                    part_facts.append(Fact("Lowest note", self._describe_pitch(lowest)))
                    part_facts.append(Fact("Highest note", self._describe_pitch(highest)))
                analysis = self.music_analyser.analyse_parts[analyse_index] \
                    if analyse_index < len(self.music_analyser.analyse_parts) else None
                analyse_index += 1
                repeats = self._describe_repeats(analysis)
                if repeats:
                    part_facts.append(Fact("Repeated bars", repeats))
                facts.parts.append({'name': self.score.part_name(ins, part_index), 'facts': part_facts})
        return facts

    def _describe_pitch(self, pitch):
        ts_pitch = TSPitch(pitch.step, pitch.octave, pitch.alter, pitch.ps,
                           accidental_name=pitch.accidental.name if pitch.accidental else None)
        vocabulary = self.score.vocabulary
        name = vocabulary.pitch(ts_pitch, bool(ts_pitch.accidental_name))
        octave = vocabulary.octave(ts_pitch)
        if not octave:
            return name
        if self.settings.octave_before_pitch:
            return f"{octave} {name}"
        return f"{name} {octave}"

    @staticmethod
    def _describe_repeats(analysis):
        if analysis is None:
            return ""
        phrases = []
        for group in getattr(analysis, 'measure_groups_list', []) or []:
            ranges = []
            for start, end in group:
                ranges.append(f"{start}" if start == end else f"{start} to {end}")
            if len(ranges) > 1:
                phrases.append("bars " + ", ".join(ranges[:-1]) + " and " + ranges[-1] + " match")
        singles = getattr(analysis, 'repeated_measures_not_in_groups_dictionary', {}) or {}
        for bar, matches in sorted(singles.items()):
            if matches:
                phrases.append(f"bar {bar} matches bar" + ("s " if len(matches) > 1 else " ")
                               + ", ".join(str(m) for m in matches))
        return "; ".join(phrases)
