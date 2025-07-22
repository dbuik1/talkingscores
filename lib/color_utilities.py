"""
Color Utilities for Talking Scores

This module handles all color-related functionality including contrast calculation,
color application, and style generation for musical elements.
"""

import re
from typing import Dict, Optional, Tuple, Union
import logging

logger = logging.getLogger("TSScore")


class ColorUtilities:
    """
    Utility class for color operations and style generation.
    
    Handles color contrast calculation, hex color validation,
    and style application for musical elements.
    """
    
    @staticmethod
    def get_contrast_color(hex_color: str) -> str:
        """
        Calculate whether black or white text provides better contrast against a background color.
        
        Args:
            hex_color: Hex color string (with or without #)
            
        Returns:
            '#000000' for light backgrounds, '#FFFFFF' for dark backgrounds
        """
        try:
            # Clean and validate hex color
            hex_color = hex_color.strip().lstrip('#')
            
            if len(hex_color) != 6:
                logger.warning(f"Invalid hex color length: {hex_color}")
                return '#FFFFFF'  # Default to white for safety
            
            # Convert to RGB
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            
            # Calculate luminance using standard formula
            luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
            
            # Return black for light backgrounds, white for dark backgrounds
            return '#000000' if luminance > 0.5 else '#FFFFFF'
            
        except ValueError as e:
            logger.error(f"Error calculating contrast for color {hex_color}: {e}")
            return '#FFFFFF'  # Safe fallback
    
    @staticmethod
    def validate_hex_color(color: str) -> bool:
        """
        Validate if a string is a proper hex color.
        
        Args:
            color: Color string to validate
            
        Returns:
            True if valid hex color, False otherwise
        """
        if not isinstance(color, str):
            return False
        
        # Remove # if present
        color = color.lstrip('#')
        
        # Check if it's 6 characters of valid hex
        if len(color) != 6:
            return False
        
        try:
            int(color, 16)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def normalize_hex_color(color: str) -> Optional[str]:
        """
        Normalize a hex color to standard format (#RRGGBB).
        
        Args:
            color: Color string to normalize
            
        Returns:
            Normalized hex color or None if invalid
        """
        if not isinstance(color, str):
            return None
        
        # Remove whitespace and # if present
        color = color.strip().lstrip('#').upper()
        
        # Validate length
        if len(color) == 3:
            # Expand short form (e.g., 'F0A' -> 'FF00AA')
            color = ''.join(c * 2 for c in color)
        elif len(color) != 6:
            return None
        
        # Validate hex characters
        if not ColorUtilities.validate_hex_color(color):
            return None
        
        return f'#{color}'


class ColorRenderer:
    """
    Handles rendering of colored text for musical elements.
    
    This class applies color styling to musical text based on the 
    application's color settings and element types.
    """
    
    def __init__(self, color_settings):
        """
        Initialize with color settings.
        
        Args:
            color_settings: ColorSettings object containing color configuration
        """
        self.color_settings = color_settings
        self.color_utils = ColorUtilities()
    
    def render_colored_text(self, text: str, pitch_letter: str, element_type: str) -> str:
        """
        Wrap text in styled <span> tags based on color settings.
        
        Args:
            text: The text to style
            pitch_letter: The pitch letter (C, D, E, etc.) for color lookup
            element_type: Type of element ('pitch', 'rhythm', 'octave')
            
        Returns:
            HTML string with appropriate styling applied
        """
        if not text or not isinstance(text, str):
            return text or ""
        
        # Determine the color to use
        color_to_use = self._determine_element_color(pitch_letter, element_type)
        
        # Apply styling if color is determined and positioning is enabled
        if color_to_use and self.color_settings.colour_position != "none":
            return self._apply_color_styling(text, color_to_use)
        
        return text
    
    def _determine_element_color(self, pitch_letter: str, element_type: str) -> Optional[str]:
        """
        Determine what color should be used for a specific element.
        
        Args:
            pitch_letter: The pitch letter for color lookup
            element_type: Type of element ('pitch', 'rhythm', 'octave')
            
        Returns:
            Hex color string or None if no color should be applied
        """
        pitch_color = self.color_settings.figure_note_colours.get(pitch_letter)
        
        if element_type == "pitch" and self.color_settings.colour_pitch:
            return pitch_color
        
        elif element_type == "rhythm":
            mode = self.color_settings.rhythm_colour_mode
            if mode == 'inherit' and self.color_settings.colour_pitch:
                return pitch_color
            elif mode == 'custom':
                return self._get_rhythm_color(text)
        
        elif element_type == "octave":
            mode = self.color_settings.octave_colour_mode
            if mode == 'inherit' and self.color_settings.colour_pitch:
                return pitch_color
            elif mode == 'custom':
                return self._get_octave_color(text)
        
        return None
    
    def _get_rhythm_color(self, text: str) -> Optional[str]:
        """Get color for rhythm text from advanced rhythm colors."""
        if not text:
            return None
        
        # Create a slug from the text for lookup
        slug_text = text.lower().replace(" ", "-")
        
        # Find matching rhythm color
        for rhythm_slug, color in self.color_settings.advanced_rhythm_colours.items():
            if rhythm_slug in slug_text:
                return color
        
        return None
    
    def _get_octave_color(self, text: str) -> Optional[str]:
        """Get color for octave text from advanced octave colors."""
        if not text:
            return None
        
        octave_text = text.lower()
        octave_colours = self.color_settings.advanced_octave_colours
        
        # Determine octave range
        if any(term in octave_text for term in ["high", "top", "5", "6", "7"]):
            return octave_colours.get("high")
        elif any(term in octave_text for term in ["mid", "4"]):
            return octave_colours.get("mid")
        elif any(term in octave_text for term in ["low", "bottom", "1", "2", "3"]):
            return octave_colours.get("low")
        
        return None
    
    def _apply_color_styling(self, text: str, color: str) -> str:
        """
        Apply the actual color styling to text.
        
        Args:
            text: Text to style
            color: Hex color to apply
            
        Returns:
            HTML span with appropriate styling
        """
        # Normalize the color
        normalized_color = self.color_utils.normalize_hex_color(color)
        if not normalized_color:
            logger.warning(f"Invalid color for styling: {color}")
            return text
        
        style_type = self.color_settings.colour_position
        
        if style_type == "background":
            contrast_color = self.color_utils.get_contrast_color(normalized_color)
            return f"<span style='color:{contrast_color}; background-color:{normalized_color};'>{text}</span>"
        elif style_type == "text":
            return f"<span style='color:{normalized_color};'>{text}</span>"
        
        return text
    
    def create_color_preview(self, color: str, text: str = "Sample") -> str:
        """
        Create a color preview span for UI display.
        
        Args:
            color: Hex color for preview
            text: Sample text to display
            
        Returns:
            HTML span showing the color preview
        """
        normalized_color = self.color_utils.normalize_hex_color(color)
        if not normalized_color:
            return f'<span class="color-preview">{text}</span>'
        
        contrast_color = self.color_utils.get_contrast_color(normalized_color)
        
        return (f'<span class="color-preview" '
                f'style="background-color:{normalized_color}; color:{contrast_color}; '
                f'border-color: #888;">{text}</span>')


