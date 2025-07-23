from datetime import datetime
import time
from jinja2 import Template
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from jinja2.loaders import FileSystemLoader

__author__ = 'BTimms'

import os
import json
import math
import pprint
import logging
import logging.handlers
import logging.config
from music21 import *
from lib.musicAnalyser import *
import re
from types import SimpleNamespace
us = environment.UserSettings()
us['warnings'] = 0
logger = logging.getLogger("TSScore")

global settings
settings = {
    'rhythmDescription': 'british',
    'dotPosition': 'before',
    'octaveDescription': 'name',
    'pitchDescription': 'noteName',
}

def get_contrast_color(hex_color):
    """
    Calculates whether black or white text has a better contrast against a given hex color.
    """
    try:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
        return 'black' if luminance > 0.5 else 'white'
    except ValueError:
        return 'white'

def render_colourful_output(text, pitchLetter, elementType, settings):
    """
    Wraps text in a styled <span>. Supports independent and inherited colouring.
    """
    toRender = text
    color_to_use = None
    pitch_color = settings.get("figureNoteColours", {}).get(pitchLetter)

    if elementType == "pitch" and settings.get("colourPitch"):
        color_to_use = pitch_color

    elif elementType == "rhythm":
        mode = settings.get("rhythm_colour_mode", "none")
        if mode == 'inherit' and settings.get("colourPitch"):
            color_to_use = pitch_color
        elif mode == 'custom':
            rhythm_colours = settings.get("advanced_rhythm_colours", {})
            slug_text = text.lower().replace(" ", "-")
            for rhythm_slug, color in rhythm_colours.items():
                if rhythm_slug in slug_text:
                    color_to_use = color
                    break
    
    elif elementType == "octave":
        mode = settings.get("octave_colour_mode", "none")
        if mode == 'inherit' and settings.get("colourPitch"):
            color_to_use = pitch_color
        elif mode == 'custom':
            octave_colours = settings.get("advanced_octave_colours", {})
            octave_text = text.lower()
            if any(term in octave_text for term in ["high", "top", "5", "6", "7"]):
                color_to_use = octave_colours.get("high")
            elif any(term in octave_text for term in ["mid", "4"]):
                color_to_use = octave_colours.get("mid")
            elif any(term in octave_text for term in ["low", "bottom", "1", "2", "3"]):
                color_to_use = octave_colours.get("low")
    
    if settings.get("colourPosition") != "none" and color_to_use:
        style_type = settings.get("colourPosition")
        if style_type == "background":
            contrast_color = get_contrast_color(color_to_use)
            toRender = f"<span style='color:{contrast_color}; background-color:{color_to_use};'>{text}</span>"
        else:
            toRender = f"<span style='color:{color_to_use};'>{text}</span>"

    return toRender
class TSEvent(object, metaclass=ABCMeta):
    duration = None
    tuplets = ""
    endTuplets = ""
    bar = None
    part = None
    tie = None
    start_offset = 0.0
    beat = 0.0

    def render(self, settings, context=None, noteLetter=None):
        rendered_elements = []
        if settings.get('rhythmDescription', 'british') != 'none' and \
           (context is None or context.duration != self.duration or self.tuplets != "" or settings['rhythmAnnouncement'] == "everyNote"):
            rendered_elements.append(self.tuplets)
            if (noteLetter != None):
                rendered_elements.append(render_colourful_output(self.duration, noteLetter, "rhythm", settings))
            else:
                rendered_elements.append(self.duration)
            rendered_elements.append(self.endTuplets)

        if self.tie and settings.get('include_ties', True):
            rendered_elements.append(f"tie {self.tie}")

        return list(filter(None, rendered_elements))


class TSDynamic(TSEvent):
    short_name = None
    long_name = None

    def __init__(self, long_name=None, short_name=None):
        if (long_name != None):
            self.long_name = long_name.capitalize()
        else:
            self.long_name = short_name

        self.short_name = short_name

    def render(self, settings, context=None):
        if self.long_name:
            return [f'[{self.long_name}]']
        return []


class TSPitch(TSEvent):
    pitch_name = None
    octave = None
    pitch_letter = None

    def __init__(self, pitch_name, octave, pitch_number, pitch_letter):
        self.pitch_name = pitch_name
        self.octave = octave
        self.pitch_number = pitch_number
        self.pitch_letter = pitch_letter

    def render(self, settings, context=None):
        rendered_elements = []
        if settings['octavePosition'] == "before":
            rendered_elements.append(self.render_octave(settings, context))
        rendered_elements.append(render_colourful_output(self.pitch_name, self.pitch_letter, "pitch", settings))
        if settings['octavePosition'] == "after":
            rendered_elements.append(self.render_octave(settings, context))
        
        return list(filter(None, rendered_elements))

    def render_octave(self, settings, context=None):
        show_octave = False
        if settings['octaveAnnouncement'] == "brailleRules":
            if context == None:
                show_octave = True
            else:
                pitch_difference = abs(context.pitch_number - self.pitch_number)
                if pitch_difference <= 4:
                    show_octave = False
                elif pitch_difference >= 5 and pitch_difference <= 7:
                    if context.octave != self.octave:
                        show_octave = True
                else:
                    show_octave = True
        elif settings['octaveAnnouncement'] == "everyNote":
            show_octave = True
        elif settings['octaveAnnouncement'] == "firstNote" and context == None:
            show_octave = True
        elif settings['octaveAnnouncement'] == "onChange":
            if context == None or (context != None and context.octave != self.octave):
                show_octave = True

        if show_octave:
            return render_colourful_output(self.octave, self.pitch_letter, "octave", settings)
        else:
            return ""


