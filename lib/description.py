"""
Turn extracted events into a structured description of each bar.

The model built here (segment, instrument, part, bar, beat) is the single
source for the web page, the text download and the braille download. Every
beat carries the same words as plain text and as HTML; the HTML only adds
colour classes.
"""

import math
from dataclasses import dataclass, field
from fractions import Fraction
from html import escape

from lib.vocabulary import Vocabulary

# Event kinds that are read out when a note or chord sounds at the same moment.
KINDS_WITH_NOTES = ("note", "chord", "unpitched", "dynamic", "chord_symbol")
SOUNDING_KINDS = ("note", "chord", "unpitched")
LEADING_KINDS = ("dynamic", "chord_symbol")

TOGETHER = " together with "
IN_BEAT_SEPARATOR = ", "


@dataclass
class Fragment:
    text: str
    css_class: str = ""

    @property
    def html(self):
        if self.css_class:
            return f'<span class="{self.css_class}">{escape(self.text)}</span>'
        return escape(self.text)


@dataclass
class BeatDescription:
    number: int
    label: str
    fragments: list = field(default_factory=list)

    @property
    def text(self):
        return "".join(fragment.text for fragment in self.fragments)

    @property
    def html(self):
        return "".join(fragment.html for fragment in self.fragments)

    @property
    def text_with_label(self):
        if self.label:
            return f"{self.label} {self.text}"
        return self.text


@dataclass
class BarDescription:
    number: int
    label: str
    signatures: list = field(default_factory=list)
    after_notes: list = field(default_factory=list)   # marks read after the bar, such as a repeat ending
    repeat_note: str = ""
    repeat_type: str = ""            # exact, rhythm or empty
    repeat_detail: str = ""
    collapsed: bool = False          # learning mode folds an exact repeat away
    whole_bar_rest: bool = False
    rest_text: str = ""
    beats: list = field(default_factory=list)

    @property
    def text(self):
        if self.whole_bar_rest:
            return self.rest_text
        return IN_BEAT_SEPARATOR.join(beat.text_with_label for beat in self.beats)

    def text_lines(self, one_beat_per_line=False):
        lines = [self.label]
        lines.extend(self.signatures)
        if self.repeat_note:
            lines.append(self.repeat_note)
        if self.collapsed:
            return lines + self.after_notes
        if self.whole_bar_rest:
            lines.append(self.rest_text)
        elif one_beat_per_line:
            lines.extend(beat.text_with_label for beat in self.beats)
        else:
            lines.append(self.text)
        lines.extend(self.after_notes)
        return lines


@dataclass
class PartDescription:
    part_index: int
    name: str
    bars: list = field(default_factory=list)


@dataclass
class InstrumentDescription:
    number: int
    name: str
    parts: list = field(default_factory=list)


@dataclass
class SegmentDescription:
    start_bar: int
    end_bar: int
    label: str
    anchor: str
    is_pickup: bool = False
    instruments: list = field(default_factory=list)

    @property
    def bars(self):
        """The segment bar by bar, each bar carrying every part that plays in it.

        Parts are labelled only when the score has more than one, so a solo
        score reads without a part name on every bar.
        """
        parts = [(instrument, part) for instrument in self.instruments for part in instrument.parts]
        label_parts = len(parts) > 1
        bars = []
        for number in range(self.start_bar, self.end_bar + 1):
            entries = []
            for instrument, part in parts:
                for bar in part.bars:
                    if bar.number == number:
                        entries.append({"label": part.name if label_parts else "", "bar": bar})
                        break
            # A bar no part describes still takes its place, so the numbering never jumps.
            bars.append({"number": number, "label": "Pickup bar" if self.is_pickup else f"Bar {number}",
                         "is_pickup": self.is_pickup, "parts": entries})
        return bars


@dataclass
class Fact:
    label: str
    value: str


