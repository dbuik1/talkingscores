"""
Musical events extracted from a score.

These classes hold facts only: what the file says, as numbers and names from
MusicXML. Wording is decided later by a vocabulary, so the same events can be
read in any style without re-parsing the score.
"""


class TSEvent:
    """One thing that happens at a point in a bar."""

    kind = "event"

    def __init__(self):
        self.quarter_length = 0.0
        self.duration_type = None      # music21 duration type: whole, half, quarter, eighth, 16th ...
        self.dots = 0
        self.tuplet_start = None       # (name, actual, normal) when this event opens a tuplet
        self.tuplet_stop = False
        self.tie = None                # start, stop, continue
        self.beam = None               # start, stop
        self.bar = None
        self.part = None
        self.start_offset = 0.0
        self.beat = 0.0
        self.grace = False             # an ornament with no length of its own

    @property
    def rhythm_key(self):
        """Two events with the same key have the same written note value."""
        return (self.duration_type, self.dots, round(self.quarter_length, 6))


class TSDynamic(TSEvent):
    kind = "dynamic"

    def __init__(self, long_name=None, short_name=None):
        super().__init__()
        self.long_name = long_name
        self.short_name = short_name


class TSChordSymbol(TSEvent):
    """A chord symbol written above the stave, such as C7."""

    kind = "chord_symbol"

    def __init__(self, figure):
        super().__init__()
        self.figure = figure


class TSPitch:
    """A single pitch: letter, octave number and accidental facts."""

    def __init__(self, step, octave, alter, pitch_number, accidental_name=None,
                 accidental_displayed=False, accidental_changed=False, differs_from_key=False):
        self.step = step
        self.octave = octave
        self.alter = alter or 0
        self.pitch_number = pitch_number
        self.accidental_name = accidental_name
        self.accidental_displayed = accidental_displayed
        self.accidental_changed = accidental_changed
        # The sounding pitch is not the one the key signature gives this letter, so
        # the letter on its own would be read as the wrong note.
        self.differs_from_key = differs_from_key
        # Set only where the notes of a chord are tied differently from each other.
        self.tie = None

    @property
    def diatonic_number(self):
        """Position on the letter ladder, for interval names."""
        return "CDEFGAB".index(self.step) + 7 * (self.octave or 0)


class TSUnpitched(TSEvent):
    kind = "unpitched"


class TSRest(TSEvent):
    kind = "rest"


class TSNote(TSEvent):
    kind = "note"

    def __init__(self):
        super().__init__()
        self.pitch = None
        self.expressions = []          # expression names, such as arpeggio or fermata


class TSChord(TSEvent):
    kind = "chord"

    def __init__(self):
        super().__init__()
        self.pitches = []
        self.expressions = []
