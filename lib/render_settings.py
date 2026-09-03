"""
Settings that control how a talking score is worded.

A reading style is a named preset. The "Musical terms" style is the one the
options form edits field by field, so stored wording options apply to it. Every
other style fixes its own wording and ignores stored wording options; layout,
playback and colour options apply to every style. Legacy option keys written by
older versions of the options form are still honoured; each one maps onto a
field here.
"""

from dataclasses import dataclass, field, fields, replace

STYLE_IDS = ("plain", "standard", "compact", "braille40", "reference")

STYLE_NAMES = {
    "plain": "Everyday words",
    "standard": "Musical terms",
    "compact": "Short",
    "braille40": "Braille display",
    "reference": "Everything",
}

# What each style sounds like, in one line and in one bar of the same music, so
# the set-up page can show a reader the difference rather than describe it. A
# style without both is a style nobody can choose knowingly.
STYLE_SUMMARIES = {
    "plain": "No music jargon. One bar at a time.",
    "standard": "Rhythm then pitch, one line per beat.",
    "compact": "Pitch first, octave only when it changes.",
    "braille40": "One bar fits a 40-cell line.",
    "reference": "Every detail the file holds, one beat per line.",
}

STYLE_SAMPLES = {
    "plain": "Bar 1. First note: hold a D for one beat. Then four quick notes: G, A, B, C.",
    "standard": "Beat 1: crotchet, D above middle C. Beat 2: quaver, G; quaver, A. Beat 3: quaver, B; quaver, C.",
    "compact": "D5 crotchet, G4 A B C5 quavers.",
    "braille40": "Bar 1: Cr D hi, Qu G mid, Qu A, Qu B, Qu C hi",
    "reference": ("Bar 1, beat 1: crotchet D5, stem down, beamed none. Beat 2: quaver G4, beam start; "
                  "quaver A4, beam end. Beat 3: quaver B4, beam start; quaver C5, beam end."),
}

DEFAULT_STYLE = "standard"


@dataclass
class RenderSettings:
    style: str = DEFAULT_STYLE

    # Layout
    bars_at_a_time: int = 2
    beat_division: str = "beat"          # "beat" groups events by beat, "bar" runs a bar together
    beat_unit: float = None              # counted beat in quarter notes; None follows the time signature
    beat_prefix: str = "words"           # "words" = Beat 1, "short" = b1, "none"

    # Rhythm
    duration_names: str = "british"      # british, american, plain, none
    duration_frequency: str = "on_change"  # on_change, every_note
    dot_position: str = "before"         # before, after

    # Pitch
    pitch_names: str = "letters"         # letters, phonetic, colours, none
    accidental_style: str = "words"      # words, symbols
    key_signature_accidentals: str = "applied"  # applied, standard, on_change
    word_order: str = "rhythm_first"     # rhythm_first, pitch_first

    # Octaves
    octave_naming: str = "descriptive"   # numeric, descriptive, plain, figurenotes, relative, none
    octave_position: str = "auto"        # auto, before, after
    octave_frequency: str = "on_change"  # every_note, on_change, first_note, braille_rules

    # Extra words
    rests: str = "all"                   # all, structural, none
    ties: bool = True
    intervals: bool = False
    chords: bool = True                  # say "3-note chord" before the pitches
    chords_low_to_high: bool = True
    chord_symbols: bool = True           # chord symbols written in the file
    arpeggios: bool = True
    dynamics: bool = True
    beams: bool = False
    abbreviations: bool = False          # fixed abbreviation table (Braille display style)
    repetition_mode: str = "learning"    # learning, detailed, none

    # Parts and playback
    instruments: list = field(default_factory=list)
    play_all: bool = False
    play_selected: bool = False
    play_unselected: bool = False

    # Colour
    colour_position: str = "none"        # none, text, background
    colour_pitch: bool = False
    rhythm_colour_mode: str = "none"     # none, inherit, custom
    octave_colour_mode: str = "none"     # none, inherit, custom
    pitch_colours: dict = field(default_factory=dict)
    rhythm_colours: dict = field(default_factory=dict)
    octave_colours: dict = field(default_factory=dict)

    # Dict-style access keeps templates and older call sites working.
    def get(self, name, default=None):
        return getattr(self, name, default)

    def __getitem__(self, name):
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def __contains__(self, name):
        return hasattr(self, name)

    def as_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def style_name(self):
        return STYLE_NAMES.get(self.style, STYLE_NAMES[DEFAULT_STYLE])

    @property
    def octave_before_pitch(self):
        if self.octave_position == "auto":
            return self.octave_naming not in ("numeric", "relative")
        return self.octave_position == "before"

    @classmethod
    def for_style(cls, style):
        preset = STYLE_PRESETS.get(style, STYLE_PRESETS[DEFAULT_STYLE])
        return cls(style=style if style in STYLE_PRESETS else DEFAULT_STYLE, **preset)

    @classmethod
    def from_options(cls, options):
        """Build settings from the options dict stored beside a score."""
        options = options or {}
        style = options.get("style", DEFAULT_STYLE)
        settings = cls.for_style(style)
        wording_is_editable = settings.style == DEFAULT_STYLE
        overrides = {}

        for legacy_key, translate in LEGACY_OPTION_MAP.items():
            if legacy_key not in options:
                continue
            translated = translate(options[legacy_key])
            if wording_is_editable or not set(translated) & WORDING_FIELDS:
                overrides.update(translated)

        field_names = {f.name for f in fields(cls)}
        for key, value in options.items():
            if key not in field_names or key == "style":
                continue
            if key in WORDING_FIELDS and not wording_is_editable:
                continue
            overrides[key] = value

        if "bars_at_a_time" in overrides:
            try:
                overrides["bars_at_a_time"] = max(1, int(overrides["bars_at_a_time"]))
            except (TypeError, ValueError):
                overrides["bars_at_a_time"] = settings.bars_at_a_time
        division = overrides.get("beat_division")
        if division not in ("bar", "beat", None):
            # The options form stores "<count>/<beat length>", such as "2/1.0".
            unit = str(division).split("/")[-1]
            try:
                overrides["beat_unit"] = float(unit)
            except ValueError:
                pass
            overrides["beat_division"] = "beat"
        elif division is None:
            overrides.pop("beat_division", None)

        return replace(settings, **overrides)


