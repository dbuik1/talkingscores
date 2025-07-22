"""
MIDI Coordination Module

This module handles MIDI file generation coordination, URL generation,
and caching strategies for the Talking Scores application.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from urllib.parse import urlencode

logger = logging.getLogger("TSScore")


@dataclass
class MIDIRequest:
    """
    Represents a request for MIDI generation.
    
    This class encapsulates all the parameters needed to generate
    a specific MIDI file variation.
    """
    start_bar: int
    end_bar: int
    binary_selected_instruments: int
    binary_play_all: int
    selection_type: Optional[str] = None  # 'all', 'sel', 'un'
    instrument_number: Optional[int] = None
    part_number: Optional[int] = None
    tempo: int = 100
    click_track: str = 'n'
    
    def to_query_params(self) -> Dict[str, str]:
        """Convert this request to query parameters."""
        params = {
            'start': str(self.start_bar),
            'end': str(self.end_bar),
            'bsi': str(self.binary_selected_instruments),
            'bpi': str(self.binary_play_all),
            't': str(self.tempo),
            'c': self.click_track
        }
        
        if self.selection_type:
            params['sel'] = self.selection_type
        if self.instrument_number:
            params['ins'] = str(self.instrument_number)
        if self.part_number:
            params['part'] = str(self.part_number)
            
        return params


class MIDIUrlGenerator:
    """
    Generates MIDI URLs for different playback scenarios.
    
    This class handles the complex URL generation logic for all the different
    MIDI file variations that can be requested.
    """
    
    def __init__(self, base_url: str):
        """
        Initialize the URL generator.
        
        Args:
            base_url: Base URL for MIDI endpoints (e.g., "/midis/file_id/filename.xml")
        """
        self.base_url = base_url.rstrip('/')
    
    def generate_selection_urls(self, base_params: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate URLs for all/selected/unselected instrument combinations.
        
        Args:
            base_params: Base parameters including start, end, bsi, bpi
            
        Returns:
            Dictionary with 'midi_all', 'midi_sel', 'midi_un' URLs
        """
        urls = {}
        
        for selection in ['all', 'sel', 'un']:
            params = base_params.copy()
            params['sel'] = selection
            urls[f'midi_{selection}'] = self._build_url(params)
        
        return urls
    
    def generate_midi_url(self, suffix: str = "", **params) -> str:
        """
        Generate a MIDI URL with arbitrary parameters.
        
        Args:
            suffix: Optional suffix to append to base URL
            **params: Query parameters
            
        Returns:
            Complete MIDI URL
        """
        url = self.base_url
        if suffix:
            url += f"/{suffix}"
        
        if params:
            query_string = urlencode(params)
            url += f"?{query_string}"
        
        return url
    
    def generate_instrument_urls(self, instrument_num: int, base_params: Dict[str, Any],
                               part_count: int = 0) -> Dict[str, Any]:
        """
        Generate URLs for a specific instrument and its parts.
        
        Args:
            instrument_num: Instrument number
            base_params: Base parameters
            part_count: Number of parts this instrument has
            
        Returns:
            Dictionary with instrument MIDI URL and part URLs
        """
        # Main instrument URL
        params = base_params.copy()
        params['ins'] = instrument_num
        instrument_url = self._build_url(params)
        
        # Individual part URLs
        part_urls = []
        for part_index in range(part_count):
            part_params = base_params.copy()
            part_params['part'] = part_index
            part_urls.append(self._build_url(part_params))
        
        return {
            'ins': instrument_num,
            'midi': instrument_url,
            'midi_parts': part_urls
        }
    
    def _build_url(self, params: Dict[str, Any]) -> str:
        """Build a complete URL from parameters."""
        if params:
            query_string = urlencode({k: str(v) for k, v in params.items()})
            return f"{self.base_url}?{query_string}"
        return self.base_url


