"""
Words for musical facts, chosen by the reading settings.

Every method returns plain text. Colour classes are attached by the renderer,
not here, so the same vocabulary serves the page, the text file and braille.
"""

from fractions import Fraction

BRITISH_DURATIONS = {
    'whole': 'semibreve', 'half': 'minim', 'quarter': 'crotchet',
    'eighth': 'quaver', '16th': 'semi-quaver', '32nd': 'demi-semi-quaver',
    '64th': 'hemi-demi-semi-quaver', 'breve': 'breve', 'zero': 'grace note',
}

AMERICAN_DURATIONS = {
    'whole': 'whole note', 'half': 'half note', 'quarter': 'quarter note',
    'eighth': 'eighth note', '16th': 'sixteenth note', '32nd': 'thirty-second note',
    '64th': 'sixty-fourth note', 'breve': 'double whole note', 'zero': 'grace note',
}

# The fixed abbreviation table used by the Braille display style.
ABBREVIATED_DURATIONS = {
    'whole': 'sb', 'half': 'mn', 'quarter': 'cr', 'eighth': 'qv',
    '16th': 'sq', '32nd': 'dsq', '64th': 'hdsq', 'breve': 'br', 'zero': 'gr',
}

DOT_WORDS = {0: '', 1: 'dotted', 2: 'double dotted', 3: 'triple dotted'}

DESCRIPTIVE_OCTAVES = {
    0: 'bottom', 1: 'bottom', 2: 'lower', 3: 'low', 4: 'mid',
    5: 'high', 6: 'higher', 7: 'top', 8: 'top',
}

PLAIN_OCTAVES = {
    0: 'lowest', 1: 'lowest', 2: 'very low', 3: 'low', 4: 'middle',
    5: 'high', 6: 'very high', 7: 'highest', 8: 'highest',
}

FIGURENOTES_OCTAVES = {
    1: 'bottom', 2: 'cross', 3: 'square', 4: 'circle',
    5: 'triangle', 6: 'higher', 7: 'top',
}

FIGURENOTES_COLOURS = {
    'C': 'red', 'D': 'brown', 'E': 'grey', 'F': 'blue',
    'G': 'black', 'A': 'yellow', 'B': 'green',
}

PHONETIC_LETTERS = {
    'C': 'charlie', 'D': 'delta', 'E': 'echo', 'F': 'foxtrot',
    'G': 'golf', 'A': 'alpha', 'B': 'bravo',
}

ACCIDENTAL_WORDS = {
    'sharp': 'sharp', 'flat': 'flat', 'natural': 'natural',
    'double-sharp': 'double sharp', 'double-flat': 'double flat',
}

ACCIDENTAL_SYMBOLS = {
    'sharp': '♯', 'flat': '♭', 'natural': '♮', 'double-sharp': '𝄪', 'double-flat': '♭♭',
}

ACCIDENTAL_ABBREVIATIONS = {
    'sharp': 'sh', 'flat': 'fl', 'natural': 'nat', 'double-sharp': 'dsh', 'double-flat': 'dfl',
}

TIE_WORDS = {'start': 'tied to next', 'stop': 'tied from previous', 'continue': 'tied through'}

INTERVAL_NAMES = {
    1: 'same note', 2: 'a second', 3: 'a third', 4: 'a fourth', 5: 'a fifth',
    6: 'a sixth', 7: 'a seventh', 8: 'an octave', 9: 'a ninth', 10: 'a tenth',
    11: 'an eleventh', 12: 'a twelfth', 13: 'a thirteenth', 14: 'a fourteenth',
    15: 'two octaves',
}

FRACTION_PHRASES = {
    Fraction(1, 2): 'half a beat', Fraction(1, 4): 'a quarter of a beat',
    Fraction(3, 4): 'three quarters of a beat', Fraction(1, 3): 'a third of a beat',
    Fraction(2, 3): 'two thirds of a beat', Fraction(1, 8): 'an eighth of a beat',
    Fraction(3, 8): 'three eighths of a beat', Fraction(1, 6): 'a sixth of a beat',
    Fraction(1, 16): 'a sixteenth of a beat',
}

