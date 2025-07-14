from datetime import datetime  # start_time = datetime.now()
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
        # Formula for luminance
        luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
        # Return black for light backgrounds, white for dark backgrounds
        return 'black' if luminance > 0.5 else 'white'
    except ValueError:
        # Fallback for invalid hex codes
        return 'white'

# Place this at the top of your talkingscoreslib.py file

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
        else: # 'text'
            toRender = f"<span style='color:{color_to_use};'>{text}</span>"

    return toRender

class TSEvent(object, metaclass=ABCMeta):
    duration = None
    tuplets = ""
    endTuplets = ""
    beat = None
    bar = None
    part = None
    tie = None

    def render(self, settings, context=None, noteLetter=None):
        rendered_elements = []
        if (context is None or context.duration != self.duration or self.tuplets != "" or settings['rhythmAnnouncement'] == "everyNote"):
            rendered_elements.append(self.tuplets)
            if (noteLetter != None):
                rendered_elements.append(render_colourful_output(self.duration, noteLetter, "rhythm", settings))
            else:
                rendered_elements.append(self.duration)
        rendered_elements.append(self.endTuplets)

        if self.tie:
            rendered_elements.append(f"tie {self.tie}")
        return rendered_elements


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
        return [self.long_name]


class TSPitch(TSEvent):
    pitch_name = None
    octave = None
    pitch_letter = None  # used for looking up colour based on pitch and fixes sharp / flat problem when modulus and the pitch number

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

        return rendered_elements

    def render_octave(self, settings, context=None):
        show_octave = False
        if settings['octaveAnnouncement'] == "brailleRules":
            if context == None:
                show_octave = True
            else:
                pitch_difference = abs(context.pitch_number - self.pitch_number)
                # if it is a 3rd or less, don't say octave
                if pitch_difference <= 4:
                    show_octave = False  # it already is...
                # if it is a 4th or 5th and octave changes, say octave
                elif pitch_difference >= 5 and pitch_difference <= 7:
                    if context.octave != self.octave:
                        show_octave = True
                # if it is more than a 5th, say octave
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
        # Render the duration
        rendered_elements.append(' '.join(super(TSUnpitched, self).render(settings, context)))
        # Render the pitch
        rendered_elements.append(' unpitched')
        return rendered_elements


class TSRest(TSEvent):
    pitch = None

    def render(self, settings, context=None):
        rendered_elements = []
        # Render the duration
        rendered_elements.append(' '.join(super(TSRest, self).render(settings, context)))
        # Render the pitch
        rendered_elements.append(' rest')
        return rendered_elements


class TSNote(TSEvent):
    pitch = None
    expressions = []

    def render(self, settings, context=None):
        rendered_elements = []
        for exp in self.expressions:
            rendered_elements.append(exp.name + ', ')

         # This now correctly calls the parent render with settings
        rendered_elements.append(' '.join(super().render(settings, context, self.pitch.pitch_letter)))

        # This now correctly calls the pitch render with settings
        rendered_elements.append(' '.join(self.pitch.render(settings, getattr(context, 'pitch', None))))
        return rendered_elements