class TSUnpitched(TSEvent):
    pitch = None

    def render(self, settings, context=None):
        rendered_elements = []
        rendered_elements.append(' '.join(super(TSUnpitched, self).render(settings, context)))
        rendered_elements.append(' unpitched')
        return rendered_elements


class TSRest(TSEvent):
    pitch = None

    def render(self, settings, context=None):
        if not settings.get('include_rests', True):
            return [] 

        rendered_elements = []
        rendered_elements.extend(super(TSRest, self).render(settings, context))
        rendered_elements.append('rest')
        
        return list(filter(None, rendered_elements))


class TSNote(TSEvent):
    pitch = None
    expressions = []

    def render(self, settings, context=None):
        rendered_elements = []
        for exp in self.expressions:
            is_arpeggio = 'arpeggio' in exp.name.lower()
            if not is_arpeggio or (is_arpeggio and settings.get('include_arpeggios', True)):
                rendered_elements.append(exp.name)

        rendered_elements.extend(super().render(settings, context, self.pitch.pitch_letter))
        rendered_elements.extend(self.pitch.render(settings, getattr(context, 'pitch', None)))
        
        return list(filter(None, rendered_elements))

class TSChord(TSEvent):
    pitches = []

    def name(self):
        return ''

    def render(self, settings, context=None):
        rendered_elements = []
        if settings.get('describe_chords', True):
            rendered_elements.append(f'{len(self.pitches)}-note chord')
        
        rendered_elements.extend(super(TSChord, self).render(settings, context))
        previous_pitch = None
        for pitch in sorted(self.pitches, key=lambda TSPitch: TSPitch.pitch_number):
            rendered_elements.extend(pitch.render(settings, previous_pitch))
            previous_pitch = pitch
        
        return list(filter(None, rendered_elements))


class TalkingScoreBase(object, metaclass=ABCMeta):
    @abstractmethod
    def get_title(self):
        pass

    @abstractmethod
    def get_composer(self):
        pass