class ColorPaletteManager:
    """
    Manages color palettes and provides preset color schemes.
    
    This class handles the different color palettes available in the application
    and provides methods to apply and validate them.
    """
    
    PRESET_PALETTES = {
        "default": {  # Figurenotes palette
            "C": "#FF0000", "D": "#A52A2A", "E": "#808080", "F": "#0000FF",
            "G": "#000000", "A": "#FFFF00", "B": "#008000"
        },
        "classic": {  # Newton/Rainbow palette
            "C": "#FF0000", "D": "#FFA500", "E": "#FFFF00", "F": "#008000",
            "G": "#0000FF", "A": "#4B0082", "B": "#EE82EE"
        },
        "high_contrast": {  # High contrast palette for accessibility
            "C": "#000000", "D": "#FFFFFF", "E": "#FF0000", "F": "#00FF00",
            "G": "#0000FF", "A": "#FFFF00", "B": "#FF00FF"
        }
    }
    
    @classmethod
    def get_palette(cls, palette_name: str) -> Dict[str, str]:
        """
        Get a preset color palette.
        
        Args:
            palette_name: Name of the palette to retrieve
            
        Returns:
            Dictionary mapping pitch letters to hex colors
        """
        palette = cls.PRESET_PALETTES.get(palette_name, cls.PRESET_PALETTES["default"])
        return palette.copy()  # Return a copy to prevent modification
    
    @classmethod
    def get_available_palettes(cls) -> list[str]:
        """Get list of available palette names."""
        return list(cls.PRESET_PALETTES.keys())
    
    @classmethod
    def validate_palette(cls, palette: Dict[str, str]) -> Tuple[bool, list[str]]:
        """
        Validate a color palette.
        
        Args:
            palette: Dictionary mapping pitch letters to colors
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check required keys
        required_keys = {"C", "D", "E", "F", "G", "A", "B"}
        missing_keys = required_keys - set(palette.keys())
        if missing_keys:
            errors.append(f"Missing pitch letters: {missing_keys}")
        
        # Validate colors
        for pitch, color in palette.items():
            if not ColorUtilities.validate_hex_color(color):
                errors.append(f"Invalid color for {pitch}: {color}")
        
        return len(errors) == 0, errors
    
    @classmethod
    def generate_default_rhythm_colors(cls, rhythms: list[str]) -> Dict[str, str]:
        """
        Generate default colors for rhythm names.
        
        Args:
            rhythms: List of rhythm names found in the score
            
        Returns:
            Dictionary mapping rhythm slugs to hex colors
        """
        colors = {}
        
        for i, rhythm_name in enumerate(rhythms):
            # Generate a color based on index
            # This creates a reasonably spaced color palette
            hue = (i * 137.5) % 360  # Golden ratio spacing
            # Convert HSV to RGB (simplified)
            color_val = int(hue / 360 * 16777215)  # Convert to hex range
            hex_color = f"#{color_val:06x}"
            
            # Create slug from rhythm name
            slug = rhythm_name.lower().replace(" ", "-")
            colors[slug] = hex_color
        
        return colors
    
    @classmethod
    def generate_default_octave_colors(cls) -> Dict[str, str]:
        """
        Generate default colors for octave ranges.
        
        Returns:
            Dictionary mapping octave ranges to hex colors
        """
        return {
            "high": "#FF4500",  # Orange-red for high
            "mid": "#B8860B",   # Dark goldenrod for mid
            "low": "#4682B4"    # Steel blue for low
        }