# Fields a named style decides for itself. Only the "Musical terms" style takes
# these from the stored options.
WORDING_FIELDS = frozenset({
    "beat_prefix", "duration_names", "duration_frequency", "dot_position",
    "pitch_names", "word_order", "octave_naming", "octave_position", "octave_frequency",
    "rests", "ties", "intervals", "chords", "chords_low_to_high", "chord_symbols",
    "arpeggios", "dynamics", "beams", "abbreviations", "repetition_mode",
})

# Presets hold only the fields that differ from the dataclass defaults.
STYLE_PRESETS = {
    "plain": dict(
        duration_names="plain",
        duration_frequency="every_note",
        octave_naming="plain",
        octave_frequency="on_change",
        rests="structural",
        word_order="pitch_first",
        chords=True,
    ),
    "standard": dict(),
    "compact": dict(
        beat_prefix="none",
        octave_naming="numeric",
        rests="structural",
        dynamics=True,
        ties=True,
    ),
    "braille40": dict(
        beat_prefix="short",
        octave_naming="numeric",
        octave_frequency="braille_rules",
        rests="structural",
        abbreviations=True,
        word_order="pitch_first",
        repetition_mode="learning",
    ),
    "reference": dict(
        duration_frequency="every_note",
        octave_naming="numeric",
        octave_frequency="every_note",
        rests="all",
        intervals=True,
        beams=True,
        repetition_mode="detailed",
    ),
}


def _legacy_choice(field_name, mapping):
    def translate(value):
        if value in mapping:
            return {field_name: mapping[value]}
        return {}
    return translate


def _legacy_bool(field_name):
    return lambda value: {field_name: bool(value)}


LEGACY_OPTION_MAP = {
    "rhythm_description": _legacy_choice("duration_names", {
        "british": "british", "american": "american", "none": "none"}),
    "rhythm_announcement": _legacy_choice("duration_frequency", {
        "onChange": "on_change", "everyNote": "every_note"}),
    "pitch_description": _legacy_choice("pitch_names", {
        "noteName": "letters", "phonetic": "phonetic", "colourNotes": "colours", "none": "none"}),
    "octave_description": _legacy_choice("octave_naming", {
        "name": "descriptive", "number": "numeric", "figureNotes": "figurenotes", "none": "none"}),
    "octave_announcement": _legacy_choice("octave_frequency", {
        "onChange": "on_change", "everyNote": "every_note",
        "firstNote": "first_note", "brailleRules": "braille_rules"}),
    "octave_position": _legacy_choice("octave_position", {"before": "before", "after": "after"}),
    "include_rests": lambda value: {"rests": "all" if value else "none"},
    "include_ties": _legacy_bool("ties"),
    "include_arpeggios": _legacy_bool("arpeggios"),
    "describe_chords": _legacy_bool("chords"),
    "include_dynamics": _legacy_bool("dynamics"),
    "figureNoteColours": lambda value: {"pitch_colours": dict(value or {})},
    "advanced_rhythm_colours": lambda value: {"rhythm_colours": dict(value or {})},
    "advanced_octave_colours": lambda value: {"octave_colours": dict(value or {})},
}