class TSChord(TSEvent):
    pitches = []

    def name(self):
        return ''

    def render(self, settings, context=None):
        rendered_elements = [f'{len(self.pitches)}-note chord']
        rendered_elements.append(' '.join(super(TSChord, self).render(settings, context)))
        previous_pitch = None
        for pitch in sorted(self.pitches, key=lambda TSPitch: TSPitch.pitch_number):
            rendered_elements.append(' '.join(pitch.render(settings, previous_pitch)))
            previous_pitch = pitch
        return [', '.join(rendered_elements)]


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

    last_tempo_inserted_index = 0  # insert_tempos() doesn't need to recheck MetronomeMarkBoundaries that have already been used
    music_analyser = None

    def __init__(self, musicxml_filepath):
        self.filepath = os.path.realpath(musicxml_filepath)
        self.score = converter.parse(musicxml_filepath)
        super(Music21TalkingScore, self).__init__()

    def get_title(self):
        if self.score.metadata.title is not None:
            return self.score.metadata.title
        # Have a guess
        for tb in self.score.flat.getElementsByClass('TextBox'):
            # in some musicxml files - a textbox might not have those attributes - so we use hasattr()...
            if hasattr(tb, 'justifty') and tb.justify == 'center' and hasattr(tb, 'alignVertical') and tb.alignVertical == 'top' and hasattr(tb, 'size') and tb.size > 18:
                return tb.content
        return "Error reading title"

    def get_composer(self):
        if self.score.metadata.composer != None:
            return self.score.metadata.composer
        # Look for a text box in the top right of the first page
        for tb in self.score.getElementsByClass('TextBox'):
            if tb.style.justify == 'right':
                return tb.content
        return "Unknown"

    def get_initial_time_signature(self):
        # Get the first measure of the first part
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
        if len(m1.flat.getElementsByClass('KeySignature')) == 0:
            ks = key.KeySignature(0)
        else:
            ks = m1.flat.getElementsByClass('KeySignature')[0]
        return self.describe_key_signature(ks)

    def describe_key_signature(self, ks):
        strKeySig = "No sharps or flats"
        if (ks.sharps > 0):
            strKeySig = str(ks.sharps) + " sharps"
        elif (ks.sharps < 0):
            strKeySig = str(abs(ks.sharps)) + " flats"
        return strKeySig

    # this was used to get the first tempo - but MetronomeMarkBoundary is better
    def get_initial_text_expression(self):
        # Get the first measure of the first part
        m1 = self.score.parts[0].measures(1, 1)
        # Get the text expressions from that measure
        text_expressions = m1.flat.getElementsByClass('TextExpression')
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

    # some tempos have soundingNumber set but not number
    # we would get an error trying to scale a tempo.number of None
    # static so that it can be called by eg midiHandler when scaling tempos
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

    # the referent is the beat duration ie are you counting crotchets or minims etc
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

    # eg flute, piano, recorder, piano
    # part_instruments = {1: ['Flute', 0, 1, 'P1'], 2: ['Piano', 1, 2, 'P2'], 3: ['Recorder', 3, 1, 'P3'], 4: ['Piano', 4, 2, 'P4']}
    # part_names = {1: 'Right hand', 2: 'Left hand', 4: 'Right hand', 5: 'Left hand'}
    # instrument names = ['Flute', 'Piano', 'Recorder', 'Piano']
    def get_instruments(self):
        # eg instrument.Name = Piano, instrument.partId = 1.  A piano has 2 staves ie two parts with the same name and same ID.  But if you have a second piano, it will have the same name but a different partId
        self.part_instruments = {}  # key = instrument (1 based), value = ["part name", 1st part index 0 based, number of parts, instrument.partId]
        self.part_names = {}  # key = part index 0 based, {part name eg "left hand" or "right hand" etc} - but part only included if instrument has multiple parts.
        instrument_names = []  # each instrument instrument once even if it has multiple parts.  still needed for Info / Options page
        ins_count = 1
        for c, instrument in enumerate(self.score.flat.getInstruments()):
            if len(self.part_instruments) == 0 or self.part_instruments[ins_count-1][3] != instrument.partId:
                pname = instrument.partName
                if pname == None:
                    pname = "Instrument  " + str(ins_count) + " (unnamed)"
                self.part_instruments[ins_count] = [pname, c, 1, instrument.partId]
                instrument_names.append(pname)

                ins_count += 1
            else:
                self.part_instruments[ins_count-1][2] += 1
                # todo - there is a more efficient way of doing this - or just let the user enter part names on the options screen - but these are OK for defaults
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
        print("part names = " + str(self.part_names))
        print("instrument names = " + str(instrument_names))
        return instrument_names

    def compare_parts_with_selected_instruments(self):
        global settings
        self.selected_instruments = []  # 1 based list of keys from part_instruments eg [1, 4]
        self.unselected_instruments = []  # eg [2,3]
        self.binary_selected_instruments = 1  # bitwise representation of all instruments - 0=not included, 1=included
        self.selected_part_names = []
        for ins in self.part_instruments.keys():
            self.binary_selected_instruments = self.binary_selected_instruments << 1
            if ins in settings.get('instruments', []): # Use .get() for safety
                self.selected_instruments.append(ins)
                self.binary_selected_instruments += 1
            else:
                self.unselected_instruments.append(ins)

        for ins in self.selected_instruments:
            ins_name = self.part_instruments[ins][0]
            if self.part_instruments[ins][2] == 1:  # instrument only has one part
                self.selected_part_names.append(ins_name)
            else:  # instrument has multiple parts
                pn1index = self.part_instruments[ins][1]
                for pni in range(pn1index, pn1index+self.part_instruments[ins][2]):
                    self.selected_part_names.append(ins_name + " - " + self.part_names[pni])

        # --- START: CORRECTED LOGIC ---
        # 1. Preserve the user's original choices for pre-generation, using .get() for safety.
        play_all_choice = settings.get('playAll', False)
        play_selected_choice = settings.get('playSelected', False)
        play_unselected_choice = settings.get('playUnselected', False)

        # 2. Apply "smart" logic to hide redundant links in the template.
        if len(self.unselected_instruments) == 0:  # All instruments selected
            settings['playUnselected'] = False
        if len(self.selected_instruments) == len(self.part_instruments) and settings.get('playAll', False): # All instruments selected AND playAll is checked
            settings['playSelected'] = False
        if len(self.selected_instruments) == 1: # Only one instrument selected
            settings['playSelected'] = False
        if len(self.part_instruments) == 1: # Only one instrument in the whole piece
            settings['playAll'] = False

        # 3. Calculate the binary flags for the URL based on the *original* choices.
        self.binary_play_all = 1  # placeholder,all,selected,unselected
        self.binary_play_all = self.binary_play_all << 1
        if play_all_choice:
            self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if play_selected_choice:
            self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if play_unselected_choice:
            self.binary_play_all += 1
        # --- END: CORRECTED LOGIC ---

        print("selected_part_names = " + str(self.selected_part_names))
        print("selected_instruments = " + str(self.selected_instruments))

    def get_number_of_parts(self):
        self.get_instruments()
        return len(self.part_instruments)

    def get_bar_range(self, range_start, range_end):
        measures = self.score.measures(range_start, range_end)
        bars_for_parts = {}
        for part in measures.parts:
            bars_for_parts.setdefault(part.id, []).extend(part.getElementsByClass('Measure'))

        return bars_for_parts

    def group_chord_pitches_by_octave(self, chord):
        chord_pitches_by_octave = {}
        for pitch in chord.pitches:
            chord_pitches_by_octave.setdefault(self._PITCH_MAP.get(str(pitch.octave), '?'), []).append(pitch.name)

        return chord_pitches_by_octave

    # for all / selected / unselected
    def generate_midi_filename_sel(self, base_url, range_start=None, range_end=None, sel=""):
        """Generates a MIDI URL for a selection of parts (all, selected, unselected)."""
        # The base_url is the complete path part, e.g., /midis/hash/file.musicxml
        query_params = f"sel={sel}&t=100&c=n"
        if range_start is not None:
            # Note: using a consistent parameter order
            query_params += f"&start={range_start}&end={range_end}"
            return f"{base_url}?{query_params}"
    def generate_part_description_data(self, part_index, start_bar, end_bar, initial_dynamic_state=None):
        """
        Generates a list of descriptive strings for a part segment with intuitive inline dynamics.
        This is the new, robust single-pass algorithm.
        It returns a simpler data structure for easier rendering in Jinja.
        """
        global settings
        part = self.score.parts[part_index]
        segment_stream = part.measures(start_bar, end_bar).flat

        description_data = {}
        active_stateful_dynamic = initial_dynamic_state
        
        # CORRECTED LINE: Added .stream() to ensure we have a generic stream object.
        for element_group in segment_stream.stream().groupElementsByOffset():
            
            new_dynamic_object = None
            for el in element_group:
                if isinstance(el, music21.dynamics.Dynamic) and el.value not in ['crescendo', 'diminuendo', 'decrescendo']:
                    new_dynamic_object = el
                    break

            notes_in_group = [e for e in element_group if isinstance(e, music21.note.GeneralNote)]
            if not notes_in_group:
                continue

            beat_event_descriptions = []
            
            for el in notes_in_group:
                desc_parts = []
                
                rhythm_desc = self.map_duration(el.duration)
                if el.duration.dots > 0:
                    dots_desc = self._DOTS_MAP.get(el.duration.dots, '')
                    rhythm_desc = f"{dots_desc}{rhythm_desc}" if settings['dotPosition'] == 'before' else f"{rhythm_desc} {dots_desc.strip()}"
                desc_parts.append(rhythm_desc)

                if el.isRest:
                    desc_parts.append("rest")
                elif el.isChord:
                    sorted_pitches = sorted(el.pitches, key=lambda p: p.ps)
                    pitch_names = " ".join([p.nameWithOctave for p in sorted_pitches])
                    desc_parts.append(f"{len(el.pitches)}-note chord ({pitch_names})")
                else:
                    desc_parts.append(el.pitch.nameWithOctave)

                dynamic_tags = []
                if new_dynamic_object and new_dynamic_object.longName != active_stateful_dynamic:
                    dynamic_tags.append(f"[{new_dynamic_object.longName.capitalize()}]")
                    active_stateful_dynamic = new_dynamic_object.longName
                    new_dynamic_object = None

                for spanner in el.getSpannerSites():
                    if isinstance(spanner, (music21.spanner.Crescendo, music21.spanner.Diminuendo)):
                        if el is spanner.getFirst():
                           dynamic_tags.append(f"[{spanner.type} start]")
                
                full_desc_for_event = " ".join(desc_parts)
                if dynamic_tags:
                    full_desc_for_event += " " + " ".join(dynamic_tags)
                beat_event_descriptions.append(full_desc_for_event)

            bar_num = notes_in_group[0].measureNumber
            beat_num_raw = notes_in_group[0].beat
            beat_str = str(beat_num_raw)
            if beat_str.endswith('.0'):
                beat_str = beat_str[:-2]
            
            final_line = f"**Beat {beat_str}:** " + ", ".join(beat_event_descriptions)
            
            if bar_num not in description_data:
                description_data[bar_num] = []
            description_data[bar_num].append(final_line)

        return (description_data, active_stateful_dynamic)

    def generate_part_descriptions(self, instrument, start_bar, end_bar, part_dynamic_states):
        """
        Calls the new rendering function for an instrument's part(s) and manages dynamic state.
        """
        # This dictionary will store the final description data for each part of the instrument
        descriptions_for_instrument = {}
        
        # An instrument can have multiple parts (e.g., piano right and left hand)
        num_parts_in_instrument = self.part_instruments[instrument][2]
        first_part_index = self.part_instruments[instrument][1]
            
        for i in range(num_parts_in_instrument):
            part_index = first_part_index + i
            
            # Get the initial state for this part for this segment
            initial_state = part_dynamic_states.get(part_index)
            
            # Call the new rendering function
            description_data, final_state = self.generate_part_description_data(
                part_index, 
                start_bar, 
                end_bar, 
                initial_dynamic_state=initial_state
            )
            
            # Store the result for this specific part
            descriptions_for_instrument[part_index] = description_data

            # IMPORTANT: Update the state for the next segment
            part_dynamic_states[part_index] = final_state
        
        return descriptions_for_instrument

    def generate_midi_filenames(self, base_url, range_start=None, range_end=None, add_instruments=[]):
        """Generates MIDI URLs for a specific instrument and its constituent parts."""
        part_midis = []
        instrument_midi = ""
        last_ins = add_instruments[-1] if add_instruments else None

        # Construct the base query string
        query_string = "t=100&c=n"
        if range_start is not None:
            query_string += f"&start={range_start}&end={range_end}"

    # Generate URLs for individual parts (if the instrument has more than one)
        for ins in add_instruments:
            if self.part_instruments[ins][2] > 1:
                start_part_index = self.part_instruments[ins][1]
                end_part_index = start_part_index + self.part_instruments[ins][2]
            for pi in range(start_part_index, end_part_index):
                part_midis.append(f"{base_url}?part={pi}&{query_string}")

    # Generate the URL for the whole instrument
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

        else:  # specific measures
            postfix_filename += "_" + str(range_start) + str(range_end)
            for ins in add_instruments:
                firstPart = True
                for pi in range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    if self.part_instruments[ins][2] > 1:
                        part_midis.append(self.generate_midi_parts_for_instrument(range_start, range_end, ins, pi-self.part_instruments[ins][1], output_path, postfix_filename))
                    pi_measures = self.score.parts[pi].measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                    if firstPart:
                        if pi != 0:  # only part 0 has tempos
                            self.insert_tempos(pi_measures, self.score.parts[0].measure(range_start).offset)
                        firstPart = False

                    # music21 v6.3.0 tries to expand repeats - which causes error if segment only includes the start repeat mark
                    for m in pi_measures.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                    s.insert(pi_measures)

        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}.mid")
        # todo - might need to add in tempos if part 0 is not included
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
        else:  # specific measures
            postfix_filename += "_" + str(range_start) + str(range_end)
            s = stream.Score(id='temp')
            print("506 instrument = " + str(instrument) + " part = " + str(part))
            pi_measures = self.score.parts[self.part_instruments[instrument][1]+part].measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
            if self.part_instruments[instrument][1]+part != 0:  # only part 0 has tempos
                self.insert_tempos(pi_measures, self.score.parts[0].measure(range_start).offset)

            # music21 v6.3.0 tries to expand repeats - which causes error if segment only includes the start repeat mark
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
            # Export the whole score
            midi_filename = os.path.join(output_path, f"{base_filename}.mid")
            if not os.path.exists(midi_filename):
                self.score.write('midi', midi_filename)
            return midi_filename
        elif len(parts) > 0:  # individual parts
            for p in self.score.parts:
                if p.id not in parts:
                    continue

                midi_filename = os.path.join(output_path, f"{base_filename}_p{p.id}_{range_start}_{range_end}.mid")
                if not os.path.exists(midi_filename):
                    midi_stream = p.measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                    if p != self.score.parts[0]:  # only part 0 has tempos
                        self.insert_tempos(midi_stream, self.score.parts[0].measure(range_start).offset)
                    # music21 v6.3.0 tries to expand repeats - which causes error if segment only includes the start repeat mark
                    for m in midi_stream.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                    midi_stream.write('midi', midi_filename)
                return midi_filename
        else:  # both hands
            midi_filename = os.path.join(output_path, f"{base_filename}_{range_start}_{range_end}.mid")
            if not os.path.exists(midi_filename):
                midi_stream = self.score.measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication'))
                # music21 v6.3.0 tries to expand repeats - which causes error if segment only includes the start repeat mark
                for pa in midi_stream.getElementsByClass('Part'):
                    for m in pa.getElementsByClass('Measure'):
                        m.removeByClass('Repeat')
                midi_stream.write('midi', midi_filename)
            return midi_filename

        return None

    # TODO need to make more efficient when working with multiple parts ie more than just the left hand piano part
    # music21 might have a better way of doing this.  If part 0 is included then tempos are already present.
    def insert_tempos(self, stream, offset_start):
        if (self.last_tempo_inserted_index > 0):  # one tempo change might need to be in many segments - especially the last tempo change in the score
            self.last_tempo_inserted_index -= 1
        for mmb in self.score.metronomeMarkBoundaries()[self.last_tempo_inserted_index:]:
            if (mmb[0] >= offset_start+stream.duration.quarterLength):  # ignore tempos that start after stream ends
                return
            if (mmb[1] > offset_start):  # if mmb ends during the segment
                if (mmb[0]) <= offset_start:  # starts before segment so insert it at the start of the stream
                    stream.insert(0, tempo.MetronomeMark(number=mmb[2].number))
                    self.last_tempo_inserted_index += 1
                else:  # starts during segment so insert it part way through the stream
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

        # return f"{self._PITCH_MAP.get(pitch[-1], '')} {pitch[0]}"

    def map_pitch(self, pitch):
        global settings
        if settings['pitchDescription'] == "colourNotes":
            pitch_name = self._PITCH_FIGURENOTES_MAP.get(pitch.name[0], "?")
        if settings['pitchDescription'] == "noteName":
            pitch_name = pitch.name[0]
        elif settings['pitchDescription'] == "none":
            pitch_name = ""
        elif settings['pitchDescription'] == "phonetic":
            pitch_name = self._PITCH_PHONETIC_MAP.get(pitch.name[0], "?")

        if pitch.accidental and pitch.accidental.displayStatus and pitch_name != "":
            pitch_name = f"{pitch_name} {pitch.accidental.fullName}"
        return pitch_name

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
        Finds all unique rhythm types present in the score.
        """
        # The _DURATION_MAP keys cover the rhythm names we use for descriptions.
        valid_rhythms = self._DURATION_MAP.values()
        found_rhythms = set()

        for n in self.score.flat.notesAndRests:
            # map_duration translates the note's type into our description term (e.g., "crotchet")
            rhythm_name = self.map_duration(n.duration)
            if rhythm_name in valid_rhythms:
                found_rhythms.add(rhythm_name)
        
        return sorted(list(found_rhythms), key=lambda r: list(valid_rhythms).index(r))

    def get_octave_range(self):
        """
        Finds the highest and lowest octaves used in the score,
        correctly handling both Notes and Chords.
        """
        all_octaves = []
        # Iterate through all note and chord elements in the score
        for element in self.score.flat.notes:
            if 'Chord' in element.classes:
                # For a Chord, get the octave of each pitch within it
                for p in element.pitches:
                    all_octaves.append(p.octave)
            elif 'Note' in element.classes:
                # For a Note, get its single octave
                all_octaves.append(element.pitch.octave)
        
        if not all_octaves:
            return {'min': 0, 'max': 0}
        
        return {'min': min(all_octaves), 'max': max(all_octaves)}


class HTMLTalkingScoreFormatter():
    """
    Handles the formatting of a Music21 score into an HTML talking score.
    """
    def __init__(self, talking_score):
        """
        Initializes the formatter with the score object and sets up the configuration.
        """
        global settings
        self.score: Music21TalkingScore = talking_score
        self.options = {}  # Initialize self.options

        options_path = self.score.filepath + '.opts'
        try:
            with open(options_path, "r") as options_fh:
                # Load the options into the instance variable
                self.options = json.load(options_fh)
        except FileNotFoundError:
            logger.warning(f"Options file not found: {options_path}. Using default settings.")
            pass # Use default .get() values below

        # Build the settings dictionary using self.options and assign it globally
        settings = {
            'pitchBeforeDuration': False,
            'describeBy': 'beat',
            'handsTogether': True,
            'barsAtATime': int(self.options.get("bars_at_a_time", 2)),
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
            'colourPosition': self.options.get("colour_position", "none"),
            'colourPitch': self.options.get("colour_pitch", False),
            'rhythm_colour_mode': self.options.get("rhythm_colour_mode", "none"),
            'octave_colour_mode': self.options.get("octave_colour_mode", "none"),
            'figureNoteColours': self.options.get("figureNoteColours", {}),
            'advanced_rhythm_colours': self.options.get("advanced_rhythm_colours", {}),
            'advanced_octave_colours': self.options.get("advanced_octave_colours", {}),
            'repetition_mode': self.options.get('repetition_mode', 'learning')
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
        
        # Pass the clean web_path to all MIDI generation functions
        selected_instruments_midis = {}
        for index, ins in enumerate(self.score.selected_instruments):
            # CORRECTED CALL
            midis = self.score.generate_midi_filenames(base_url=web_path, range_start=start, range_end=end, add_instruments=[ins])
            selected_instruments_midis[ins] = {"ins": ins,  "midi": midis[0], "midi_parts": midis[1]}

        # CORRECTED CALLS
        midiAll = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="all")
        midiSelected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="sel")
        midiUnselected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start, range_end=end, sel="un")
        full_score_midis = {'selected_instruments_midis': selected_instruments_midis, 'midi_all': midiAll, 'midi_sel': midiSelected, 'midi_un': midiUnselected}

        # Also pass the clean web_path here
        music_segments = self.get_music_segments(output_path, web_path)

        return template.render({
            'settings': settings,
            'basic_information': self.get_basic_information(),
            'preamble': self.get_preamble(),
            'full_score_midis': full_score_midis,
            'music_segments': music_segments,
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
            # Local imports to prevent circular dependency at startup
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
                # Instantiate the handler
                mh = MidiHandler(dummy_request, id_hash, xml_filename)
                # --- PERFORMANCE FIX: Pass the already-parsed score object ---
                mh.score = self.score.score
                # Call the master generation function
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
        number_of_bars = self.score.get_number_of_bars()

        self.time_and_keys = {}
        all_time_sigs = self.score.score.parts[0].flat.getElementsByClass('TimeSignature')
        for count, ts in enumerate(all_time_sigs):
            description = f"Time signature - {count + 1} of {len(all_time_sigs)} is {self.score.describe_time_signature(ts)}."
            self.time_and_keys.setdefault(ts.measureNumber, []).append(description)

        all_key_sigs = self.score.score.parts[0].flat.getElementsByClass('KeySignature')
        for count, ks in enumerate(all_key_sigs):
            description = f"Key signature - {count + 1} of {len(all_key_sigs)} is {self.score.describe_key_signature(ks)}."
            self.time_and_keys.setdefault(ks.measureNumber, []).append(description)
        
        # Initialize dynamic state tracker for each part. This will persist across segments.
        part_dynamic_states = {pi: None for pi in range(len(self.score.score.parts))}

        # Determine bar ranges to process, including a pickup bar if it exists
        bar_ranges = []
        measures = self.score.score.parts[0].getElementsByClass('Measure')
        if not measures:
            return [] # No bars in score
        
        first_measure_num = measures[0].number
        if first_measure_num == 0:
            bar_ranges.append((0, 0)) # Pickup bar segment
            start_index = 1
        else:
            start_index = first_measure_num

        for bar_index in range(start_index, number_of_bars + 1, settings['barsAtATime']):
            end_bar_index = min(bar_index + settings['barsAtATime'] - 1, number_of_bars)
            bar_ranges.append((bar_index, end_bar_index))

        # Main loop to generate all data for each music segment
        for start_bar, end_bar in bar_ranges:
            
            self._trigger_midi_generation(start_bar=start_bar, end_bar=end_bar)

            selected_instruments_descriptions = {}
            selected_instruments_midis = {}
            
            for ins in self.score.selected_instruments:
                # Generate MIDI links (existing logic)
                midis = self.score.generate_midi_filenames(base_url=web_path, range_start=start_bar, range_end=end_bar, add_instruments=[ins])
                selected_instruments_midis[ins] = {"ins": ins,  "midi": midis[0], "midi_parts": midis[1]}
                
                # Generate Descriptions using the NEW state-managed method
                # Note: part_dynamic_states is passed by reference and gets updated inside the function
                selected_instruments_descriptions[ins] = self.score.generate_part_descriptions(
                    instrument=ins, 
                    start_bar=start_bar, 
                    end_bar=end_bar, 
                    part_dynamic_states=part_dynamic_states
                )
            
            midiAll = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="all")
            midiSelected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="sel")
            midiUnselected = self.score.generate_midi_filename_sel(base_url=web_path, range_start=start_bar, range_end=end_bar, sel="un")

            segment_start_label = str(start_bar) if start_bar != 0 else f"{start_bar} - pickup"
            
            music_segments.append({
                'start_bar': segment_start_label, 
                'end_bar': end_bar,
                'selected_instruments_descriptions': selected_instruments_descriptions, 
                'selected_instruments_midis': selected_instruments_midis, 
                'midi_all': midiAll, 
                'midi_sel': midiSelected, 
                'midi_un': midiUnselected
            })
            
        return music_segments


# if __name__ == '__main__':
# 
#     # testScoreFilePath = '../talkingscoresapp/static/data/macdowell-to-a-wild-rose.xml'
#     testScoreFilePath = '../media/172a28455fa5cfbdaa4eecd5f63a0a2ebaddd92d569980fb402811b9cd5cce4a/MozartPianoSonata.xml'
#     # testScoreFilePath = '../talkingscores/talkingscoresapp/static/data/bach-2-part-invention-no-13.xml'
# 
#     testScoreOutputFilePath = testScoreFilePath.replace('.xml', '.html')
# 
#     testScore = Music21TalkingScore(testScoreFilePath)
#     tsf = HTMLTalkingScoreFormatter(testScore)
#     html = tsf.generateHTML()
# 
#     with open(testScoreOutputFilePath, "wb") as fh:
#         fh.write(html)
# 
#     os.system(f'open http://0.0.0.0:8000/static/data/{os.path.basename(testScoreOutputFilePath)}')