class Music21TalkingScore(TalkingScoreBase):

    _OCTAVE_MAP = {
        1: 'bottom',
        2: 'lower',
        3: 'low',
        4: 'mid',
        5: 'high',
        6: 'higher',
        7: 'top'
    }

    _OCTAVE_FIGURENOTES_MAP = {
        1: 'bottom',
        2: 'cross',
        3: 'square',
        4: 'circle',
        5: 'triangle',
        6: 'higher',
        7: 'top'
    }

    _DOTS_MAP = {
        0: '',
        1: 'dotted ',
        2: 'double dotted ',
        3: 'triple dotted '
    }

    _DURATION_MAP = {
        'whole': 'semibreve',
        'half': 'minim',
        'quarter': 'crotchet',
        'eighth': 'quaver',
        '16th': 'semi-quaver',
        '32nd': 'demi-semi-quaver',
        '64th': 'hemi-demi-semi-quaver',
        'zero': 'grace note',
    }

    _PITCH_FIGURENOTES_MAP = {
        'C': 'red',
        'D': 'brown',
        'E': 'grey',
        'F': 'blue',
        'G': 'black',
        'A': 'yellow',
        'B': 'green',
    }

    _PITCH_PHONETIC_MAP = {
        'C': 'charlie',
        'D': 'bravo',
        'E': 'echo',
        'F': 'foxtrot',
        'G': 'golf',
        'A': 'alpha',
        'B': 'bravo',
    }

    last_tempo_inserted_index = 0
    music_analyser = None

    def __init__(self, musicxml_filepath):
        self.filepath = os.path.realpath(musicxml_filepath)
        self.score = converter.parse(musicxml_filepath)
        super(Music21TalkingScore, self).__init__()

    def get_title(self):
        if self.score.metadata.title is not None:
            return self.score.metadata.title
        for tb in self.score.flatten().getElementsByClass('TextBox'):
            if hasattr(tb, 'justifty') and tb.justify == 'center' and hasattr(tb, 'alignVertical') and tb.alignVertical == 'top' and hasattr(tb, 'size') and tb.size > 18:
                return tb.content
        return "Error reading title"

    def get_composer(self):
        if self.score.metadata.composer != None:
            return self.score.metadata.composer
        for tb in self.score.getElementsByClass('TextBox'):
            if tb.style.justify == 'right':
                return tb.content
        return "Unknown"

    def get_initial_time_signature(self):
        m1 = self.score.parts[0].measures(1, 1)
        initial_time_signature = None
        if (len(self.score.parts[0].getElementsByClass('Measure')[0].getElementsByClass(meter.TimeSignature)) > 0):
            initial_time_signature = self.score.parts[0].getElementsByClass('Measure')[0].getElementsByClass(meter.TimeSignature)[0]
        return self.describe_time_signature(initial_time_signature)

    def describe_time_signature(self, ts):
        if ts != None:
            return " ".join(ts.ratioString.split("/"))
        else:
            return " error reading time signature...  "

    def get_initial_key_signature(self):
        m1 = self.score.parts[0].measures(1, 1)
        if len(m1.flatten().getElementsByClass('KeySignature')) == 0:
            ks = key.KeySignature(0)
        else:
            ks = m1.flatten().getElementsByClass('KeySignature')[0]
        return self.describe_key_signature(ks)

    def describe_key_signature(self, ks):
        strKeySig = "No sharps or flats"
        if (ks.sharps > 0):
            strKeySig = str(ks.sharps) + " sharps"
        elif (ks.sharps < 0):
            strKeySig = str(abs(ks.sharps)) + " flats"
        return strKeySig

    def get_initial_text_expression(self):
        m1 = self.score.parts[0].measures(1, 1)
        text_expressions = m1.flatten().getElementsByClass('TextExpression')
        for te in text_expressions:
            return te.content

    def get_initial_tempo(self):
        global settings
        try:
            settings
        except NameError:
            settings = None
        if settings == None:
            settings = {}
            settings['dotPosition'] = "before"
            settings['rhythmDescription'] = "british"
        return self.describe_tempo(self.score.metronomeMarkBoundaries()[0][2])
    def get_beat_division_options(self):
        """
        Analyzes the initial time signature of the score and returns a list
        of valid beat division options for the user.
        """
        ts = None
        try:
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            for item in first_measure:
                if isinstance(item, meter.TimeSignature):
                    ts = item
                    break
            
            if not ts:
                ts = self.score.getTimeSignatures()[0]
        except Exception as e:
            self.logger.error(f"Could not find any TimeSignature in the score. Error: {e}")
            return []

        options = []
        seen_values = set()

        def add_option(display, value):
            if value not in seen_values:
                options.append({'display': display, 'value': value})
                seen_values.add(value)

        add_option('Group by Bar (continuous)', 'bar')

        default_beat_string = self.map_duration(ts.beatDuration)
        default_display = f"{ts.beatCount} {default_beat_string} beats (Default)"
        default_value = f"{ts.beatCount}/{ts.beatDuration.quarterLength}"
        add_option(default_display, default_value)
        
        face_value_beat_string = self.map_duration(duration.Duration(1.0 / ts.denominator))
        face_value_display = f"{ts.numerator} {face_value_beat_string} beats"
        face_value_value = f"{ts.numerator}/{ts.denominator}"
        add_option(face_value_display, face_value_value)

        if ts.numerator % 3 == 0 and ts.numerator > 3:
            compound_beat_count = ts.numerator / 3
            simple_beat_name = self.map_duration(duration.Duration(1.0 / ts.denominator))
            
            compound_beat_string = f"Dotted {simple_beat_name}"
            compound_display = f"{int(compound_beat_count)} {compound_beat_string} beats"
            
            compound_beat_duration_ql = (1.0 / ts.denominator) * 3
            compound_value = f"{int(compound_beat_count)}/{compound_beat_duration_ql}"
            add_option(compound_display, compound_value)

        return options

    @staticmethod
    def fix_tempo_number(tempo):
        if (tempo.number == None):
            if (tempo.numberSounding != None):
                tempo.number = tempo.numberSounding
            else:
                tempo.number = 120
                tempo.text = "Error - " + tempo.text
        return tempo

    def describe_tempo(self, tempo):
        tempo_text = ""
        tempo = self.fix_tempo_number(tempo)
        if (tempo.text != None):
            tempo_text += tempo.text + " (" + str(math.floor(tempo.number)) + " bpm @ " + self.describe_tempo_referent(tempo) + ")"
        else:
            tempo_text += str(math.floor(tempo.number)) + " bpm @ " + self.describe_tempo_referent(tempo)
        return tempo_text

    def describe_tempo_referent(self, tempo):
        global settings
        tempo_text = ""
        if settings['dotPosition'] == "before":
            tempo_text = self._DOTS_MAP.get(tempo.referent.dots)
        tempo_text += self.map_duration(tempo.referent)
        if settings['dotPosition'] == "after":
            tempo_text += " " + self._DOTS_MAP.get(tempo.referent.dots)

        return tempo_text

    def get_number_of_bars(self):
        return len(self.score.parts[0].getElementsByClass('Measure'))
    def get_instruments(self):
        self.part_instruments = {}
        self.part_names = {}
        instrument_names = []
        ins_count = 1
        for c, instrument in enumerate(self.score.flatten().getInstruments()):
            if len(self.part_instruments) == 0 or self.part_instruments[ins_count-1][3] != instrument.partId:
                pname = instrument.partName
                if pname == None:
                    pname = "Instrument  " + str(ins_count) + " (unnamed)"
                self.part_instruments[ins_count] = [pname, c, 1, instrument.partId]
                instrument_names.append(pname)

                ins_count += 1
            else:
                self.part_instruments[ins_count-1][2] += 1
                if self.part_instruments[ins_count-1][2] == 2:
                    self.part_names[c-1] = "Right hand"
                    self.part_names[c] = "Left hand"
                elif self.part_instruments[ins_count-1][2] == 3:
                    self.part_names[c-2] = "Part 1"
                    self.part_names[c-1] = "Part 2"
                    self.part_names[c] = "Part 3"
                else:
                    self.part_names[c] = "Part " + str(self.part_instruments[ins_count-1][2])

        logger.debug(f"part instruments = {self.part_instruments}")
        return instrument_names

    def compare_parts_with_selected_instruments(self):
        global settings
        self.selected_instruments = []
        self.unselected_instruments = []
        self.binary_selected_instruments = 1
        self.selected_part_names = []
        for ins in self.part_instruments.keys():
            self.binary_selected_instruments = self.binary_selected_instruments << 1
            if ins in settings.get('instruments', []):
                self.selected_instruments.append(ins)
                self.binary_selected_instruments += 1
            else:
                self.unselected_instruments.append(ins)

        for ins in self.selected_instruments:
            ins_name = self.part_instruments[ins][0]
            if self.part_instruments[ins][2] == 1:
                self.selected_part_names.append(ins_name)
            else:
                pn1index = self.part_instruments[ins][1]
                for pni in range(pn1index, pn1index+self.part_instruments[ins][2]):
                    self.selected_part_names.append(ins_name + " - " + self.part_names[pni])

        play_all_choice = settings.get('playAll', False)
        play_selected_choice = settings.get('playSelected', False)
        play_unselected_choice = settings.get('playUnselected', False)

        if len(self.part_instruments) == 1:
            settings['playAll'] = False
            settings['playSelected'] = False
        
        if len(self.unselected_instruments) == 0:
            settings['playUnselected'] = False
        if len(self.selected_instruments) == len(self.part_instruments) and settings.get('playAll', False):
            settings['playSelected'] = False
        if len(self.selected_instruments) == 1:
            settings['playSelected'] = False

        self.binary_play_all = 1
        self.binary_play_all = self.binary_play_all << 1
        if play_all_choice:
            self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if play_selected_choice:
            self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if play_unselected_choice:
            self.binary_play_all += 1

    def get_number_of_parts(self):
        self.get_instruments()
        return len(self.part_instruments)

    def get_bar_range(self, range_start, range_end):
        measures = self.score.measures(range_start, range_end)
        bars_for_parts = {}
        for part in measures.parts:
            bars_for_parts.setdefault(part.id, []).extend(part.getElementsByClass('Measure'))

        return bars_for_parts
    def get_events_for_bar_range(self, start_bar, end_bar, part_index):
        intermediate_events = {}

        measures = self.score.parts[part_index].measures(start_bar, end_bar)
        if measures.measure(start_bar) != None and len(measures.measure(start_bar).getElementsByClass(meter.TimeSignature)) == 0:
            measures.measure(start_bar).insert(0, self.timeSigs[start_bar])

        logger.info(f'Processing part - {part_index} - bars {start_bar} to {end_bar}')
        
        first_bar_num = start_bar
        last_bar_num = end_bar

        for bar_index in range(first_bar_num, last_bar_num + 1):
            measure = measures.measure(bar_index)
            if measure is not None:
                self.update_events_for_measure(measure, intermediate_events)
        
        if settings.get('include_dynamics', True):
            for spanner in self.score.parts[part_index].spanners.elements:
                first = spanner.getFirst()
                last = spanner.getLast()

                if first.measureNumber is None or last.measureNumber is None:
                    continue

                if first.measureNumber <= last_bar_num and last.measureNumber >= first_bar_num:
                    spanner_type = type(spanner).__name__
                    if spanner_type == 'Crescendo' or spanner_type == 'Diminuendo':
                        if first.measureNumber >= first_bar_num:
                            event = TSDynamic(long_name=f'{spanner_type} Start')
                            event.start_offset = first.offset
                            event.beat = first.beat
                            intermediate_events.setdefault(first.measureNumber, {}).setdefault(first.offset, {}).setdefault(1, []).append(event)
                        
                        if last.measureNumber <= last_bar_num:
                            event = TSDynamic(long_name=f'{spanner_type} End')
                            event.start_offset = last.offset + last.duration.quarterLength
                            event.beat = last.beat + last.duration.quarterLength
                            intermediate_events.setdefault(last.measureNumber, {}).setdefault(event.start_offset, {}).setdefault(1, []).append(event)

        final_events_by_bar = {}
        for bar_num in range(first_bar_num, last_bar_num + 1):
            if bar_num in intermediate_events:
                time_points = intermediate_events[bar_num]
                sorted_time_points = []
                for offset, voices in sorted(time_points.items()):
                    first_event = next(iter(next(iter(voices.values()))))
                    
                    sorted_time_points.append({
                        'offset': offset,
                        'beat': first_event.beat,
                        'voices': voices
                    })
                final_events_by_bar[bar_num] = sorted_time_points
            
        return final_events_by_bar

    def update_events_for_measure(self, measure_stream, events, voice: int = 1, state=None):
        if state is None:
            state = {}

        for element in measure_stream.elements:
            element_type = type(element).__name__
            event = None
            
            if element_type == 'Note':
                event = TSNote()
                pitch_name = self.map_pitch(element.pitch, state)
                event.pitch = TSPitch(pitch_name, self.map_octave(element.pitch.octave), element.pitch.ps, element.pitch.name[0])
                if element.tie:
                    event.tie = element.tie.type
                event.expressions = element.expressions
            elif element_type == 'Rest':
                event = TSRest()
            elif element_type == 'Chord':
                event = TSChord()
                chord_pitches = []
                for p in element.pitches:
                    pitch_name = self.map_pitch(p, state)
                    chord_pitches.append(TSPitch(pitch_name, self.map_octave(p.octave), p.ps, p.name[0]))
                event.pitches = chord_pitches
                if element.tie:
                    event.tie = element.tie.type
            elif element_type == 'Dynamic':
                if settings.get('include_dynamics', True):
                    event = TSDynamic(long_name=element.longName, short_name=element.value)
            elif element_type == 'Voice':
                self.update_events_for_measure(element, events, int(element.id), state=state)
                continue
            
            if event is None:
                continue

            event.start_offset = element.offset
            event.beat = element.beat
            event.duration = ""
            if (len(element.duration.tuplets) > 0):
                if (element.duration.tuplets[0].type == "start"):
                    if (element.duration.tuplets[0].fullName == "Triplet"):
                        event.tuplets = "triplets "
                    else:
                        event.tuplets = element.duration.tuplets[0].fullName + " (" + str(element.duration.tuplets[0].tupletActual[0]) + " in " + str(element.duration.tuplets[0].tupletNormal[0]) + ") "
                elif (element.duration.tuplets[0].type == "stop" and element.duration.tuplets[0].fullName != "Triplet"):
                    event.endTuplets = "end tuplet "

            if settings['dotPosition'] == "before":
                event.duration += self.map_dots(element.duration.dots)
            event.duration += self.map_duration(element.duration)
            if settings['dotPosition'] == "after":
                event.duration += " " + self.map_dots(element.duration.dots)
            
            events.setdefault(measure_stream.measureNumber, {})\
                .setdefault(element.offset, {})\
                .setdefault(voice, [])\
                .append(event)

    def group_chord_pitches_by_octave(self, chord):
        chord_pitches_by_octave = {}
        for pitch in chord.pitches:
            chord_pitches_by_octave.setdefault(self._PITCH_MAP.get(str(pitch.octave), '?'), []).append(pitch.name)

        return chord_pitches_by_octave
    def generate_midi_filename_sel(self, base_url, range_start=None, range_end=None, sel=""):
        """Generates a MIDI URL for a selection of parts (all, selected, unselected)."""
        query_params = f"bsi={self.binary_selected_instruments}&bpi={self.binary_play_all}"
        if sel:
            query_params += f"&sel={sel}"
        if range_start is not None:
            query_params += f"&start={range_start}&end={range_end}"
        return f"{base_url}?{query_params}"

    def generate_part_descriptions(self, instrument, start_bar, end_bar):
        part_descriptions = []
        for pi in range(self.part_instruments[instrument][1], self.part_instruments[instrument][1]+self.part_instruments[instrument][2]):
            part_descriptions.append(self.get_events_for_bar_range(start_bar, end_bar, pi))

        return part_descriptions

    def generate_midi_filenames(self, base_url, range_start=None, range_end=None, add_instruments=[]):
        """Generates MIDI URLs for a specific instrument and its constituent parts."""
        part_midis = []
        instrument_midi = ""
        last_ins = add_instruments[-1] if add_instruments else None

        query_string = f"bsi={self.binary_selected_instruments}&bpi={self.binary_play_all}"
        if range_start is not None:
            query_string += f"&start={range_start}&end={range_end}"

        for ins in add_instruments:
            if self.part_instruments[ins][2] > 1:
                start_part_index = self.part_instruments[ins][1]
                end_part_index = start_part_index + self.part_instruments[ins][2]
                for pi in range(start_part_index, end_part_index):
                    part_midis.append(f"{base_url}?part={pi}&{query_string}")

        if last_ins is not None:
            instrument_midi = f"{base_url}?ins={last_ins}&{query_string}"

        return (instrument_midi, part_midis)

    def generate_midi_for_instruments(self, prefix, range_start=None, range_end=None, add_instruments=[], output_path="", postfix_filename=""):
        part_midis = []
        s = stream.Score(id='temp')

        if range_start is None and range_end is None:
            for ins in add_instruments:
                for pi in range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    s.insert(self.score.parts[pi])
                    if self.part_instruments[ins][2] > 1:
                        part_midis.append(self.generate_midi_parts_for_instrument(range_start, range_end, ins, pi-self.part_instruments[ins][1], output_path, postfix_filename))

        else:
            postfix_filename += "_" + str(range_start) + str(range_end)
            for ins in add_instruments:
                firstPart = True
                for pi in range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    if self.part_instruments[ins][2] > 1:
                        part_midis.append(self.generate_midi_parts_for_instrument(range_start, range_end, ins, pi-self.part_instruments[ins][1], output_path, postfix_filename))
                    pi_measures = self.score.parts[pi].measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                    if firstPart:
                        if pi != 0:
                            self.insert_tempos(pi_measures, self.score.parts[0].measure(range_start).offset)
                        firstPart = False

                    for m in pi_measures.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                    s.insert(pi_measures)

        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}.mid")
        if not os.path.exists(midi_filename):
            s.write('midi', midi_filename)
        part_midis = [prefix + os.path.basename(s) for s in part_midis]
        return (prefix+os.path.basename(midi_filename), part_midis)

    def generate_midi_parts_for_instrument(self, range_start=None, range_end=None, instrument=0, part=0, output_path="", postfix_filename=""):
        s = stream.Score(id='temp')
        if range_start is None and range_end is None:
            s = stream.Score(id='temp')
            s.insert(self.score.parts[self.part_instruments[instrument][1]+part])
            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{(part+1)}.mid")
            if not os.path.exists(midi_filename):
                s.write('midi', midi_filename)
        else:
            postfix_filename += "_" + str(range_start) + str(range_end)
            s = stream.Score(id='temp')
            pi_measures = self.score.parts[self.part_instruments[instrument][1]+part].measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
            if self.part_instruments[instrument][1]+part != 0:
                self.insert_tempos(pi_measures, self.score.parts[0].measure(range_start).offset)

            for m in pi_measures.getElementsByClass('Measure'):
                m.removeByClass('Repeat')
            s.insert(pi_measures)

            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{(part+1)}.mid")
            if not os.path.exists(midi_filename):
                s.write('midi', midi_filename)
        return midi_filename

    def generate_midi_for_part_range(self, range_start=None, range_end=None, parts=[], output_path=""):

        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        if range_start is None and range_end is None:
            midi_filename = os.path.join(output_path, f"{base_filename}.mid")
            if not os.path.exists(midi_filename):
                self.score.write('midi', midi_filename)
            return midi_filename
        elif len(parts) > 0:
            for p in self.score.parts:
                if p.id not in parts:
                    continue

                midi_filename = os.path.join(output_path, f"{base_filename}_p{p.id}_{range_start}_{range_end}.mid")
                if not os.path.exists(midi_filename):
                    midi_stream = p.measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                    if p != self.score.parts[0]:
                        self.insert_tempos(midi_stream, self.score.parts[0].measure(range_start).offset)
                    for m in midi_stream.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                    midi_stream.write('midi', midi_filename)
                return midi_filename
        else:
            midi_filename = os.path.join(output_path, f"{base_filename}_{range_start}_{range_end}.mid")
            if not os.path.exists(midi_filename):
                midi_stream = self.score.measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                for pa in midi_stream.getElementsByClass('Part'):
                    for m in pa.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                midi_stream.write('midi', midi_filename)
            return midi_filename

        return None

    def insert_tempos(self, stream, offset_start):
        if (self.last_tempo_inserted_index > 0):
            self.last_tempo_inserted_index -= 1
        for mmb in self.score.metronomeMarkBoundaries()[self.last_tempo_inserted_index:]:
            if (mmb[0] >= offset_start+stream.duration.quarterLength):
                return
            if (mmb[1] > offset_start):
                if (mmb[0]) <= offset_start:
                    stream.insert(0, tempo.MetronomeMark(number=mmb[2].number))
                    self.last_tempo_inserted_index += 1
                else:
                    stream.insert(mmb[0]-offset_start, tempo.MetronomeMark(number=mmb[2].number))
                    self.last_tempo_inserted_index += 1
    def map_octave(self, octave):
        global settings
        if settings['octaveDescription'] == "figureNotes":
            return self._OCTAVE_FIGURENOTES_MAP.get(octave, "?")
        elif settings['octaveDescription'] == "name":
            return self._OCTAVE_MAP.get(octave, "?")
        elif settings['octaveDescription'] == "none":
            return ""
        elif settings['octaveDescription'] == "number":
            return str(octave)

    def map_pitch(self, pitch, state):
        global settings
        mode = settings.get('key_signature_accidentals', 'applied')
        
        if settings['pitchDescription'] == "colourNotes":
            base_name = self._PITCH_FIGURENOTES_MAP.get(pitch.step, "?")
        elif settings['pitchDescription'] == "phonetic":
            base_name = self._PITCH_PHONETIC_MAP.get(pitch.step, "?")
        else:
             base_name = pitch.step if settings['pitchDescription'] == 'noteName' else ''

        if not pitch.accidental:
            return base_name

        show_accidental = False
        if mode == 'applied':
            if pitch.accidental.name != 'natural':
                show_accidental = True
        elif mode == 'standard':
            if pitch.accidental.displayStatus:
                show_accidental = True
        elif mode == 'onChange':
            current_alter = pitch.alter
            step = pitch.step
            last_seen_alter = state.get(step)
            if last_seen_alter is None or current_alter != last_seen_alter:
                state[step] = current_alter
                show_accidental = True
        
        if not show_accidental:
            return base_name

        if settings.get('accidental_style') == 'symbols':
            symbol_map = {
                'sharp': '♯', 'flat': '♭', 'natural': '♮',
                'double-sharp': '𝄪', 'double-flat': '♭♭'
            }
            accidental_text = symbol_map.get(pitch.accidental.name, '')
            return f"{base_name}{accidental_text}"
        else:
            accidental_text = pitch.accidental.fullName
            return f"{base_name} {accidental_text}"

    def map_duration(self, duration):
        global settings
        if settings['rhythmDescription'] == "american":
            return duration.type
        elif settings['rhythmDescription'] == "british":
            return self._DURATION_MAP.get(duration.type, f'Unknown duration {duration.type}')
        elif settings['rhythmDescription'] == "none":
            return ""

    def map_dots(self, dots):
        if settings['rhythmDescription'] == "none":
            return ""
        else:
            return self._DOTS_MAP.get(dots)
        
    def get_rhythm_range(self):
        """
        Finds all unique rhythm types present in the score, independent of user settings.
        """
        valid_rhythm_types = self._DURATION_MAP.keys()
        found_rhythms = set()

        for n in self.score.flatten().notesAndRests:
            if n.duration.type in valid_rhythm_types:
                found_rhythms.add(self._DURATION_MAP[n.duration.type])
        
        return sorted(list(found_rhythms), key=lambda r: list(self._DURATION_MAP.values()).index(r))

    def get_octave_range(self):
        """
        Finds the highest and lowest octaves used in the score,
        correctly handling both Notes and Chords.
        """
        all_octaves = []
        for element in self.score.flatten().notes:
            if 'Chord' in element.classes:
                for p in element.pitches:
                    all_octaves.append(p.octave)
            elif 'Note' in element.classes:
                all_octaves.append(element.pitch.octave)
        
        if not all_octaves:
            return {'min': 0, 'max': 0}
        
        return {'min': min(all_octaves), 'max': max(all_octaves)}
