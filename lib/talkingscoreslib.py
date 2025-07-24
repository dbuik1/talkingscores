"""
Talking Scores Library - Core MusicXML Processing and HTML Generation

This module provides the main classes for converting MusicXML files into accessible
talking score descriptions with synchronized MIDI playback.

Author: BTimms
"""

from datetime import datetime
import time
import os
import json
import math
import pprint
import logging
import logging.handlers
import logging.config
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from types import SimpleNamespace

from jinja2 import Template, Environment, FileSystemLoader
from music21 import *

from lib.musicAnalyser import *

# Configure music21 to suppress warnings
us = environment.UserSettings()
us['warnings'] = 0
logger = logging.getLogger("TSScore")

# Global settings - TODO: Consider moving to a settings class in future refactoring
global settings
settings = {
    'rhythmDescription': 'british',
    'dotPosition': 'before',
    'octaveDescription': 'name',
    'pitchDescription': 'noteName',
}


def get_contrast_color(hex_color):
    """
    Calculate whether black or white text has better contrast against a hex color.
    
    Args:
        hex_color (str): Hex color code (with or without #)
        
    Returns:
        str: 'black' or 'white' for optimal contrast
    """
    try:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
        return 'black' if luminance > 0.5 else 'white'
    except ValueError:
        return 'white'


def render_colourful_output(text, pitch_letter, element_type, settings):
    """
    Wrap text in styled HTML spans for visual accessibility.
    
    Supports independent and inherited coloring for pitch, rhythm, and octave elements.
    
    Args:
        text (str): The text content to style
        pitch_letter (str): The pitch letter (C, D, E, etc.) for color lookup
        element_type (str): Type of element ('pitch', 'rhythm', 'octave')
        settings (dict): Current display settings
        
    Returns:
        str: HTML-formatted text with appropriate styling
    """
    to_render = text
    color_to_use = None
    pitch_color = settings.get("figureNoteColours", {}).get(pitch_letter)

    if element_type == "pitch" and settings.get("colourPitch"):
        color_to_use = pitch_color
    elif element_type == "rhythm":
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
    elif element_type == "octave":
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
            to_render = f"<span style='color:{contrast_color}; background-color:{color_to_use};'>{text}</span>"
        else:
            to_render = f"<span style='color:{color_to_use};'>{text}</span>"

    return to_render


class TSEvent(object, metaclass=ABCMeta):
    """
    Abstract base class for all musical events in a Talking Score.
    
    Represents a single musical event (note, rest, chord, etc.) with timing
    and rendering information.
    """
    
    def __init__(self):
        self.duration = None
        self.tuplets = ""
        self.end_tuplets = ""
        self.bar = None
        self.part = None
        self.tie = None
        self.start_offset = 0.0
        self.beat = 0.0

    def render(self, settings, context=None, note_letter=None):
        """
        Render this event as descriptive text.
        
        Args:
            settings (dict): Current display settings
            context (TSEvent): Previous event for context-aware rendering
            note_letter (str): Note letter for rhythm coloring
            
        Returns:
            list: List of rendered text elements
        """
        rendered_elements = []
        
        if (settings.get('rhythmDescription', 'british') != 'none' and 
            (context is None or context.duration != self.duration or 
             self.tuplets != "" or settings['rhythmAnnouncement'] == "everyNote")):
            
            rendered_elements.append(self.tuplets)
            if note_letter is not None:
                rendered_elements.append(render_colourful_output(self.duration, note_letter, "rhythm", settings))
            else:
                rendered_elements.append(self.duration)
            rendered_elements.append(self.end_tuplets)

        if self.tie and settings.get('include_ties', True):
            rendered_elements.append(f"tie {self.tie}")

        return list(filter(None, rendered_elements))


class TSDynamic(TSEvent):
    """Musical dynamic marking (forte, piano, crescendo, etc.)."""
    
    def __init__(self, long_name=None, short_name=None):
        super().__init__()
        self.long_name = long_name.capitalize() if long_name else short_name
        self.short_name = short_name

    def render(self, settings, context=None):
        """Render the dynamic marking."""
        if self.long_name:
            return [f'[{self.long_name}]']
        return []


class TSPitch(TSEvent):
    """A single pitch with octave information."""
    
    def __init__(self, pitch_name, octave, pitch_number, pitch_letter):
        super().__init__()
        self.pitch_name = pitch_name
        self.octave = octave
        self.pitch_number = pitch_number
        self.pitch_letter = pitch_letter

    def render(self, settings, context=None):
        """Render the pitch with optional octave information."""
        rendered_elements = []
        
        if settings['octavePosition'] == "before":
            rendered_elements.append(self._render_octave(settings, context))
        
        rendered_elements.append(render_colourful_output(self.pitch_name, self.pitch_letter, "pitch", settings))
        
        if settings['octavePosition'] == "after":
            rendered_elements.append(self._render_octave(settings, context))
        
        return list(filter(None, rendered_elements))

    def _render_octave(self, settings, context=None):
        """Determine whether to show octave based on settings and context."""
        show_octave = False
        
        if settings['octaveAnnouncement'] == "brailleRules":
            if context is None:
                show_octave = True
            else:
                pitch_difference = abs(context.pitch_number - self.pitch_number)
                if pitch_difference <= 4:
                    show_octave = False
                elif 5 <= pitch_difference <= 7:
                    if context.octave != self.octave:
                        show_octave = True
                else:
                    show_octave = True
        elif settings['octaveAnnouncement'] == "everyNote":
            show_octave = True
        elif settings['octaveAnnouncement'] == "firstNote" and context is None:
            show_octave = True
        elif settings['octaveAnnouncement'] == "onChange":
            if context is None or (context is not None and context.octave != self.octave):
                show_octave = True

        if show_octave:
            return render_colourful_output(self.octave, self.pitch_letter, "octave", settings)
        else:
            return ""


class TSUnpitched(TSEvent):
    """Unpitched percussion or similar instrument."""
    
    def __init__(self):
        super().__init__()
        self.pitch = None

    def render(self, settings, context=None):
        """Render unpitched event."""
        rendered_elements = []
        rendered_elements.append(' '.join(super().render(settings, context)))
        rendered_elements.append(' unpitched')
        return rendered_elements


