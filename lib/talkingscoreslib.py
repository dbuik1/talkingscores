"""
Talking Scores Library - Main Coordination Module

This module provides the main coordination classes for the Talking Scores application,
integrating musical analysis, MIDI generation, and HTML rendering with a clean,
modular architecture prepared for future enhancements.
"""

import os
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass
from abc import ABC, abstractmethod

# Import refactored modules with absolute imports  
from lib.settings_manager import SettingsManager, TalkingScoresSettings
from lib.color_utilities import ColorRenderer, ColorPaletteManager
from lib.musical_events import MusicalEventFactory, RenderContext
from lib.midi_coordinator import MIDICoordinator, MIDIRequest
from lib.template_renderer import TemplateManager
from lib.musicAnalyser import MusicAnalyser
from lib.score_analyzer import ScoreAnalyzer

# Music21 imports
from music21 import converter, stream, meter, key, tempo, note, interval, duration

logger = logging.getLogger("TSScore")


global settings
settings = {
    'rhythmDescription': 'british',
    'dotPosition': 'before',
    'octaveDescription': 'name',
    'pitchDescription': 'noteName',
}


class TalkingScoreError(Exception):
    """Base exception for Talking Score operations."""
    pass


class ScoreParsingError(TalkingScoreError):
    """Exception raised when score parsing fails."""
    pass


class AnalysisError(TalkingScoreError):
    """Exception raised when musical analysis fails."""
    pass


@dataclass
class ScoreMetadata:
    """Container for basic score metadata."""
    title: str = "Unknown Title"
    composer: str = "Unknown Composer"
    number_of_bars: int = 0
    number_of_parts: int = 0
    time_signature: str = ""
    key_signature: str = ""
    tempo: str = ""


class TalkingScoreBase(ABC):
    """
    Abstract base class for talking score implementations.
    
    This class defines the interface that all talking score implementations
    must provide, allowing for different backends in the future.
    """
    
    @abstractmethod
    def get_title(self) -> str:
        """Get the title of the musical work."""
        pass
    
    @abstractmethod
    def get_composer(self) -> str:
        """Get the composer of the musical work."""
        pass
    
    @abstractmethod
    def get_metadata(self) -> ScoreMetadata:
        """Get comprehensive metadata about the score."""
        pass
    
    @abstractmethod
    def analyze_score(self, settings: TalkingScoresSettings) -> Dict[str, Any]:
        """Analyze the musical content of the score."""
        pass


class DurationMapper:
    """
    Handles mapping between music21 durations and human-readable descriptions.
    
    This class encapsulates all duration-related mapping logic that was
    previously scattered throughout the codebase.
    """
    
    # British terminology mapping
    BRITISH_DURATION_MAP = {
        'whole': 'semibreve',
        'half': 'minim', 
        'quarter': 'crotchet',
        'eighth': 'quaver',
        '16th': 'semi-quaver',
        '32nd': 'demi-semi-quaver',
        '64th': 'hemi-demi-semi-quaver',
        'zero': 'grace note',
    }
    
    # American terminology (music21 default)
    AMERICAN_DURATION_MAP = {
        'whole': 'whole note',
        'half': 'half note',
        'quarter': 'quarter note',
        'eighth': 'eighth note',
        '16th': 'sixteenth note',
        '32nd': 'thirty-second note',
        '64th': 'sixty-fourth note',
        'zero': 'grace note',
    }
    
    DOTS_MAP = {
        0: '',
        1: 'dotted ',
        2: 'double dotted ',
        3: 'triple dotted '
    }
    
    def __init__(self, settings: TalkingScoresSettings):
        self.settings = settings
    
    def map_duration(self, duration_obj) -> str:
        """
        Map a music21 duration to a human-readable description.
        
        Args:
            duration_obj: music21 Duration object
            
        Returns:
            Human-readable duration description
        """
        if self.settings.rendering.rhythm_description == 'none':
            return ""
        
        duration_text = ""
        
        # Add dots before if configured
        if self.settings.rendering.dot_position == "before":
            dots = getattr(duration_obj, 'dots', 0)
            duration_text += self.DOTS_MAP.get(dots, '')
        
        # Add main duration name
        duration_type = getattr(duration_obj, 'type', 'quarter')
        
        if self.settings.rendering.rhythm_description == 'british':
            duration_text += self.BRITISH_DURATION_MAP.get(duration_type, f'Unknown duration {duration_type}')
        else:  # american
            duration_text += self.AMERICAN_DURATION_MAP.get(duration_type, duration_type)
        
        # Add dots after if configured
        if self.settings.rendering.dot_position == "after":
            dots = getattr(duration_obj, 'dots', 0)
            if dots > 0:
                duration_text += " " + self.DOTS_MAP.get(dots, '').strip()
        
        return duration_text