class HTMLTalkingScoreFormatter():
    def __init__(self, talking_score):
        global settings
        self.score: Music21TalkingScore = talking_score
        self.options = {}

        options_path = self.score.filepath + '.opts'
        try:
            with open(options_path, "r") as options_fh:
                self.options = json.load(options_fh)
        except FileNotFoundError:
            logger.warning(f"Options file not found: {options_path}. Using default settings.")
            pass

        settings.update({
            'barsAtATime': int(self.options.get("bars_at_a_time", 2)),
            'beat_division': self.options.get("beat_division"),
            'include_rests': self.options.get("include_rests", True),
            'include_ties': self.options.get("include_ties", True),
            'include_arpeggios': self.options.get("include_arpeggios", True),
            'describe_chords': self.options.get("describe_chords", True),
            'playAll': self.options.get("play_all", False),
            'playSelected': self.options.get("play_selected", False),
            'playUnselected': self.options.get("play_unselected", False),
            'instruments': self.options.get("instruments", []),
            'pitchDescription': self.options.get("pitch_description", "noteName"),
            'rhythmDescription': self.options.get("rhythm_description", "british"),
            'dotPosition': self.options.get("dot_position", "before"),
            'rhythmAnnouncement': self.options.get("rhythm_announcement", "onChange"),
            'octaveDescription': self.options.get("octave_description", "name"),
            'octavePosition': self.options.get("octave_position", "before"),
            'octaveAnnouncement': self.options.get("octave_announcement", "onChange"),
            'include_dynamics': self.options.get("include_dynamics", True),
            'accidental_style': self.options.get("accidental_style", "words"),
            'repetition_mode': self.options.get('repetition_mode', 'learning'),
            'key_signature_accidentals': self.options.get("key_signature_accidentals", "applied"),
            'colourPosition': self.options.get("colour_position", "none"),
            'colourPitch': self.options.get("colour_pitch", False),
            'rhythm_colour_mode': self.options.get("rhythm_colour_mode", "none"),
            'octave_colour_mode': self.options.get("octave_colour_mode", "none"),
            'figureNoteColours': self.options.get("figureNoteColours", {}),
            'advanced_rhythm_colours': self.options.get("advanced_rhythm_colours", {}),
            'advanced_octave_colours': self.options.get("advanced_octave_colours", {}),
        })

    def _create_music_segment(self, start_bar, end_bar, web_path):
        """Internal helper to generate a music segment dictionary for a given bar range."""
        self._trigger_midi_generation(start_bar=start_bar, end_bar=end_bar)
        
        selected_instruments_midis = {}
        for index, ins in enumerate(self.score.selected_instruments):
            midis = self.score.generate_midi_filenames(base_url=web_path, range_start=start_bar, range_end=end_bar, add_instruments=[ins])
            selected_instruments_midis[ins] = {"ins": ins,  "midi": midis[0], "midi_parts": midis[1]}
        
        midiAll = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="all")
        midiSelected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="sel")
        midiUnselected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="un")

        selected_instruments_descriptions = {}
        for index, ins in enumerate(self.score.selected_instruments):
            selected_instruments_descriptions[ins] = self.score.generate_part_descriptions(instrument=ins, start_bar=start_bar, end_bar=end_bar)

        return {
            'start_bar': start_bar, 
            'end_bar': end_bar, 
            'selected_instruments_descriptions': selected_instruments_descriptions, 
            'selected_instruments_midis': selected_instruments_midis, 
            'midi_all': midiAll, 
            'midi_sel': midiSelected, 
            'midi_un': midiUnselected
        }

    def generateHTML(self, output_path="", web_path=""):
        global settings
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        template = env.get_template('talkingscore.html')

        self.score.get_instruments()
        self.score.compare_parts_with_selected_instruments()

        self.music_analyser = MusicAnalyser()
        self.music_analyser.setScore(self.score)
        
        start = self.score.score.parts[0].getElementsByClass('Measure')[0].number
        end = self.score.score.parts[0].getElementsByClass('Measure')[-1].number

        self._trigger_midi_generation(start, end)
        
        selected_instruments_midis = {}
        for index, ins in enumerate(self.score.selected_instruments):
            midis = self.score.generate_midi_filenames(base_url=web_path, range_start=start, range_end=end, add_instruments=[ins])
            selected_instruments_midis[ins] = {"ins": ins,  "midi": midis[0], "midi_parts": midis[1]}

        midiAll = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="all")
        midiSelected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="sel")
        midiUnselected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="un")
        full_score_midis = {'selected_instruments_midis': selected_instruments_midis, 'midi_all': midiAll, 'midi_sel': midiSelected, 'midi_un': midiUnselected}

        music_segments = self.get_music_segments(output_path, web_path)
        beat_division_options = self.score.get_beat_division_options()

        return template.render({
            'settings': settings,
            'basic_information': self.get_basic_information(),
            'preamble': self.get_preamble(),
            'full_score_midis': full_score_midis,
            'music_segments': music_segments,
            'beat_division_options': beat_division_options,
            'instruments': self.score.part_instruments,
            'part_names': self.score.part_names,
            'binary_selected_instruments': self.score.binary_selected_instruments,
            'binary_play_all': self.score.binary_play_all,
            'play_all': settings['playAll'],
            'play_selected': settings['playSelected'],
            'play_unselected': settings['playUnselected'],
            'time_and_keys': self.time_and_keys,
            'parts_summary': self.music_analyser.summary_parts,
            'general_summary': self.music_analyser.general_summary,
            'repetition_in_contexts': self.music_analyser.repetition_in_contexts,
            'selected_part_names': self.score.selected_part_names,
            'immediate_repetition_contexts': self.music_analyser.immediate_repetition_contexts,
        })

    def _trigger_midi_generation(self, start_bar, end_bar):
        from lib.midiHandler import MidiHandler
        from types import SimpleNamespace
        
        logger.info(f"Pre-generating all MIDI files for bars {start_bar}-{end_bar}...")
        
        id_hash = os.path.basename(os.path.dirname(self.score.filepath))
        xml_filename = os.path.basename(self.score.filepath)

        get_params = {
            'start': str(start_bar),
            'end': str(end_bar),
            'bsi': str(self.score.binary_selected_instruments),
            'bpi': str(self.score.binary_play_all),
            'upfront_generate': 'true'
        }
        dummy_request = SimpleNamespace(GET=get_params)
        
        try:
            mh = MidiHandler(dummy_request, id_hash, xml_filename)
            mh.score = self.score.score
            mh.make_midi_files()
            logger.info(f"Successfully generated MIDIs for bars {start_bar}-{end_bar}.")
        except Exception as e:
            logger.error(f"Failed to pre-generate MIDI files for bars {start_bar}-{end_bar}: {e}", exc_info=True)

    def get_basic_information(self):
        return {
            'title': self.score.get_title(),
            'composer': self.score.get_composer(),
        }

    def get_preamble(self):
        return {
            'time_signature': self.score.get_initial_time_signature(),
            'key_signature': self.score.get_initial_key_signature(),
            'tempo': self.score.get_initial_tempo(),
            'number_of_bars': self.score.get_number_of_bars(),
            'number_of_parts': self.score.get_number_of_parts(),
        }
    def get_music_segments(self, output_path, web_path):
        global settings
        logger.info("Start of get_music_segments")

        music_segments = []
        
        self.time_and_keys = {}
        total = len(self.score.score.parts[0].flatten().getElementsByClass('TimeSignature'))
        for count, ts in enumerate(self.score.score.parts[0].flatten().getElementsByClass('TimeSignature')):
            description = "Time signature - " + str(count+1) + " of " + str(total) + " is " + self.score.describe_time_signature(ts) + ".  "
            self.time_and_keys.setdefault(ts.measureNumber, []).append(description)

        total = len(self.score.score.parts[0].flatten().getElementsByClass('KeySignature'))
        for count, ks in enumerate(self.score.score.parts[0].flatten().getElementsByClass('KeySignature')):
            description = "Key signature - " + str(count+1) + " of " + str(total) + " is " + self.score.describe_key_signature(ks) + ".  "
            self.time_and_keys.setdefault(ks.measureNumber, []).append(description)
        
        self.score.timeSigs = {}
        previous_ts = self.score.score.parts[0].getElementsByClass('Measure')[0].getTimeSignatures()[0] if self.score.score.parts[0].hasMeasures() else self.score.get_initial_time_signature()

        start_bar_for_loop = self.score.score.parts[0].getElementsByClass('Measure')[0].number
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        
        active_time_sig = first_measure.timeSignature or previous_ts
        if active_time_sig and first_measure.duration.quarterLength < active_time_sig.barDuration.quarterLength:
            pickup_bar_num = first_measure.number
            logger.info(f"Anacrusis (pickup bar) detected at measure {pickup_bar_num}.")
            
            self.score.timeSigs[pickup_bar_num] = previous_ts

            segment = self._create_music_segment(start_bar=pickup_bar_num, end_bar=pickup_bar_num, web_path=web_path)
            
            segment['start_bar'] = 'Pickup'
            segment['end_bar'] = ''
            music_segments.append(segment)
            
            start_bar_for_loop = pickup_bar_num + 1

        total_measures = self.score.score.parts[0].getElementsByClass('Measure')[-1].number
        
        for bar_index in range(start_bar_for_loop, total_measures + 1, settings['barsAtATime']):
            end_bar_index = bar_index + settings['barsAtATime'] - 1
            if end_bar_index > total_measures:
                end_bar_index = total_measures

            if self.score.score.parts[0].measure(bar_index) is None:
                break
            
            for checkts in range(bar_index, end_bar_index + 1):
                measure_at_ts = self.score.score.parts[0].measure(checkts)
                if measure_at_ts and len(measure_at_ts.getElementsByClass(meter.TimeSignature)) > 0:
                    previous_ts = measure_at_ts.getElementsByClass(meter.TimeSignature)[0]
                self.score.timeSigs[checkts] = previous_ts

            segment = self._create_music_segment(start_bar=bar_index, end_bar=end_bar_index, web_path=web_path)
            music_segments.append(segment)

        return music_segments