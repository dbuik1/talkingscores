"""
Template Rendering Module

This module handles template management, context preparation,
and rendering for the Talking Scores HTML generation.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("TSScore")


@dataclass
class TemplateContext:
    """
    Container for template rendering context.
    
    This class organizes all the data needed for template rendering
    into logical groups for easier management.
    """
    # Basic score information
    title: str = "Unknown Title"
    composer: str = "Unknown Composer"
    
    # Musical structure
    time_signature: str = ""
    key_signature: str = ""
    tempo: str = ""
    number_of_bars: int = 0
    number_of_parts: int = 0
    
    # Playback information
    play_all: bool = False
    play_selected: bool = False
    play_unselected: bool = False
    
    # Instrument information
    instruments: Dict[int, List] = None
    part_names: Dict[int, str] = None
    selected_part_names: List[str] = None
    
    # MIDI URLs and contexts
    full_score_midis: Dict[str, Any] = None
    music_segments: List[Dict[str, Any]] = None
    
    # Analysis information
    general_summary: str = ""
    parts_summary: List[str] = None
    repetition_in_contexts: Dict[int, str] = None
    immediate_repetition_contexts: Dict[int, Dict[str, str]] = None
    
    # Metadata for bars
    time_and_keys: Dict[int, List[str]] = None
    
    # Settings and options
    settings: Dict[str, Any] = None
    beat_division_options: List[Dict[str, str]] = None
    
    # Binary representations for MIDI generation
    binary_selected_instruments: int = 0
    binary_play_all: int = 0
    
    def __post_init__(self):
        """Initialize None fields with empty defaults."""
        if self.instruments is None:
            self.instruments = {}
        if self.part_names is None:
            self.part_names = {}
        if self.selected_part_names is None:
            self.selected_part_names = []
        if self.full_score_midis is None:
            self.full_score_midis = {}
        if self.music_segments is None:
            self.music_segments = []
        if self.parts_summary is None:
            self.parts_summary = []
        if self.repetition_in_contexts is None:
            self.repetition_in_contexts = {}
        if self.immediate_repetition_contexts is None:
            self.immediate_repetition_contexts = {}
        if self.time_and_keys is None:
            self.time_and_keys = {}
        if self.settings is None:
            self.settings = {}
        if self.beat_division_options is None:
            self.beat_division_options = []


class TemplateContextBuilder:
    """
    Builder class for constructing template contexts.
    
    This class provides a fluent interface for building complex
    template contexts step by step.
    """
    
    def __init__(self):
        self.context = TemplateContext()
    
    def with_basic_info(self, title: str, composer: str) -> 'TemplateContextBuilder':
        """Add basic score information."""
        self.context.title = title
        self.context.composer = composer
        return self
    
    def with_musical_structure(self, time_sig: str, key_sig: str, tempo: str,
                             num_bars: int, num_parts: int) -> 'TemplateContextBuilder':
        """Add musical structure information."""
        self.context.time_signature = time_sig
        self.context.key_signature = key_sig
        self.context.tempo = tempo
        self.context.number_of_bars = num_bars
        self.context.number_of_parts = num_parts
        return self
    
    def with_playback_options(self, play_all: bool, play_selected: bool,
                            play_unselected: bool) -> 'TemplateContextBuilder':
        """Add playback option flags."""
        self.context.play_all = play_all
        self.context.play_selected = play_selected
        self.context.play_unselected = play_unselected
        return self
    
    def with_instruments(self, instruments: Dict[int, List], part_names: Dict[int, str],
                        selected_part_names: List[str]) -> 'TemplateContextBuilder':
        """Add instrument information."""
        self.context.instruments = instruments
        self.context.part_names = part_names
        self.context.selected_part_names = selected_part_names
        return self
    
    def with_midi_context(self, full_score_midis: Dict[str, Any],
                         music_segments: List[Dict[str, Any]]) -> 'TemplateContextBuilder':
        """Add MIDI URLs and context."""
        self.context.full_score_midis = full_score_midis
        self.context.music_segments = music_segments
        return self
    
    def with_analysis(self, general_summary: str, parts_summary: List[str],
                     repetition_contexts: Dict[int, str],
                     immediate_contexts: Dict[int, Dict[str, str]]) -> 'TemplateContextBuilder':
        """Add musical analysis information."""
        self.context.general_summary = general_summary
        self.context.parts_summary = parts_summary
        self.context.repetition_in_contexts = repetition_contexts
        self.context.immediate_repetition_contexts = immediate_contexts
        return self
    
    def with_metadata(self, time_and_keys: Dict[int, List[str]]) -> 'TemplateContextBuilder':
        """Add bar metadata."""
        self.context.time_and_keys = time_and_keys
        return self
    
    def with_settings(self, settings: Dict[str, Any],
                     beat_options: List[Dict[str, str]]) -> 'TemplateContextBuilder':
        """Add settings and options."""
        self.context.settings = settings
        self.context.beat_division_options = beat_options
        return self
    
    def with_binary_flags(self, binary_instruments: int,
                         binary_play_all: int) -> 'TemplateContextBuilder':
        """Add binary representation flags."""
        self.context.binary_selected_instruments = binary_instruments
        self.context.binary_play_all = binary_play_all
        return self
    
    def build(self) -> TemplateContext:
        """Build and return the completed context."""
        return self.context


class TemplateManager:
    """
    Manages template loading, context preparation, and rendering.
    
    This class provides a centralized way to handle all template-related
    operations for the Talking Scores application.
    """
    
    def __init__(self, template_directory: Optional[str] = None):
        """
        Initialize the template manager.
        
        Args:
            template_directory: Directory containing templates. If None, uses default.
        """
        if template_directory is None:
            # Default to the lib directory where templates are located
            template_directory = os.path.dirname(__file__)
        
        self.template_directory = template_directory
        self._jinja_env = None
    
    @property
    def jinja_env(self):
        """Lazy-loaded Jinja2 environment."""
        if self._jinja_env is None:
            try:
                from jinja2 import Environment, FileSystemLoader
                self._jinja_env = Environment(
                    loader=FileSystemLoader(self.template_directory),
                    autoescape=True,  # Enable auto-escaping for security
                    trim_blocks=True,
                    lstrip_blocks=True
                )
                
                # Add custom filters if needed
                self._register_custom_filters()
                
            except ImportError:
                logger.error("Jinja2 not available for template rendering")
                raise
        
        return self._jinja_env
    
    def _register_custom_filters(self):
        """Register custom Jinja2 filters for musical content."""
        
        def format_bar_range(start_bar, end_bar):
            """Format a bar range for display."""
            if start_bar == 'Pickup':
                return 'Pickup Bar'
            elif start_bar == end_bar:
                return f'Bar {start_bar}'
            else:
                return f'Bars {start_bar} to {end_bar}'
        
        def format_instrument_name(instrument_info, part_names, instrument_num):
            """Format an instrument name with part information."""
            if not instrument_info:
                return f"Instrument {instrument_num}"
            
            name = instrument_info[0]
            part_count = instrument_info[2] if len(instrument_info) > 2 else 1
            
            if part_count == 1:
                return name
            else:
                return f"{name} (multi-part)"
        
        def safe_get(dictionary, key, default=""):
            """Safely get a value from a dictionary."""
            if isinstance(dictionary, dict):
                return dictionary.get(key, default)
            return default
        
        # Register filters
        self.jinja_env.filters['format_bar_range'] = format_bar_range
        self.jinja_env.filters['format_instrument_name'] = format_instrument_name
        self.jinja_env.filters['safe_get'] = safe_get
    
    def render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Render a template with the given context.
        
        Args:
            template_name: Name of the template file
            context: Context dictionary for template rendering
            
        Returns:
            Rendered template as string
            
        Raises:
            TemplateNotFound: If template file doesn't exist
            TemplateRuntimeError: If rendering fails
        """
        try:
            template = self.jinja_env.get_template(template_name)
            return template.render(context)
            
        except Exception as e:
            logger.error(f"Error rendering template {template_name}: {e}")
            raise
    
    def render_talking_score(self, context: TemplateContext) -> str:
        """
        Render the main talking score template.
        
        Args:
            context: Template context object
            
        Returns:
            Rendered HTML as string
        """
        # Convert context object to dictionary for Jinja2
        context_dict = self._context_to_dict(context)
        
        # Add some computed values for convenience
        context_dict.update({
            'basic_information': {
                'title': context.title,
                'composer': context.composer
            },
            'preamble': {
                'time_signature': context.time_signature,
                'key_signature': context.key_signature,
                'tempo': context.tempo,
                'number_of_bars': context.number_of_bars,
                'number_of_parts': context.number_of_parts,
            }
        })
        
        return self.render_template('talkingscore.html', context_dict)
    
    def _context_to_dict(self, context: TemplateContext) -> Dict[str, Any]:
        """Convert a TemplateContext object to a dictionary."""
        return {
            'settings': context.settings,
            'instruments': context.instruments,
            'part_names': context.part_names,
            'selected_part_names': context.selected_part_names,
            'full_score_midis': context.full_score_midis,
            'music_segments': context.music_segments,
            'general_summary': context.general_summary,
            'parts_summary': context.parts_summary,
            'repetition_in_contexts': context.repetition_in_contexts,
            'immediate_repetition_contexts': context.immediate_repetition_contexts,
            'time_and_keys': context.time_and_keys,
            'beat_division_options': context.beat_division_options,
            'binary_selected_instruments': context.binary_selected_instruments,
            'binary_play_all': context.binary_play_all,
            'play_all': context.play_all,
            'play_selected': context.play_selected,
            'play_unselected': context.play_unselected,
        }
    
    def validate_template_context(self, context: Dict[str, Any]) -> List[str]:
        """
        Validate that a template context has all required fields.
        
        Args:
            context: Context dictionary to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        required_fields = [
            'basic_information', 'preamble', 'settings',
            'instruments', 'music_segments'
        ]
        
        for field in required_fields:
            if field not in context:
                errors.append(f"Missing required field: {field}")
        
        # Validate nested structures
        if 'basic_information' in context:
            basic_info = context['basic_information']
            if not isinstance(basic_info, dict) or 'title' not in basic_info:
                errors.append("basic_information must be a dict with 'title' field")
        
        if 'preamble' in context:
            preamble = context['preamble']
            if not isinstance(preamble, dict):
                errors.append("preamble must be a dict")
        
        return errors
    
    def create_error_template_context(self, error_message: str) -> Dict[str, Any]:
        """
        Create a minimal template context for error display.
        
        Args:
            error_message: Error message to display
            
        Returns:
            Minimal context dictionary for error template
        """
        return {
            'basic_information': {
                'title': 'Error',
                'composer': 'System'
            },
            'preamble': {
                'time_signature': '',
                'key_signature': '',
                'tempo': '',
                'number_of_bars': 0,
                'number_of_parts': 0,
            },
            'settings': {},
            'instruments': {},
            'part_names': {},
            'selected_part_names': [],
            'full_score_midis': {},
            'music_segments': [],
            'general_summary': f"Error: {error_message}",
            'parts_summary': [],
            'repetition_in_contexts': {},
            'immediate_repetition_contexts': {},
            'time_and_keys': {},
            'beat_division_options': [],
            'binary_selected_instruments': 0,
            'binary_play_all': 0,
            'play_all': False,
            'play_selected': False,
            'play_unselected': False,
        }
    
    def get_available_templates(self) -> List[str]:
        """
        Get a list of available template files.
        
        Returns:
            List of template filenames
        """
        try:
            template_files = []
            for filename in os.listdir(self.template_directory):
                if filename.endswith(('.html', '.htm', '.xml', '.txt')):
                    template_files.append(filename)
            return sorted(template_files)
        except OSError:
            logger.error(f"Could not list templates in {self.template_directory}")
            return []