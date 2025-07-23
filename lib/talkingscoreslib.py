"""
Talking Scores Library Module

This module provides the core functionality for converting MusicXML files into accessible
talking scores. It creates detailed textual descriptions of musical content with support
for various customization options including rhythm descriptions, pitch naming conventions,
octave announcements, and visual styling.

Key Components:
- TSEvent hierarchy: Represents different musical events (notes, chords, rests, dynamics)
- Music21TalkingScore: Main class for parsing MusicXML and extracting musical information
- HTMLTalkingScoreFormatter: Generates HTML output with embedded audio controls

The module supports multiple description styles (British/American rhythm names, various
pitch description modes, configurable octave handling) and can generate both full scores
and segmented portions with synchronized MIDI playback.
"""

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

# Configure music21 environment settings
us = environment.UserSettings()
us['warnings'] = 0
logger = logging.getLogger("TSScore")

# Global settings dictionary (updated by HTMLTalkingScoreFormatter)
global settings
settings = {
    'rhythmDescription': 'british',
    'dotPosition': 'before',
    'octaveDescription': 'name',
    'pitchDescription': 'noteName',
}


def get_contrast_color(hex_color):
    """
    Calculate whether black or white text provides better contrast against a given hex color.
    
    Args:
        hex_color (str): Hexadecimal color code (with or without #)
        
    Returns:
        str: 'black' for light backgrounds, 'white' for dark backgrounds
    """
    try:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        # Calculate relative luminance using standard formula
        luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
        return 'black' if luminance > 0.5 else 'white'
    except ValueError:
        # Fallback for invalid hex codes
        return 'white'


def render_colourful_output(text, pitch_letter, element_type, settings):
    """
    Wrap text in styled HTML spans based on color configuration.
    
    Supports independent and inherited coloring for different musical elements
    (pitch, rhythm, octave) with customizable color schemes.
    
    Args:
        text (str): Text content to be styled
        pitch_letter (str): Single letter pitch name (A-G) for color lookup
        element_type (str): Type of element ('pitch', 'rhythm', 'octave')
        settings (dict): Configuration settings including color preferences
        
    Returns:
        str: HTML-wrapped text with styling, or original text if no coloring
    """
    # CHECK FOR GLOBAL DISABLE FIRST
    if settings.get('disable_all_coloring', False):
        return text
    
    rendered_text = text
    color_to_use = None
    pitch_color = settings.get("figureNoteColours", {}).get(pitch_letter)

    # Determine which color to use based on element type and settings
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
    
    # Apply styling if color is specified and positioning is configured
    if settings.get("colourPosition") != "none" and color_to_use:
        style_type = settings.get("colourPosition")
        if style_type == "background":
            contrast_color = get_contrast_color(color_to_use)
            rendered_text = f"<span style='color:{contrast_color}; background-color:{color_to_use};'>{text}</span>"
        else:  # 'text' style
            rendered_text = f"<span style='color:{color_to_use};'>{text}</span>"

    return rendered_text


class TSEvent(object, metaclass=ABCMeta):
    """
    Abstract base class for all musical events in a talking score.
    
    This class defines the common interface and shared attributes for all
    musical events including notes, chords, rests, and dynamics. It handles
    duration rendering, tuplet information, and tie descriptions.
    
    Attributes:
        duration (str): Human-readable duration description
        tuplets (str): Opening tuplet description
        endTuplets (str): Closing tuplet description
        bar (int): Measure number containing this event
        part (int): Part number containing this event
        tie (str): Tie type ('start', 'stop', 'continue')
        start_offset (float): Time offset within the measure
        beat (float): Beat position within the measure
    """
    
    def __init__(self):
        """Initialize common attributes for all musical events."""
        self.duration = None
        self.tuplets = ""
        self.endTuplets = ""
        self.bar = None
        self.part = None
        self.tie = None
        self.start_offset = 0.0
        self.beat = 0.0

    def render(self, settings, context=None, note_letter=None):
        """
        Render the event as human-readable text based on settings and context.
        
        Args:
            settings (dict): Configuration for rendering (rhythm style, etc.)
            context (TSEvent): Previous event for comparison-based rendering
            note_letter (str): Pitch letter for rhythm coloring (optional)
            
        Returns:
            list: List of rendered text elements to be joined
        """
        rendered_elements = []
        
        # Add rhythm description if enabled and conditions are met
        if (settings.get('rhythmDescription', 'british') != 'none' and 
            (context is None or 
             context.duration != self.duration or 
             self.tuplets != "" or 
             settings['rhythmAnnouncement'] == "everyNote")):
            
            rendered_elements.append(self.tuplets)
            if note_letter is not None:
                rendered_elements.append(render_colourful_output(self.duration, note_letter, "rhythm", settings))
            else:
                rendered_elements.append(self.duration)
            rendered_elements.append(self.endTuplets)

        # Add tie information if enabled
        if self.tie and settings.get('include_ties', True):
            rendered_elements.append(f"tie {self.tie}")

        return list(filter(None, rendered_elements))


class TSDynamic(TSEvent):
    """
    Represents a dynamic marking in a musical score (forte, piano, crescendo, etc.).
    
    Dynamic markings provide expression information and are rendered as
    bracketed text when dynamics are enabled in the settings.
    
    Attributes:
        short_name (str): Abbreviated dynamic name (f, p, mp, etc.)
        long_name (str): Full dynamic name (forte, piano, mezzo-piano, etc.)
    """

    def __init__(self, long_name=None, short_name=None):
        """
        Initialize a dynamic marking.
        
        Args:
            long_name (str): Full name of the dynamic
            short_name (str): Abbreviated name of the dynamic
        """
        super().__init__()
        if long_name is not None:
            self.long_name = long_name.capitalize()
        else:
            self.long_name = short_name
        self.short_name = short_name

    def render(self, settings, context=None):
        """
        Render the dynamic marking as bracketed text.
        
        Args:
            settings (dict): Configuration settings
            context (TSEvent): Previous event (unused for dynamics)
            
        Returns:
            list: Bracketed dynamic name if present, empty list otherwise
        """
        if self.long_name:
            return [f'[{self.long_name}]']
        return []


class TSPitch(TSEvent):
    """
    Represents pitch information for a musical note.
    
    This class handles the rendering of pitch names and octave information
    based on user preferences for pitch description style and octave announcement rules.
    
    Attributes:
        pitch_name (str): Formatted pitch name (e.g., "C sharp", "D flat")
        octave (str): Octave description (e.g., "high", "mid", "4")
        pitch_number (int): MIDI pitch number for interval calculations
        pitch_letter (str): Single letter pitch name (A-G) for color lookup
    """

    def __init__(self, pitch_name, octave, pitch_number, pitch_letter):
        """
        Initialize pitch information.
        
        Args:
            pitch_name (str): Human-readable pitch name
            octave (str): Octave description
            pitch_number (int): MIDI pitch number
            pitch_letter (str): Single letter pitch name
        """
        super().__init__()
        self.pitch_name = pitch_name
        self.octave = octave
        self.pitch_number = pitch_number
        self.pitch_letter = pitch_letter

    def render(self, settings, context=None):
        """
        Render pitch information with optional octave based on settings.
        
        Args:
            settings (dict): Configuration for pitch and octave rendering
            context (TSPitch): Previous pitch for octave announcement rules
            
        Returns:
            list: Rendered pitch and octave elements
        """
        rendered_elements = []
        
        # Position octave before or after pitch based on settings
        if settings['octavePosition'] == "before":
            rendered_elements.append(self.render_octave(settings, context))
        
        rendered_elements.append(render_colourful_output(self.pitch_name, self.pitch_letter, "pitch", settings))
        
        if settings['octavePosition'] == "after":
            rendered_elements.append(self.render_octave(settings, context))
        
        return list(filter(None, rendered_elements))

    def render_octave(self, settings, context=None):
        """
        Determine whether to render octave information based on announcement rules.
        
        Args:
            settings (dict): Configuration including octave announcement rules
            context (TSPitch): Previous pitch for comparison
            
        Returns:
            str: Octave description or empty string
        """
        show_octave = False
        
        if settings['octaveAnnouncement'] == "brailleRules":
            if context is None:
                show_octave = True
            else:
                pitch_difference = abs(context.pitch_number - self.pitch_number)
                if pitch_difference <= 4:
                    # 3rd or less - don't announce octave
                    show_octave = False
                elif 5 <= pitch_difference <= 7:
                    # 4th or 5th - announce if octave changes
                    show_octave = (context.octave != self.octave)
                else:
                    # More than 5th - always announce octave
                    show_octave = True
        elif settings['octaveAnnouncement'] == "everyNote":
            show_octave = True
        elif settings['octaveAnnouncement'] == "firstNote" and context is None:
            show_octave = True
        elif settings['octaveAnnouncement'] == "onChange":
            show_octave = (context is None or context.octave != self.octave)

        if show_octave:
            return render_colourful_output(self.octave, self.pitch_letter, "octave", settings)
        else:
            return ""