class TSRest(TSEvent):
    """Musical rest."""
    
    def __init__(self):
        super().__init__()
        self.pitch = None

    def render(self, settings, context=None):
        """Render rest if rests are enabled in settings."""
        if not settings.get('include_rests', True):
            return []

        rendered_elements = []
        rendered_elements.extend(super().render(settings, context))
        rendered_elements.append('rest')
        
        return list(filter(None, rendered_elements))


class TSNote(TSEvent):
    """Single musical note with pitch and optional expressions."""
    
    def __init__(self):
        super().__init__()
        self.pitch = None
        self.expressions = []

    def render(self, settings, context=None):
        """Render note with expressions, rhythm, and pitch."""
        rendered_elements = []
        
        # Add expressions (arpeggios, etc.)
        for exp in self.expressions:
            is_arpeggio = 'arpeggio' in exp.name.lower()
            if not is_arpeggio or (is_arpeggio and settings.get('include_arpeggios', True)):
                rendered_elements.append(exp.name)

        # Add rhythm and pitch information
        rendered_elements.extend(super().render(settings, context, self.pitch.pitch_letter))
        rendered_elements.extend(self.pitch.render(settings, getattr(context, 'pitch', None)))
        
        return list(filter(None, rendered_elements))


class TSChord(TSEvent):
    """Musical chord with multiple pitches."""
    
    def __init__(self):
        super().__init__()
        self.pitches = []

    def name(self):
        """Return empty name for compatibility."""
        return ''

    def render(self, settings, context=None):
        """Render chord with note count and individual pitches."""
        rendered_elements = []
        
        if settings.get('describe_chords', True):
            rendered_elements.append(f'{len(self.pitches)}-note chord')
        
        rendered_elements.extend(super().render(settings, context))
        
        previous_pitch = None
        for pitch in sorted(self.pitches, key=lambda p: p.pitch_number):
            rendered_elements.extend(pitch.render(settings, previous_pitch))
            previous_pitch = pitch
        
        return list(filter(None, rendered_elements))


class TalkingScoreBase(object, metaclass=ABCMeta):
    """Abstract base class for talking score implementations."""
    
    @abstractmethod
    def get_title(self):
        """Get the score title."""
        pass

    @abstractmethod
    def get_composer(self):
        """Get the composer name."""
        pass


