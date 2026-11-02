"""
Suggested fingering for instruments other than the piano.

Each instrument turns a note's sounding pitch into what the player does: a
string and fret on the guitar, a string and finger on the violin, a valve
combination on the trumpet. Pitches are MIDI numbers (middle C is 60), always
at sounding pitch; each instrument converts to its own written pitch.

Every note's fingering is held as a small dict, so the read-out can say where
the hand moves without parsing words back.
"""

import re
from itertools import product

INSTRUMENTS = ("piano", "guitar", "violin", "trumpet")


GUITAR_NAMES = re.compile(r"guitar|gitarre|guitare|chitarra", re.IGNORECASE)
VIOLIN_NAMES = re.compile(r"violin|violino|geige|violon\b", re.IGNORECASE)
TRUMPET_NAMES = re.compile(r"trumpet|tromba|trompete|trompette|cornet", re.IGNORECASE)


def detect(instrument_object, names):
    """guitar, violin or trumpet for a part played on one, from its instrument or its name, else None."""
    classes = {cls.__name__ for cls in type(instrument_object).__mro__}
    if "Guitar" in classes and "ElectricBass" not in classes and not re.search("bass", names, re.IGNORECASE):
        return "guitar"
    if "Violin" in classes:
        return "violin"
    if "Trumpet" in classes:
        return "trumpet"
    if GUITAR_NAMES.search(names) and not re.search("bass", names, re.IGNORECASE):
        return "guitar"
    if VIOLIN_NAMES.search(names):
        return "violin"
    if TRUMPET_NAMES.search(names):
        return "trumpet"
    return None


# Guitar: standard tuning, written an octave above sounding.

GUITAR_OPEN = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}   # string number: sounding pitch
GUITAR_FRETS = 19
# Frets one hand covers without moving: the index finger's fret and three above.
GUITAR_SPAN = 3


def guitar_places(pitch):
    """Every (string, fret) that sounds this pitch."""
    return [(string, int(round(pitch)) - open_pitch)
            for string, open_pitch in GUITAR_OPEN.items()
            if 0 <= int(round(pitch)) - open_pitch <= GUITAR_FRETS]


def _guitar_shapes(pitches):
    """Ways to play notes struck together: one string each, fretted notes within one hand's reach."""
    shapes = []
    for places in product(*(guitar_places(p) for p in pitches)):
        strings = [string for string, _ in places]
        if len(set(strings)) != len(strings):
            continue
        fretted = [fret for _, fret in places if fret]
        if fretted and max(fretted) - min(fretted) > GUITAR_SPAN:
            continue
        shapes.append(places)
    return shapes


def _guitar_position(shape):
    fretted = [fret for _, fret in shape if fret]
    return min(fretted) if fretted else None


def plan_guitar(moments):
    """A (string, fret) per note, for moments of sounding pitches, lowest first.

    The cheapest path keeps the hand still, then low on the neck: moving the
    hand costs a little per fret, and a high fret a little more than a low one.
    A moment no shape fits is left unfingered and breaks the path.
    """
    results = [None] * len(moments)
    layers = []
    for index, pitches in enumerate(moments):
        shapes = _guitar_shapes(pitches) if pitches else []
        if not shapes:
            _cheapest_guitar_path(layers, results)
            layers = []
            continue
        layers.append((index, shapes))
    _cheapest_guitar_path(layers, results)
    return results


def _guitar_own_cost(shape):
    return sum(0.15 * fret for _, fret in shape)


def _guitar_move_cost(previous, current):
    before, after = _guitar_position(previous), _guitar_position(current)
    if before is None or after is None:
        return 0.0
    if after <= before + GUITAR_SPAN and after >= before:
        return 0.0
    return 1.0 + abs(after - before) * 0.5


def _cheapest_guitar_path(layers, results):
    if not layers:
        return
    costs = [_guitar_own_cost(shape) for shape in layers[0][1]]
    pointers = []
    for (_, previous_shapes), (_, shapes) in zip(layers, layers[1:]):
        new_costs, back = [], []
        for shape in shapes:
            best = min(range(len(previous_shapes)),
                       key=lambda i: costs[i] + _guitar_move_cost(previous_shapes[i], shape))
            new_costs.append(costs[best] + _guitar_move_cost(previous_shapes[best], shape)
                             + _guitar_own_cost(shape))
            back.append(best)
        costs = new_costs
        pointers.append(back)
    choice = min(range(len(costs)), key=costs.__getitem__)
    for layer in range(len(layers) - 1, -1, -1):
        index, shapes = layers[layer]
        results[index] = shapes[choice]
        if layer:
            choice = pointers[layer - 1][choice]