class TSUnpitched(TSEvent):
    """
    Represents an unpitched musical event (percussion, etc.).
    
    These events have duration but no specific pitch information.
    They are rendered with their duration followed by "unpitched".
    """

    def __init__(self):
        """Initialize an unpitched event."""
        super().__init__()
        self.pitch = None

    def render(self, settings, context=None):
        """
        Render unpitched event with duration and unpitched label.
        
        Args:
            settings (dict): Configuration settings
            context (TSEvent): Previous event for duration comparison
            
        Returns:
            list: Duration description followed by 'unpitched'
        """
        rendered_elements = []
        # Render the duration using parent class method
        rendered_elements.append(' '.join(super(TSUnpitched, self).render(settings, context)))
        # Add unpitched label
        rendered_elements.append(' unpitched')
        return rendered_elements


class TSRest(TSEvent):
    """
    Represents a rest (silence) in a musical score.
    
    Rests can be included or excluded from the description based on settings.
    When included, they are rendered with their duration followed by "rest".
    """

    def __init__(self):
        """Initialize a rest event."""
        super().__init__()
        self.pitch = None

    def render(self, settings, context=None):
        """
        Render rest with duration if rests are enabled in settings.
        
        Args:
            settings (dict): Configuration including rest inclusion preference
            context (TSEvent): Previous event for duration comparison
            
        Returns:
            list: Duration and 'rest' label, or empty list if rests disabled
        """
        if not settings.get('include_rests', True):
            return []

        rendered_elements = []
        rendered_elements.extend(super(TSRest, self).render(settings, context))
        rendered_elements.append('rest')
        
        return list(filter(None, rendered_elements))


class TSNote(TSEvent):
    """
    Represents a single musical note with pitch, duration, and optional expressions.
    
    Notes are the primary melodic elements and include pitch information,
    rhythm description, and any attached expressions like arpeggios.
    
    Attributes:
        pitch (TSPitch): Pitch information for this note
        expressions (list): List of musical expressions attached to this note
    """

    def __init__(self):
        """Initialize a musical note."""
        super().__init__()
        self.pitch = None
        self.expressions = []

    def render(self, settings, context=None):
        """
        Render note with expressions, duration, and pitch information.
        
        Args:
            settings (dict): Configuration for rendering various elements
            context (TSEvent): Previous event for comparison-based rendering
            
        Returns:
            list: Complete description including expressions, duration, and pitch
        """
        rendered_elements = []
        
        # Add musical expressions (like arpeggios)
        for expression in self.expressions:
            is_arpeggio = 'arpeggio' in expression.name.lower()
            if not is_arpeggio or (is_arpeggio and settings.get('include_arpeggios', True)):
                rendered_elements.append(expression.name)

        # Add duration information using parent class method
        rendered_elements.extend(super().render(settings, context, self.pitch.pitch_letter))
        
        # Add pitch information
        context_pitch = getattr(context, 'pitch', None) if context else None
        rendered_elements.extend(self.pitch.render(settings, context_pitch))
        
        return list(filter(None, rendered_elements))


class TSChord(TSEvent):
    """
    Represents a musical chord containing multiple simultaneous pitches.
    
    Chords can be announced as "X-note chord" and include all constituent
    pitches listed from lowest to highest with appropriate spacing.
    
    Attributes:
        pitches (list): List of TSPitch objects in the chord
    """

    def __init__(self):
        """Initialize a musical chord."""
        super().__init__()
        self.pitches = []

    def name(self):
        """
        Get the name of the chord (placeholder for future harmonic analysis).
        
        Returns:
            str: Empty string (chord naming not currently implemented)
        """
        return ''

    def render(self, settings, context=None):
        """
        Render chord with optional announcement and individual pitches.
        
        Args:
            settings (dict): Configuration for chord and pitch rendering
            context (TSEvent): Previous event for comparison-based rendering
            
        Returns:
            list: Chord description including size announcement and pitch list
        """
        rendered_elements = []
        
        # Add chord size announcement if enabled
        if settings.get('describe_chords', True):
            rendered_elements.append(f'{len(self.pitches)}-note chord')
        
        # Add duration information using parent class method
        rendered_elements.extend(super(TSChord, self).render(settings, context))
        
        # Add individual pitches sorted from lowest to highest
        previous_pitch = None
        for pitch in sorted(self.pitches, key=lambda ts_pitch: ts_pitch.pitch_number):
            rendered_elements.extend(pitch.render(settings, previous_pitch))
            previous_pitch = pitch
        
        return list(filter(None, rendered_elements))
class TalkingScoreBase(object, metaclass=ABCMeta):
    """
    Abstract base class defining the interface for talking score implementations.
    
    This class establishes the contract that all talking score implementations
    must follow, ensuring consistent access to basic musical information.
    """
    
    @abstractmethod
    def get_title(self):
        """
        Get the title of the musical work.
        
        Returns:
            str: Title of the musical work
        """
        pass

    @abstractmethod
    def get_composer(self):
        """
        Get the composer of the musical work.
        
        Returns:
            str: Name of the composer
        """
        pass


