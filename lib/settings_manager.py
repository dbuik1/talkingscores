"""
Settings and Configuration Management for Talking Scores

This module provides centralized configuration management with validation
and type safety for all application settings.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
import logging
import json
from pathlib import Path

logger = logging.getLogger("TSScore")


@dataclass
class RenderingSettings:
    """Settings for musical content rendering."""
    rhythm_description: str = 'british'
    dot_position: str = 'before'
    octave_description: str = 'name'
    pitch_description: str = 'noteName'
    octave_position: str = 'before'
    octave_announcement: str = 'onChange'
    rhythm_announcement: str = 'onChange'
    
    # Content inclusion settings
    include_rests: bool = True
    include_ties: bool = True
    include_arpeggios: bool = True
    include_dynamics: bool = True
    describe_chords: bool = True
    
    # Accidental handling
    accidental_style: str = 'words'
    key_signature_accidentals: str = 'applied'
    
    # Repetition analysis
    repetition_mode: str = 'learning'
    
    def validate(self) -> bool:
        """Validate all settings have valid values."""
        valid_rhythm_descriptions = ['british', 'american', 'none']
        valid_dot_positions = ['before', 'after']
        valid_octave_descriptions = ['name', 'number', 'figureNotes', 'none']
        valid_pitch_descriptions = ['noteName', 'colourNotes', 'phonetic', 'none']
        valid_positions = ['before', 'after']
        valid_announcements = ['onChange', 'everyNote', 'firstNote', 'brailleRules']
        valid_accidental_styles = ['words', 'symbols']
        valid_key_sig_modes = ['applied', 'onChange', 'standard']
        valid_repetition_modes = ['none', 'learning', 'detailed']
        
        validations = [
            (self.rhythm_description in valid_rhythm_descriptions, "Invalid rhythm_description"),
            (self.dot_position in valid_dot_positions, "Invalid dot_position"),
            (self.octave_description in valid_octave_descriptions, "Invalid octave_description"),
            (self.pitch_description in valid_pitch_descriptions, "Invalid pitch_description"),
            (self.octave_position in valid_positions, "Invalid octave_position"),
            (self.octave_announcement in valid_announcements, "Invalid octave_announcement"),
            (self.rhythm_announcement in valid_announcements, "Invalid rhythm_announcement"),
            (self.accidental_style in valid_accidental_styles, "Invalid accidental_style"),
            (self.key_signature_accidentals in valid_key_sig_modes, "Invalid key_signature_accidentals"),
            (self.repetition_mode in valid_repetition_modes, "Invalid repetition_mode"),
        ]
        
        for is_valid, error_msg in validations:
            if not is_valid:
                logger.error(error_msg)
                return False
        
        return True


@dataclass
class ColorSettings:
    """Settings for color rendering and visual styling."""
    colour_position: str = 'none'
    colour_pitch: bool = False
    rhythm_colour_mode: str = 'none'
    octave_colour_mode: str = 'none'
    figure_note_colours: Dict[str, str] = field(default_factory=dict)
    advanced_rhythm_colours: Dict[str, str] = field(default_factory=dict)
    advanced_octave_colours: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize default color palettes if empty."""
        if not self.figure_note_colours:
            self.figure_note_colours = {
                'C': '#FF0000', 'D': '#A52A2A', 'E': '#808080', 'F': '#0000FF',
                'G': '#000000', 'A': '#FFFF00', 'B': '#008000'
            }
    
    def validate(self) -> bool:
        """Validate color settings."""
        valid_positions = ['none', 'text', 'background']
        valid_colour_modes = ['none', 'inherit', 'custom']
        
        if self.colour_position not in valid_positions:
            logger.error(f"Invalid colour_position: {self.colour_position}")
            return False
        
        if self.rhythm_colour_mode not in valid_colour_modes:
            logger.error(f"Invalid rhythm_colour_mode: {self.rhythm_colour_mode}")
            return False
        
        if self.octave_colour_mode not in valid_colour_modes:
            logger.error(f"Invalid octave_colour_mode: {self.octave_colour_mode}")
            return False
        
        return True


@dataclass
class PlaybackSettings:
    """Settings for MIDI playback and generation."""
    play_all: bool = False
    play_selected: bool = False
    play_unselected: bool = False
    instruments: List[int] = field(default_factory=list)
    bars_at_a_time: int = 2
    beat_division: Optional[str] = None
    
    def validate(self) -> bool:
        """Validate playback settings."""
        if self.bars_at_a_time not in [1, 2, 4, 8]:
            logger.error(f"Invalid bars_at_a_time: {self.bars_at_a_time}")
            return False
        
        if not isinstance(self.instruments, list):
            logger.error("instruments must be a list")
            return False
        
        return True