MIXED_FRACTION_PHRASES = {
    Fraction(1, 2): 'a half', Fraction(1, 4): 'a quarter', Fraction(3, 4): 'three quarters',
    Fraction(1, 3): 'a third', Fraction(2, 3): 'two thirds', Fraction(1, 8): 'an eighth',
}


def beats_phrase(quarter_length, beat_quarter_length):
    """Describe a length as beats: "1 beat", "half a beat", "2 and a half beats"."""
    if not quarter_length:
        return 'grace note'
    beats = Fraction(quarter_length).limit_denominator(48) / Fraction(beat_quarter_length or 1).limit_denominator(48)
    whole = beats.numerator // beats.denominator
    remainder = beats - whole
    if remainder == 0:
        return '1 beat' if whole == 1 else f'{whole} beats'
    if whole == 0:
        phrase = FRACTION_PHRASES.get(remainder)
        return phrase or f'{float(beats):g} of a beat'
    mixed = MIXED_FRACTION_PHRASES.get(remainder)
    if mixed:
        return f'{whole} and {mixed} beats'
    return f'{float(beats):g} beats'


class Vocabulary:
    def __init__(self, settings):
        self.settings = settings

    # Rhythm

    def dots(self, dots):
        if self.settings.abbreviations:
            return 'd' * dots
        return DOT_WORDS.get(dots, '')

    def duration(self, event, beat_quarter_length=1.0):
        """The written note value, including dots, in the chosen words."""
        names = self.settings.duration_names
        if names == 'none':
            return ''
        if self.settings.abbreviations:
            base = ABBREVIATED_DURATIONS.get(event.duration_type, event.duration_type or '')
            return self.dots(event.dots) + base
        if names == 'plain':
            return beats_phrase(event.quarter_length, beat_quarter_length)
        table = AMERICAN_DURATIONS if names == 'american' else BRITISH_DURATIONS
        base = table.get(event.duration_type, event.duration_type or '')
        dots = self.dots(event.dots)
        if not dots:
            return base
        if self.settings.dot_position == 'after':
            return f'{base} {dots}'
        return f'{dots} {base}'

    def duration_slug(self, event):
        """Key used for rhythm colour classes, matching the options form."""
        name = BRITISH_DURATIONS.get(event.duration_type, event.duration_type or '')
        return name.lower().replace(' ', '-')

    def tuplet_start(self, tuplet):
        name, actual, normal = tuplet
        if self.settings.abbreviations:
            return f'{actual}:{normal}'
        if name == 'Triplet':
            return 'triplets'
        return f'{name} ({actual} in {normal})'

    def tuplet_stop(self):
        return '' if self.settings.abbreviations else 'end tuplet'

    # Pitch

    def pitch(self, pitch, show_accidental):
        names = self.settings.pitch_names
        if names == 'colours':
            base = FIGURENOTES_COLOURS.get(pitch.step, pitch.step)
        elif names == 'phonetic':
            base = PHONETIC_LETTERS.get(pitch.step, pitch.step)
        elif names == 'none':
            base = ''
        else:
            base = pitch.step
        if not show_accidental or not pitch.accidental_name:
            return base
        if self.settings.abbreviations:
            return f'{base}{ACCIDENTAL_ABBREVIATIONS.get(pitch.accidental_name, "")}'
        if self.settings.accidental_style == 'symbols':
            return f'{base}{ACCIDENTAL_SYMBOLS.get(pitch.accidental_name, "")}'
        return f'{base} {ACCIDENTAL_WORDS.get(pitch.accidental_name, pitch.accidental_name)}'

    def show_accidental(self, pitch):
        mode = self.settings.key_signature_accidentals
        if not pitch.accidental_name:
            return False
        if mode == 'standard':
            return bool(pitch.accidental_displayed)
        if mode in ('on_change', 'onChange'):
            return bool(pitch.accidental_changed)
        return pitch.accidental_name != 'natural'

    def octave(self, pitch, previous_pitch=None):
        naming = self.settings.octave_naming
        octave = pitch.octave
        if naming == 'none':
            return ''
        if naming == 'numeric':
            return str(octave)
        if naming == 'plain':
            return PLAIN_OCTAVES.get(octave, str(octave))
        if naming == 'figurenotes':
            return FIGURENOTES_OCTAVES.get(octave, str(octave))
        if naming == 'relative':
            if previous_pitch is None:
                return PLAIN_OCTAVES.get(octave, str(octave))
            if pitch.pitch_number > previous_pitch.pitch_number:
                return 'up'
            if pitch.pitch_number < previous_pitch.pitch_number:
                return 'down'
            return 'same'
        return DESCRIPTIVE_OCTAVES.get(octave, str(octave))

    def octave_band(self, octave):
        """high, mid or low: the key used for octave colour classes."""
        if octave is None:
            return 'mid'
        if octave >= 5:
            return 'high'
        if octave == 4:
            return 'mid'
        return 'low'

    def interval(self, previous_pitch, pitch):
        if previous_pitch is None:
            return ''
        steps = pitch.diatonic_number - previous_pitch.diatonic_number
        size = abs(steps) + 1
        name = INTERVAL_NAMES.get(size, f'{size - 1} steps')
        if steps == 0:
            return 'same note'
        direction = 'up' if steps > 0 else 'down'
        if self.settings.abbreviations:
            return f'{direction} {size}'
        return f'{direction} {name}'

    # Other events

    def rest(self, event, beat_quarter_length=1.0):
        if self.settings.abbreviations:
            return f'{self.duration(event, beat_quarter_length)} r'.strip()
        if self.settings.duration_names == 'plain':
            return f'rest for {beats_phrase(event.quarter_length, beat_quarter_length)}'
        duration = self.duration(event, beat_quarter_length)
        return f'{duration} rest'.strip()

    def unpitched(self, event, beat_quarter_length=1.0):
        return f'{self.duration(event, beat_quarter_length)} unpitched'.strip()

    def tie(self, tie_type):
        if self.settings.abbreviations:
            return 'tie'
        return TIE_WORDS.get(tie_type, '')

    def chord_count(self, count):
        if self.settings.abbreviations:
            return f'{count}ch'
        if self.settings.duration_names == 'plain':
            return f'{count} notes together'
        return f'{count}-note chord'

    def chord_symbol(self, figure):
        if self.settings.abbreviations:
            return f'[{figure}]'
        return f'chord symbol {figure}'

    def dynamic(self, event):
        if self.settings.abbreviations and event.short_name:
            return event.short_name
        name = event.long_name or event.short_name or ''
        return name.lower()

    def beam(self, beam_type):
        if beam_type == 'start':
            return 'beam starts'
        if beam_type == 'stop':
            return 'beam ends'
        return ''

    def expression(self, name):
        return name.lower()

    def beat_label(self, beat_number):
        prefix = self.settings.beat_prefix
        if prefix == 'none':
            return ''
        if prefix == 'short':
            return f'b{beat_number}'
        return f'Beat {beat_number}'

    def whole_bar_rest(self):
        if self.settings.abbreviations:
            return 'bar r'
        return 'Rests for the whole bar'

    def same_as_bar(self, bar_number):
        if self.settings.abbreviations:
            return f'= bar {bar_number}'
        return f'Same as bar {bar_number}'

    def same_rhythm_as_bar(self, bar_number):
        if self.settings.abbreviations:
            return f'rhythm = bar {bar_number}'
        return f'Same rhythm as bar {bar_number}'

    def octave_reference_line(self):
        """One line per part that says what the octave words mean."""
        naming = self.settings.octave_naming
        if naming == 'plain':
            return 'Middle means the octave from middle C up to the B above it. High is the octave above that, low the octave below.'
        if naming == 'descriptive':
            return 'Mid means the octave from middle C up to the B above it. High is the octave above that, low the octave below.'
        if naming == 'numeric':
            return 'Octave numbers follow scientific pitch notation: middle C is C4.'
        if naming == 'relative':
            return 'Up, down and same give the direction from the previous note.'
        return ''
