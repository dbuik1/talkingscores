"""
Talking Scores Library

This package contains the core functionality for the Talking Scores application.
"""

# Import main classes for easy access
from .talkingscoreslib import (
    Music21TalkingScore,
    HTMLTalkingScoreFormatter,
    TalkingScoreBase,
    TalkingScoreError,
    ScoreParsingError,
    AnalysisError
)

from .settings_manager import SettingsManager, TalkingScoresSettings
from .color_utilities import ColorUtilities, ColorRenderer
from .musical_events import MusicalEventFactory
from .midi_coordinator import MIDICoordinator
from .template_renderer import TemplateManager
from .score_analyzer import ScoreAnalyzer

__all__ = [
    'Music21TalkingScore',
    'HTMLTalkingScoreFormatter', 
    'TalkingScoreBase',
    'TalkingScoreError',
    'ScoreParsingError',
    'AnalysisError',
    'SettingsManager',
    'TalkingScoresSettings',
    'ColorUtilities',
    'ColorRenderer',
    'MusicalEventFactory',
    'MIDICoordinator',
    'TemplateManager',
    'ScoreAnalyzer'
]