@dataclass
class TalkingScoresSettings:
    """Main settings container for the Talking Scores application."""
    rendering: RenderingSettings = field(default_factory=RenderingSettings)
    colors: ColorSettings = field(default_factory=ColorSettings)
    playback: PlaybackSettings = field(default_factory=PlaybackSettings)
    
    def validate(self) -> bool:
        """Validate all settings."""
        return (self.rendering.validate() and 
                self.colors.validate() and 
                self.playback.validate())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TalkingScoresSettings':
        """Create settings from dictionary (e.g., from JSON file)."""
        try:
            rendering_data = {}
            colors_data = {}
            playback_data = {}
            
            # Map flat dictionary keys to nested structure
            for key, value in data.items():
                if key in ['rhythm_description', 'dot_position', 'octave_description', 
                          'pitch_description', 'octave_position', 'octave_announcement',
                          'rhythm_announcement', 'include_rests', 'include_ties',
                          'include_arpeggios', 'include_dynamics', 'describe_chords',
                          'accidental_style', 'key_signature_accidentals', 'repetition_mode']:
                    rendering_data[key] = value
                elif key in ['colour_position', 'colour_pitch', 'rhythm_colour_mode',
                            'octave_colour_mode', 'figureNoteColours', 'advanced_rhythm_colours',
                            'advanced_octave_colours']:
                    if key == 'figureNoteColours':
                        colors_data['figure_note_colours'] = value
                    else:
                        colors_data[key] = value
                elif key in ['play_all', 'play_selected', 'play_unselected', 'instruments',
                            'bars_at_a_time', 'beat_division']:
                    playback_data[key] = value
            
            return cls(
                rendering=RenderingSettings(**rendering_data),
                colors=ColorSettings(**colors_data),
                playback=PlaybackSettings(**playback_data)
            )
        except Exception as e:
            logger.error(f"Error creating settings from dict: {e}")
            return cls()  # Return defaults on error
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to flat dictionary for template use."""
        result = {}
        
        # Rendering settings
        for field_name, field_value in self.rendering.__dict__.items():
            result[field_name] = field_value
        
        # Color settings  
        for field_name, field_value in self.colors.__dict__.items():
            if field_name == 'figure_note_colours':
                result['figureNoteColours'] = field_value
            else:
                result[field_name] = field_value
        
        # Playback settings
        for field_name, field_value in self.playback.__dict__.items():
            result[field_name] = field_value
        
        return result


class SettingsManager:
    """
    Centralized settings management with file I/O and validation.
    
    This class handles loading, saving, and validating application settings
    while providing a clean interface for the rest of the application.
    """
    
    def __init__(self, default_settings: Optional[TalkingScoresSettings] = None):
        self._settings = default_settings or TalkingScoresSettings()
        self._settings_cache = {}
    
    @property
    def settings(self) -> TalkingScoresSettings:
        """Get current settings."""
        return self._settings
    
    def load_from_file(self, file_path: Union[str, Path]) -> bool:
        """
        Load settings from a JSON file.
        
        Args:
            file_path: Path to the settings file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning(f"Settings file not found: {file_path}")
                return False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._settings = TalkingScoresSettings.from_dict(data)
            
            if not self._settings.validate():
                logger.error("Loaded settings failed validation, using defaults")
                self._settings = TalkingScoresSettings()
                return False
            
            logger.info(f"Successfully loaded settings from {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading settings from {file_path}: {e}")
            self._settings = TalkingScoresSettings()
            return False
    
    def save_to_file(self, file_path: Union[str, Path]) -> bool:
        """
        Save current settings to a JSON file.
        
        Args:
            file_path: Path where to save the settings
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            if not self._settings.validate():
                logger.error("Cannot save invalid settings")
                return False
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._settings.to_dict(), f, indent=2)
            
            logger.info(f"Successfully saved settings to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving settings to {file_path}: {e}")
            return False
    
    def update_settings(self, **kwargs) -> bool:
        """
        Update settings with new values.
        
        Args:
            **kwargs: Setting keys and values to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create new settings from current + updates
            current_dict = self._settings.to_dict()
            current_dict.update(kwargs)
            
            new_settings = TalkingScoresSettings.from_dict(current_dict)
            
            if not new_settings.validate():
                logger.error("Updated settings failed validation")
                return False
            
            self._settings = new_settings
            return True
            
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return False
    
    def get_template_context(self) -> Dict[str, Any]:
        """Get settings formatted for template context."""
        return self._settings.to_dict()
    
    def reset_to_defaults(self):
        """Reset all settings to default values."""
        self._settings = TalkingScoresSettings()
        logger.info("Settings reset to defaults")