class PitchMapper:
    """
    Handles mapping between music21 pitches and human-readable descriptions.
    
    This class manages pitch naming, octave descriptions, and accidental handling
    according to the application settings.
    """
    
    OCTAVE_NAME_MAP = {
        1: 'bottom', 2: 'lower', 3: 'low', 4: 'mid',
        5: 'high', 6: 'higher', 7: 'top'
    }
    
    OCTAVE_FIGURENOTES_MAP = {
        1: 'bottom', 2: 'cross', 3: 'square', 4: 'circle',
        5: 'triangle', 6: 'higher', 7: 'top'
    }
    
    PITCH_FIGURENOTES_MAP = {
        'C': 'red', 'D': 'brown', 'E': 'grey', 'F': 'blue',
        'G': 'black', 'A': 'yellow', 'B': 'green'
    }
    
    PITCH_PHONETIC_MAP = {
        'C': 'charlie', 'D': 'delta', 'E': 'echo', 'F': 'foxtrot',
        'G': 'golf', 'A': 'alpha', 'B': 'bravo'
    }
    
    def __init__(self, settings: TalkingScoresSettings):
        self.settings = settings
    
    def map_pitch(self, pitch, state: Optional[Dict] = None) -> str:
        """
        Map a music21 pitch to a human-readable description.
        
        Args:
            pitch: music21 Pitch object
            state: State dictionary for tracking accidental context
            
        Returns:
            Human-readable pitch description
        """
        if state is None:
            state = {}
        
        # Determine base name based on pitch description setting
        if self.settings.rendering.pitch_description == "colourNotes":
            base_name = self.PITCH_FIGURENOTES_MAP.get(pitch.step, "?")
        elif self.settings.rendering.pitch_description == "phonetic":
            base_name = self.PITCH_PHONETIC_MAP.get(pitch.step, "?")
        elif self.settings.rendering.pitch_description == "noteName":
            base_name = pitch.step
        else:  # none
            return ''
        
        # Handle accidentals if present
        if pitch.accidental:
            return self._add_accidental_to_pitch(base_name, pitch, state)
        
        return base_name
    
    def map_octave(self, octave_number: int) -> str:
        """
        Map an octave number to a human-readable description.
        
        Args:
            octave_number: Numeric octave (1-7)
            
        Returns:
            Human-readable octave description
        """
        octave_desc = self.settings.rendering.octave_description
        
        if octave_desc == "figureNotes":
            return self.OCTAVE_FIGURENOTES_MAP.get(octave_number, "?")
        elif octave_desc == "name":
            return self.OCTAVE_NAME_MAP.get(octave_number, "?")
        elif octave_desc == "number":
            return str(octave_number)
        else:  # none
            return ""
    
    def _add_accidental_to_pitch(self, base_name: str, pitch, state: Dict) -> str:
        """Add accidental information to a pitch name."""
        mode = self.settings.rendering.key_signature_accidentals
        
        # Determine if accidental should be shown
        show_accidental = False
        
        if mode == 'applied':
            # Show sharps/flats but never naturals
            if pitch.accidental.name != 'natural':
                show_accidental = True
        elif mode == 'standard':
            # Show only explicitly displayed accidentals
            if pitch.accidental.displayStatus:
                show_accidental = True
        elif mode == 'onChange':
            # Show when accidental changes from previous occurrence
            current_alter = pitch.alter
            step = pitch.step
            last_seen_alter = state.get(step)
            if last_seen_alter is None or current_alter != last_seen_alter:
                state[step] = current_alter
                show_accidental = True
        
        if not show_accidental:
            return base_name
        
        # Format the accidental
        if self.settings.rendering.accidental_style == 'symbols':
            symbol_map = {
                'sharp': '♯', 'flat': '♭', 'natural': '♮',
                'double-sharp': '𝄪', 'double-flat': '♭♭'
            }
            accidental_text = symbol_map.get(pitch.accidental.name, '')
            return f"{base_name}{accidental_text}"
        else:  # 'words'
            accidental_text = pitch.accidental.fullName
            return f"{base_name} {accidental_text}"