@dataclass
class ScoreFacts:
    piece: list = field(default_factory=list)      # title, composer, key, time, tempo, bars, parts
    changes: list = field(default_factory=list)    # time, key and tempo changes with bar numbers
    parts: list = field(default_factory=list)      # per part: name and a list of Fact
    octave_reference: str = ""                     # what the octave words mean, in the words in use


def relative_luminance(hex_colour):
    """The WCAG relative luminance of a hex colour, or None if it is not one."""
    try:
        value = hex_colour.lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except (ValueError, AttributeError, TypeError):
        return None
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_colour(hex_colour):
    """Black or white, whichever has the higher contrast ratio against the colour.

    Perceived brightness and contrast ratio disagree around the middle of the
    range, and it is the ratio that decides whether the word can be read.
    """
    luminance = relative_luminance(hex_colour)
    if luminance is None:
        return "white"
    against_black = (luminance + 0.05) / 0.05
    against_white = 1.05 / (luminance + 0.05)
    return "black" if against_black >= against_white else "white"


def slugify_colour_key(value):
    return "".join(ch if ch.isalnum() else "-" for ch in str(value).lower()).strip("-")


class Palette:
    """CSS classes and the stylesheet for the colour choices stored with a score."""

    def __init__(self, settings):
        self.settings = settings
        self.active = settings.colour_position not in ("none", "", None)
        self.pitch_colours = {k.upper(): v for k, v in (settings.pitch_colours or {}).items() if v}
        self.rhythm_colours = {slugify_colour_key(k): v for k, v in (settings.rhythm_colours or {}).items() if v}
        self.octave_colours = {k.lower(): v for k, v in (settings.octave_colours or {}).items() if v}

    @property
    def root_class(self):
        if not self.active:
            return ""
        return "colour-words"

    def pitch_class(self, step):
        if self.active and self.settings.colour_pitch and step in self.pitch_colours:
            return f"colour-pitch-{step.lower()}"
        return ""

    def rhythm_class(self, duration_slug, step):
        if not self.active:
            return ""
        mode = self.settings.rhythm_colour_mode
        if mode == "inherit":
            return self.pitch_class(step)
        if mode == "custom" and duration_slug in self.rhythm_colours:
            return f"colour-rhythm-{duration_slug}"
        return ""

    def octave_class(self, band, step):
        if not self.active:
            return ""
        mode = self.settings.octave_colour_mode
        if mode == "inherit":
            return self.pitch_class(step)
        if mode == "custom" and band in self.octave_colours:
            return f"colour-octave-{band}"
        return ""

    def css(self):
        if not self.active:
            return ""
        rules = []

        def rule(selector, colour):
            # The colour goes behind the word rather than into it: a palette that
            # keeps its meaning across themes cannot also meet 4.5:1 as ink on both
            # a cream page and a black one, and the ink here is chosen to.
            rules.append(
                f".colour-words {selector} {{ background-color: {colour}; "
                f"color: {contrast_colour(colour)}; padding: 0 0.15em; border-radius: 0.2em; }}")

        if self.settings.colour_pitch:
            for step, colour in self.pitch_colours.items():
                rule(f".colour-pitch-{step.lower()}", colour)
        if self.settings.rhythm_colour_mode == "custom":
            for slug, colour in self.rhythm_colours.items():
                rule(f".colour-rhythm-{slug}", colour)
        if self.settings.octave_colour_mode == "custom":
            for band, colour in self.octave_colours.items():
                rule(f".colour-octave-{band}", colour)
        return "\n".join(rules)