class Music21TalkingScore(TalkingScoreBase):
    """
    Main class for processing MusicXML files using the music21 library.
    
    This class handles the conversion of MusicXML files into talking score
    data structures and provides methods for generating MIDI files and
    extracting musical information.
    """

    # Class constants for mapping music21 data to readable descriptions
    _OCTAVE_MAP = {
        1: 'bottom', 2: 'lower', 3: 'low', 4: 'mid',
        5: 'high', 6: 'higher', 7: 'top'
    }

    _OCTAVE_FIGURENOTES_MAP = {
        1: 'bottom', 2: 'cross', 3: 'square', 4: 'circle',
        5: 'triangle', 6: 'higher', 7: 'top'
    }

    _DOTS_MAP = {
        0: '', 1: 'dotted ', 2: 'double dotted ', 3: 'triple dotted '
    }

    _DURATION_MAP = {
        'whole': 'semibreve', 'half': 'minim', 'quarter': 'crotchet',
        'eighth': 'quaver', '16th': 'semi-quaver', '32nd': 'demi-semi-quaver',
        '64th': 'hemi-demi-semi-quaver', 'zero': 'grace note',
    }

    _PITCH_FIGURENOTES_MAP = {
        'C': 'red', 'D': 'brown', 'E': 'grey', 'F': 'blue',
        'G': 'black', 'A': 'yellow', 'B': 'green',
    }

    _PITCH_PHONETIC_MAP = {
        'C': 'charlie', 'D': 'bravo', 'E': 'echo', 'F': 'foxtrot',
        'G': 'golf', 'A': 'alpha', 'B': 'bravo',
    }

    def __init__(self, musicxml_filepath):
        """
        Initialize with a MusicXML file.
        
        Args:
            musicxml_filepath (str): Path to the MusicXML file
        """
        self.filepath = os.path.realpath(musicxml_filepath)
        self.score = converter.parse(musicxml_filepath)
        self.last_tempo_inserted_index = 0
        self.music_analyser = None
        super().__init__()

    def get_title(self):
        """Extract the score title from metadata or text boxes."""
        if self.score.metadata.title is not None:
            return self.score.metadata.title
            
        for tb in self.score.flatten().getElementsByClass('TextBox'):
            if (hasattr(tb, 'justify') and tb.justify == 'center' and 
                hasattr(tb, 'alignVertical') and tb.alignVertical == 'top' and 
                hasattr(tb, 'size') and tb.size > 18):
                return tb.content
                
        return "Error reading title"

    def get_composer(self):
        """Extract the composer name from metadata or text boxes."""
        if self.score.metadata.composer is not None:
            return self.score.metadata.composer
            
        for tb in self.score.getElementsByClass('TextBox'):
            if tb.style.justify == 'right':
                return tb.content
                
        return "Unknown"

    def get_initial_time_signature(self):
        """Get the initial time signature description."""
        first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
        time_signatures = first_measure.getElementsByClass(meter.TimeSignature)
        
        initial_time_signature = time_signatures[0] if time_signatures else None
        return self.describe_time_signature(initial_time_signature)

    def describe_time_signature(self, ts):
        """Convert time signature to readable description."""
        if ts is not None:
            return " ".join(ts.ratioString.split("/"))
        else:
            return " error reading time signature...  "

    def get_initial_key_signature(self):
        """Get the initial key signature description."""
        m1 = self.score.parts[0].measures(1, 1)
        key_signatures = m1.flatten().getElementsByClass('KeySignature')
        
        if not key_signatures:
            ks = key.KeySignature(0)
        else:
            ks = key_signatures[0]
            
        return self.describe_key_signature(ks)

    def describe_key_signature(self, ks):
        """Convert key signature to readable description."""
        if ks.sharps > 0:
            return f"{ks.sharps} sharps"
        elif ks.sharps < 0:
            return f"{abs(ks.sharps)} flats"
        else:
            return "No sharps or flats"

    def get_initial_text_expression(self):
        """Get the first text expression from the score."""
        m1 = self.score.parts[0].measures(1, 1)
        text_expressions = m1.flatten().getElementsByClass('TextExpression')
        
        for te in text_expressions:
            return te.content

    def get_initial_tempo(self):
        """Get the initial tempo description."""
        global settings
        if settings is None:
            settings = {
                'dotPosition': "before",
                'rhythmDescription': "british"
            }
        return self.describe_tempo(self.score.metronomeMarkBoundaries()[0][2])

    def get_beat_division_options(self):
        """
        Analyze the time signature and return valid beat division options.
        
        Returns:
            list: List of dictionaries with 'display' and 'value' keys
        """
        ts = self._get_initial_time_signature_object()
        if not ts:
            return []

        options = []
        seen_values = set()

        def add_option(display, value):
            if value not in seen_values:
                options.append({'display': display, 'value': value})
                seen_values.add(value)

        # Add standard options
        add_option('Group by Bar (continuous)', 'bar')

        default_beat_string = self.map_duration(ts.beatDuration)
        default_display = f"{ts.beatCount} {default_beat_string} beats (Default)"
        default_value = f"{ts.beatCount}/{ts.beatDuration.quarterLength}"
        add_option(default_display, default_value)
        
        face_value_beat_string = self.map_duration(duration.Duration(1.0 / ts.denominator))
        face_value_display = f"{ts.numerator} {face_value_beat_string} beats"
        face_value_value = f"{ts.numerator}/{ts.denominator}"
        add_option(face_value_display, face_value_value)

        # Add compound time option if applicable
        if ts.numerator % 3 == 0 and ts.numerator > 3:
            compound_beat_count = ts.numerator / 3
            simple_beat_name = self.map_duration(duration.Duration(1.0 / ts.denominator))
            compound_beat_string = f"Dotted {simple_beat_name}"
            compound_display = f"{int(compound_beat_count)} {compound_beat_string} beats"
            compound_beat_duration_ql = (1.0 / ts.denominator) * 3
            compound_value = f"{int(compound_beat_count)}/{compound_beat_duration_ql}"
            add_option(compound_display, compound_value)

        return options

    def _get_initial_time_signature_object(self):
        """Helper method to get the initial time signature object."""
        try:
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            for item in first_measure:
                if isinstance(item, meter.TimeSignature):
                    return item
            
            # Fallback to score-level time signatures
            time_signatures = self.score.getTimeSignatures()
            return time_signatures[0] if time_signatures else None
        except Exception as e:
            logger.error(f"Could not find TimeSignature: {e}")
            return None

    @staticmethod
    def fix_tempo_number(tempo):
        """Ensure tempo has a valid number, using fallbacks if necessary."""
        if tempo.number is None:
            if tempo.numberSounding is not None:
                tempo.number = tempo.numberSounding
            else:
                tempo.number = 120
                tempo.text = "Error - " + (tempo.text or "")
        return tempo

    def describe_tempo(self, tempo):
        """Convert tempo marking to readable description."""
        tempo = self.fix_tempo_number(tempo)
        tempo_text = ""
        
        if tempo.text is not None:
            tempo_text += f"{tempo.text} ({math.floor(tempo.number)} bpm @ {self.describe_tempo_referent(tempo)})"
        else:
            tempo_text += f"{math.floor(tempo.number)} bpm @ {self.describe_tempo_referent(tempo)}"
            
        return tempo_text

    def describe_tempo_referent(self, tempo):
        """Describe the note value that the tempo refers to."""
        global settings
        tempo_text = ""
        
        if settings['dotPosition'] == "before":
            tempo_text = self._DOTS_MAP.get(tempo.referent.dots, '')
            
        tempo_text += self.map_duration(tempo.referent)
        
        if settings['dotPosition'] == "after":
            tempo_text += " " + self._DOTS_MAP.get(tempo.referent.dots, '')

        return tempo_text

    def get_number_of_bars(self):
        """Get the total number of measures in the score."""
        return len(self.score.parts[0].getElementsByClass('Measure'))

    def get_instruments(self):
        """
        Extract instrument information and organize parts.
        
        Sets up self.part_instruments and self.part_names dictionaries.
        """
        self.part_instruments = {}
        self.part_names = {}
        instrument_names = []
        ins_count = 1
        
        for c, instrument in enumerate(self.score.flatten().getInstruments()):
            if (len(self.part_instruments) == 0 or 
                self.part_instruments[ins_count-1][3] != instrument.partId):
                
                part_name = instrument.partName or f"Instrument {ins_count} (unnamed)"
                self.part_instruments[ins_count] = [part_name, c, 1, instrument.partId]
                instrument_names.append(part_name)
                ins_count += 1
            else:
                self.part_instruments[ins_count-1][2] += 1
                self._assign_part_names(c, ins_count-1)

        logger.debug(f"part instruments = {self.part_instruments}")
        return instrument_names

    def _assign_part_names(self, current_index, instrument_index):
        """Assign descriptive names to multiple parts of the same instrument."""
        part_count = self.part_instruments[instrument_index][2]
        
        if part_count == 2:
            self.part_names[current_index-1] = "Right hand"
            self.part_names[current_index] = "Left hand"
        elif part_count == 3:
            self.part_names[current_index-2] = "Part 1"
            self.part_names[current_index-1] = "Part 2"
            self.part_names[current_index] = "Part 3"
        else:
            self.part_names[current_index] = f"Part {part_count}"

    def compare_parts_with_selected_instruments(self):
        """
        Compare available instruments with user selections.
        
        Sets up playback options based on selected instruments.
        """
        global settings
        
        self.selected_instruments = []
        self.unselected_instruments = []
        self.binary_selected_instruments = 1
        self.selected_part_names = []
        
        # Process instrument selections
        for ins in self.part_instruments.keys():
            self.binary_selected_instruments = self.binary_selected_instruments << 1
            if ins in settings.get('instruments', []):
                self.selected_instruments.append(ins)
                self.binary_selected_instruments += 1
            else:
                self.unselected_instruments.append(ins)

        # Generate part names for selected instruments
        for ins in self.selected_instruments:
            ins_name = self.part_instruments[ins][0]
            if self.part_instruments[ins][2] == 1:
                self.selected_part_names.append(ins_name)
            else:
                first_part_index = self.part_instruments[ins][1]
                part_count = self.part_instruments[ins][2]
                for part_index in range(first_part_index, first_part_index + part_count):
                    self.selected_part_names.append(f"{ins_name} - {self.part_names[part_index]}")

        self._configure_playback_options(settings)

    def _configure_playback_options(self, settings):
        """Configure which playback options should be available."""
        play_all_choice = settings.get('playAll', False)
        play_selected_choice = settings.get('playSelected', False)
        play_unselected_choice = settings.get('playUnselected', False)

        # Disable inappropriate options
        if len(self.part_instruments) == 1:
            settings['playAll'] = False
            settings['playSelected'] = False
        
        if len(self.unselected_instruments) == 0:
            settings['playUnselected'] = False
            
        if (len(self.selected_instruments) == len(self.part_instruments) and 
            settings.get('playAll', False)):
            settings['playSelected'] = False
            
        if len(self.selected_instruments) == 1:
            settings['playSelected'] = False

        # Set up binary encoding for playback options
        self.binary_play_all = 1
        for choice in [play_all_choice, play_selected_choice, play_unselected_choice]:
            self.binary_play_all = self.binary_play_all << 1
            if choice:
                self.binary_play_all += 1

    def get_number_of_parts(self):
        """Get the number of instrument parts in the score."""
        self.get_instruments()
        return len(self.part_instruments)

    def get_bar_range(self, range_start, range_end):
        """
        Get measures for all parts within a specified range.
        
        Args:
            range_start (int): Starting measure number
            range_end (int): Ending measure number
            
        Returns:
            dict: Dictionary mapping part IDs to lists of measures
        """
        measures = self.score.measures(range_start, range_end)
        bars_for_parts = {}
        
        for part in measures.parts:
            bars_for_parts.setdefault(part.id, []).extend(part.getElementsByClass('Measure'))

        return bars_for_parts

    def get_events_for_bar_range(self, start_bar, end_bar, part_index):
        """
        Extract musical events from a range of bars for a specific part.
        
        This method processes music21 objects and converts them into TSEvent objects
        for consistent handling throughout the application.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            part_index (int): Index of the part to process
            
        Returns:
            dict: Nested dictionary of events organized by bar and time point
        """
        intermediate_events = {}
        measures = self.score.parts[part_index].measures(start_bar, end_bar)
        
        # Ensure time signature is available
        if (measures.measure(start_bar) is not None and 
            not measures.measure(start_bar).getElementsByClass(meter.TimeSignature)):
            measures.measure(start_bar).insert(0, self.timeSigs[start_bar])

        logger.info(f'Processing part {part_index} - bars {start_bar} to {end_bar}')
        
        # Process each measure
        for bar_index in range(start_bar, end_bar + 1):
            measure = measures.measure(bar_index)
            if measure is not None:
                self.update_events_for_measure(measure, intermediate_events)
        
        # Add dynamic spanners (crescendo, diminuendo) if enabled
        if settings.get('include_dynamics', True):
            self._add_dynamic_spanners(part_index, start_bar, end_bar, intermediate_events)

        return self._organize_events_by_time_point(intermediate_events, start_bar, end_bar)

    def _add_dynamic_spanners(self, part_index, start_bar, end_bar, intermediate_events):
        """Add crescendo and diminuendo markings to events."""
        for spanner in self.score.parts[part_index].spanners.elements:
            first = spanner.getFirst()
            last = spanner.getLast()

            if (first.measureNumber is None or last.measureNumber is None or
                first.measureNumber > end_bar or last.measureNumber < start_bar):
                continue

            spanner_type = type(spanner).__name__
            if spanner_type in ['Crescendo', 'Diminuendo']:
                if first.measureNumber >= start_bar:
                    event = TSDynamic(long_name=f'{spanner_type} Start')
                    event.start_offset = first.offset
                    event.beat = first.beat
                    intermediate_events.setdefault(first.measureNumber, {}).setdefault(
                        first.offset, {}).setdefault(1, []).append(event)
                
                if last.measureNumber <= end_bar:
                    event = TSDynamic(long_name=f'{spanner_type} End')
                    event.start_offset = last.offset + last.duration.quarterLength
                    event.beat = last.beat + last.duration.quarterLength
                    intermediate_events.setdefault(last.measureNumber, {}).setdefault(
                        event.start_offset, {}).setdefault(1, []).append(event)

    def _organize_events_by_time_point(self, intermediate_events, start_bar, end_bar):
        """Organize events into time points with beat information."""
        final_events_by_bar = {}
        
        for bar_num in range(start_bar, end_bar + 1):
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

    def update_events_for_measure(self, measure_stream, events, voice=1, state=None):
        """
        Convert music21 elements in a measure to TSEvent objects.
        
        Args:
            measure_stream: music21 measure or voice stream
            events (dict): Dictionary to populate with events
            voice (int): Voice number for multi-voice music
            state (dict): State for tracking accidentals and other context
        """
        if state is None:
            state = {}

        for element in measure_stream.elements:
            event = self._create_event_from_element(element, state)
            
            if event is None:
                # Handle Voice elements recursively
                if type(element).__name__ == 'Voice':
                    self.update_events_for_measure(element, events, int(element.id), state=state)
                continue

            self._set_event_timing_and_duration(event, element)
            
            events.setdefault(measure_stream.measureNumber, {})\
                  .setdefault(element.offset, {})\
                  .setdefault(voice, [])\
                  .append(event)

    def _create_event_from_element(self, element, state):
        """Create appropriate TSEvent object from music21 element."""
        element_type = type(element).__name__
        
        if element_type == 'Note':
            event = TSNote()
            pitch_name = self.map_pitch(element.pitch, state)
            event.pitch = TSPitch(pitch_name, self.map_octave(element.pitch.octave), 
                                 element.pitch.ps, element.pitch.name[0])
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
                chord_pitches.append(TSPitch(pitch_name, self.map_octave(p.octave), 
                                           p.ps, p.name[0]))
            event.pitches = chord_pitches
            if element.tie:
                event.tie = element.tie.type
                
        elif element_type == 'Dynamic':
            if settings.get('include_dynamics', True):
                event = TSDynamic(long_name=element.longName, short_name=element.value)
            else:
                return None
        else:
            return None
            
        return event

    def _set_event_timing_and_duration(self, event, element):
        """Set timing and duration information for an event."""
        event.start_offset = element.offset
        event.beat = element.beat
        event.duration = ""
        
        # Handle tuplets
        if element.duration.tuplets:
            tuplet = element.duration.tuplets[0]
            if tuplet.type == "start":
                if tuplet.fullName == "Triplet":
                    event.tuplets = "triplets "
                else:
                    event.tuplets = f"{tuplet.fullName} ({tuplet.tupletActual[0]} in {tuplet.tupletNormal[0]}) "
            elif tuplet.type == "stop" and tuplet.fullName != "Triplet":
                event.end_tuplets = "end tuplet "

        # Handle duration description
        if settings['dotPosition'] == "before":
            event.duration += self.map_dots(element.duration.dots)
        event.duration += self.map_duration(element.duration)
        if settings['dotPosition'] == "after":
            event.duration += " " + self.map_dots(element.duration.dots)

    # ============================================================================
    # MIDI GENERATION METHODS
    # 
    # These methods handle all MIDI file generation. This is the section that will
    # be most relevant for the future architecture changes to use lightweight MIDI
    # manipulation instead of regenerating everything with music21.
    # ============================================================================

    def generate_midi_filename_sel(self, base_url, range_start=None, range_end=None, sel=""):
        """
        Generate MIDI URL for a selection of parts (all, selected, unselected).
        
        Args:
            base_url (str): Base URL for MIDI endpoints
            range_start (int, optional): Starting measure
            range_end (int, optional): Ending measure  
            sel (str): Selection type ("all", "sel", "un")
            
        Returns:
            str: Complete MIDI URL with query parameters
        """
        query_params = f"bsi={self.binary_selected_instruments}&bpi={self.binary_play_all}"
        if sel:
            query_params += f"&sel={sel}"
        if range_start is not None:
            query_params += f"&start={range_start}&end={range_end}"
        return f"{base_url}?{query_params}"

    def generate_part_descriptions(self, instrument, start_bar, end_bar):
        """
        Generate event descriptions for all parts of an instrument.
        
        Args:
            instrument (int): Instrument number
            start_bar (int): Starting bar
            end_bar (int): Ending bar
            
        Returns:
            list: List of event descriptions for each part
        """
        part_descriptions = []
        instrument_info = self.part_instruments[instrument]
        first_part_index = instrument_info[1]
        part_count = instrument_info[2]
        
        for part_index in range(first_part_index, first_part_index + part_count):
            part_descriptions.append(
                self.get_events_for_bar_range(start_bar, end_bar, part_index)
            )

        return part_descriptions

    def generate_midi_filenames(self, base_url, range_start=None, range_end=None, add_instruments=[]):
        """
        Generate MIDI URLs for specific instruments and their parts.
        
        Args:
            base_url (str): Base URL for MIDI endpoints
            range_start (int, optional): Starting measure
            range_end (int, optional): Ending measure
            add_instruments (list): List of instrument numbers to include
            
        Returns:
            tuple: (instrument_midi_url, list_of_part_midi_urls)
        """
        part_midis = []
        instrument_midi = ""
        
        if not add_instruments:
            return (instrument_midi, part_midis)
            
        last_ins = add_instruments[-1]

        query_string = f"bsi={self.binary_selected_instruments}&bpi={self.binary_play_all}"
        if range_start is not None:
            query_string += f"&start={range_start}&end={range_end}"

        # Generate part MIDI URLs for multi-part instruments
        for ins in add_instruments:
            if self.part_instruments[ins][2] > 1:
                start_part_index = self.part_instruments[ins][1]
                end_part_index = start_part_index + self.part_instruments[ins][2]
                for part_index in range(start_part_index, end_part_index):
                    part_midis.append(f"{base_url}?part={part_index}&{query_string}")

        # Generate main instrument MIDI URL
        if last_ins is not None:
            instrument_midi = f"{base_url}?ins={last_ins}&{query_string}"

        return (instrument_midi, part_midis)

    def generate_midi_for_instruments(self, prefix, range_start=None, range_end=None, 
                                    add_instruments=[], output_path="", postfix_filename=""):
        """
        Generate actual MIDI files for specified instruments.
        
        NOTE: This method contains the current MIDI generation logic that will
        be replaced in the future architecture. The goal is to generate base
        MIDI files here and then use lightweight manipulation for variations.
        
        Args:
            prefix (str): URL prefix for generated files
            range_start (int, optional): Starting measure
            range_end (int, optional): Ending measure
            add_instruments (list): Instruments to include
            output_path (str): Directory for output files
            postfix_filename (str): Suffix for filenames
            
        Returns:
            tuple: (main_midi_url, list_of_part_midi_urls)
        """
        part_midis = []
        score_stream = stream.Score(id='temp')

        if range_start is None and range_end is None:
            self._generate_full_score_midi(score_stream, add_instruments, part_midis, 
                                         range_start, range_end, output_path, postfix_filename)
        else:
            self._generate_range_midi(score_stream, add_instruments, part_midis,
                                    range_start, range_end, output_path, postfix_filename)

        # Generate final MIDI file
        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}.mid")
        
        if not os.path.exists(midi_filename):
            score_stream.write('midi', midi_filename)
            
        part_midis = [prefix + os.path.basename(s) for s in part_midis]
        return (prefix + os.path.basename(midi_filename), part_midis)

    def _generate_full_score_midi(self, score_stream, add_instruments, part_midis,
                                range_start, range_end, output_path, postfix_filename):
        """Generate MIDI for the complete score."""
        for ins in add_instruments:
            instrument_info = self.part_instruments[ins]
            first_part = instrument_info[1]
            part_count = instrument_info[2]
            
            for part_index in range(first_part, first_part + part_count):
                score_stream.insert(self.score.parts[part_index])
                
                if part_count > 1:
                    part_midi = self.generate_midi_parts_for_instrument(
                        range_start, range_end, ins, part_index - first_part, 
                        output_path, postfix_filename
                    )
                    part_midis.append(part_midi)

    def _generate_range_midi(self, score_stream, add_instruments, part_midis,
                           range_start, range_end, output_path, postfix_filename):
        """Generate MIDI for a specific range of measures."""
        postfix_filename += f"_{range_start}{range_end}"
        
        for ins in add_instruments:
            instrument_info = self.part_instruments[ins]
            first_part = instrument_info[1]
            part_count = instrument_info[2]
            first_part_processed = True
            
            for part_index in range(first_part, first_part + part_count):
                if part_count > 1:
                    part_midi = self.generate_midi_parts_for_instrument(
                        range_start, range_end, ins, part_index - first_part,
                        output_path, postfix_filename
                    )
                    part_midis.append(part_midi)
                
                part_measures = self.score.parts[part_index].measures(
                    range_start, range_end, 
                    collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                )
                
                if first_part_processed and part_index != 0:
                    self.insert_tempos(part_measures, self.score.parts[0].measure(range_start).offset)
                    first_part_processed = False

                # Remove repeat markings for cleaner playback
                for measure in part_measures.getElementsByClass('Measure'):
                    measure.removeByClass('Repeat')
                    
                score_stream.insert(part_measures)

    def generate_midi_parts_for_instrument(self, range_start=None, range_end=None, 
                                         instrument=0, part=0, output_path="", postfix_filename=""):
        """
        Generate MIDI file for a specific part of an instrument.
        
        Args:
            range_start (int, optional): Starting measure
            range_end (int, optional): Ending measure
            instrument (int): Instrument number
            part (int): Part number within instrument
            output_path (str): Output directory
            postfix_filename (str): Filename suffix
            
        Returns:
            str: Path to generated MIDI file
        """
        score_stream = stream.Score(id='temp')
        part_index = self.part_instruments[instrument][1] + part
        
        if range_start is None and range_end is None:
            score_stream.insert(self.score.parts[part_index])
            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{part+1}.mid")
        else:
            postfix_filename += f"_{range_start}{range_end}"
            part_measures = self.score.parts[part_index].measures(
                range_start, range_end,
                collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
            )
            
            if part_index != 0:
                self.insert_tempos(part_measures, self.score.parts[0].measure(range_start).offset)

            for measure in part_measures.getElementsByClass('Measure'):
                measure.removeByClass('Repeat')
                
            score_stream.insert(part_measures)
            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{part+1}.mid")

        if not os.path.exists(midi_filename):
            score_stream.write('midi', midi_filename)
            
        return midi_filename

    def generate_midi_for_part_range(self, range_start=None, range_end=None, parts=[], output_path=""):
        """
        Generate MIDI file for specific parts within a range.
        
        Args:
            range_start (int, optional): Starting measure
            range_end (int, optional): Ending measure
            parts (list): List of part IDs to include
            output_path (str): Output directory
            
        Returns:
            str: Path to generated MIDI file
        """
        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        
        if range_start is None and range_end is None:
            midi_filename = os.path.join(output_path, f"{base_filename}.mid")
            if not os.path.exists(midi_filename):
                self.score.write('midi', midi_filename)
            return midi_filename
            
        elif len(parts) > 0:
            for part in self.score.parts:
                if part.id not in parts:
                    continue

                midi_filename = os.path.join(output_path, f"{base_filename}_p{part.id}_{range_start}_{range_end}.mid")
                if not os.path.exists(midi_filename):
                    midi_stream = part.measures(
                        range_start, range_end,
                        collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                    )
                    
                    if part != self.score.parts[0]:
                        self.insert_tempos(midi_stream, self.score.parts[0].measure(range_start).offset)
                        
                    for measure in midi_stream.getElementsByClass('Measure'):
                        measure.removeByClass('Repeat')
                        
                    midi_stream.write('midi', midi_filename)
                return midi_filename
        else:
            midi_filename = os.path.join(output_path, f"{base_filename}_{range_start}_{range_end}.mid")
            if not os.path.exists(midi_filename):
                midi_stream = self.score.measures(
                    range_start, range_end,
                    collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                )
                
                for part in midi_stream.getElementsByClass('Part'):
                    for measure in part.getElementsByClass('Measure'):
                        measure.removeByClass('Repeat')
                        
                midi_stream.write('midi', midi_filename)
            return midi_filename

        return None

    def insert_tempos(self, stream, offset_start):
        """
        Insert tempo markings into a stream at appropriate positions.
        
        Args:
            stream: music21 stream to modify
            offset_start (float): Starting offset for the stream
        """
        if self.last_tempo_inserted_index > 0:
            self.last_tempo_inserted_index -= 1
            
        for mmb in self.score.metronomeMarkBoundaries()[self.last_tempo_inserted_index:]:
            if mmb[0] >= offset_start + stream.duration.quarterLength:
                return
                
            if mmb[1] > offset_start:
                if mmb[0] <= offset_start:
                    stream.insert(0, tempo.MetronomeMark(number=mmb[2].number))
                    self.last_tempo_inserted_index += 1
                else:
                    stream.insert(mmb[0] - offset_start, tempo.MetronomeMark(number=mmb[2].number))
                    self.last_tempo_inserted_index += 1

    # ============================================================================
    # END OF MIDI GENERATION METHODS
    # ============================================================================

    def map_octave(self, octave):
        """Map numeric octave to descriptive text based on settings."""
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
        """
        Map pitch to descriptive text with accidental handling.
        
        Args:
            pitch: music21 pitch object
            state (dict): State for tracking accidentals
            
        Returns:
            str: Descriptive pitch text
        """
        global settings
        mode = settings.get('key_signature_accidentals', 'applied')
        
        # Get base pitch name
        if settings['pitchDescription'] == "colourNotes":
            base_name = self._PITCH_FIGURENOTES_MAP.get(pitch.step, "?")
        elif settings['pitchDescription'] == "phonetic":
            base_name = self._PITCH_PHONETIC_MAP.get(pitch.step, "?")
        else:
            base_name = pitch.step if settings['pitchDescription'] == 'noteName' else ''

        if not pitch.accidental:
            return base_name

        # Determine if accidental should be shown
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

        # Format accidental
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
        """Map music21 duration to descriptive text based on settings."""
        global settings
        
        if settings['rhythmDescription'] == "american":
            return duration.type
        elif settings['rhythmDescription'] == "british":
            return self._DURATION_MAP.get(duration.type, f'Unknown duration {duration.type}')
        elif settings['rhythmDescription'] == "none":
            return ""

    def map_dots(self, dots):
        """Map number of dots to descriptive text."""
        if settings['rhythmDescription'] == "none":
            return ""
        else:
            return self._DOTS_MAP.get(dots, '')
        
    def get_rhythm_range(self):
        """
        Find all unique rhythm types present in the score.
        
        Returns:
            list: Sorted list of rhythm descriptions found in the score
        """
        valid_rhythm_types = self._DURATION_MAP.keys()
        found_rhythms = set()

        for note in self.score.flatten().notesAndRests:
            if note.duration.type in valid_rhythm_types:
                found_rhythms.add(self._DURATION_MAP[note.duration.type])
        
        return sorted(list(found_rhythms), 
                     key=lambda r: list(self._DURATION_MAP.values()).index(r))

    def get_octave_range(self):
        """
        Find the highest and lowest octaves used in the score.
        
        Returns:
            dict: Dictionary with 'min' and 'max' octave numbers
        """
        all_octaves = []
        
        for element in self.score.flatten().notes:
            if 'Chord' in element.classes:
                for pitch in element.pitches:
                    all_octaves.append(pitch.octave)
            elif 'Note' in element.classes:
                all_octaves.append(element.pitch.octave)
        
        if not all_octaves:
            return {'min': 0, 'max': 0}
        
        return {'min': min(all_octaves), 'max': max(all_octaves)}