class Music21TalkingScore(TalkingScoreBase):
    """
    Main implementation of talking score functionality using music21.
    
    This class coordinates all aspects of talking score generation including
    parsing, analysis, and rendering while maintaining a clean interface.
    """
    
    def __init__(self, musicxml_filepath):
        # FIXED: Ensure filepath is always stored as a string for consistency
        self.filepath = str(os.path.realpath(musicxml_filepath))
        self.score = converter.parse(musicxml_filepath)
        super(Music21TalkingScore, self).__init__()
        
        # Initialize component managers
        self.settings_manager = SettingsManager()
        self.duration_mapper = DurationMapper(self.settings_manager.settings)
        self.pitch_mapper = PitchMapper(self.settings_manager.settings)
        
        # Score analysis data
        self.part_instruments = {}
        self.part_names = {}
        self.selected_instruments = []
        self.selected_part_names = []
        self.binary_selected_instruments = 1
        self.binary_play_all = 1
        
        # Initialize analysis components
        self._initialize_analysis_components()
    
    def _initialize_analysis_components(self):
        """Initialize musical analysis components."""
        try:
            self.music_analyser = MusicAnalyser()
            self.score_analyzer = ScoreAnalyzer(self.score)
        except Exception as e:
            logger.warning(f"Failed to initialize analysis components: {e}")
            self.music_analyser = None
            self.score_analyzer = None
    
    def get_title(self) -> str:
        """Get the title of the musical work."""
        if self.score.metadata and self.score.metadata.title:
            return self.score.metadata.title
        
        # Try to find title in text boxes (fallback)
        for text_box in self.score.flatten().getElementsByClass('TextBox'):
            if (hasattr(text_box, 'justify') and text_box.justify == 'center' and
                hasattr(text_box, 'alignVertical') and text_box.alignVertical == 'top' and
                hasattr(text_box, 'size') and text_box.size > 18):
                return text_box.content
        
        return "Unknown Title"
    
    def get_composer(self) -> str:
        """Get the composer of the musical work."""
        if self.score.metadata and self.score.metadata.composer:
            return self.score.metadata.composer
        
        # Try to find composer in text boxes (fallback)
        for text_box in self.score.getElementsByClass('TextBox'):
            if hasattr(text_box, 'style') and text_box.style.justify == 'right':
                return text_box.content
        
        return "Unknown Composer"
    
    def get_metadata(self) -> ScoreMetadata:
        """Get comprehensive metadata about the score."""
        return ScoreMetadata(
            title=self.get_title(),
            composer=self.get_composer(),
            number_of_bars=self.get_number_of_bars(),
            number_of_parts=self.get_number_of_parts(),
            time_signature=self.get_initial_time_signature(),
            key_signature=self.get_initial_key_signature(),
            tempo=self.get_initial_tempo()
        )
    
    def get_number_of_bars(self) -> int:
        """Get the number of measures in the score."""
        try:
            return len(self.score.parts[0].getElementsByClass('Measure'))
        except (IndexError, AttributeError):
            return 0
    
    def get_number_of_parts(self) -> int:
        """Get the number of parts in the score."""
        self.get_instruments()  # Ensure instruments are analyzed
        return len(self.part_instruments)
    
    def get_initial_time_signature(self) -> str:
        """Get the initial time signature of the score."""
        try:
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            time_sigs = first_measure.getElementsByClass(meter.TimeSignature)
            if time_sigs:
                return self.describe_time_signature(time_sigs[0])
        except (IndexError, AttributeError):
            pass
        return "Error reading time signature"
    
    def describe_time_signature(self, time_sig) -> str:
        """Describe a time signature in human-readable format."""
        if time_sig:
            return " ".join(time_sig.ratioString.split("/"))
        return "Unknown time signature"
    
    def get_initial_key_signature(self) -> str:
        """Get the initial key signature of the score."""
        try:
            first_measure = self.score.parts[0].measures(1, 1)
            key_sigs = first_measure.flatten().getElementsByClass('KeySignature')
            if key_sigs:
                return self.describe_key_signature(key_sigs[0])
            else:
                # Default to no accidentals
                return self.describe_key_signature(key.KeySignature(0))
        except (IndexError, AttributeError):
            return "Error reading key signature"
    
    def describe_key_signature(self, key_sig) -> str:
        """Describe a key signature in human-readable format."""
        if key_sig.sharps > 0:
            return f"{key_sig.sharps} sharps"
        elif key_sig.sharps < 0:
            return f"{abs(key_sig.sharps)} flats"
        else:
            return "No sharps or flats"
    
    def get_initial_tempo(self) -> str:
        """Get the initial tempo marking of the score."""
        try:
            tempo_boundaries = self.score.metronomeMarkBoundaries()
            if tempo_boundaries:
                first_tempo = tempo_boundaries[0][2]
                return self.describe_tempo(first_tempo)
        except (IndexError, AttributeError):
            pass
        return "No tempo specified"
    
    def describe_tempo(self, tempo_mark) -> str:
        """Describe a tempo marking in human-readable format."""
        tempo_mark = self.fix_tempo_number(tempo_mark)
        
        tempo_text = ""
        if hasattr(tempo_mark, 'text') and tempo_mark.text:
            tempo_text += f"{tempo_mark.text} ({math.floor(tempo_mark.number)} bpm @ {self._describe_tempo_referent(tempo_mark)})"
        else:
            tempo_text += f"{math.floor(tempo_mark.number)} bpm @ {self._describe_tempo_referent(tempo_mark)}"
        
        return tempo_text
    
    def _describe_tempo_referent(self, tempo_mark) -> str:
        """Describe the referent (beat unit) of a tempo marking."""
        if not hasattr(tempo_mark, 'referent'):
            return "quarter note"
        
        return self.duration_mapper.map_duration(tempo_mark.referent)
    
    @staticmethod
    def fix_tempo_number(tempo_mark):
        """Fix tempo marks that have soundingNumber but not number."""
        if not hasattr(tempo_mark, 'number') or tempo_mark.number is None:
            if hasattr(tempo_mark, 'numberSounding') and tempo_mark.numberSounding is not None:
                tempo_mark.number = tempo_mark.numberSounding
            else:
                tempo_mark.number = 120
                if hasattr(tempo_mark, 'text'):
                    tempo_mark.text = "Error - " + (tempo_mark.text or "")
        return tempo_mark
    
    def get_instruments(self) -> List[str]:
        """
        Analyze and return the instruments in the score.
        
        Returns:
            List of instrument names
        """
        self.part_instruments = {}
        self.part_names = {}
        instrument_names = []
        
        try:
            instrument_count = 1
            
            for part_index, instrument in enumerate(self.score.flatten().getInstruments()):
                part_name = instrument.partName or f"Instrument {instrument_count} (unnamed)"
                
                # Check if this is a new instrument or continuation of previous
                if (len(self.part_instruments) == 0 or 
                    self.part_instruments[instrument_count-1][3] != instrument.partId):
                    
                    # New instrument
                    self.part_instruments[instrument_count] = [part_name, part_index, 1, instrument.partId]
                    instrument_names.append(part_name)
                    instrument_count += 1
                else:
                    # Additional part of previous instrument
                    self.part_instruments[instrument_count-1][2] += 1
                    self._assign_part_names(instrument_count-1, part_index)
            
            logger.debug(f"Found {len(self.part_instruments)} instruments")
            
        except Exception as e:
            logger.error(f"Error analyzing instruments: {e}")
            
        return instrument_names
    
    def _assign_part_names(self, instrument_index: int, part_index: int):
        """Assign names to multiple parts of an instrument."""
        num_parts = self.part_instruments[instrument_index + 1][2]
        
        if num_parts == 2:
            # Piano-style naming
            first_part_index = part_index - 1
            self.part_names[first_part_index] = "Right hand"
            self.part_names[part_index] = "Left hand"
        else:
            # Generic part naming
            first_part_index = self.part_instruments[instrument_index + 1][1]
            for i in range(num_parts):
                self.part_names[first_part_index + i] = f"Part {i + 1}"
    
    def get_beat_division_options(self) -> List[Dict[str, str]]:
        """
        Get available beat division options based on the time signature.
        
        Returns:
            List of dictionaries with 'display' and 'value' keys
        """
        try:
            # Find the first time signature
            time_sig = None
            first_measure = self.score.parts[0].getElementsByClass('Measure')[0]
            
            for item in first_measure:
                if isinstance(item, meter.TimeSignature):
                    time_sig = item
                    break
            
            if not time_sig:
                time_sigs = self.score.getTimeSignatures()
                if time_sigs:
                    time_sig = time_sigs[0]
            
            if not time_sig:
                return [{'display': 'Group by Bar (continuous)', 'value': 'bar'}]
            
            options = []
            seen_values = set()
            
            def add_option(display: str, value: str):
                if value not in seen_values:
                    options.append({'display': display, 'value': value})
                    seen_values.add(value)
            
            # Add "No Beats" option
            add_option('Group by Bar (continuous)', 'bar')
            
            # Default music21 interpretation
            default_beat_string = self.duration_mapper.map_duration(time_sig.beatDuration)
            default_display = f"{time_sig.beatCount} {default_beat_string} beats (Default)"
            default_value = f"{time_sig.beatCount}/{time_sig.beatDuration.quarterLength}"
            add_option(default_display, default_value)
            
            # Face value interpretation
            face_value_duration = duration.Duration(1.0 / time_sig.denominator)
            face_value_beat_string = self.duration_mapper.map_duration(face_value_duration)
            face_value_display = f"{time_sig.numerator} {face_value_beat_string} beats"
            face_value_value = f"{time_sig.numerator}/{time_sig.denominator}"
            add_option(face_value_display, face_value_value)
            
            # Compound meter interpretation
            if time_sig.numerator % 3 == 0 and time_sig.numerator > 3:
                compound_beat_count = time_sig.numerator // 3
                simple_beat_name = self.duration_mapper.map_duration(face_value_duration)
                compound_beat_string = f"Dotted {simple_beat_name}"
                compound_display = f"{compound_beat_count} {compound_beat_string} beats"
                compound_beat_duration_ql = (1.0 / time_sig.denominator) * 3
                compound_value = f"{compound_beat_count}/{compound_beat_duration_ql}"
                add_option(compound_display, compound_value)
            
            return options
            
        except Exception as e:
            logger.error(f"Error generating beat division options: {e}")
            return [{'display': 'Group by Bar (continuous)', 'value': 'bar'}]
    
    def get_rhythm_range(self) -> List[str]:
        """Get all unique rhythm types present in the score."""
        found_rhythms = set()
        
        try:
            for element in self.score.flatten().notesAndRests:
                rhythm_name = self.duration_mapper.map_duration(element.duration)
                if rhythm_name and rhythm_name != "Unknown duration":
                    found_rhythms.add(rhythm_name)
        except Exception as e:
            logger.error(f"Error finding rhythm range: {e}")
        
        # Sort rhythms by typical duration length
        duration_order = ['semibreve', 'minim', 'crotchet', 'quaver', 'semi-quaver']
        found_list = list(found_rhythms)
        
        def rhythm_sort_key(rhythm):
            for i, standard in enumerate(duration_order):
                if standard in rhythm:
                    return i
            return len(duration_order)  # Unknown rhythms at end
        
        return sorted(found_list, key=rhythm_sort_key)
    
    def get_octave_range(self) -> Dict[str, int]:
        """Get the range of octaves used in the score."""
        all_octaves = []
        
        try:
            for element in self.score.flatten().notes:
                if hasattr(element, 'pitches'):  # Chord
                    for pitch in element.pitches:
                        all_octaves.append(pitch.octave)
                elif hasattr(element, 'pitch'):  # Note
                    all_octaves.append(element.pitch.octave)
        except Exception as e:
            logger.error(f"Error finding octave range: {e}")
        
        if not all_octaves:
            return {'min': 0, 'max': 0}
        
        return {'min': min(all_octaves), 'max': max(all_octaves)}
    
    def analyze_score(self, settings: TalkingScoresSettings) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of the musical score.
        
        Args:
            settings: Application settings for analysis
            
        Returns:
            Dictionary containing analysis results
        """
        try:
            # Update internal settings
            self.settings_manager._settings = settings
            self.duration_mapper = DurationMapper(settings)
            self.pitch_mapper = PitchMapper(settings)
            
            # Perform musical analysis
            if self.music_analyser:
                self.music_analyser.setScore(self)
            
            # Compile analysis results
            analysis_results = {
                'general_summary': getattr(self.music_analyser, 'general_summary', ''),
                'parts_summary': getattr(self.music_analyser, 'summary_parts', []),
                'repetition_in_contexts': getattr(self.music_analyser, 'repetition_in_contexts', {}),
                'immediate_repetition_contexts': getattr(self.music_analyser, 'immediate_repetition_contexts', {}),
                'time_and_keys': self._analyze_structural_changes()
            }
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"Error during score analysis: {e}")
            raise AnalysisError(f"Failed to analyze score: {e}")
    
    def _analyze_structural_changes(self) -> Dict[int, List[str]]:
        """Analyze time signature, key signature, and tempo changes."""
        changes_by_bar = {}
        
        try:
            first_part = self.score.parts[0]
            
            # Time signature changes
            time_sigs = first_part.flatten().getElementsByClass('TimeSignature')
            for i, ts in enumerate(time_sigs):
                if hasattr(ts, 'measureNumber'):
                    description = f"Time signature - {i+1} of {len(time_sigs)} is {self.describe_time_signature(ts)}."
                    changes_by_bar.setdefault(ts.measureNumber, []).append(description)
            
            # Key signature changes
            key_sigs = first_part.flatten().getElementsByClass('KeySignature')
            for i, ks in enumerate(key_sigs):
                if hasattr(ks, 'measureNumber'):
                    description = f"Key signature - {i+1} of {len(key_sigs)} is {self.describe_key_signature(ks)}."
                    changes_by_bar.setdefault(ks.measureNumber, []).append(description)
            
            # Tempo changes  
            tempos = self.score.flatten().getElementsByClass('MetronomeMark')
            for i, tempo_mark in enumerate(tempos):
                if hasattr(tempo_mark, 'measureNumber'):
                    description = f"Tempo - {i+1} of {len(tempos)} is {self.describe_tempo(tempo_mark)}."
                    changes_by_bar.setdefault(tempo_mark.measureNumber, []).append(description)
                    
        except Exception as e:
            logger.error(f"Error analyzing structural changes: {e}")
        
        return changes_by_bar
    
    def compare_parts_with_selected_instruments(self):
        """
        Compare available parts with selected instruments and update internal state.
        
        This method handles the complex logic of determining what MIDI files
        to generate based on user selections.
        """
        settings = self.settings_manager.settings
        
        # Initialize selection tracking
        self.selected_instruments = []
        self.unselected_instruments = []
        self.binary_selected_instruments = 1
        self.selected_part_names = []
        
        # Build selected instruments list
        for instrument_num in self.part_instruments.keys():
            self.binary_selected_instruments = self.binary_selected_instruments << 1
            if instrument_num in settings.playback.instruments:
                self.selected_instruments.append(instrument_num)
                self.binary_selected_instruments += 1
            else:
                self.unselected_instruments.append(instrument_num)
        
        # Build selected part names
        for instrument_num in self.selected_instruments:
            instrument_info = self.part_instruments[instrument_num]
            instrument_name = instrument_info[0]
            
            if instrument_info[2] == 1:  # Single part instrument
                self.selected_part_names.append(instrument_name)
            else:  # Multi-part instrument
                start_part_index = instrument_info[1]
                for part_offset in range(instrument_info[2]):
                    part_index = start_part_index + part_offset
                    part_name = self.part_names.get(part_index, f"Part {part_offset + 1}")
                    self.selected_part_names.append(f"{instrument_name} - {part_name}")
        
        # Calculate binary playback flags
        self.binary_play_all = 1
        if settings.playback.play_all:
            self.binary_play_all = (self.binary_play_all << 1) + 1
        else:
            self.binary_play_all = self.binary_play_all << 1
            
        if settings.playback.play_selected:
            self.binary_play_all = (self.binary_play_all << 1) + 1
        else:
            self.binary_play_all = self.binary_play_all << 1
            
        if settings.playback.play_unselected:
            self.binary_play_all = (self.binary_play_all << 1) + 1
        else:
            self.binary_play_all = self.binary_play_all << 1
        
        logger.debug(f"Selected instruments: {self.selected_instruments}")
        logger.debug(f"Binary flags - instruments: {self.binary_selected_instruments}, playback: {self.binary_play_all}")

class HTMLTalkingScoreFormatter():
    def __init__(self, talking_score):
        global settings
        self.score: Music21TalkingScore = talking_score
        self.options = {}

        # FIXED: Convert filepath to string to handle both str and Path objects
        filepath_str = str(self.score.filepath)
        options_path = filepath_str + '.opts'
        
        try:
            with open(options_path, "r") as options_fh:
                self.options = json.load(options_fh)
        except FileNotFoundError:
            logger.warning(f"Options file not found: {options_path}. Using default settings.")
            pass

        settings = {
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
            'repetition_mode': self.options.get('repetition_mode', 'learning')
        }
        
        # FIXED: Initialize components with proper parameters
        try:
            # FIXED: Determine cache directory from score filepath (convert to string)
            cache_directory = os.path.dirname(filepath_str)
            
            # Initialize MIDI coordinator with both required parameters
            self.midi_coordinator = MIDICoordinator("", cache_directory)  # URL will be set in generateHTML
            
            # Initialize settings manager
            self.settings_manager = SettingsManager(self.options)
            
            # Initialize other components
            self.template_manager = TemplateManager()
            self.color_renderer = ColorRenderer(self.settings_manager.settings.colors if hasattr(self.settings_manager.settings, 'colors') else None)
            
        except Exception as e:
            logger.warning(f"Could not initialize advanced components: {e}. Using fallback mode.")
            # Fallback: set to None and handle gracefully in other methods
            self.midi_coordinator = None
            self.settings_manager = None
            self.template_manager = None
            self.color_renderer = None
    
    def _load_settings_from_file(self):
        """Load settings from the .opts file if available."""
        options_path = str(self.score.filepath) + '.opts'
        if os.path.exists(options_path):
            self.score.settings_manager.load_from_file(options_path)
            logger.debug(f"Loaded settings from {options_path}")
    
    def generateHTML(self, output_path="", web_path=""):
        """Generate HTML for the talking score."""
        try:
            from jinja2 import Environment, FileSystemLoader
            env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
            template = env.get_template('talkingscore.html')

            self.score.get_instruments()
            self.score.compare_parts_with_selected_instruments()

            self.music_analyser = MusicAnalyser()
            self.music_analyser.setScore(self.score)
            
            start = self.score.score.parts[0].getElementsByClass('Measure')[0].number
            end = self.score.score.parts[0].getElementsByClass('Measure')[-1].number

            # FIXED: Initialize or update MIDI coordinator with proper paths
            if self.midi_coordinator is None or not hasattr(self.midi_coordinator, 'base_url'):
                cache_directory = output_path or os.path.dirname(self.score.filepath)
                self.midi_coordinator = MIDICoordinator(web_path, cache_directory)
            else:
                # Update existing coordinator with new paths
                self.midi_coordinator.base_url = web_path
                self.midi_coordinator.cache_directory = output_path or os.path.dirname(self.score.filepath)

            self._trigger_midi_generation(start, end)
            
            # Generate MIDI contexts
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

            # FIXED: Create properly structured basic_information
            basic_info = {
                'title': self.score.get_title(),
                'composer': self.score.get_composer()
            }
            
            # FIXED: Create properly structured preamble
            preamble_info = {
                'time_signature': self.score.get_initial_time_signature(),
                'key_signature': self.score.get_initial_key_signature(),
                'tempo': self.score.get_initial_tempo(),
                'number_of_bars': self.score.get_number_of_bars(),
                'number_of_parts': self.score.get_number_of_parts(),
            }

            return template.render({
                'settings': settings,  # Use the global settings dict for now
                'basic_information': basic_info,  # FIXED: Now a proper dict
                'preamble': preamble_info,  # FIXED: Now a proper dict
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
            
        except Exception as e:
            logger.error(f"Error generating HTML: {e}")
            raise TalkingScoreError(f"Failed to generate HTML: {e}")
    
    def _generate_music_segments(self, output_path: str, web_path: str) -> List[Dict[str, Any]]:
        """Generate music segments with MIDI coordination."""
        segments = []
        settings = self.score.settings_manager.settings
        
        try:
            # Get segment boundaries
            start_bar, end_bar = self._get_score_range()
            bars_at_a_time = settings.playback.bars_at_a_time
            
            # Handle pickup bars
            segments.extend(self._handle_pickup_bars(start_bar, web_path))
            
            # Generate regular segments
            current_bar = start_bar
            while current_bar <= end_bar:
                segment_end = min(current_bar + bars_at_a_time - 1, end_bar)
                
                segment = self._create_music_segment(current_bar, segment_end, output_path, web_path)
                segments.append(segment)
                
                current_bar += bars_at_a_time
            
            return segments
            
        except Exception as e:
            logger.error(f"Error generating music segments: {e}")
            return []
    
    def _get_score_range(self) -> Tuple[int, int]:
        """Get the start and end bar numbers for the score."""
        try:
            first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
            last_measure = self.score.score.parts[0].getElementsByClass('Measure')[-1]
            return first_measure.number, last_measure.number
        except (IndexError, AttributeError):
            return 1, 1
    
    def _handle_pickup_bars(self, start_bar: int, web_path: str) -> List[Dict[str, Any]]:
        """Handle pickup bars (anacrusis) if present."""
        segments = []
        
        try:
            first_measure = self.score.score.parts[0].getElementsByClass('Measure')[0]
            
            # Check for pickup bar
            time_sig = first_measure.timeSignature or first_measure.previous('TimeSignature')
            if (time_sig and 
                first_measure.duration.quarterLength < time_sig.barDuration.quarterLength):
                
                logger.info(f"Pickup bar detected at measure {first_measure.number}")
                
                segment = self._create_music_segment(first_measure.number, first_measure.number, "", web_path)
                segment['start_bar'] = 'Pickup'
                segment['end_bar'] = ''
                segments.append(segment)
                
        except Exception as e:
            logger.warning(f"Error handling pickup bars: {e}")
        
        return segments
    
    def _create_music_segment(self, start_bar: int, end_bar: int, output_path: str, web_path: str) -> Dict[str, Any]:
        """Create a single music segment with all necessary data."""
        # Trigger MIDI generation for this segment
        self._trigger_midi_generation(start_bar, end_bar)
        
        # Generate MIDI URLs
        midi_context = self._generate_midi_context(start_bar, end_bar, web_path)
        
        # Generate musical descriptions
        descriptions = self._generate_segment_descriptions(start_bar, end_bar)
        
        # Combine into segment
        segment = {
            'start_bar': start_bar,
            'end_bar': end_bar,
            'selected_instruments_descriptions': descriptions,
            **midi_context
        }
        
        return segment
    
    def _trigger_midi_generation(self, start_bar: int, end_bar: int):
        """Trigger MIDI generation for a segment."""
        from lib.midiHandler import MidiHandler
        from types import SimpleNamespace
        
        try:
            # FIXED: Ensure proper path handling
            filepath_str = str(self.score.filepath)
            file_id = os.path.basename(os.path.dirname(filepath_str))
            xml_filename = os.path.basename(filepath_str)
            
            get_params = {
                'start': str(start_bar),
                'end': str(end_bar),
                'bsi': str(self.score.binary_selected_instruments),
                'bpi': str(self.score.binary_play_all),
                'upfront_generate': 'true'
            }
            dummy_request = SimpleNamespace(GET=get_params)
            
            # Create MIDI handler and trigger generation
            midi_handler = MidiHandler(dummy_request, file_id, xml_filename)
            midi_handler.score = self.score.score  # Pass pre-parsed score
            midi_handler.make_midi_files()
            
            logger.debug(f"Triggered MIDI generation for bars {start_bar}-{end_bar}")
            
        except Exception as e:
            logger.error(f"Failed to trigger MIDI generation for bars {start_bar}-{end_bar}: {e}")
    
    def _generate_midi_context(self, start_bar: int, end_bar: int, web_path: str) -> Dict[str, Any]:
        """Generate MIDI URLs and context for a segment."""
        from .midi_coordinator import MIDIUrlGenerator
        
        try:
            url_generator = MIDIUrlGenerator(web_path)
            
            # Base parameters for this segment
            base_params = {
                'bsi': self.score.binary_selected_instruments,
                'bpi': self.score.binary_play_all,
                'start': start_bar,
                'end': end_bar
            }
            
            # Generate selection URLs (all/selected/unselected)
            selection_urls = url_generator.generate_selection_urls(base_params)
            
            # Generate individual instrument URLs
            instrument_midis = {}
            for instrument_num in self.score.selected_instruments:
                instrument_params = base_params.copy()
                instrument_params['ins'] = instrument_num
                instrument_url = url_generator.generate_midi_url("", **instrument_params)
                
                # Generate part URLs if instrument has multiple parts
                part_urls = []
                instrument_info = self.score.part_instruments[instrument_num]
                if instrument_info[2] > 1:  # Multiple parts
                    start_part_index = instrument_info[1]
                    for part_offset in range(instrument_info[2]):
                        part_index = start_part_index + part_offset
                        part_params = base_params.copy()
                        part_params['part'] = part_index
                        part_url = url_generator.generate_midi_url("", **part_params)
                        part_urls.append(part_url)
                
                instrument_midis[instrument_num] = {
                    'ins': instrument_num,
                    'midi': instrument_url,
                    'midi_parts': part_urls
                }
            
            return {
                'midi_all': selection_urls.get('midi_all', ''),
                'midi_sel': selection_urls.get('midi_sel', ''),
                'midi_un': selection_urls.get('midi_un', ''),
                'selected_instruments_midis': instrument_midis
            }
            
        except Exception as e:
            logger.error(f"Error generating MIDI context: {e}")
            return {
                'midi_all': '', 'midi_sel': '', 'midi_un': '',
                'selected_instruments_midis': {}
            }
    
    def _generate_segment_descriptions(self, start_bar: int, end_bar: int) -> Dict[int, List[Dict[int, Any]]]:
        """Generate musical descriptions for a segment."""
        descriptions = {}
        
        try:
            for instrument_num in self.score.selected_instruments:
                instrument_descriptions = []
                instrument_info = self.score.part_instruments[instrument_num]
                
                # Generate descriptions for each part of this instrument
                start_part_index = instrument_info[1]
                for part_offset in range(instrument_info[2]):
                    part_index = start_part_index + part_offset
                    
                    # Get events for this part and bar range
                    part_events = self.score.get_events_for_bar_range(start_bar, end_bar, part_index)
                    instrument_descriptions.append(part_events)
                
                descriptions[instrument_num] = instrument_descriptions
            
            return descriptions
            
        except Exception as e:
            logger.error(f"Error generating segment descriptions: {e}")
            return {}


# Global settings compatibility - will be deprecated in future versions
settings = {}

def get_contrast_color(hex_color: str) -> str:
    """
    Legacy function for color contrast calculation.
    
    This function is maintained for backwards compatibility.
    New code should use ColorUtilities.get_contrast_color() instead.
    """
    from .color_utilities import ColorUtilities
    return ColorUtilities.get_contrast_color(hex_color)

def render_colourful_output(text: str, pitch_letter: str, element_type: str, settings_dict: Dict[str, Any]) -> str:
    """
    Legacy function for colored text rendering.
    
    This function is maintained for backwards compatibility.
    New code should use ColorRenderer.render_colored_text() instead.
    """
    try:
        from .color_utilities import ColorRenderer
        from .settings_manager import TalkingScoresSettings
        
        # Convert settings dict to proper settings object
        settings_obj = TalkingScoresSettings.from_dict(settings_dict)
        color_renderer = ColorRenderer(settings_obj.colors)
        
        return color_renderer.render_colored_text(text, pitch_letter, element_type)
    except Exception as e:
        logger.error(f"Error in legacy color rendering: {e}")
        return text  # Fallback to uncolored text


# Backwards compatibility exports
__all__ = [
    'Music21TalkingScore',
    'HTMLTalkingScoreFormatter', 
    'TalkingScoreBase',
    'TalkingScoreError',
    'ScoreParsingError',
    'AnalysisError',
    'get_contrast_color',
    'render_colourful_output'
]
                