class Music21TalkingScore(TalkingScoreBase):
    """
    Main class for processing MusicXML files into talking scores using music21.
    
    This class handles parsing MusicXML files, extracting musical information,
    and providing methods to generate textual descriptions and MIDI files.
    It supports various customization options for describing rhythm, pitch,
    octave information, and other musical elements.
    
    The class maintains mappings for different description styles and handles
    the conversion between music21 objects and human-readable text.
    
    Attributes:
        filepath (str): Path to the source MusicXML file
        score (music21.Stream): Parsed musical score
        last_tempo_inserted_index (int): Tracking for tempo insertion in segments
        music_analyser (MusicAnalyser): Analysis component for pattern recognition
    """

    # Octave number to descriptive name mapping
    _OCTAVE_MAP = {
        1: 'bottom',
        2: 'lower', 
        3: 'low',
        4: 'mid',
        5: 'high',
        6: 'higher',
        7: 'top'
    }

    # Octave mapping for Figurenotes system
    _OCTAVE_FIGURENOTES_MAP = {
        1: 'bottom',
        2: 'cross',
        3: 'square',
        4: 'circle',
        5: 'triangle',
        6: 'higher',
        7: 'top'
    }

    # Dot count to descriptive text mapping
    _DOTS_MAP = {
        0: '',
        1: 'dotted ',
        2: 'double dotted ',
        3: 'triple dotted '
    }

    # American to British rhythm name conversion
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

    # Pitch name to Figurenotes color mapping
    _PITCH_FIGURENOTES_MAP = {
        'C': 'red',
        'D': 'brown',
        'E': 'grey',
        'F': 'blue',
        'G': 'black',
        'A': 'yellow',
        'B': 'green',
    }

    # Pitch name to phonetic alphabet mapping
    _PITCH_PHONETIC_MAP = {
        'C': 'charlie',
        'D': 'bravo',
        'E': 'echo',
        'F': 'foxtrot',
        'G': 'golf',
        'A': 'alpha',
        'B': 'bravo',
    }

    def __init__(self, musicxml_filepath):
        """
        Initialize a Music21TalkingScore from a MusicXML file.
        
        Args:
            musicxml_filepath (str): Path to the MusicXML file to process
            
        Raises:
            Music21Exception: If the file cannot be parsed
        """
        self.filepath = os.path.realpath(musicxml_filepath)
        self.score = converter.parse(musicxml_filepath)
        self.last_tempo_inserted_index = 0
        self.music_analyser = None
        super(Music21TalkingScore, self).__init__()

    def get_title(self):
        """
        Extract the title from the MusicXML file.
        
        First attempts to read from metadata, then falls back to searching
        for centered text boxes with large font sizes.
        
        Returns:
            str: Title of the musical work or error message
        """
        if self.score.metadata.title is not None:
            return self.score.metadata.title
            
        # Search for title in text boxes as fallback
        for text_box in self.score.flatten().getElementsByClass('TextBox'):
            # Check for text box attributes that suggest a title
            if (hasattr(text_box, 'justify') and text_box.justify == 'center' and
                hasattr(text_box, 'alignVertical') and text_box.alignVertical == 'top' and
                hasattr(text_box, 'size') and text_box.size > 18):
                return text_box.content
                
        return "Error reading title"

    def get_composer(self):
        """
        Extract the composer name from the MusicXML file.
        
        First attempts to read from metadata, then searches for right-aligned
        text boxes which often contain composer information.
        
        Returns:
            str: Name of the composer or "Unknown"
        """
        if self.score.metadata.composer is not None:
            return self.score.metadata.composer
            
        # Search for composer in right-aligned text boxes
        for text_box in self.score.getElementsByClass('TextBox'):
            if hasattr(text_box, 'style') and text_box.style.justify == 'right':
                return text_box.content
                
        return "Unknown"

    def get_initial_time_signature(self):
        """
        Get the initial time signature of the musical work.
        
        Returns:
            str: Human-readable time signature description
        """
        first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
        time_signatures = first_measure.getElementsByClass(meter.TimeSignature)
        
        initial_time_signature = None
        if len(time_signatures) > 0:
            initial_time_signature = time_signatures[0]
            
        return self.describe_time_signature(initial_time_signature)

    def describe_time_signature(self, time_signature):
        """
        Convert a time signature object to human-readable text.
        
        Args:
            time_signature (meter.TimeSignature): Time signature to describe
            
        Returns:
            str: Space-separated numerator and denominator or error message
        """
        if time_signature is not None:
            return " ".join(time_signature.ratioString.split("/"))
        else:
            return " error reading time signature...  "

    def get_initial_key_signature(self):
        """
        Get the initial key signature of the musical work.
        
        Returns:
            str: Human-readable key signature description
        """
        first_measure = self.score.parts[0].measures(1, 1)
        key_signatures = first_measure.flatten().getElementsByClass('KeySignature')
        
        if len(key_signatures) == 0:
            key_signature = key.KeySignature(0)  # No sharps or flats
        else:
            key_signature = key_signatures[0]
            
        return self.describe_key_signature(key_signature)

    def describe_key_signature(self, ks):
        """
        Enhanced key signature description with key name first, then details.
        Format: "B♭ major (5 flats: B♭, E♭, A♭, D♭, G♭)"
        """
        # Order of sharps and flats
        SHARPS_ORDER = ['F♯', 'C♯', 'G♯', 'D♯', 'A♯', 'E♯', 'B♯']
        FLATS_ORDER = ['B♭', 'E♭', 'A♭', 'D♭', 'G♭', 'C♭', 'F♭']
        
        # Major key names based on number of sharps/flats
        SHARP_KEYS = ['C', 'G', 'D', 'A', 'E', 'B', 'F♯', 'C♯']
        FLAT_KEYS = ['C', 'F', 'B♭', 'E♭', 'A♭', 'D♭', 'G♭', 'C♭']
        
        if ks.sharps == 0:
            return "C major (no sharps or flats)"
        elif ks.sharps > 0:
            # Sharps
            num_sharps = ks.sharps
            sharp_names = SHARPS_ORDER[:num_sharps]
            major_key = SHARP_KEYS[num_sharps]
            
            return f"{major_key} major ({num_sharps} sharp{'s' if num_sharps > 1 else ''}: {', '.join(sharp_names)})"
        else:
            # Flats
            num_flats = abs(ks.sharps)
            flat_names = FLATS_ORDER[:num_flats]
            major_key = FLAT_KEYS[num_flats]
            
            return f"{major_key} major ({num_flats} flat{'s' if num_flats > 1 else ''}: {', '.join(flat_names)})"

    def get_initial_text_expression(self):
        """
        Get the first text expression from the score (legacy method).
        
        This method was used to get initial tempo but MetronomeMarkBoundary
        is now preferred.
        
        Returns:
            str: Content of first text expression or None
        """
        first_measure = self.score.parts[0].measures(1, 1)
        text_expressions = first_measure.flatten().getElementsByClass('TextExpression')
        
        for text_expression in text_expressions:
            return text_expression.content
        return None

    def get_initial_tempo(self):
        """
        Get the initial tempo marking of the musical work.
        
        Returns:
            str: Human-readable tempo description
        """
        global settings
        
        # Ensure settings is initialized
        if settings is None:
            settings = {
                'dotPosition': "before",
                'rhythmDescription': "british"
            }
            
        tempo_boundaries = self.score.metronomeMarkBoundaries()
        if tempo_boundaries:
            return self.describe_tempo(tempo_boundaries[0][2])
        return "No tempo specified"

    def get_beat_division_options(self):
        """
        Analyze the time signature and return valid beat division options.
        
        This method examines the initial time signature and generates
        appropriate beat grouping options for the user interface.
        
        Returns:
            list: List of dictionaries with 'display' and 'value' keys
        """
        time_signature = None
        
        try:
            # Find time signature in the first measure
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            for item in first_measure:
                if isinstance(item, meter.TimeSignature):
                    time_signature = item
                    break
            
            # Fallback to score-level search
            if not time_signature:
                time_signature = self.score.getTimeSignatures()[0]
                
        except Exception as e:
            logger.error(f"Could not find TimeSignature in the score. Error: {e}")
            return []

        options = []
        seen_values = set()

        def add_option(display, value):
            """Helper function to add unique options."""
            if value not in seen_values:
                options.append({'display': display, 'value': value})
                seen_values.add(value)

        # 1. Continuous bar grouping option
        add_option('Group by Bar (continuous)', 'bar')

        # 2. Default music21 interpretation
        default_beat_string = self.map_duration(time_signature.beatDuration)
        default_display = f"{time_signature.beatCount} {default_beat_string} beats (Default)"
        default_value = f"{time_signature.beatCount}/{time_signature.beatDuration.quarterLength}"
        add_option(default_display, default_value)
        
        # 3. Face value interpretation (numerator/denominator)
        face_value_beat_string = self.map_duration(duration.Duration(1.0 / time_signature.denominator))
        face_value_display = f"{time_signature.numerator} {face_value_beat_string} beats"
        face_value_value = f"{time_signature.numerator}/{time_signature.denominator}"
        add_option(face_value_display, face_value_value)

        # 4. Compound meter interpretation (if applicable)
        if time_signature.numerator % 3 == 0 and time_signature.numerator > 3:
            compound_beat_count = time_signature.numerator / 3
            simple_beat_name = self.map_duration(duration.Duration(1.0 / time_signature.denominator))
            compound_beat_string = f"Dotted {simple_beat_name}"
            compound_display = f"{int(compound_beat_count)} {compound_beat_string} beats"
            compound_beat_duration_ql = (1.0 / time_signature.denominator) * 3
            compound_value = f"{int(compound_beat_count)}/{compound_beat_duration_ql}"
            add_option(compound_display, compound_value)

        return options

    @staticmethod
    def fix_tempo_number(tempo):
        """
        Ensure tempo has a valid number value for scaling operations.
        
        Some tempos have soundingNumber set but not number, which causes
        errors when trying to scale. This method provides a fallback.
        
        Args:
            tempo (tempo.MetronomeMark): Tempo marking to fix
            
        Returns:
            tempo.MetronomeMark: Tempo with valid number value
        """
        if tempo.number is None:
            if tempo.numberSounding is not None:
                tempo.number = tempo.numberSounding
            else:
                tempo.number = 120
                tempo.text = "Error - " + (tempo.text or "")
        return tempo

    def describe_tempo(self, tempo):
        """
        Convert a tempo marking to human-readable text.
        
        Args:
            tempo (tempo.MetronomeMark): Tempo marking to describe
            
        Returns:
            str: Formatted tempo description with BPM and beat unit
        """
        tempo = self.fix_tempo_number(tempo)
        tempo_text = ""
        
        if tempo.text is not None:
            tempo_text += f"{tempo.text} ({math.floor(tempo.number)} bpm @ {self.describe_tempo_referent(tempo)})"
        else:
            tempo_text += f"{math.floor(tempo.number)} bpm @ {self.describe_tempo_referent(tempo)}"
            
        return tempo_text

    def describe_tempo_referent(self, tempo):
        """
        Describe the beat unit for a tempo marking (e.g., "crotchet", "minim").
        
        Args:
            tempo (tempo.MetronomeMark): Tempo marking with referent
            
        Returns:
            str: Description of the beat unit including dots if present
        """
        global settings
        tempo_text = ""
        
        # Add dots before or after based on settings
        if settings['dotPosition'] == "before":
            tempo_text = self._DOTS_MAP.get(tempo.referent.dots, "")
            
        tempo_text += self.map_duration(tempo.referent)
        
        if settings['dotPosition'] == "after":
            tempo_text += " " + self._DOTS_MAP.get(tempo.referent.dots, "")

        return tempo_text

    def get_number_of_bars(self):
        """
        Get the total number of measures in the score.
        
        Returns:
            int: Number of measures in the first part
        """
        return len(self.score.parts[0].getElementsByClass('Measure'))
    def get_instruments(self):
        """
        Analyze the score to identify instruments and their parts.
        
        This method creates comprehensive mappings of instruments to parts,
        handling multi-staff instruments (like piano) and generating appropriate
        part names for display.
        
        Returns:
            list: List of instrument names for the options interface
        """
        # Initialize instrument tracking dictionaries
        self.part_instruments = {}  # {instrument_num: [name, first_part_index, part_count, part_id]}
        self.part_names = {}  # {part_index: part_name} for multi-part instruments
        instrument_names = []  # Unique instrument names for the interface
        
        instrument_count = 1
        
        for part_index, instrument in enumerate(self.score.flatten().getInstruments()):
            # Check if this is a new instrument or additional part of existing instrument
            is_new_instrument = (len(self.part_instruments) == 0 or 
                               self.part_instruments[instrument_count - 1][3] != instrument.partId)
            
            if is_new_instrument:
                # New instrument found
                instrument_name = instrument.partName or f"Instrument {instrument_count} (unnamed)"
                self.part_instruments[instrument_count] = [instrument_name, part_index, 1, instrument.partId]
                instrument_names.append(instrument_name)
                instrument_count += 1
            else:
                # Additional part for existing instrument
                self.part_instruments[instrument_count - 1][2] += 1
                self._assign_part_names(instrument_count - 1, part_index)

        logger.debug(f"Part instruments = {self.part_instruments}")
        logger.debug(f"Part names = {self.part_names}")
        logger.debug(f"Instrument names = {instrument_names}")
        
        return instrument_names

    def _assign_part_names(self, instrument_index, current_part_index):
        """
        Assign descriptive names to parts within multi-part instruments.
        
        Args:
            instrument_index (int): Index of the instrument (1-based)
            current_part_index (int): Index of the current part (0-based)
        """
        part_count = self.part_instruments[instrument_index][2]
        first_part_index = self.part_instruments[instrument_index][1]
        
        if part_count == 2:
            # Two parts: typically "Right hand" and "Left hand" for piano
            self.part_names[first_part_index] = "Right hand"
            self.part_names[current_part_index] = "Left hand"
        elif part_count == 3:
            # Three parts: number them
            self.part_names[first_part_index] = "Part 1"
            self.part_names[first_part_index + 1] = "Part 2"
            self.part_names[current_part_index] = "Part 3"
        else:
            # More than three parts: use part numbers
            self.part_names[current_part_index] = f"Part {part_count}"

    def compare_parts_with_selected_instruments(self):
        """
        Compare available instruments with user selections and calculate binary flags.
        
        This method processes the user's instrument selections and creates
        binary representations for MIDI generation, while also applying
        smart logic to hide redundant playback options in the interface.
        """
        global settings
        
        # Initialize selection tracking
        self.selected_instruments = []  # 1-based list of selected instrument numbers
        self.unselected_instruments = []  # 1-based list of unselected instrument numbers
        self.binary_selected_instruments = 1  # Binary representation for MIDI URLs
        self.selected_part_names = []  # Display names for selected parts

        # Process each instrument to determine selection status
        for instrument_num in self.part_instruments.keys():
            self.binary_selected_instruments = self.binary_selected_instruments << 1
            
            if instrument_num in settings.get('instruments', []):
                self.selected_instruments.append(instrument_num)
                self.binary_selected_instruments += 1
            else:
                self.unselected_instruments.append(instrument_num)

        # Generate display names for selected parts
        for instrument_num in self.selected_instruments:
            self._add_selected_part_names(instrument_num)

        # Store original user choices for URL generation
        play_all_choice = settings.get('playAll', False)
        play_selected_choice = settings.get('playSelected', False)
        play_unselected_choice = settings.get('playUnselected', False)

        # Apply smart logic to hide redundant interface options
        self._apply_smart_playback_logic()

        # Calculate binary flags for MIDI URLs based on original choices
        self.binary_play_all = self._calculate_binary_play_flags(
            play_all_choice, play_selected_choice, play_unselected_choice
        )

        logger.debug(f"Selected part names = {self.selected_part_names}")
        logger.debug(f"Selected instruments = {self.selected_instruments}")

    def _add_selected_part_names(self, instrument_num):
        """
        Add display names for parts of a selected instrument.
        
        Args:
            instrument_num (int): 1-based instrument number
        """
        instrument_info = self.part_instruments[instrument_num]
        instrument_name = instrument_info[0]
        first_part_index = instrument_info[1]
        part_count = instrument_info[2]

        if part_count == 1:
            # Single-part instrument
            self.selected_part_names.append(instrument_name)
        else:
            # Multi-part instrument
            for part_offset in range(part_count):
                part_index = first_part_index + part_offset
                part_name = self.part_names[part_index]
                self.selected_part_names.append(f"{instrument_name} - {part_name}")

    def _apply_smart_playback_logic(self):
        """
        Apply logic to hide redundant playback options in the interface.
        """
        global settings
        
        # Hide redundant options for single instruments
        if len(self.part_instruments) == 1:
            settings['playAll'] = False
            settings['playSelected'] = False
        
        # Hide unselected option if no unselected instruments
        if len(self.unselected_instruments) == 0:
            settings['playUnselected'] = False
            
        # Hide selected option if all instruments are selected and playAll is enabled
        if (len(self.selected_instruments) == len(self.part_instruments) and 
            settings.get('playAll', False)):
            settings['playSelected'] = False
            
        # Hide selected option for single selected instrument
        if len(self.selected_instruments) == 1:
            settings['playSelected'] = False

    def _calculate_binary_play_flags(self, play_all, play_selected, play_unselected):
        """
        Calculate binary representation of playback options for MIDI URLs.
        
        Args:
            play_all (bool): Whether to include "play all" option
            play_selected (bool): Whether to include "play selected" option  
            play_unselected (bool): Whether to include "play unselected" option
            
        Returns:
            int: Binary representation of playback flags
        """
        binary_flags = 1  # Start with placeholder bit
        
        # Add flags in order: all, selected, unselected
        binary_flags = (binary_flags << 1) + (1 if play_all else 0)
        binary_flags = (binary_flags << 1) + (1 if play_selected else 0)
        binary_flags = (binary_flags << 1) + (1 if play_unselected else 0)
        
        return binary_flags

    def get_number_of_parts(self):
        """
        Get the total number of parts across all instruments.
        
        Returns:
            int: Total number of parts in the score
        """
        self.get_instruments()
        return len(self.part_instruments)

    def get_bar_range(self, range_start, range_end):
        """
        Extract measures within a specified range from all parts.
        
        Args:
            range_start (int): Starting measure number
            range_end (int): Ending measure number
            
        Returns:
            dict: {part_id: [measures]} mapping for the specified range
        """
        measures = self.score.measures(range_start, range_end)
        bars_for_parts = {}
        
        for part in measures.parts:
            part_measures = part.getElementsByClass('Measure')
            bars_for_parts.setdefault(part.id, []).extend(part_measures)

        return bars_for_parts

    def get_events_for_bar_range(self, start_bar, end_bar, part_index):
        """
        Extract and organize musical events for a specific bar range and part.
        
        This method processes measures to create a nested structure of events
        organized by bar number, time offset, and voice for template rendering.
        
        Args:
            start_bar (int): Starting bar number (inclusive)
            end_bar (int): Ending bar number (inclusive)
            part_index (int): Zero-based part index
            
        Returns:
            dict: {bar_num: [time_points]} where time_points contain event data
        """
        # Initialize intermediate structure for event collection
        intermediate_events = {}

        # Get measures for the specified range
        measures = self.score.parts[part_index].measures(start_bar, end_bar)
        
        # Ensure time signature is available in first measure if missing
        first_measure = measures.measure(start_bar)
        if (first_measure is not None and 
            len(first_measure.getElementsByClass(meter.TimeSignature)) == 0):
            first_measure.insert(0, self.time_signatures[start_bar])

        logger.info(f'Processing part {part_index} - bars {start_bar} to {end_bar}')

        # Process each measure to collect events
        for bar_number in range(start_bar, end_bar + 1):
            measure = measures.measure(bar_number)
            if measure is not None:
                self.update_events_for_measure(measure, intermediate_events)
        
        # Process dynamics spanners if enabled
        if settings.get('include_dynamics', True):
            self._process_dynamic_spanners(part_index, start_bar, end_bar, intermediate_events)

        # Convert intermediate structure to final template-friendly format
        return self._convert_to_final_events_structure(intermediate_events, start_bar, end_bar)

    def _process_dynamic_spanners(self, part_index, start_bar, end_bar, intermediate_events):
        """
        Process dynamic spanners (crescendo, diminuendo) within the bar range.
        
        Args:
            part_index (int): Part index to process
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            intermediate_events (dict): Event collection to update
        """
        for spanner in self.score.parts[part_index].spanners.elements:
            first_element = spanner.getFirst()
            last_element = spanner.getLast()

            # Skip spanners without measure numbers
            if (first_element.measureNumber is None or 
                last_element.measureNumber is None):
                continue

            # Only process spanners that overlap with current segment
            if (first_element.measureNumber <= end_bar and 
                last_element.measureNumber >= start_bar):
                
                spanner_type = type(spanner).__name__
                if spanner_type in ['Crescendo', 'Diminuendo']:
                    self._add_spanner_events(spanner, spanner_type, first_element, 
                                           last_element, start_bar, end_bar, intermediate_events)

    def _add_spanner_events(self, spanner, spanner_type, first_element, last_element,
                           start_bar, end_bar, intermediate_events):
        """
        Add start and end events for a dynamic spanner.
        
        Args:
            spanner: The dynamic spanner object
            spanner_type (str): Type of spanner ('Crescendo' or 'Diminuendo')
            first_element: First element of the spanner
            last_element: Last element of the spanner
            start_bar (int): Starting bar of the segment
            end_bar (int): Ending bar of the segment
            intermediate_events (dict): Event collection to update
        """
        # Add spanner start event
        if first_element.measureNumber >= start_bar:
            start_event = TSDynamic(long_name=f'{spanner_type} Start')
            start_event.start_offset = first_element.offset
            start_event.beat = first_element.beat
            
            measure_events = intermediate_events.setdefault(first_element.measureNumber, {})
            offset_events = measure_events.setdefault(first_element.offset, {})
            voice_events = offset_events.setdefault(1, [])
            voice_events.append(start_event)
        
        # Add spanner end event
        if last_element.measureNumber <= end_bar:
            end_event = TSDynamic(long_name=f'{spanner_type} End')
            end_event.start_offset = last_element.offset + last_element.duration.quarterLength
            end_event.beat = last_element.beat + last_element.duration.quarterLength
            
            measure_events = intermediate_events.setdefault(last_element.measureNumber, {})
            offset_events = measure_events.setdefault(end_event.start_offset, {})
            voice_events = offset_events.setdefault(1, [])
            voice_events.append(end_event)

    def _convert_to_final_events_structure(self, intermediate_events, start_bar, end_bar):
        """
        Convert intermediate event structure to final template-friendly format.
        
        Args:
            intermediate_events (dict): Raw event data organized by bar/offset/voice
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            
        Returns:
            dict: {bar_num: [time_points]} formatted for template rendering
        """
        final_events_by_bar = {}
        
        # Process only the requested bar range to prevent data leakage
        for bar_num in range(start_bar, end_bar + 1):
            if bar_num in intermediate_events:
                time_points_data = intermediate_events[bar_num]
                sorted_time_points = []
                
                # Sort time points by offset and create template structure
                for offset, voices in sorted(time_points_data.items()):
                    # Get beat information from first event for display
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
        Process all musical elements in a measure and add them to the events structure.
        
        This method handles the conversion of music21 objects (notes, chords, rests, etc.)
        into TSEvent objects organized by measure, offset, and voice.
        
        Args:
            measure_stream (music21.Stream): Measure or voice to process
            events (dict): Event collection to update {bar: {offset: {voice: [events]}}}
            voice (int): Voice number for this stream (default: 1)
            state (dict): Pitch state for accidental tracking (default: None)
        """
        if state is None:
            state = {}

        for element in measure_stream.elements:
            element_type = type(element).__name__
            event = None
            
            # Process different element types
            if element_type == 'Note':
                event = self._process_note_element(element, state)
            elif element_type == 'Rest':
                event = TSRest()
            elif element_type == 'Chord':
                event = self._process_chord_element(element)
            elif element_type == 'Dynamic':
                # Only create dynamic events if dynamics are enabled
                if settings.get('include_dynamics', True):
                    event = TSDynamic(long_name=element.longName, short_name=element.value)
            elif element_type == 'Voice':
                # Recursively process voice contents
                self.update_events_for_measure(element, events, int(element.id), state=state)
                continue
            
            # Skip if no event was created
            if event is None:
                continue

            # Set common event properties
            event.start_offset = element.offset
            event.beat = element.beat
            
            # Process duration and tuplets
            self._process_duration_and_tuplets(event, element)
            
            # Add event to the events structure
            measure_events = events.setdefault(measure_stream.measureNumber, {})
            offset_events = measure_events.setdefault(element.offset, {})
            voice_events = offset_events.setdefault(voice, [])
            voice_events.append(event)

    def _process_note_element(self, note_element, state):
        """
        Convert a music21 Note to a TSNote with pitch and expression information.
        
        Args:
            note_element (music21.Note): Note element to process
            state (dict): Pitch state for accidental tracking
            
        Returns:
            TSNote: Processed note event
        """
        event = TSNote()
        
        # Create pitch information
        pitch_name = self.map_pitch(note_element.pitch, state)
        event.pitch = TSPitch(
            pitch_name,
            self.map_octave(note_element.pitch.octave),
            note_element.pitch.ps,
            note_element.pitch.name[0]
        )
        
        # Add tie information if present
        if note_element.tie:
            event.tie = note_element.tie.type
            
        # Copy expressions (arpeggios, etc.)
        event.expressions = note_element.expressions
        
        return event

    def _process_chord_element(self, chord_element):
        """
        Convert a music21 Chord to a TSChord with multiple pitches.
        
        Args:
            chord_element (music21.Chord): Chord element to process
            
        Returns:
            TSChord: Processed chord event
        """
        event = TSChord()
        chord_pitches = []
        
        # Process each pitch in the chord
        for pitch in chord_element.pitches:
            pitch_name = self.map_pitch(pitch, {})  # Empty state for chords
            chord_pitches.append(TSPitch(
                pitch_name,
                self.map_octave(pitch.octave),
                pitch.ps,
                pitch.name[0]
            ))
        
        event.pitches = chord_pitches
        
        # Add tie information if present
        if chord_element.tie:
            event.tie = chord_element.tie.type
            
        return event

    def _process_duration_and_tuplets(self, event, element):
        """
        Process duration and tuplet information for a musical event.
        
        Args:
            event (TSEvent): Event to update with duration information
            element (music21.Music21Object): Source element with duration
        """
        event.duration = ""
        
        # Process tuplets
        if len(element.duration.tuplets) > 0:
            tuplet = element.duration.tuplets[0]
            if tuplet.type == "start":
                if tuplet.fullName == "Triplet":
                    event.tuplets = "triplets "
                else:
                    event.tuplets = f"{tuplet.fullName} ({tuplet.tupletActual[0]} in {tuplet.tupletNormal[0]}) "
            elif tuplet.type == "stop" and tuplet.fullName != "Triplet":
                event.endTuplets = "end tuplet "

        # Process duration with dots
        if settings['dotPosition'] == "before":
            event.duration += self.map_dots(element.duration.dots)
        
        event.duration += self.map_duration(element.duration)
        
        if settings['dotPosition'] == "after":
            event.duration += " " + self.map_dots(element.duration.dots)

    def group_chord_pitches_by_octave(self, chord):
        """
        Group chord pitches by their octave for analysis (legacy method).
        
        Args:
            chord (music21.Chord): Chord to analyze
            
        Returns:
            dict: {octave_description: [pitch_names]}
        """
        chord_pitches_by_octave = {}
        
        for pitch in chord.pitches:
            octave_desc = self._OCTAVE_MAP.get(str(pitch.octave), '?')
            pitch_list = chord_pitches_by_octave.setdefault(octave_desc, [])
            pitch_list.append(pitch.name)

        return chord_pitches_by_octave

    def generate_midi_filename_sel(self, base_url, range_start=None, range_end=None, sel=""):
        """
        Generate a MIDI URL for a selection of parts (all, selected, unselected).
        
        Args:
            base_url (str): Base URL for MIDI generation
            range_start (int): Starting bar number (optional)
            range_end (int): Ending bar number (optional)
            sel (str): Selection type ("all", "sel", "un")
            
        Returns:
            str: Complete MIDI URL with query parameters
        """
        # Build query parameters including binary selection indicators
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
            instrument (int): 1-based instrument number
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            
        Returns:
            list: List of event descriptions for each part of the instrument
        """
        part_descriptions = []
        instrument_info = self.part_instruments[instrument]
        first_part_index = instrument_info[1]
        part_count = instrument_info[2]
        
        # Generate descriptions for each part of the instrument
        for part_offset in range(part_count):
            part_index = first_part_index + part_offset
            events = self.get_events_for_bar_range(start_bar, end_bar, part_index)
            part_descriptions.append(events)

        return part_descriptions

    def generate_midi_filenames(self, base_url, range_start=None, range_end=None, add_instruments=[]):
        """
        Generate MIDI URLs for a specific instrument and its constituent parts.
        
        Args:
            base_url (str): Base URL for MIDI generation
            range_start (int): Starting bar number (optional)
            range_end (int): Ending bar number (optional)
            add_instruments (list): List of instrument numbers to include
            
        Returns:
            tuple: (instrument_midi_url, [part_midi_urls])
        """
        part_midis = []
        instrument_midi = ""
        last_instrument = add_instruments[-1] if add_instruments else None

        # Base query string with binary indicators
        query_string = f"bsi={self.binary_selected_instruments}&bpi={self.binary_play_all}"
        if range_start is not None:
            query_string += f"&start={range_start}&end={range_end}"

        # Generate URLs for individual parts
        for instrument_num in add_instruments:
            instrument_info = self.part_instruments[instrument_num]
            if instrument_info[2] > 1:  # Multi-part instrument
                first_part_index = instrument_info[1]
                part_count = instrument_info[2]
                
                for part_offset in range(part_count):
                    part_index = first_part_index + part_offset
                    part_url = f"{base_url}?part={part_index}&{query_string}"
                    part_midis.append(part_url)

        # Generate the URL for the whole instrument
        if last_instrument is not None:
            instrument_midi = f"{base_url}?ins={last_instrument}&{query_string}"

        return (instrument_midi, part_midis)

    def generate_midi_for_instruments(self, prefix, range_start=None, range_end=None, 
                                    add_instruments=[], output_path="", postfix_filename=""):
        """
        Generate MIDI files for specified instruments (legacy file-based method).
        
        This method creates actual MIDI files on disk. It's being phased out
        in favor of on-demand MIDI generation via URLs.
        
        Args:
            prefix (str): URL prefix for MIDI files
            range_start (int): Starting bar number (optional)
            range_end (int): Ending bar number (optional)
            add_instruments (list): List of instrument numbers to include
            output_path (str): Directory for output files
            postfix_filename (str): Suffix for filenames
            
        Returns:
            tuple: (main_midi_filename, [part_midi_filenames])
        """
        part_midis = []
        score_stream = stream.Score(id='temp')

        if range_start is None and range_end is None:
            # Generate full score MIDI
            for instrument_num in add_instruments:
                instrument_info = self.part_instruments[instrument_num]
                first_part_index = instrument_info[1]
                part_count = instrument_info[2]
                
                for part_offset in range(part_count):
                    part_index = first_part_index + part_offset
                    score_stream.insert(self.score.parts[part_index])
                    
                    if part_count > 1:
                        part_midi = self.generate_midi_parts_for_instrument(
                            range_start, range_end, instrument_num, part_offset, 
                            output_path, postfix_filename
                        )
                        part_midis.append(part_midi)
        else:
            # Generate segment MIDI
            postfix_filename += f"_{range_start}_{range_end}"
            
            for instrument_num in add_instruments:
                instrument_info = self.part_instruments[instrument_num]
                first_part_index = instrument_info[1]
                part_count = instrument_info[2]
                is_first_part = True
                
                for part_offset in range(part_count):
                    part_index = first_part_index + part_offset
                    
                    if part_count > 1:
                        part_midi = self.generate_midi_parts_for_instrument(
                            range_start, range_end, instrument_num, part_offset,
                            output_path, postfix_filename
                        )
                        part_midis.append(part_midi)
                    
                    # Extract measures with necessary musical context
                    part_measures = self.score.parts[part_index].measures(
                        range_start, range_end,
                        collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                    )
                    
                    # Insert tempos if not from part 0 (which already has them)
                    if is_first_part and part_index != 0:
                        start_offset = self.score.parts[0].measure(range_start).offset
                        self.insert_tempos(part_measures, start_offset)
                        is_first_part = False

                    # Remove repeat marks to avoid expansion errors
                    for measure in part_measures.getElementsByClass('Measure'):
                        measure.removeByClass('Repeat')
                    
                    score_stream.insert(part_measures)

        # Generate the main MIDI file
        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}.mid")
        
        if not os.path.exists(midi_filename):
            score_stream.write('midi', midi_filename)
        
        # Convert part file paths to URLs
        part_midis = [prefix + os.path.basename(midi_path) for midi_path in part_midis]
        
        return (prefix + os.path.basename(midi_filename), part_midis)

    def generate_midi_parts_for_instrument(self, range_start=None, range_end=None, 
                                         instrument=0, part=0, output_path="", postfix_filename=""):
        """
        Generate MIDI file for a specific part of an instrument (legacy method).
        
        Args:
            range_start (int): Starting bar number (optional)
            range_end (int): Ending bar number (optional)
            instrument (int): Instrument number (0-based in this context)
            part (int): Part number within the instrument (0-based)
            output_path (str): Directory for output files
            postfix_filename (str): Suffix for filename
            
        Returns:
            str: Path to generated MIDI file
        """
        score_stream = stream.Score(id='temp')
        
        if range_start is None and range_end is None:
            # Full score for this part
            part_index = self.part_instruments[instrument][1] + part
            score_stream.insert(self.score.parts[part_index])
            
            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{part + 1}.mid")
            
            if not os.path.exists(midi_filename):
                score_stream.write('midi', midi_filename)
        else:
            # Specific measures for this part
            postfix_filename += f"_{range_start}_{range_end}"
            part_index = self.part_instruments[instrument][1] + part
            
            logger.debug(f"Generating MIDI for instrument {instrument} part {part} (part_index {part_index})")
            
            part_measures = self.score.parts[part_index].measures(
                range_start, range_end,
                collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
            )
            
            # Insert tempos if not from part 0
            if part_index != 0:
                start_offset = self.score.parts[0].measure(range_start).offset
                self.insert_tempos(part_measures, start_offset)

            # Remove repeat marks to avoid expansion errors
            for measure in part_measures.getElementsByClass('Measure'):
                measure.removeByClass('Repeat')
            
            score_stream.insert(part_measures)

            base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{part + 1}.mid")
            
            if not os.path.exists(midi_filename):
                score_stream.write('midi', midi_filename)
        
        return midi_filename

    def generate_midi_for_part_range(self, range_start=None, range_end=None, 
                                   parts=[], output_path=""):
        """
        Generate MIDI file for a range of parts (legacy method).
        
        Args:
            range_start (int): Starting bar number (optional)
            range_end (int): Ending bar number (optional)
            parts (list): List of part IDs to include
            output_path (str): Directory for output files
            
        Returns:
            str: Path to generated MIDI file or None
        """
        base_filename = os.path.splitext(os.path.basename(self.filepath))[0]
        
        if range_start is None and range_end is None:
            # Export the whole score
            midi_filename = os.path.join(output_path, f"{base_filename}.mid")
            if not os.path.exists(midi_filename):
                self.score.write('midi', midi_filename)
            return midi_filename
            
        elif len(parts) > 0:
            # Individual parts
            for part in self.score.parts:
                if part.id not in parts:
                    continue

                midi_filename = os.path.join(output_path, f"{base_filename}_p{part.id}_{range_start}_{range_end}.mid")
                
                if not os.path.exists(midi_filename):
                    midi_stream = part.measures(
                        range_start, range_end,
                        collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                    )
                    
                    # Insert tempos if not from part 0
                    if part != self.score.parts[0]:
                        start_offset = self.score.parts[0].measure(range_start).offset
                        self.insert_tempos(midi_stream, start_offset)
                    
                    # Remove repeat marks
                    for measure in midi_stream.getElementsByClass('Measure'):
                        measure.removeByClass('Repeat')
                    
                    midi_stream.write('midi', midi_filename)
                
                return midi_filename
        else:
            # All parts for the range
            midi_filename = os.path.join(output_path, f"{base_filename}_{range_start}_{range_end}.mid")
            
            if not os.path.exists(midi_filename):
                midi_stream = self.score.measures(
                    range_start, range_end,
                    collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')
                )
                
                # Remove repeat marks from all parts
                for part in midi_stream.getElementsByClass('Part'):
                    for measure in part.getElementsByClass('Measure'):
                        measure.removeByClass('Repeat')
                
                midi_stream.write('midi', midi_filename)
            
            return midi_filename

        return None

    def insert_tempos(self, stream, offset_start):
        """
        Insert tempo markings into a stream that doesn't have them.
        
        This method is used when generating MIDI for individual parts,
        since only part 0 typically contains tempo information.
        
        Args:
            stream (music21.Stream): Stream to insert tempos into
            offset_start (float): Starting offset for the stream
        """
        # Optimize by starting from the last inserted tempo
        if self.last_tempo_inserted_index > 0:
            self.last_tempo_inserted_index -= 1
        
        tempo_boundaries = self.score.metronomeMarkBoundaries()
        
        for tempo_info in tempo_boundaries[self.last_tempo_inserted_index:]:
            tempo_start_offset = tempo_info[0]
            tempo_end_offset = tempo_info[1]
            tempo_mark = tempo_info[2]
            
            # Skip tempos that start after the stream ends
            if tempo_start_offset >= offset_start + stream.duration.quarterLength:
                return
            
            # Process tempos that affect this stream
            if tempo_end_offset > offset_start:
                if tempo_start_offset <= offset_start:
                    # Tempo starts before stream, insert at beginning
                    stream.insert(0, tempo.MetronomeMark(number=tempo_mark.number))
                    self.last_tempo_inserted_index += 1
                else:
                    # Tempo starts during stream, insert at appropriate offset
                    insert_offset = tempo_start_offset - offset_start
                    stream.insert(insert_offset, tempo.MetronomeMark(number=tempo_mark.number))
                    self.last_tempo_inserted_index += 1
    def map_octave(self, octave):
        """
        Convert octave number to descriptive text based on settings.
        
        Args:
            octave (int): Octave number (1-7)
            
        Returns:
            str: Descriptive octave text or empty string
        """
        global settings
        
        octave_description_mode = settings['octaveDescription']
        
        if octave_description_mode == "figureNotes":
            return self._OCTAVE_FIGURENOTES_MAP.get(octave, "?")
        elif octave_description_mode == "name":
            return self._OCTAVE_MAP.get(octave, "?")
        elif octave_description_mode == "none":
            return ""
        elif octave_description_mode == "number":
            return str(octave)
        
        return self._OCTAVE_MAP.get(octave, "?")

    def map_pitch(self, pitch, state):
        """
        Convert pitch to descriptive text based on settings and accidental handling.
        
        Args:
            pitch (music21.Pitch): Pitch object to convert
            state (dict): State tracking for accidental display rules
            
        Returns:
            str: Formatted pitch name with appropriate accidentals
        """
        global settings
        mode = settings.get('key_signature_accidentals', 'applied')
        #Enharmonic conversion
        if settings.get('enharmonic_conversion', False):
            pitch = self._convert_to_enharmonic_equivalent(pitch)

    
        
        # Determine the base pitch name based on description style
        if settings['pitchDescription'] == "colourNotes":
            base_name = self._PITCH_FIGURENOTES_MAP.get(pitch.step, "?")
        elif settings['pitchDescription'] == "phonetic":
            base_name = self._PITCH_PHONETIC_MAP.get(pitch.step, "?")
        elif settings['pitchDescription'] == 'noteName':
            base_name = pitch.step
        else:  # 'none' or other
            base_name = ''

        # Handle accidentals if present
        if not pitch.accidental:
            return base_name

        # Determine if accidental should be shown based on mode
        show_accidental = False
        
        if mode == 'applied':
            # Show sharps/flats but never naturals (per user request)
            if pitch.accidental.name != 'natural':
                show_accidental = True
        elif mode == 'standard':
            # Show only accidentals explicitly displayed on the page
            if pitch.accidental.displayStatus:
                show_accidental = True
        elif mode == 'onChange':
            # Show accidentals when they differ from the last occurrence
            current_alter = pitch.alter
            step = pitch.step
            last_seen_alter = state.get(step)
            
            if last_seen_alter is None or current_alter != last_seen_alter:
                state[step] = current_alter
                show_accidental = True
        
        if not show_accidental:
            return base_name

        # Format the accidental based on style preference
        accidental_style = settings.get('accidental_style', 'words')
        
        if accidental_style == 'symbols':
            symbol_map = {
                'sharp': '♯',
                'flat': '♭',
                'natural': '♮',
                'double-sharp': '𝄪',
                'double-flat': '♭♭'
            }
            accidental_text = symbol_map.get(pitch.accidental.name, '')
            return f"{base_name}{accidental_text}"
        else:  # 'words' style
            accidental_text = pitch.accidental.fullName
            return f"{base_name} {accidental_text}"
    def _convert_to_enharmonic_equivalent(self, pitch):
        """
        Streamlined enharmonic conversion - check for double accidentals first,
        then only check B, C, E, F for single accidentals.
        
        Args:
            pitch: music21 Pitch object
            
        Returns:
            music21 Pitch object with simplified accidental
        """
        from music21 import pitch as pitch21
        
        if not pitch.accidental:
            return pitch
        
        step = pitch.step
        accidental_name = pitch.accidental.name
        
        # STEP 1: Check for double accidentals first (any note can have these)
        if accidental_name == 'double-sharp':
            # All double sharps can be simplified
            double_sharp_map = {
                'F': 'G', 'C': 'D', 'G': 'A', 'D': 'E', 'A': 'B', 'E': 'F#', 'B': 'C#'
            }
            if step in double_sharp_map:
                try:
                    new_pitch = pitch21.Pitch(double_sharp_map[step])
                    new_pitch.octave = pitch.octave
                    return new_pitch
                except Exception:
                    return pitch
                    
        elif accidental_name == 'double-flat':
            # All double flats can be simplified
            double_flat_map = {
                'B': 'A', 'E': 'D', 'A': 'G', 'D': 'C', 'G': 'F', 'C': 'Bb', 'F': 'Eb'
            }
            if step in double_flat_map:
                try:
                    new_pitch = pitch21.Pitch(double_flat_map[step])
                    new_pitch.octave = pitch.octave
                    return new_pitch
                except Exception:
                    return pitch
        
        # STEP 2: Only check B, C, E, F for single accidentals (the only ones that can be simplified)
        elif step in ['B', 'C', 'E', 'F']:
            if step == 'E' and accidental_name == 'sharp':
                # E♯ → F
                try:
                    new_pitch = pitch21.Pitch('F')
                    new_pitch.octave = pitch.octave
                    return new_pitch
                except Exception:
                    return pitch
                    
            elif step == 'B' and accidental_name == 'sharp':
                # B♯ → C
                try:
                    new_pitch = pitch21.Pitch('C')
                    new_pitch.octave = pitch.octave
                    return new_pitch
                except Exception:
                    return pitch
                    
            elif step == 'C' and accidental_name == 'flat':
                # C♭ → B
                try:
                    new_pitch = pitch21.Pitch('B')
                    new_pitch.octave = pitch.octave - 1  # C♭4 becomes B3
                    return new_pitch
                except Exception:
                    return pitch
                    
            elif step == 'F' and accidental_name == 'flat':
                # F♭ → E
                try:
                    new_pitch = pitch21.Pitch('E')
                    new_pitch.octave = pitch.octave
                    return new_pitch
                except Exception:
                    return pitch
        
        # No conversion needed/possible
        return pitch

    def map_duration(self, duration):
        """
        Convert duration to descriptive text based on rhythm description setting.
        
        Args:
            duration (music21.Duration): Duration object to convert
            
        Returns:
            str: Descriptive duration text or empty string
        """
        global settings
        rhythm_description_mode = settings['rhythmDescription']
        
        if rhythm_description_mode == "american":
            return duration.type
        elif rhythm_description_mode == "british":
            return self._DURATION_MAP.get(duration.type, f'Unknown duration {duration.type}')
        elif rhythm_description_mode == "none":
            return ""
        
        return duration.type

    def map_dots(self, dots):
        """
        Convert dot count to descriptive text.
        
        Args:
            dots (int): Number of dots on the note
            
        Returns:
            str: Descriptive dot text or empty string
        """
        global settings
        
        if settings['rhythmDescription'] == "none":
            return ""
        else:
            return self._DOTS_MAP.get(dots, "")
        
    def get_rhythm_range(self):
        """
        Find all unique rhythm types present in the score.
        
        This method scans the entire score to identify which rhythm types
        are actually used, independent of user settings.
        
        Returns:
            list: Sorted list of British English rhythm names found in the score
        """
        valid_rhythm_types = self._DURATION_MAP.keys()
        found_rhythms = set()

        # Scan all notes and rests in the score
        for musical_element in self.score.flatten().notesAndRests:
            if musical_element.duration.type in valid_rhythm_types:
                british_name = self._DURATION_MAP[musical_element.duration.type]
                found_rhythms.add(british_name)
        
        # Sort based on the order in the duration map (longest to shortest)
        rhythm_order = list(self._DURATION_MAP.values())
        return sorted(list(found_rhythms), key=lambda r: rhythm_order.index(r))

    def get_octave_range(self):
        """
        Find the highest and lowest octaves used in the score.
        
        This method correctly handles both individual notes and chords
        to determine the full octave range of the musical work.
        
        Returns:
            dict: {'min': lowest_octave, 'max': highest_octave}
        """
        all_octaves = []
        
        # Iterate through all musical elements that have pitch
        for element in self.score.flatten().notes:
            if 'Chord' in element.classes:
                # For chords, collect octaves from all pitches
                for pitch in element.pitches:
                    all_octaves.append(pitch.octave)
            elif 'Note' in element.classes:
                # For single notes, collect the octave
                all_octaves.append(element.pitch.octave)
        
        if not all_octaves:
            return {'min': 0, 'max': 0}
        
        return {'min': min(all_octaves), 'max': max(all_octaves)}


