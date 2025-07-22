"""
Musical Events Module

This module provides classes for representing musical events in a talking score,
with proper rendering and context management for accessibility.
"""

import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

logger = logging.getLogger("TSScore")


@dataclass
class RenderContext:
    """
    Context information for rendering musical events.
    
    This class tracks the rendering state to allow for intelligent
    decisions about when to include or omit certain information.
    """
    previous_event: Optional['TSEvent'] = None
    previous_pitch: Optional['TSPitch'] = None
    bar_number: int = 1
    beat_number: float = 1.0
    time_signature: Optional[str] = None
    key_signature: Optional[str] = None
    is_first_event_in_bar: bool = True
    is_first_event_in_beat: bool = True
    accidental_state: Dict[str, Any] = field(default_factory=dict)
    
    def update_for_new_bar(self, bar_number: int):
        """Update context for a new bar."""
        self.bar_number = bar_number
        self.beat_number = 1.0
        self.is_first_event_in_bar = True
        self.is_first_event_in_beat = True
        # Clear accidental state for new bar (depends on key signature mode)
        if hasattr(self, 'clear_accidentals_on_bar'):
            self.accidental_state.clear()
    
    def update_for_new_beat(self, beat_number: float):
        """Update context for a new beat."""
        self.beat_number = beat_number
        self.is_first_event_in_beat = True
    
    def update_for_event(self, event: 'TSEvent'):
        """Update context after processing an event."""
        self.previous_event = event
        self.is_first_event_in_bar = False
        self.is_first_event_in_beat = False