def guitar_text(string, fret):
    return f"string {string} open" if fret == 0 else f"string {string} fret {fret}"


# Violin: first position, written at sounding pitch.

VIOLIN_STRINGS = (("E", 76), ("A", 69), ("D", 62), ("G", 55))
# Semitones above the open string, in first position.
VIOLIN_FINGERS = {0: "open", 1: "low 1", 2: "1", 3: "low 2", 4: "high 2", 5: "3", 6: "high 3", 7: "4"}


def violin_place(pitch):
    """(string, finger) in first position, or None for a note outside it.

    The highest string that reaches the note is used, so an open string is
    preferred to a fourth finger on the string below.
    """
    pitch = int(round(pitch))
    for name, open_pitch in VIOLIN_STRINGS:
        distance = pitch - open_pitch
        if 0 <= distance <= 7:
            return name, VIOLIN_FINGERS[distance]
    return None


def violin_text(string, finger):
    return f"{string} string open" if finger == "open" else f"{finger} on {string}"


# Trumpet in B flat: written a tone above sounding.

TRUMPET_WRITTEN_RANGE = (54, 84)     # written F sharp below middle C to the C two octaves above middle C
TRUMPET_VALVES = {
    54: "1 2 3", 55: "1 3", 56: "2 3", 57: "1 2", 58: "1", 59: "2", 60: "open",
    61: "1 2 3", 62: "1 3", 63: "2 3", 64: "1 2", 65: "1", 66: "2", 67: "open",
    68: "2 3", 69: "1 2", 70: "1", 71: "2", 72: "open",
    73: "1 2", 74: "1", 75: "2", 76: "open", 77: "1", 78: "2", 79: "open",
    80: "2 3", 81: "1 2", 82: "1", 83: "2", 84: "open",
}


def trumpet_valves(pitch):
    """The standard valves for a sounding pitch on a B flat trumpet, or None outside its range."""
    return TRUMPET_VALVES.get(int(round(pitch)) + 2)


def trumpet_text(valves):
    if valves == "open":
        return "open"
    numbers = valves.split()
    if len(numbers) == 1:
        return f"valve {numbers[0]}"
    return "valves " + ", ".join(numbers[:-1]) + " and " + numbers[-1]


# Reading fingering back

def describe(instrument, moments):
    """Where the hand goes in one bar, then every note's fingering.

    moments: one list per moment of (note name, fingering dict), in the
    order they sound. Returns (positions, every note), with positions empty
    where the instrument has nothing to say beyond the notes themselves.
    """
    moments = [[note for note in moment if note[1]] for moment in moments]
    moments = [moment for moment in moments if moment]
    if not moments:
        return "", ""
    detail = ", ".join(" with ".join(f"{name} {info['text']}" for name, info in moment) for moment in moments)
    if instrument == "guitar":
        return _guitar_positions(moments), detail
    if instrument == "violin":
        return _violin_positions(moments), detail
    return "", detail


def _guitar_positions(moments):
    phrases = []
    position = None
    for moment in moments:
        frets = [info["fret"] for _, info in moment if info.get("fret")]
        if not frets and any("fret" not in info for _, info in moment):
            continue
        if not frets:
            if not phrases:
                phrases.append("open strings")
            continue
        if position is None:
            position = min(frets)
            phrases = [f"hand at fret {position}"]
            continue
        if min(frets) < position or max(frets) > position + GUITAR_SPAN:
            position = min(frets)
            phrases.append(f"moves to fret {position}")
    return ", ".join(phrases)


def _violin_positions(moments):
    phrases = []
    string = None
    for moment in moments:
        name, info = moment[0]
        if "string" not in info:
            continue
        if info["string"] != string:
            string = info["string"]
            phrases.append(f"on the {string} string" if not phrases else f"to the {string} string")
    return "first position, " + ", ".join(phrases) if phrases else ""