class HTMLTalkingScoreFormatter():
    """
    Formats a Music21TalkingScore into HTML with embedded audio controls.
    
    This class handles the complete generation of talking score HTML,
    including loading user options, generating musical segments,
    and creating the final formatted output with navigation and audio controls.
    
    The formatter supports various customization options and can generate
    both full scores and segmented portions with synchronized MIDI playback.
    
    Attributes:
        score (Music21TalkingScore): The musical score to format
        options (dict): User preferences loaded from options file
        music_analyser (MusicAnalyser): Analysis component for pattern recognition
        time_signatures (dict): Time signature cache for segment processing
        time_and_keys (dict): Time/key change information for display
    """

    def __init__(self, talking_score):
        """
        Initialize the formatter with a talking score and load user options.
        
        Args:
            talking_score (Music21TalkingScore): Score to format
        """
        global settings
        self.score = talking_score
        self.options = {}

        # Load user options from file
        options_path = self.score.filepath + '.opts'
        try:
            with open(options_path, "r") as options_file:
                self.options = json.load(options_file)
        except FileNotFoundError:
            logger.warning(f"Options file not found: {options_path}. Using default settings.")

        # Update global settings with user preferences
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
            'enharmonic_conversion': self.options.get("enharmonic_conversion", False),
            'disable_all_coloring': self.options.get("disable_all_coloring", False),
        })

    def _create_music_segment(self, start_bar, end_bar, web_path):
        """
        Create a music segment dictionary for a given bar range.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            web_path (str): Base URL path for MIDI generation
            
        Returns:
            dict: Complete segment data for template rendering
        """
        # Pre-generate all MIDI files for this segment
        self._trigger_midi_generation(start_bar=start_bar, end_bar=end_bar)
        
        # Generate MIDI URLs for individual instruments
        selected_instruments_midis = {}
        for instrument_num in self.score.selected_instruments:
            midis = self.score.generate_midi_filenames(
                base_url=web_path, 
                range_start=start_bar, 
                range_end=end_bar, 
                add_instruments=[instrument_num]
            )
            selected_instruments_midis[instrument_num] = {
                "ins": instrument_num,
                "midi": midis[0],
                "midi_parts": midis[1]
            }
        
        # Generate MIDI URLs for combined selections
        midi_all = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="all"
        )
        midi_selected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="sel"
        )
        midi_unselected = self.score.generate_midi_filename_sel(
            base_url=web_path, range_start=start_bar, range_end=end_bar, sel="un"
        )

        # Generate textual descriptions for selected instruments
        selected_instruments_descriptions = {}
        for instrument_num in self.score.selected_instruments:
            selected_instruments_descriptions[instrument_num] = self.score.generate_part_descriptions(
                instrument=instrument_num, start_bar=start_bar, end_bar=end_bar
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

    def generateHTML(self, output_path="", web_path=""):
        """
        Generate the complete HTML talking score.
        
        This is the main method that coordinates all aspects of HTML generation,
        including instrument analysis, segment creation, and template rendering.
        
        Args:
            output_path (str): Directory path for MIDI file output
            web_path (str): Base URL path for MIDI links
            
        Returns:
            str: Complete HTML content for the talking score
        """
        global settings
        from jinja2 import Environment, FileSystemLoader
        
        # Setup Jinja2 template environment
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        template = env.get_template('talkingscore.html')

        # Initialize score analysis
        self.score.get_instruments()
        self.score.compare_parts_with_selected_instruments()

        self.music_analyser = MusicAnalyser()
        self.music_analyser.set_score(self.score)
        
        # Determine score range
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        last_measure = self.score.score.parts[0].getElementsByClass('Measure')[-1]
        start_bar = first_measure.number
        end_bar = last_measure.number

        # Pre-generate full score MIDI files
        self._trigger_midi_generation(start_bar, end_bar)
        
        # Generate MIDI URLs for full score playback
        selected_instruments_midis = {}
        for instrument_num in self.score.selected_instruments:
            midis = self.score.generate_midi_filenames(
                base_url=web_path, 
                range_start=start_bar, 
                range_end=end_bar, 
                add_instruments=[instrument_num]
            )
            selected_instruments_midis[instrument_num] = {
                "ins": instrument_num,
                "midi": midis[0],
                "midi_parts": midis[1]
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
        
        full_score_midis = {
            'selected_instruments_midis': selected_instruments_midis, 
            'midi_all': midi_all, 
            'midi_sel': midi_selected, 
            'midi_un': midi_unselected
        }

        # Generate music segments
        music_segments = self.get_music_segments(output_path, web_path)
        
        # Get beat division options for the interface
        beat_division_options = self.score.get_beat_division_options()

        # Debug output for beat division options
        logger.debug("--- DEBUG INFO: Beat Division Options ---")
        logger.debug(beat_division_options)

        # Render the complete HTML template
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
        """
        Pre-generate all MIDI files for a bar range to improve performance.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
        """
        # Local imports to prevent circular dependency at startup
        from lib.midiHandler import MidiHandler
        from types import SimpleNamespace
        
        logger.info(f"Pre-generating all MIDI files for bars {start_bar}-{end_bar}...")
        
        # Create parameters for MIDI generation
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
            # Instantiate MIDI handler and pre-generate files
            midi_handler = MidiHandler(dummy_request, id_hash, xml_filename)
            # Performance optimization: pass the already-parsed score object
            midi_handler.score = self.score.score
            midi_handler.make_midi_files()
            logger.info(f"Successfully generated MIDIs for bars {start_bar}-{end_bar}.")
        except Exception as e:
            logger.error(f"Failed to pre-generate MIDI files for bars {start_bar}-{end_bar}: {e}", exc_info=True)

    def get_basic_information(self):
        """
        Get basic score information for the template.
        
        Returns:
            dict: Title and composer information
        """
        return {
            'title': self.score.get_title(),
            'composer': self.score.get_composer(),
        }

    def get_preamble(self):
        """
        Get preamble information (time signature, key, tempo, etc.) for the template.
        
        Returns:
            dict: Musical preamble information
        """
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
        
        This method handles the complex logic of dividing the score into segments,
        managing pickup bars, and collecting time signature and key signature changes.
        
        Args:
            output_path (str): Directory for MIDI output
            web_path (str): Base URL for MIDI links
            
        Returns:
            list: List of music segment dictionaries
        """
        global settings
        logger.info("Start of get_music_segments")

        music_segments = []
        
        # Collect time signature and key signature information
        self.time_and_keys = {}
        self._collect_time_signature_info()
        self._collect_key_signature_info()
        
        # Initialize time signature cache
        self.score.time_signatures = {}
        previous_time_signature = self._get_initial_time_signature()

        # Handle pickup (anacrusis) bars
        start_bar_for_loop = self._process_pickup_bar(music_segments, web_path, previous_time_signature)
        
        # Process main bars in segments
        self._process_main_bar_segments(music_segments, start_bar_for_loop, web_path, previous_time_signature)

        return music_segments

    def _collect_time_signature_info(self):
        """Collect time signature change information for display."""
        time_signatures = self.score.score.parts[0].flatten().getElementsByClass('TimeSignature')
        total_count = len(time_signatures)
        
        for index, time_sig in enumerate(time_signatures):
            description = (f"Time signature - {index + 1} of {total_count} is "
                         f"{self.score.describe_time_signature(time_sig)}. ")
            self.time_and_keys.setdefault(time_sig.measureNumber, []).append(description)

    def _collect_key_signature_info(self):
        """Collect key signature change information for display."""
        key_signatures = self.score.score.parts[0].flatten().getElementsByClass('KeySignature')
        total_count = len(key_signatures)
        
        for index, key_sig in enumerate(key_signatures):
            description = (f"Key signature - {index + 1} of {total_count} is "
                         f"{self.score.describe_key_signature(key_sig)}. ")
            self.time_and_keys.setdefault(key_sig.measureNumber, []).append(description)

    def _get_initial_time_signature(self):
        """Get the initial time signature for the score."""
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        time_signatures = first_measure.getTimeSignatures()
        
        if self.score.score.parts[0].hasMeasures() and time_signatures:
            return time_signatures[0]
        else:
            return self.score.get_initial_time_signature()

    def _process_pickup_bar(self, music_segments, web_path, previous_time_signature):
        """
        Process pickup (anacrusis) bar if present.
        
        Returns:
            int: Starting bar number for the main loop
        """
        global settings
        
        first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
        start_bar_for_loop = first_measure.number
        
        # Check if first measure is a pickup bar
        active_time_signature = first_measure.timeSignature or previous_time_signature
        
        if (active_time_signature and 
            first_measure.duration.quarterLength < active_time_signature.barDuration.quarterLength):
            
            pickup_bar_num = first_measure.number
            logger.info(f"Anacrusis (pickup bar) detected at measure {pickup_bar_num}.")
            
            # Cache time signature for pickup bar
            self.score.time_signatures[pickup_bar_num] = previous_time_signature

            # Create pickup bar segment
            segment = self._create_music_segment(
                start_bar=pickup_bar_num, 
                end_bar=pickup_bar_num, 
                web_path=web_path
            )
            
            # Special labeling for pickup bar
            segment['start_bar'] = 'Pickup'
            segment['end_bar'] = ''
            music_segments.append(segment)
            
            # Main loop starts after pickup bar
            start_bar_for_loop = pickup_bar_num + 1

        return start_bar_for_loop

    def _process_main_bar_segments(self, music_segments, start_bar_for_loop, web_path, previous_time_signature):
        """
        Process the main bars of the score in segments.
        
        Args:
            music_segments (list): List to append segments to
            start_bar_for_loop (int): Starting bar number
            web_path (str): Base URL for MIDI links
            previous_time_signature: Current time signature
        """
        global settings
        
        total_measures = self.score.score.parts[0].getElementsByClass('Measure')[-1].number
        bars_at_a_time = settings['barsAtATime']
        
        for bar_index in range(start_bar_for_loop, total_measures + 1, bars_at_a_time):
            end_bar_index = min(bar_index + bars_at_a_time - 1, total_measures)

            # Check if measure exists
            if self.score.score.parts[0].measure(bar_index) is None:
                break
            
            # Pre-populate time signatures for the segment
            for measure_num in range(bar_index, end_bar_index + 1):
                measure = self.score.score.parts[0].measure(measure_num)
                if measure and measure.getElementsByClass(meter.TimeSignature):
                    previous_time_signature = measure.getElementsByClass(meter.TimeSignature)[0]
                self.score.time_signatures[measure_num] = previous_time_signature

            # Create segment
            segment = self._create_music_segment(
                start_bar=bar_index, 
                end_bar=end_bar_index, 
                web_path=web_path
            )
            music_segments.append(segment)