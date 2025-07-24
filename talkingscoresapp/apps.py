"""
Django app configuration for the Talking Scores application.
"""

from django.apps import AppConfig


class TalkingscoresappConfig(AppConfig):
    """
    Configuration class for the Talking Scores application.
    
    This app handles the conversion of MusicXML files to accessible
    talking score HTML descriptions with MIDI playback.
    """
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'talkingscoresapp'
    verbose_name = 'Talking Scores'