def _safe_colour(value):
    """Only hex colours reach the stylesheet; anything else is dropped."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) in (4, 7) and value.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in value[1:]):
        return value
    return None


def clean_colour_map(colours, allowed_keys=None):
    """Keys become CSS class names, so only known keys made of safe characters survive."""
    cleaned = {}
    for key, value in (colours or {}).items():
        slug = slugify_colour_key(key)
        if not slug or (allowed_keys is not None and slug not in allowed_keys):
            continue
        colour = _safe_colour(value)
        if colour:
            cleaned[slug] = colour
    return cleaned


class PartState:
    """What the reader has just heard, reset at the start of every bar."""

    def __init__(self):
        self.previous_rhythm = None
        self.previous_pitch = None
        self.first_pitch_seen = False


class DescriptionBuilder:
    def __init__(self, settings, time_and_keys=None, bar_endings=None,
                 immediate_repetitions=None, detailed_repetitions=None):
        self.settings = settings
        self.vocabulary = Vocabulary(settings)
        self.palette = Palette(settings)
        self.time_and_keys = time_and_keys or {}
        self.bar_endings = bar_endings or {}
        self.immediate_repetitions = immediate_repetitions or {}
        self.detailed_repetitions = detailed_repetitions or {}

    # Bars

    def build_part(self, part_index, name, events_by_bar, bar_lengths, beat_quarter_length, pickup_bar=None):
        """
        events_by_bar: {bar_number: [time_point, ...]} as produced by the score.
        bar_lengths: {bar_number: (written bar length, actual length)} in quarter notes.
        beat_quarter_length: one length for every bar, or {bar_number: length} when
        the time signature changes inside the range.
        """
        part = PartDescription(part_index=part_index, name=name)
        for bar_number in sorted(events_by_bar):
            written_length, actual_length = bar_lengths.get(bar_number, (None, None))
            if isinstance(beat_quarter_length, dict):
                beat_ql = beat_quarter_length.get(bar_number, 1.0)
            else:
                beat_ql = beat_quarter_length
            part.bars.append(self.build_bar(
                bar_number, events_by_bar[bar_number], part_index,
                beat_ql, written_length, actual_length,
                is_pickup=(bar_number == pickup_bar),
            ))
        return part

    def build_bar(self, bar_number, time_points, part_index, beat_quarter_length,
                  written_length=None, actual_length=None, is_pickup=False):
        bar = BarDescription(number=bar_number, label=self.bar_label(bar_number, is_pickup))
        bar.signatures = list(self.time_and_keys.get(bar_number, []))
        bar.after_notes = list(self.bar_endings.get(bar_number, []))
        self._add_repeat_notes(bar, part_index, bar_number)

        has_sounding_event = any(
            event.kind in SOUNDING_KINDS
            for time_point in time_points
            for events in time_point["voices"].values()
            for event in events
        )
        if not has_sounding_event:
            bar.whole_bar_rest = True
            bar.rest_text = self.vocabulary.whole_bar_rest()
            return bar

        # A pickup bar counts its beats back from the bar line.
        beat_shift = 0.0
        if is_pickup and written_length and actual_length and actual_length < written_length:
            beat_shift = written_length - actual_length

        beat_ql = beat_quarter_length or 1.0
        state = PartState()
        current_beat = None
        beat_description = None
        for time_point in time_points:
            events = self._events_at(time_point)
            if not events:
                continue
            fragments = self._render_time_point(events, state, beat_ql, time_point)
            if not fragments:
                continue
            beat_number = self._beat_number(time_point["offset"] + beat_shift, beat_ql)
            if self.settings.beat_division == "bar":
                beat_number = 1
            if beat_description is None or beat_number != current_beat:
                current_beat = beat_number
                label = "" if self.settings.beat_division == "bar" else self.vocabulary.beat_label(beat_number)
                beat_description = BeatDescription(number=beat_number, label=label)
                bar.beats.append(beat_description)
            elif beat_description.fragments:
                beat_description.fragments.append(Fragment(IN_BEAT_SEPARATOR, "sep"))
            beat_description.fragments.extend(fragments)
        return bar

    def bar_label(self, bar_number, is_pickup):
        if is_pickup:
            return "Pickup bar"
        return f"Bar {bar_number}"

    def _add_repeat_notes(self, bar, part_index, bar_number):
        mode = self.settings.repetition_mode
        if mode == "none":
            return
        immediate = self.immediate_repetitions.get(part_index, {}).get(bar_number)
        if immediate:
            bar.repeat_type = immediate.get("type", "")
            previous = bar_number - 1
            if bar.repeat_type == "exact":
                bar.repeat_note = self.vocabulary.same_as_bar(previous)
                bar.collapsed = mode == "learning"
            elif bar.repeat_type == "rhythm":
                bar.repeat_note = self.vocabulary.same_rhythm_as_bar(previous)
        if mode == "detailed":
            detail = self.detailed_repetitions.get(part_index, {}).get(bar_number)
            if detail:
                bar.repeat_detail = detail

    @staticmethod
    def _beat_number(offset, beat_ql):
        position = Fraction(offset).limit_denominator(96) / Fraction(beat_ql).limit_denominator(96)
        return int(math.floor(position)) + 1

    def _events_at(self, time_point):
        """Events at one moment, voices in order, rests dropped when a note sounds."""
        voices = time_point["voices"]
        ordered = [event for voice in sorted(voices) for event in voices[voice]]
        if any(event.kind in SOUNDING_KINDS for event in ordered):
            return [event for event in ordered if event.kind in KINDS_WITH_NOTES]
        return ordered

    def _render_time_point(self, events, state, beat_ql, time_point):
        """
        One moment in the bar: dynamics and chord symbols lead, grace notes come
        next, and only the notes that sound together are joined with "together with".
        A hairpin's ending follows the note it closes on.
        """
        leading = [event for event in events
                   if event.kind in LEADING_KINDS and not getattr(event, "trailing", False)]
        trailing = [event for event in events if getattr(event, "trailing", False)]
        graces = [event for event in events if event.kind not in LEADING_KINDS and event.grace]
        sounding = [event for event in events if event.kind not in LEADING_KINDS and not event.grace]
        only_event = len(sounding) == 1
        rendered = []
        for group, joiner in ((leading, IN_BEAT_SEPARATOR), (graces, IN_BEAT_SEPARATOR),
                              (sounding, TOGETHER), (trailing, IN_BEAT_SEPARATOR)):
            group_fragments = []
            for event in group:
                fragments = self.render_event(event, state, beat_ql, only_event_on_beat=only_event)
                if not fragments:
                    continue
                if group_fragments:
                    group_fragments.append(Fragment(joiner, "sep" if joiner == IN_BEAT_SEPARATOR else ""))
                group_fragments.extend(fragments)
            if not group_fragments:
                continue
            if rendered:
                rendered.append(Fragment(IN_BEAT_SEPARATOR, "sep"))
            rendered.extend(group_fragments)
        return rendered

    # Events

    def render_event(self, event, state, beat_ql=1.0, only_event_on_beat=True):
        kind = event.kind
        if kind == "dynamic":
            if not self.settings.dynamics:
                return []
            return [Fragment(self.vocabulary.dynamic(event), "change")]
        if kind == "chord_symbol":
            if not self.settings.chord_symbols:
                return []
            return [Fragment(self.vocabulary.chord_symbol(event.figure))]
        if kind == "rest":
            if not self._rest_is_read(event, beat_ql, only_event_on_beat):
                return []
            fragments = self._tuplet_fragments(event, opening=True)
            fragments.append(Fragment(self.vocabulary.rest(event, beat_ql)))
            fragments.extend(self._tuplet_fragments(event, opening=False))
            state.previous_rhythm = event.rhythm_key
            return self._join(fragments)
        if kind == "unpitched":
            fragments = [Fragment(self.vocabulary.unpitched(event, beat_ql))]
            fragments.extend(self._articulation_fragments(event))
            fragments.extend(self._slur_fragments(event))
            state.previous_rhythm = event.rhythm_key
            return self._join(fragments)
        if kind == "note":
            return self._render_note(event, state, beat_ql)
        if kind == "chord":
            return self._render_chord(event, state, beat_ql)
        return []

    def _rest_is_read(self, event, beat_ql, only_event_on_beat):
        rule = self.settings.rests
        if rule == "none":
            return False
        if rule == "all":
            return True
        # Structural rests: a beat or longer, at the start of the bar, or alone on their beat.
        return (event.quarter_length >= beat_ql - 1e-6
                or abs(event.start_offset) < 1e-6
                or only_event_on_beat)

    def _render_note(self, event, state, beat_ql):
        words = []
        for expression in event.expressions:
            if "arpeggio" in expression.lower() and not self.settings.arpeggios:
                continue
            words.append(Fragment(self.vocabulary.expression(expression)))
        rhythm = self._rhythm_fragments(event, state, event.pitch.step, beat_ql)
        pitch = self._pitch_fragments(event.pitch, state.previous_pitch)
        if self.settings.intervals and state.previous_pitch is not None:
            interval = self.vocabulary.interval(state.previous_pitch, event.pitch)
            if interval:
                pitch.append(Fragment(interval))
        if self.settings.word_order == "pitch_first":
            words.extend(pitch)
            words.extend(rhythm)
        else:
            words.extend(rhythm)
            words.extend(pitch)
        words.extend(self._tuplet_fragments(event, opening=False))
        words.extend(self._articulation_fragments(event))
        words.extend(self._tie_fragments(event))
        words.extend(self._slur_fragments(event))
        words.extend(self._beam_fragments(event))
        state.previous_pitch = event.pitch
        if not event.grace:
            state.previous_rhythm = event.rhythm_key
        return self._join(words)

    def _render_chord(self, event, state, beat_ql):
        words = []
        for expression in event.expressions:
            if "arpeggio" in expression.lower() and not self.settings.arpeggios:
                continue
            words.append(Fragment(self.vocabulary.expression(expression)))
        pitches = sorted(event.pitches, key=lambda p: p.pitch_number)
        if not self.settings.chords_low_to_high:
            pitches.reverse()
        if self.settings.chords:
            words.append(Fragment(self.vocabulary.chord_count(len(pitches))))
        rhythm = self._rhythm_fragments(event, state, pitches[0].step if pitches else None, beat_ql)
        pitch_words = []
        previous = state.previous_pitch
        for pitch in pitches:
            pitch_words.extend(self._pitch_fragments(pitch, previous))
            # A tie set on one note of a chord belongs to that note, so it is read
            # beside it rather than over the whole chord.
            pitch_words.extend(self._tie_words(pitch.tie))
            previous = pitch
        if self.settings.word_order == "pitch_first":
            words.extend(pitch_words)
            words.extend(rhythm)
        else:
            words.extend(rhythm)
            words.extend(pitch_words)
        words.extend(self._tuplet_fragments(event, opening=False))
        words.extend(self._articulation_fragments(event))
        words.extend(self._tie_fragments(event))
        words.extend(self._slur_fragments(event))
        words.extend(self._beam_fragments(event))
        if pitches:
            state.previous_pitch = pitches[-1]
        if not event.grace:
            state.previous_rhythm = event.rhythm_key
        return self._join(words)

    def _rhythm_fragments(self, event, state, step, beat_ql):
        """The note value; the tuplet's closing words follow the pitch, not the value."""
        fragments = self._tuplet_fragments(event, opening=True)
        if event.grace:
            fragments.append(Fragment(self.vocabulary.grace()))
            return fragments
        if self.settings.duration_names == "none":
            return fragments
        announce = (
            self.settings.duration_frequency == "every_note"
            or state.previous_rhythm != event.rhythm_key
            or event.tuplet_start is not None
        )
        if announce:
            css = self.palette.rhythm_class(self.vocabulary.duration_slug(event), step) if step else ""
            fragments.append(Fragment(self.vocabulary.duration(event, beat_ql), css))
        return fragments

    def _tuplet_fragments(self, event, opening):
        if opening and event.tuplet_start:
            return [Fragment(self.vocabulary.tuplet_start(event.tuplet_start))]
        if not opening and event.tuplet_stop:
            text = self.vocabulary.tuplet_stop()
            return [Fragment(text)] if text else []
        return []

    def _pitch_fragments(self, pitch, previous_pitch):
        fragments = []
        octave_text = ""
        if self._octave_is_read(pitch, previous_pitch):
            octave_text = self.vocabulary.octave(pitch, previous_pitch)
        octave_fragment = None
        if octave_text:
            band = self.vocabulary.octave_band(pitch.octave)
            octave_fragment = Fragment(octave_text, self.palette.octave_class(band, pitch.step))
        name = self.vocabulary.pitch(pitch, self.vocabulary.show_accidental(pitch))
        name_fragment = Fragment(name, self.palette.pitch_class(pitch.step)) if name else None
        if self.settings.octave_before_pitch:
            if octave_fragment:
                fragments.append(octave_fragment)
            if name_fragment:
                fragments.append(name_fragment)
        else:
            if name_fragment:
                fragments.append(name_fragment)
            if octave_fragment:
                fragments.append(octave_fragment)
        return fragments

    def _octave_is_read(self, pitch, previous_pitch):
        if self.settings.octave_naming == "none":
            return False
        frequency = self.settings.octave_frequency
        if frequency == "every_note" or self.settings.octave_naming == "relative":
            return True
        if previous_pitch is None:
            return True
        if frequency == "first_note":
            return False
        if frequency == "braille_rules":
            # Braille music counts letter steps: within a fourth no octave mark; a
            # fifth to a seventh only when the octave changes; an octave or more always.
            steps = abs(previous_pitch.diatonic_number - pitch.diatonic_number)
            if steps <= 3:
                return False
            if steps <= 6:
                return previous_pitch.octave != pitch.octave
            return True
        return previous_pitch.octave != pitch.octave

    def _articulation_fragments(self, event):
        if not self.settings.articulations:
            return []
        fragments = []
        for name in event.articulations:
            text = self.vocabulary.articulation(name)
            if text:
                fragments.append(Fragment(text))
        return fragments

    def _slur_fragments(self, event):
        if not (event.slur and self.settings.slurs):
            return []
        text = self.vocabulary.slur(event.slur)
        return [Fragment(text)] if text else []

    def _tie_fragments(self, event):
        return self._tie_words(event.tie)

    def _tie_words(self, tie_type):
        if tie_type and self.settings.ties:
            text = self.vocabulary.tie(tie_type)
            if text:
                return [Fragment(text)]
        return []

    def _beam_fragments(self, event):
        if event.beam and self.settings.beams:
            text = self.vocabulary.beam(event.beam)
            if text:
                return [Fragment(text)]
        return []

    @staticmethod
    def _join(fragments):
        """Put a single space between the words of one event."""
        joined = []
        for fragment in fragments:
            if not fragment.text:
                continue
            if joined:
                joined.append(Fragment(" "))
            joined.append(fragment)
        return joined


# Plain text

def segments_to_text(segments, facts=None, title="", one_beat_per_line=False):
    """The text download: one line per bar per part, or per beat when asked."""
    lines = []
    if title and not facts:
        lines.append(title)
        lines.append("")
    if facts:
        for fact in facts.piece:
            lines.append(f"{fact.label}: {fact.value}")
        for change in facts.changes:
            lines.append(change)
        if facts.octave_reference:
            lines.append(facts.octave_reference)
        lines.append("")
    for segment in segments:
        if segment.start_bar != segment.end_bar:
            lines.append(segment.label)
        for instrument in segment.instruments:
            if len(segment.instruments) > 1:
                lines.append(instrument.name)
            for part in instrument.parts:
                if len(instrument.parts) > 1:
                    lines.append(part.name)
                for bar in part.bars:
                    lines.extend(bar.text_lines(one_beat_per_line))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
