"""
Piano fingering: suggesting fingers for notes, and reading fingers back as words.

Fingers are numbered as pianists number them, 1 for the thumb to 5 for the
little finger, on both hands. The suggestions come from a cost model in the
spirit of Parncutt and others (1997): each pair of consecutive fingers has a
relaxed, a comfortable and a practical span in semitones, and stretching past
them, passing the thumb, or putting the thumb on a black key costs more. The
cheapest fingering for the whole part is found by dynamic programming, so a
choice early in a phrase can depend on the notes after it. Fingers printed in
the score are fixed points the suggestion has to pass through.

Experienced pianists agree with one another on about 70 per cent of notes, so
a suggestion is one playable fingering, never the only one.
"""

from itertools import combinations

FINGERS = (1, 2, 3, 4, 5)

# Spans in semitones from the lower-numbered finger to the higher-numbered one
# for the right hand: practical minimum, comfortable minimum, relaxed minimum,
# relaxed maximum, comfortable maximum, practical maximum. A negative span
# means the fingers cross, which only the thumb with fingers 2 to 4 can do;
# the practical minimums for those pairs are wider than Parncutt's so the
# thumb can pass under a fourth, as in an arpeggio.
SPANS = {
    (1, 2): (-7, -3, 1, 5, 8, 10),
    (1, 3): (-7, -2, 3, 7, 10, 12),
    (1, 4): (-5, -1, 5, 9, 12, 14),
    (1, 5): (1, 1, 7, 10, 13, 15),
    (2, 3): (1, 1, 1, 2, 3, 5),
    (2, 4): (1, 1, 3, 4, 5, 7),
    (2, 5): (2, 2, 5, 6, 8, 10),
    (3, 4): (1, 1, 1, 2, 2, 4),
    (3, 5): (1, 1, 3, 4, 5, 7),
    (4, 5): (1, 1, 1, 2, 3, 5),
}

# A leap wider than any span lifts the hand, which costs the same whichever
# fingers take off and land.
LEAP_COST = 8.0
IMPOSSIBLE = 50.0
BLACK_PITCH_CLASSES = frozenset({1, 3, 6, 8, 10})


def is_black(pitch_number):
    return int(round(pitch_number)) % 12 in BLACK_PITCH_CLASSES


def pair_cost(finger_a, pitch_a, finger_b, pitch_b, hand):
    """What moving from one finger on one note to another finger on the next costs."""
    distance = pitch_b - pitch_a
    if hand == "left":
        # The left hand's fingers count downwards, so its spans mirror the right hand's.
        distance = -distance
    if finger_a == finger_b:
        return 0.0 if distance == 0 else 6.0 + abs(distance) * 0.5
    if distance == 0:
        return 1.0
    low, high = sorted((finger_a, finger_b))
    span = distance if finger_b > finger_a else -distance
    min_prac, min_comf, min_rel, max_rel, max_comf, max_prac = SPANS[(low, high)]
    if span > max_prac or (span < min_prac and abs(distance) > 7):
        return LEAP_COST
    if span < min_prac:
        return IMPOSSIBLE
    thumb = low == 1
    if span < 0:
        # Passing the thumb under, or a finger over the thumb, is how scales are
        # played; it costs a little more the further the hand has to turn.
        return 4.0 + abs(span) * 0.5 + (1.0 if high == 4 else 0.0)
    cost = 0.0
    if span < min_rel:
        cost += (min_rel - span) * (2.0 if thumb else 1.0)
    if span > max_rel:
        cost += (span - max_rel) * (1.0 if thumb else 2.0)
    if span < min_comf:
        cost += (min_comf - span) * 2.0
    if span > max_comf:
        cost += (span - max_comf) * 2.0
    if {finger_a, finger_b} == {3, 4}:
        cost += 0.5
    return cost


def finger_cost(finger, pitch_number):
    """The cost of one finger on one key, whatever comes before or after."""
    cost = 0.0
    if finger == 4:
        cost += 0.25
    if is_black(pitch_number):
        if finger == 1:
            cost += 2.0
        elif finger == 5:
            cost += 1.0
    return cost


def candidates(pitches, hand, fixed):
    """Every finger assignment for one moment, lowest note first.

    The right hand plays a chord with fingers rising from the bottom note, the
    left hand with fingers rising from the top note. A finger printed in the
    score for a note keeps that note on that finger.
    """
    count = len(pitches)
    found = []
    for chosen in combinations(FINGERS, count):
        fingers = chosen if hand == "right" else tuple(reversed(chosen))
        if any(fixed[i] is not None and fixed[i] != fingers[i] for i in range(count)):
            continue
        found.append(fingers)
    return found


def chord_cost(pitches, fingers, hand):
    cost = sum(finger_cost(f, p) for f, p in zip(fingers, pitches))
    for i in range(len(pitches) - 1):
        span_cost = pair_cost(fingers[i], pitches[i], fingers[i + 1], pitches[i + 1], hand)
        # Notes struck together cannot be reached with a leap.
        cost += IMPOSSIBLE if span_cost == LEAP_COST else span_cost
        if abs(fingers[i] - fingers[i + 1]) == 1 and abs(pitches[i + 1] - pitches[i]) >= 3:
            # Neighbouring fingers on a third or wider leave the hand cramped
            # where skipping a finger lets it rest open.
            cost += 0.5
    return cost