class TSEvent(ABC):
    """
    Abstract base class for all talking score events.
    
    This class defines the interface that all musical events must implement
    for consistent rendering and behavior.
    """
    
    def __init__(self):
        self.duration_text = ""
        self.tuplet_text = ""
        self.end_tuplet_text = ""
        self.bar_number = None
        self.beat_position = 0.0
        self.tie_info = None
        self.start_offset = 0.0
        self.expressions = []
    
    @abstractmethod
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """
        Render this event to a list of text elements.
        
        Args:
            settings: Application settings object
            context: Optional rendering context
            
        Returns:
            List of text elements describing this event
        """
        pass
    
    def render_duration(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """
        Render duration information for this event.
        
        Args:
            settings: Application settings object
            context: Optional rendering context
            
        Returns:
            List of duration-related text elements
        """
        if settings.rendering.rhythm_description == 'none':
            return []
        
        elements = []
        
        # Add tuplet start if present
        if self.tuplet_text:
            elements.append(self.tuplet_text)
        
        # Add duration description
        if self.duration_text and self._should_announce_duration(settings, context):
            elements.append(self.duration_text)
        
        # Add tuplet end if present
        if self.end_tuplet_text:
            elements.append(self.end_tuplet_text)
        
        return elements
    
    def _should_announce_duration(self, settings, context: Optional[RenderContext]) -> bool:
        """Determine if duration should be announced based on settings and context."""
        if settings.rendering.rhythm_announcement == "everyNote":
            return True
        elif settings.rendering.rhythm_announcement == "onChange":
            if context is None or context.previous_event is None:
                return True
            return context.previous_event.duration_text != self.duration_text
        return True
    
    def render_tie(self, settings) -> List[str]:
        """Render tie information if present."""
        if self.tie_info and settings.content.include_ties:
            return [f"tie {self.tie_info}"]
        return []


class TSPitch:
    """
    Represents a musical pitch with octave and accidental information.
    """
    
    def __init__(self, pitch_name: str, octave: str, pitch_number: float, pitch_letter: str):
        self.pitch_name = pitch_name
        self.octave = octave
        self.pitch_number = pitch_number
        self.pitch_letter = pitch_letter  # For color mapping
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """
        Render this pitch to text elements.
        
        Args:
            settings: Application settings object
            context: Optional rendering context for octave decisions
            
        Returns:
            List of text elements describing this pitch
        """
        elements = []
        
        # Determine octave placement
        if settings.rendering.octave_position == "before":
            octave_text = self._render_octave(settings, context)
            if octave_text:
                elements.append(octave_text)
        
        # Add pitch name
        if settings.rendering.pitch_description != 'none':
            # Apply coloring if enabled
            if hasattr(settings, 'colors') and settings.colors.colour_pitch:
                from lib.color_utilities import ColorRenderer
                color_renderer = ColorRenderer(settings.colors)
                pitch_text = color_renderer.render_colored_text(
                    self.pitch_name, self.pitch_letter, "pitch"
                )
            else:
                pitch_text = self.pitch_name
            elements.append(pitch_text)
        
        # Add octave after if configured
        if settings.rendering.octave_position == "after":
            octave_text = self._render_octave(settings, context)
            if octave_text:
                elements.append(octave_text)
        
        return elements
    
    def _render_octave(self, settings, context: Optional[RenderContext]) -> str:
        """Render octave information based on settings and context."""
        if settings.rendering.octave_description == 'none':
            return ""
        
        # Determine if octave should be shown
        show_octave = False
        
        if settings.rendering.octave_announcement == "everyNote":
            show_octave = True
        elif settings.rendering.octave_announcement == "firstNote":
            show_octave = (context is None or context.previous_pitch is None)
        elif settings.rendering.octave_announcement == "onChange":
            if context is None or context.previous_pitch is None:
                show_octave = True
            elif context.previous_pitch.octave != self.octave:
                show_octave = True
        elif settings.rendering.octave_announcement == "brailleRules":
            show_octave = self._apply_braille_octave_rules(context)
        
        if show_octave:
            # Apply coloring if enabled
            if hasattr(settings, 'colors') and hasattr(settings.colors, 'octave_colour_mode'):
                if settings.colors.octave_colour_mode != 'none':
                    from lib.color_utilities import ColorRenderer
                    color_renderer = ColorRenderer(settings.colors)
                    return color_renderer.render_colored_text(
                        self.octave, self.pitch_letter, "octave"
                    )
            return self.octave
        
        return ""
    
    def _apply_braille_octave_rules(self, context: Optional[RenderContext]) -> bool:
        """Apply braille music octave announcement rules."""
        if context is None or context.previous_pitch is None:
            return True
        
        # Calculate interval from previous pitch
        pitch_difference = abs(context.previous_pitch.pitch_number - self.pitch_number)
        
        # 3rd or less: don't announce octave
        if pitch_difference <= 4:
            return False
        # 4th or 5th with octave change: announce octave
        elif 5 <= pitch_difference <= 7:
            return context.previous_pitch.octave != self.octave
        # More than 5th: always announce octave
        else:
            return True


class TSNote(TSEvent):
    """
    Represents a single musical note.
    """
    
    def __init__(self):
        super().__init__()
        self.pitch: Optional[TSPitch] = None
        self.expressions = []
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """Render this note to text elements."""
        elements = []
        
        # Add expressions (ornaments, articulations, etc.)
        for expression in self.expressions:
            # Filter arpeggios based on settings
            is_arpeggio = 'arpeggio' in expression.name.lower() if hasattr(expression, 'name') else False
            if not is_arpeggio or settings.content.include_arpeggios:
                elements.append(expression.name if hasattr(expression, 'name') else str(expression))
        
        # Add duration information
        elements.extend(self.render_duration(settings, context))
        
        # Add pitch information
        if self.pitch:
            previous_pitch = context.previous_pitch if context else None
            elements.extend(self.pitch.render(settings, context))
            
            # Update context with current pitch
            if context:
                context.previous_pitch = self.pitch
        
        # Add tie information
        elements.extend(self.render_tie(settings))
        
        return [elem for elem in elements if elem]  # Filter out empty elements


class TSChord(TSEvent):
    """
    Represents a musical chord (multiple simultaneous pitches).
    """
    
    def __init__(self):
        super().__init__()
        self.pitches: List[TSPitch] = []
        self.chord_name: Optional[str] = None
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """Render this chord to text elements."""
        elements = []
        
        # Add chord description if enabled
        if settings.content.describe_chords and len(self.pitches) > 1:
            elements.append(f'{len(self.pitches)}-note chord')
        
        # Add duration information
        elements.extend(self.render_duration(settings, context))
        
        # Add individual pitches (sorted by pitch height)
        if self.pitches:
            sorted_pitches = sorted(self.pitches, key=lambda p: p.pitch_number)
            previous_pitch = context.previous_pitch if context else None
            
            for pitch in sorted_pitches:
                elements.extend(pitch.render(settings, context))
                previous_pitch = pitch
            
            # Update context with highest pitch
            if context:
                context.previous_pitch = sorted_pitches[-1]
        
        # Add tie information
        elements.extend(self.render_tie(settings))
        
        return [elem for elem in elements if elem]


class TSRest(TSEvent):
    """
    Represents a musical rest (silence).
    """
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """Render this rest to text elements."""
        if not settings.content.include_rests:
            return []
        
        elements = []
        
        # Add duration information
        elements.extend(self.render_duration(settings, context))
        
        # Add rest indication
        elements.append('rest')
        
        return [elem for elem in elements if elem]


class TSUnpitched(TSEvent):
    """
    Represents an unpitched percussion note.
    """
    
    def __init__(self):
        super().__init__()
        self.instrument_name = "unpitched"
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """Render this unpitched note to text elements."""
        elements = []
        
        # Add duration information
        elements.extend(self.render_duration(settings, context))
        
        # Add instrument/unpitched indication
        elements.append(self.instrument_name)
        
        return [elem for elem in elements if elem]


class TSDynamic(TSEvent):
    """
    Represents a dynamic marking (forte, piano, etc.).
    """
    
    def __init__(self, short_name: Optional[str] = None, long_name: Optional[str] = None):
        super().__init__()
        self.short_name = short_name
        self.long_name = long_name or short_name
    
    def render(self, settings, context: Optional[RenderContext] = None) -> List[str]:
        """Render this dynamic marking to text elements."""
        if not settings.content.include_dynamics:
            return []
        
        if self.long_name:
            return [f'[{self.long_name.capitalize()}]']
        return []


class MusicalEventFactory:
    """
    Factory class for creating TSEvent objects from music21 elements.
    
    This class handles the conversion from music21's representation
    to our talking score representation.
    """
    
    @staticmethod
    def create_event_from_music21(element, settings_dict: Dict[str, Any]) -> Optional[TSEvent]:
        """
        Create a TSEvent from a music21 element.
        
        Args:
            element: music21 element (Note, Rest, Chord, etc.)
            settings_dict: Dictionary of application settings
            
        Returns:
            Appropriate TSEvent subclass or None if not supported
        """
        try:
            element_type = type(element).__name__
            
            if element_type == 'Note':
                return MusicalEventFactory._create_note(element, settings_dict)
            elif element_type == 'Rest':
                return MusicalEventFactory._create_rest(element, settings_dict)
            elif element_type == 'Chord':
                return MusicalEventFactory._create_chord(element, settings_dict)
            elif element_type == 'Dynamic':
                return MusicalEventFactory._create_dynamic(element, settings_dict)
            elif element_type == 'Unpitched':
                return MusicalEventFactory._create_unpitched(element, settings_dict)
            else:
                logger.debug(f"Unsupported element type: {element_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating event from music21 element: {e}")
            return None
    
    @staticmethod
    def _create_note(note_element, settings_dict: Dict[str, Any]) -> TSNote:
        """Create a TSNote from a music21 Note."""
        event = TSNote()
        
        # Create pitch representation
        from lib.talkingscoreslib import PitchMapper
        
        # Create a minimal settings object for the pitch mapper
        class MinimalSettings:
            class Rendering:
                def __init__(self, settings_dict):
                    self.pitch_description = settings_dict.get('pitch_description', 'noteName')
                    self.octave_description = settings_dict.get('octave_description', 'name')
                    self.accidental_style = settings_dict.get('accidental_style', 'words')
                    self.key_signature_accidentals = settings_dict.get('key_signature_accidentals', 'applied')
            
            def __init__(self, settings_dict):
                self.rendering = self.Rendering(settings_dict)
        
        minimal_settings = MinimalSettings(settings_dict)
        pitch_mapper = PitchMapper(minimal_settings)
        
        pitch_name = pitch_mapper.map_pitch(note_element.pitch)
        octave_name = pitch_mapper.map_octave(note_element.pitch.octave)
        
        event.pitch = TSPitch(
            pitch_name=pitch_name,
            octave=octave_name,
            pitch_number=note_element.pitch.ps,
            pitch_letter=note_element.pitch.step
        )
        
        # Set duration and other properties
        MusicalEventFactory._set_common_properties(event, note_element, settings_dict)
        
        # Add expressions
        if hasattr(note_element, 'expressions'):
            event.expressions = note_element.expressions
        
        # Add tie information
        if hasattr(note_element, 'tie') and note_element.tie:
            event.tie_info = note_element.tie.type
        
        return event
    
    @staticmethod
    def _create_rest(rest_element, settings_dict: Dict[str, Any]) -> TSRest:
        """Create a TSRest from a music21 Rest."""
        event = TSRest()
        MusicalEventFactory._set_common_properties(event, rest_element, settings_dict)
        return event
    
    @staticmethod
    def _create_chord(chord_element, settings_dict: Dict[str, Any]) -> TSChord:
        """Create a TSChord from a music21 Chord."""
        event = TSChord()
        
        # Create pitch representations for all pitches in the chord
        from lib.talkingscoreslib import PitchMapper
        
        class MinimalSettings:
            class Rendering:
                def __init__(self, settings_dict):
                    self.pitch_description = settings_dict.get('pitch_description', 'noteName')
                    self.octave_description = settings_dict.get('octave_description', 'name')
                    self.accidental_style = settings_dict.get('accidental_style', 'words')
                    self.key_signature_accidentals = settings_dict.get('key_signature_accidentals', 'applied')
            
            def __init__(self, settings_dict):
                self.rendering = self.Rendering(settings_dict)
        
        minimal_settings = MinimalSettings(settings_dict)
        pitch_mapper = PitchMapper(minimal_settings)
        
        for pitch in chord_element.pitches:
            pitch_name = pitch_mapper.map_pitch(pitch)
            octave_name = pitch_mapper.map_octave(pitch.octave)
            
            ts_pitch = TSPitch(
                pitch_name=pitch_name,
                octave=octave_name,
                pitch_number=pitch.ps,
                pitch_letter=pitch.step
            )
            event.pitches.append(ts_pitch)
        
        # Set chord name if available
        try:
            event.chord_name = chord_element.commonName
        except:
            event.chord_name = f"{len(event.pitches)}-note chord"
        
        # Set duration and other properties
        MusicalEventFactory._set_common_properties(event, chord_element, settings_dict)
        
        # Add tie information
        if hasattr(chord_element, 'tie') and chord_element.tie:
            event.tie_info = chord_element.tie.type
        
        return event
    
    @staticmethod
    def _create_dynamic(dynamic_element, settings_dict: Dict[str, Any]) -> TSDynamic:
        """Create a TSDynamic from a music21 Dynamic."""
        long_name = getattr(dynamic_element, 'longName', None)
        short_name = getattr(dynamic_element, 'value', None)
        return TSDynamic(short_name=short_name, long_name=long_name)
    
    @staticmethod
    def _create_unpitched(unpitched_element, settings_dict: Dict[str, Any]) -> TSUnpitched:
        """Create a TSUnpitched from a music21 Unpitched element."""
        event = TSUnpitched()
        MusicalEventFactory._set_common_properties(event, unpitched_element, settings_dict)
        return event
    
    @staticmethod
    def _set_common_properties(event: TSEvent, music21_element, settings_dict: Dict[str, Any]):
        """Set properties common to all events."""
        # Set timing information
        if hasattr(music21_element, 'offset'):
            event.start_offset = music21_element.offset
        if hasattr(music21_element, 'beat'):
            event.beat_position = music21_element.beat
        if hasattr(music21_element, 'measureNumber'):
            event.bar_number = music21_element.measureNumber
        
        # Set duration information
        if hasattr(music21_element, 'duration'):
            from lib.talkingscoreslib import DurationMapper
            
            class MinimalSettings:
                class Rendering:
                    def __init__(self, settings_dict):
                        self.rhythm_description = settings_dict.get('rhythm_description', 'british')
                        self.dot_position = settings_dict.get('dot_position', 'before')
                
                def __init__(self, settings_dict):
                    self.rendering = self.Rendering(settings_dict)
            
            minimal_settings = MinimalSettings(settings_dict)
            duration_mapper = DurationMapper(minimal_settings)
            event.duration_text = duration_mapper.map_duration(music21_element.duration)
        
        # Handle tuplets
        if hasattr(music21_element, 'duration') and hasattr(music21_element.duration, 'tuplets'):
            tuplets = music21_element.duration.tuplets
            if tuplets:
                tuplet = tuplets[0]
                if tuplet.type == "start":
                    if tuplet.fullName == "Triplet":
                        event.tuplet_text = "triplets"
                    else:
                        actual = tuplet.tupletActual[0] if tuplet.tupletActual else "?"
                        normal = tuplet.tupletNormal[0] if tuplet.tupletNormal else "?"
                        event.tuplet_text = f"{tuplet.fullName} ({actual} in {normal})"
                elif tuplet.type == "stop" and tuplet.fullName != "Triplet":
                    event.end_tuplet_text = "end tuplet"