class HTMLTalkingScoreFormatter:
    """
    Formatter class that converts Music21TalkingScore data into HTML output.
    
    This class handles the generation of the final HTML talking score with
    embedded navigation, MIDI controls, and formatted musical descriptions.
    """
    
    def __init__(self, talking_score):
        """
        Initialize the formatter with a talking score and load options.
        
        Args:
            talking_score (Music21TalkingScore): The score to format
        """
        global settings
        self.score = talking_score
        self.options = {}

        # Load user options from file
        options_path = self.score.filepath + '.opts'
        try:
            with open(options_path, "r") as options_fh:
                self.options = json.load(options_fh)
        except FileNotFoundError:
            logger.warning(f"Options file not found: {options_path}. Using default settings.")

        # Update global settings with user preferences
        self._update_settings_from_options()

    def _update_settings_from_options(self):
        """Update global settings dictionary with user options."""
        global settings
        
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

    def generateHTML(self, output_path="", web_path=""):
        """
        Generate the complete HTML talking score.
        
        Args:
            output_path (str): Directory for MIDI file output
            web_path (str): Base URL for web resources
            
        Returns:
            str: Complete HTML content for the talking score
        """
        global settings
        
        # Set up template environment
        template = self._setup_template_environment()
        
        # Prepare score data
        self._prepare_score_analysis()
        
        # Get score range and generate MIDI files
        start_bar, end_bar = self._get_score_range()
        
        # NOTE: Removed the problematic _trigger_midi_generation call here
        # MIDI generation is now handled within _create_music_segment
        
        # Generate MIDI URLs and music segments
        full_score_midis = self._generate_full_score_midis(web_path, start_bar, end_bar)
        music_segments = self.get_music_segments(output_path, web_path)
        beat_division_options = self.score.get_beat_division_options()

        # Render template with all data
        return template.render({
            'settings': settings,
            'basic_information': self._get_basic_information(),
            'preamble': self._get_preamble(),
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

    def _setup_template_environment(self):
        """Set up Jinja2 template environment and load template."""
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        return env.get_template('talkingscore.html')

    def _prepare_score_analysis(self):
        """Prepare instrument data and musical analysis."""
        self.score.get_instruments()
        self.score.compare_parts_with_selected_instruments()

        self.music_analyser = MusicAnalyser()
        self.music_analyser.setScore(self.score)

    def _get_score_range(self):
        """Get the start and end measure numbers of the score."""
        measures = self.score.score.parts[0].getElementsByClass('Measure')
        start_bar = measures[0].number
        end_bar = measures[-1].number
        return start_bar, end_bar

    def _generate_full_score_midis(self, web_path, start_bar, end_bar):
        """Generate MIDI URLs for the complete score."""
        selected_instruments_midis = {}
        
        for index, ins in enumerate(self.score.selected_instruments):
            midis = self.score.generate_midi_filenames(
                base_url=web_path, range_start=start_bar, range_end=end_bar, 
                add_instruments=[ins]
            )
            selected_instruments_midis[ins] = {
                "ins": ins, "midi": midis[0], "midi_parts": midis[1]
            }

        midi_all = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="all"
        )
        midi_selected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="sel"
        )
        midi_unselected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="un"
        )

        return {
            'selected_instruments_midis': selected_instruments_midis,
            'midi_all': midi_all,
            'midi_sel': midi_selected,
            'midi_un': midi_unselected
        }

    def _trigger_midi_generation(self, start_bar, end_bar):
        """
        Pre-generate MIDI files for the specified range.
        
        This method triggers the MidiHandler to create all necessary MIDI files
        upfront, improving user experience by avoiding delays during playback.
        """
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
            midi_handler = MidiHandler(dummy_request, id_hash, xml_filename)
            midi_handler.score = self.score.score
            midi_handler.make_midi_files()
            logger.info(f"Successfully generated MIDIs for bars {start_bar}-{end_bar}.")
        except Exception as e:
            logger.error(f"Failed to pre-generate MIDI files for bars {start_bar}-{end_bar}: {e}", exc_info=True)

    def _create_music_segment(self, start_bar, end_bar, web_path):
        """
        Create a music segment dictionary for a given bar range.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            web_path (str): Base URL for web resources
            
        Returns:
            dict: Complete segment data with MIDI URLs and descriptions
        """
        # MIDI generation happens here for each segment
        self._trigger_midi_generation(start_bar=start_bar, end_bar=end_bar)
        
        # Generate MIDI URLs for selected instruments
        selected_instruments_midis = {}
        for index, ins in enumerate(self.score.selected_instruments):
            midis = self.score.generate_midi_filenames(
                base_url=web_path, range_start=start_bar, range_end=end_bar, 
                add_instruments=[ins]
            )
            selected_instruments_midis[ins] = {
                "ins": ins, "midi": midis[0], "midi_parts": midis[1]
            }
        
        # Generate combined MIDI URLs
        midi_all = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="all"
        )
        midi_selected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="sel"
        )
        midi_unselected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="un"
        )

        # Generate text descriptions
        selected_instruments_descriptions = {}
        for index, ins in enumerate(self.score.selected_instruments):
            selected_instruments_descriptions[ins] = self.score.generate_part_descriptions(
                instrument=ins, start_bar=start_bar, end_bar=end_bar
            )

        return {
            'start_bar': start_bar,
            'end_bar': end_bar,
            'selected_instruments_descriptions': selected_instruments_descriptions,
            'selected_instruments_midis': selected_instruments_midis,
            'midi_all': midi_all,
            'midi_sel': midi_selected,
            'midi_un': midi_unselected
        }

    def _get_basic_information(self):
        """Get basic score information for template rendering."""
        return {
            'title': self.score.get_title(),
            'composer': self.score.get_composer(),
        }

    def _get_preamble(self):
        """Get score preamble information for template rendering."""
        return {
            'time_signature': self.score.get_initial_time_signature(),
            'key_signature': self.score.get_initial_key_signature(),
            'tempo': self.score.get_initial_tempo(),
            'number_of_bars': self.score.get_number_of_bars(),
            'number_of_parts': self.score.get_number_of_parts(),
        }

    def get_music_segments(self, output_path, web_path):
        """
        Generate all music segments for the score.
        
        This method divides the score into manageable segments based on user
        preferences and creates the necessary data structures for rendering.
        
        Args:
            output_path (str): Directory for MIDI file output
            web_path (str): Base URL for web resources
            
        Returns:
            list: List of music segment dictionaries
        """
        global settings
        logger.info("Start of get_music_segments")

        music_segments = []
        
        # Process time and key signature changes
        self._process_time_and_key_changes()
        
        # Set up time signatures for each measure
        self._setup_measure_time_signatures()
        
        # Handle pickup bar if present
        start_bar_for_loop = self._handle_pickup_bar(music_segments, web_path)
        
        # Generate main music segments
        self._generate_main_segments(start_bar_for_loop, music_segments, web_path)

        return music_segments

    def _process_time_and_key_changes(self):
        """Process and catalog all time signature and key signature changes."""
        self.time_and_keys = {}
        
        # Process time signature changes
        time_signatures = self.score.score.parts[0].flatten().getElementsByClass('TimeSignature')
        total_time_sigs = len(time_signatures)
        
        for count, ts in enumerate(time_signatures):
            description = (f"Time signature - {count+1} of {total_time_sigs} is "
                         f"{self.score.describe_time_signature(ts)}.")
            self.time_and_keys.setdefault(ts.measureNumber, []).append(description)

        # Process key signature changes
        key_signatures = self.score.score.parts[0].flatten().getElementsByClass('KeySignature')
        total_key_sigs = len(key_signatures)
        
        for count, ks in enumerate(key_signatures):
            description = (f"Key signature - {count+1} of {total_key_sigs} is "
                         f"{self.score.describe_key_signature(ks)}.")
            self.time_and_keys.setdefault(ks.measureNumber, []).append(description)

    def _setup_measure_time_signatures(self):
        """Set up time signature tracking for each measure."""
        self.score.timeSigs = {}
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        
        if self.score.score.parts[0].hasMeasures():
            initial_time_signatures = first_measure.getTimeSignatures()
            previous_ts = initial_time_signatures[0] if initial_time_signatures else None
        else:
            previous_ts = self.score.get_initial_time_signature()

        # Assign time signatures to all measures
        total_measures = self.score.score.parts[0].getElementsByClass('Measure')[-1].number
        for measure_num in range(first_measure.number, total_measures + 1):
            measure = self.score.score.parts[0].measure(measure_num)
            if measure and measure.getElementsByClass(meter.TimeSignature):
                previous_ts = measure.getElementsByClass(meter.TimeSignature)[0]
            self.score.timeSigs[measure_num] = previous_ts

    def _handle_pickup_bar(self, music_segments, web_path):
        """
        Handle pickup bar (anacrusis) if present.
        
        Args:
            music_segments (list): List to append pickup segment to
            web_path (str): Base URL for web resources
            
        Returns:
            int: Starting bar number for main loop
        """
        global settings
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        start_bar_for_loop = first_measure.number
        
        active_time_sig = first_measure.timeSignature or self.score.timeSigs.get(first_measure.number)
        
        if (active_time_sig and 
            first_measure.duration.quarterLength < active_time_sig.barDuration.quarterLength):
            
            pickup_bar_num = first_measure.number
            logger.info(f"Anacrusis (pickup bar) detected at measure {pickup_bar_num}.")
            
            self.score.timeSigs[pickup_bar_num] = active_time_sig

            segment = self._create_music_segment(
                start_bar=pickup_bar_num, end_bar=pickup_bar_num, web_path=web_path
            )
            
            segment['start_bar'] = 'Pickup'
            segment['end_bar'] = ''
            music_segments.append(segment)
            
            start_bar_for_loop = pickup_bar_num + 1

        return start_bar_for_loop

    def _generate_main_segments(self, start_bar_for_loop, music_segments, web_path):
        """
        Generate the main music segments based on bars-at-a-time setting.
        
        Args:
            start_bar_for_loop (int): Starting bar for segmentation
            music_segments (list): List to append segments to
            web_path (str): Base URL for web resources
        """
        global settings
        total_measures = self.score.score.parts[0].getElementsByClass('Measure')[-1].number
        
        for bar_index in range(start_bar_for_loop, total_measures + 1, settings['barsAtATime']):
            end_bar_index = min(bar_index + settings['barsAtATime'] - 1, total_measures)

            if self.score.score.parts[0].measure(bar_index) is None:
                break

            segment = self._create_music_segment(
                start_bar=bar_index, end_bar=end_bar_index, web_path=web_path
            )
            music_segments.append(segment)