def transition_cost(previous, current, hand):
    """Moving from one moment to the next, judged on the outer notes of each."""
    (prev_pitches, prev_fingers), (pitches, fingers) = previous, current
    costs = []
    for edge in (0, -1):
        cost = pair_cost(prev_fingers[edge], prev_pitches[edge], fingers[edge], pitches[edge], hand)
        if len(prev_pitches) > 1 and len(pitches) > 1 and prev_fingers[edge] == fingers[edge]:
            # One chord to the next keeps its shape and moves the whole hand,
            # which is how chords are played, not a finger sliding between keys.
            cost = abs(pitches[edge] - prev_pitches[edge]) * 0.25
        costs.append(cost)
    return sum(costs) / 2.0


def plan(moments, hand):
    """Fingers for a run of moments.

    moments: one list per moment of (pitch number, printed finger or None),
    in the order they sound. Returns one tuple of fingers per moment, matching
    each moment's notes sorted from lowest to highest, or None for a moment
    with more notes than one hand has fingers.
    """
    hand = "left" if hand == "left" else "right"
    results = [None] * len(moments)
    run = []
    for index, moment in enumerate(moments):
        if 0 < len(moment) <= len(FINGERS):
            run.append(index)
            continue
        _plan_run(moments, run, hand, results)
        run = []
    _plan_run(moments, run, hand, results)
    return results


def _plan_run(moments, indices, hand, results):
    if not indices:
        return
    layers = []
    for index in indices:
        notes = sorted(moments[index], key=lambda note: note[0])
        pitches = [note[0] for note in notes]
        fixed = [note[1] for note in notes]
        options = candidates(pitches, hand, fixed) or candidates(pitches, hand, [None] * len(pitches))
        layers.append((pitches, options))

    first_pitches, first_options = layers[0]
    costs = [chord_cost(first_pitches, option, hand) for option in first_options]
    back_pointers = []
    for (prev_pitches, prev_options), (pitches, options) in zip(layers, layers[1:]):
        new_costs = []
        pointers = []
        for option in options:
            own = chord_cost(pitches, option, hand)
            best_cost, best_index = None, 0
            for prev_index, prev_option in enumerate(prev_options):
                total = costs[prev_index] + transition_cost(
                    (prev_pitches, prev_option), (pitches, option), hand)
                if best_cost is None or total < best_cost:
                    best_cost, best_index = total, prev_index
            new_costs.append(best_cost + own)
            pointers.append(best_index)
        costs = new_costs
        back_pointers.append(pointers)

    choice = min(range(len(costs)), key=costs.__getitem__)
    chosen = [None] * len(layers)
    for layer in range(len(layers) - 1, -1, -1):
        chosen[layer] = layers[layer][1][choice]
        if layer > 0:
            choice = back_pointers[layer - 1][choice]
    for index, fingers in zip(indices, chosen):
        results[index] = fingers


# Reading fingers back

def diatonic_number(step, octave):
    return "CDEFGAB".index(step) + 7 * (octave or 0)


def describe(moments, hand):
    """Hand positions and shifts for one bar, then every finger in order.

    moments: one list per moment of (name, finger, step, octave, pitch number),
    in the order they sound, each moment's notes from lowest to highest.
    Returns (positions, every finger), both as text, or ("", "") when no note
    in the bar has a finger.
    """
    moments = [[note for note in moment if note[1]] for moment in moments]
    moments = [moment for moment in moments if moment]
    if not moments:
        return "", ""
    detail = ", ".join(" with ".join(f"{note[0]} {note[1]}" for note in moment) for moment in moments)

    left = hand == "left"
    phrases = [_landing(moments[0])]
    previous = _lead(moments[0], left)
    # A change of finger on a held note moves the hand before the next note.
    position = _thumb_position(previous, left, last=True)
    for moment in moments[1:]:
        lead = _lead(moment, left)
        finger = first_finger(lead[1])
        before = _last_finger(previous[1])
        rising = lead[4] > previous[4]
        falling = lead[4] < previous[4]
        towards_little_finger = falling if left else rising
        towards_thumb = rising if left else falling
        thumb = _thumb_position(lead, left)
        if finger == 1 and before not in (None, 1) and towards_little_finger:
            phrases.append(f"thumb under on {lead[0]}")
        elif before == 1 and finger not in (None, 1) and towards_thumb:
            phrases.append(f"{finger} over on {lead[0]}")
        elif thumb is not None and position is not None and abs(thumb - position) >= 2:
            phrases.append(f"hand moves, {_landing(moment)}")
        elif thumb is not None:
            # A stretch of one key keeps the hand where it was.
            previous = lead
            continue
        position = _thumb_position(lead, left, last=True)
        previous = lead
    return ", ".join(phrases), detail


def _lead(moment, left):
    """The note that places the hand: the lowest for the right hand, the highest for the left."""
    return moment[-1] if left else moment[0]


def _landing(moment):
    fingers = " ".join(note[1] for note in moment)
    names = " ".join(note[0] for note in moment)
    return f"{fingers} on {names}"


def first_finger(text):
    """A finger change on one note, such as 3-1, starts on its first finger."""
    try:
        return int(str(text).replace("-", " ").split()[0])
    except (ValueError, IndexError):
        return None


def _last_finger(text):
    try:
        return int(str(text).replace("-", " ").split()[-1])
    except (ValueError, IndexError):
        return None


def _thumb_position(note, left, last=False):
    """Where the thumb would rest, counted in letter steps, with the hand spread one key per finger."""
    finger = _last_finger(note[1]) if last else first_finger(note[1])
    if finger is None or note[2] is None:
        return None
    number = diatonic_number(note[2], note[3])
    return number + (finger - 1) if left else number - (finger - 1)