class MIDICacheManager:
    """
    Manages MIDI file caching and generation strategies.
    
    This class handles the logic for determining when MIDI files need
    to be generated and manages cache invalidation.
    """
    
    def __init__(self, cache_directory: str):
        """
        Initialize the cache manager.
        
        Args:
            cache_directory: Directory where MIDI files are cached
        """
        self.cache_directory = cache_directory
        self.generation_flags = {}  # Track what's been generated
    
    def is_segment_cached(self, start_bar: int, end_bar: int, cache_type: str = "ondemand") -> bool:
        """
        Check if a segment has been fully cached.
        
        Args:
            start_bar: Starting bar number
            end_bar: Ending bar number
            cache_type: Type of cache ("upfront" or "ondemand")
            
        Returns:
            True if segment is fully cached
        """
        flag_name = f"s{start_bar}e{end_bar}_{cache_type}.generated"
        flag_path = os.path.join(self.cache_directory, flag_name)
        return os.path.exists(flag_path)
    
    def mark_segment_cached(self, start_bar: int, end_bar: int, cache_type: str = "ondemand"):
        """
        Mark a segment as fully cached.
        
        Args:
            start_bar: Starting bar number
            end_bar: Ending bar number
            cache_type: Type of cache ("upfront" or "ondemand")
        """
        flag_name = f"s{start_bar}e{end_bar}_{cache_type}.generated"
        flag_path = os.path.join(self.cache_directory, flag_name)
        
        try:
            os.makedirs(self.cache_directory, exist_ok=True)
            with open(flag_path, 'w') as f:
                f.write("generated")
            logger.debug(f"Marked segment {start_bar}-{end_bar} as cached ({cache_type})")
        except OSError as e:
            logger.error(f"Could not mark segment as cached: {e}")
    
    def clear_cache(self, pattern: Optional[str] = None):
        """
        Clear cached files matching a pattern.
        
        Args:
            pattern: Optional pattern to match. If None, clears all cache.
        """
        if not os.path.exists(self.cache_directory):
            return
        
        try:
            for filename in os.listdir(self.cache_directory):
                if pattern is None or pattern in filename:
                    file_path = os.path.join(self.cache_directory, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        logger.debug(f"Removed cached file: {filename}")
        except OSError as e:
            logger.error(f"Error clearing cache: {e}")


class MIDICoordinator:
    """
    Main coordinator for MIDI-related operations.
    
    This class brings together URL generation, caching, and request
    coordination to provide a clean interface for MIDI operations.
    """
    
    def __init__(self, base_url: str, cache_directory: str):
        """
        Initialize the MIDI coordinator.
        
        Args:
            base_url: Base URL for MIDI endpoints
            cache_directory: Directory for MIDI file caching
        """
        self.url_generator = MIDIUrlGenerator(base_url)
        self.cache_manager = MIDICacheManager(cache_directory)
        self.base_url = base_url
        self.cache_directory = cache_directory
    
    def generate_full_score_context(self, start_bar: int, end_bar: int,
                                  binary_selected_instruments: int, binary_play_all: int,
                                  selected_instruments: List[int],
                                  part_instruments: Dict[int, List]) -> Dict[str, Any]:
        """
        Generate complete MIDI context for a full score.
        
        Args:
            start_bar: Starting bar number
            end_bar: Ending bar number
            binary_selected_instruments: Binary representation of selected instruments
            binary_play_all: Binary representation of playback options
            selected_instruments: List of selected instrument numbers
            part_instruments: Dictionary mapping instrument numbers to part info
            
        Returns:
            Complete MIDI context dictionary
        """
        base_params = {
            'start': start_bar,
            'end': end_bar,
            'bsi': binary_selected_instruments,
            'bpi': binary_play_all
        }
        
        # Generate selection URLs (all/selected/unselected)
        selection_urls = self.url_generator.generate_selection_urls(base_params)
        
        # Generate individual instrument URLs
        instrument_midis = {}
        for instrument_num in selected_instruments:
            if instrument_num in part_instruments:
                instrument_info = part_instruments[instrument_num]
                part_count = instrument_info[2] if len(instrument_info) > 2 else 0
                
                instrument_context = self.url_generator.generate_instrument_urls(
                    instrument_num, base_params, part_count
                )
                instrument_midis[instrument_num] = instrument_context
        
        return {
            **selection_urls,
            'selected_instruments_midis': instrument_midis
        }
    
    def generate_segment_context(self, start_bar: int, end_bar: int,
                               binary_selected_instruments: int, binary_play_all: int,
                               selected_instruments: List[int],
                               part_instruments: Dict[int, List]) -> Dict[str, Any]:
        """
        Generate MIDI context for a specific segment.
        
        This is similar to generate_full_score_context but may have
        different caching or generation strategies for segments.
        """
        return self.generate_full_score_context(
            start_bar, end_bar, binary_selected_instruments, binary_play_all,
            selected_instruments, part_instruments
        )
    
    def ensure_segment_generated(self, start_bar: int, end_bar: int,
                                binary_selected_instruments: int, binary_play_all: int,
                                generation_type: str = "ondemand") -> bool:
        """
        Ensure a segment's MIDI files are generated.
        
        Args:
            start_bar: Starting bar number
            end_bar: Ending bar number
            binary_selected_instruments: Binary representation of selected instruments
            binary_play_all: Binary representation of playback options
            generation_type: Type of generation ("upfront" or "ondemand")
            
        Returns:
            True if generation was successful or already cached
        """
        if self.cache_manager.is_segment_cached(start_bar, end_bar, generation_type):
            logger.debug(f"Segment {start_bar}-{end_bar} already cached ({generation_type})")
            return True
        
        try:
            # Trigger MIDI generation
            from lib.midiHandler import MidiHandler
            from types import SimpleNamespace
            
            # Create mock request for generation
            get_params = {
                'start': str(start_bar),
                'end': str(end_bar),
                'bsi': str(binary_selected_instruments),
                'bpi': str(binary_play_all),
                'upfront_generate': 'true' if generation_type == "upfront" else None
            }
            
            # Remove None values
            get_params = {k: v for k, v in get_params.items() if v is not None}
            
            dummy_request = SimpleNamespace(GET=get_params)
            
            # Extract file information from base URL
            # Expected format: /midis/file_id/filename.xml
            url_parts = self.base_url.strip('/').split('/')
            if len(url_parts) >= 3 and url_parts[0] == 'midis':
                file_id = url_parts[1]
                filename = url_parts[2]
                
                midi_handler = MidiHandler(dummy_request, file_id, filename)
                midi_handler.make_midi_files()
                
                # Mark as cached
                self.cache_manager.mark_segment_cached(start_bar, end_bar, generation_type)
                
                logger.debug(f"Successfully generated MIDI for segment {start_bar}-{end_bar}")
                return True
            else:
                logger.error(f"Invalid base URL format: {self.base_url}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to generate MIDI for segment {start_bar}-{end_bar}: {e}")
            return False
    
    def create_midi_request(self, start_bar: int, end_bar: int,
                           binary_selected_instruments: int, binary_play_all: int,
                           **kwargs) -> MIDIRequest:
        """
        Create a structured MIDI request.
        
        Args:
            start_bar: Starting bar number
            end_bar: Ending bar number
            binary_selected_instruments: Binary representation of selected instruments
            binary_play_all: Binary representation of playback options
            **kwargs: Additional parameters
            
        Returns:
            MIDIRequest object
        """
        return MIDIRequest(
            start_bar=start_bar,
            end_bar=end_bar,
            binary_selected_instruments=binary_selected_instruments,
            binary_play_all=binary_play_all,
            **kwargs
        )