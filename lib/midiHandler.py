"""
MIDI Handler Module for Talking Scores

This module handles the generation of MIDI files from MusicXML scores with various
configurations including tempo variations, click tracks, and instrument selections.
Supports both on-demand and upfront generation with caching mechanisms.
"""

__author__ = 'PMarchant'

import os
import json
import math
import logging
import logging.handlers
import logging.config
from music21 import *
from talkingscores.settings import BASE_DIR, MEDIA_ROOT, STATIC_ROOT, STATIC_URL
from talkingscoreslib import Music21TalkingScore

logger = logging.getLogger("TSScore")


class MidiHandler:
    """
    Handles MIDI file generation from MusicXML scores with support for various
    playback configurations including tempo changes, click tracks, and instrument selection.
    
    This class manages the conversion of musical scores to MIDI format with caching
    to improve performance for repeated requests.
    """

    def __init__(self, request, folder, filename):
        """
        Initialize the MIDI handler with request parameters and file information.
        
        Args:
            request: Django request object containing query parameters
            folder: Directory containing the source MusicXML file
            filename: Name of the MusicXML file (without .mid extension)
        """
        self.query_string = request
        self.folder = folder
        self.filename = filename.replace(".mid", "")
        self.score = None  # Will hold pre-parsed music21 score object
        self.score_segment = None
        self.tempo_shift = 0
        self.selected_instruments = []
        self.all_selected_parts = []
        self.all_unselected_parts = []
        self.selected_instrument_parts = {}
        self.play_together_unselected = False
        self.play_together_selected = False
        self.play_together_all = False

    def _parse_binary_selection_integer(self, binary_int):
        """
        Parse a binary integer to extract boolean selection flags.
        
        Args:
            binary_int: Integer representing binary flags
            
        Returns:
            list: Boolean values extracted from binary representation
        """
        selections = []
        while binary_int > 1:
            selections.append(bool(binary_int & 1))
            binary_int = binary_int >> 1
        selections.reverse()
        return selections

    def _get_playback_options(self):
        """
        Extract playback options from query parameters.
        
        Sets instance variables for play_together options based on binary flags.
        """
        binary_playback_int = int(self.query_string.GET.get("bpi"))
        self.play_together_unselected = bool(binary_playback_int & 1)
        binary_playback_int = binary_playback_int >> 1
        self.play_together_selected = bool(binary_playback_int & 1)
        binary_playback_int = binary_playback_int >> 1
        self.play_together_all = bool(binary_playback_int & 1)

    def _map_instruments_to_parts(self):
        """
        Map selected instruments to their corresponding parts in the score.
        
        Populates the selected_instrument_parts dictionary and part lists
        based on instrument selection flags.
        """
        instrument_index = -1
        previous_instrument = ""
        
        for part_index, part in enumerate(self.score.flatten().getInstruments()):
            if part.partId != previous_instrument:
                instrument_index += 1
            
            if instrument_index < len(self.selected_instruments) and self.selected_instruments[instrument_index]:
                self.all_selected_parts.append(part_index)
                if instrument_index in self.selected_instrument_parts:
                    self.selected_instrument_parts[instrument_index].append(part_index)
                else:
                    self.selected_instrument_parts[instrument_index] = [part_index]
            else:
                self.all_unselected_parts.append(part_index)
                
            previous_instrument = part.partId

    def get_selected_instruments(self):
        """
        Parse instrument selection from query parameters and map to score parts.
        
        Extracts binary instrument selection flags and playback options,
        then maps them to the actual parts in the musical score.
        """
        binary_selection_int = int(self.query_string.GET.get("bsi"))
        self.selected_instruments = self._parse_binary_selection_integer(binary_selection_int)
        
        # Initialize part tracking variables
        self.all_selected_parts = []
        self.all_unselected_parts = []
        self.selected_instrument_parts = {}
        
        self._map_instruments_to_parts()
        self._get_playback_options()

    def _should_generate_cache_files(self):
        """
        Determine if cache files should be generated based on request type.
        
        Returns:
            tuple: (flag_mode, tempos_to_generate, clicks_to_generate)
        """
        is_upfront_call = self.query_string.GET.get("upfront_generate")
        
        if is_upfront_call:
            return "upfront", [100], ['n']
        else:
            return "ondemand", [50, 100, 150], ['n', 'be']

    def _check_generation_cache(self, start, end, flag_mode):
        """
        Check if MIDI files have already been generated for this range.
        
        Args:
            start: Starting measure number
            end: Ending measure number
            flag_mode: Either "upfront" or "ondemand"
            
        Returns:
            tuple: (cache_exists, flag_path)
        """
        flag_name = f"s{start}e{end}_{flag_mode}.generated"
        flag_path = os.path.join(MEDIA_ROOT, self.folder, flag_name)
        
        if os.path.exists(flag_path):
            logger.info(f"MIDI cache hit for {flag_name}. Skipping generation.")
            return True, flag_path
        
        return False, flag_path

    def _create_cache_flag(self, flag_path):
        """
        Create a flag file to indicate successful MIDI generation.
        
        Args:
            flag_path: Path where the flag file should be created
        """
        try:
            with open(flag_path, 'w') as f:
                f.write("generated")
            logger.info(f"Created MIDI cache flag: {os.path.basename(flag_path)}")
        except OSError as e:
            logger.error(f"Could not write cache flag file {flag_path}: {e}")

    def _extract_score_segment(self, start, end):
        """
        Extract a segment of the score between specified measures.
        
        Args:
            start: Starting measure number
            end: Ending measure number
            
        Returns:
            float: The offset of the starting measure
        """
        offset = 0.0
        if self.score.parts and self.score.parts[0].measure(start):
            offset = self.score.parts[0].measure(start).offset

        self.score_segment = stream.Score(id='tempSegment')
        for part in self.score.parts:
            measures_in_range = part.measures(start, end)
            if measures_in_range:
                # Remove repeat markers that can cause playback issues
                for measure in measures_in_range.getElementsByClass('Measure'):
                    measure.removeByClass('Repeat')
                self.score_segment.insert(0, measures_in_range)
        
        return offset

    def _generate_individual_instrument_files(self, start, end, tempo, click):
        """
        Generate MIDI files for individual instruments and their parts.
        
        Args:
            start: Starting measure number
            end: Ending measure number
            tempo: Tempo setting
            click: Click track setting
        """
        for index, parts_list in enumerate(self.selected_instrument_parts.values()):
            if not parts_list:
                continue
                
            # Generate file for entire instrument (if multiple parts)
            instrument_path = self.make_midi_path_from_options(
                start=start, end=end, ins=index+1, tempo=tempo, click=click
            )
            
            if not os.path.exists(instrument_path):
                instrument_score = stream.Score(id='temp')
                for part_index in parts_list:
                    if len(self.score_segment.parts) > part_index:
                        instrument_score.insert(0, self.score_segment.parts[part_index])
                
                if instrument_score.parts:
                    self._apply_tempo_and_click(instrument_score, start, tempo, click)
                    instrument_score.write('midi', instrument_path)

            # Generate individual part files if instrument has multiple parts
            if len(parts_list) > 1:
                for part_index in parts_list:
                    part_path = self.make_midi_path_from_options(
                        start=start, end=end, part=part_index, tempo=tempo, click=click
                    )
                    
                    if not os.path.exists(part_path):
                        part_score = stream.Score(id='temp_part')
                        if len(self.score_segment.parts) > part_index:
                            part_score.insert(0, self.score_segment.parts[part_index])
                        
                        if part_score.parts:
                            self._apply_tempo_and_click(part_score, start, tempo, click)
                            part_score.write('midi', part_path)

    def _apply_tempo_and_click(self, score, start_measure, tempo, click):
        """
        Apply tempo changes and click track to a score.
        
        Args:
            score: The music21 Score object to modify
            start_measure: Starting measure number for offset calculation
            tempo: Tempo multiplier (as percentage, e.g., 100 for normal speed)
            click: Click track type ('n' for none, 'be' for beat emphasis)
        """
        # Calculate offset for tempo insertion
        offset = 0.0
        if self.score.parts and self.score.parts[0].measure(start_measure):
            offset = self.score.parts[0].measure(start_measure).offset
            
        self.insert_tempos(score, offset, tempo/100)
        self.insert_click_track(score, click)

    def make_midi_files(self):
        """
        Generate MIDI files for the score with various tempo and click track combinations.
        
        This method handles the main logic for MIDI file generation, including
        caching checks, score parsing, and file creation for different playback options.
        """
        # Parse score if not already loaded
        if not self.score:
            xml_file_path = os.path.join(MEDIA_ROOT, self.folder, self.filename)
            self.score = converter.parse(xml_file_path)

        self.get_selected_instruments()
        
        # Determine measure range
        start_param = self.query_string.GET.get("start")
        if start_param is not None:
            start = int(start_param)
            end = int(self.query_string.GET.get("end"))
        else:
            start = self.score.parts[0].getElementsByClass('Measure')[0].number
            end = self.score.parts[0].getElementsByClass('Measure')[-1].number

        # Check cache and determine generation parameters
        flag_mode, tempos_to_generate, clicks_to_generate = self._should_generate_cache_files()
        cache_exists, flag_path = self._check_generation_cache(start, end, flag_mode)
        
        if cache_exists:
            return

        # Extract the score segment for the specified range
        offset = self._extract_score_segment(start, end)
        self.tempo_shift = 0

        # Generate files for all tempo and click combinations
        for click in clicks_to_generate:
            for tempo in tempos_to_generate:
                # Generate combined files based on selection options
                if self.play_together_all:
                    self.make_midi_together(start, end, offset, tempo, click, "all")
                    
                if self.play_together_selected and self.all_selected_parts:
                    self.make_midi_together(start, end, offset, tempo, click, "sel")
                    
                if self.play_together_unselected and self.all_unselected_parts:
                    self.make_midi_together(start, end, offset, tempo, click, "un")

                # Generate individual instrument and part files
                self._generate_individual_instrument_files(start, end, tempo, click)

        # Create cache flag on successful completion
        self._create_cache_flag(flag_path)

    def make_midi_together(self, start, end, offset, tempo, click, which_parts):
        """
        Generate a MIDI file combining multiple parts together.
        
        Args:
            start: Starting measure number
            end: Ending measure number
            offset: Time offset for the segment
            tempo: Tempo setting
            click: Click track setting
            which_parts: "all", "sel" (selected), or "un" (unselected)
        """
        path = self.make_midi_path_from_options(start=start, end=end, sel=which_parts, tempo=tempo, click=click)
        if os.path.exists(path):
            return

        # Determine which parts to include
        parts_to_include = []
        if which_parts == "sel":
            parts_to_include = self.all_selected_parts
        elif which_parts == "un":
            parts_to_include = self.all_unselected_parts
        
        combined_score = stream.Score(id='temp')
        
        for part_index, part in enumerate(self.score_segment.parts):
            if which_parts == "all" or part_index in parts_to_include:
                # Re-fetch measures to avoid cloning issues
                part_measures = self.score.parts[part_index].measures(
                    start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')
                )
                combined_score.insert(0, part_measures)
        
        if not combined_score.parts:
            logger.info(f"Skipping MIDI generation for '{which_parts}' because there are no parts to include.")
            return

        self.insert_tempos(combined_score, offset, tempo/100)
        self.insert_click_track(combined_score, click)
        combined_score.write('midi', path)

    def _create_click_measure(self, original_measure, time_signature):
        """
        Create a click track measure based on the time signature.
        
        Args:
            original_measure: The original measure to base timing on
            time_signature: The time signature for this measure
            
        Returns:
            stream.Measure: A measure containing click track notes
        """
        click_measure = stream.Measure()
        click_measure.mergeAttributes(original_measure)
        click_measure.duration = time_signature.barDuration

        # Downbeat (first beat) - different pitch for emphasis
        downbeat_note = note.Note('D2')
        downbeat_note.duration = time_signature.getBeatDuration(0)
        click_measure.append(downbeat_note)

        # Remaining beats
        beat_position = time_signature.getBeatDuration(0).quarterLength
        for beat_num in range(0, time_signature.beatCount - 1):
            beat_note = note.Note('F#2')
            beat_note.duration = time_signature.getBeatDuration(beat_position)
            beat_position += beat_note.duration.quarterLength
            click_measure.append(beat_note)

        return click_measure

    def _handle_incomplete_measure(self, measure, time_signature, score):
        """
        Handle measures that are shorter than the time signature indicates.
        
        Args:
            measure: The incomplete measure
            time_signature: Expected time signature
            score: The score to adjust
            
        Returns:
            float: The rest duration that was added
        """
        if (measure.duration.quarterLength < time_signature.barDuration.quarterLength and 
            len(measure.getElementsByClass(['Note', 'Rest'])) > 0):
            
            rest_duration = time_signature.barDuration.quarterLength - measure.duration.quarterLength
            
            # Add rests to all parts in the score segment
            for part in self.score_segment.parts:
                rest_note = note.Rest()
                rest_note.duration.quarterLength = rest_duration
                part.getElementsByClass(stream.Measure)[0].insertAndShift(0, rest_note)
                
                # Adjust offsets for subsequent measures
                for subsequent_measure in part.getElementsByClass(stream.Measure)[1:]:
                    subsequent_measure.offset += rest_duration
            
            # Adjust offsets in the current score
            for part in score.parts:
                for subsequent_measure in part.getElementsByClass(stream.Measure)[1:]:
                    subsequent_measure.offset += rest_duration
            
            # Adjust tempo mark offsets
            for tempo_mark in score.getElementsByClass(tempo.MetronomeMark):
                if tempo_mark.offset > 0:
                    tempo_mark.offset += rest_duration
            
            return rest_duration
        
        return 0.0

    def insert_click_track(self, score, click):
        """
        Insert a click track into the score for rhythm guidance.
        
        Args:
            score: The music21 Score object to add click track to
            click: Click track type ('n' for none, 'be' for beat emphasis)
        """
        if click == 'n':
            return

        click_track = stream.Stream()
        percussion_instrument = instrument.Percussion()
        percussion_instrument.midiChannel = 9
        click_track.insert(0, percussion_instrument)

        current_time_signature = None
        shift_measure_offset = 0

        for measure in score.getElementsByClass(stream.Part)[0].getElementsByClass(stream.Measure):
            # Get time signature for this measure
            measure_time_sigs = measure.getElementsByClass(meter.TimeSignature)
            if len(measure_time_sigs) > 0:
                current_time_signature = measure_time_sigs[0]
            elif current_time_signature is None:
                current_time_signature = measure.previous('TimeSignature')
                if current_time_signature is None:
                    current_time_signature = meter.TimeSignature('4/4')

            # Create click measure
            click_measure = self._create_click_measure(measure, current_time_signature)
            
            # Handle incomplete measures by adding rests
            rest_duration = self._handle_incomplete_measure(measure, current_time_signature, score)
            if rest_duration > 0:
                shift_measure_offset = rest_duration
                self.tempo_shift = rest_duration

            click_track.append(click_measure)

        score.insert(click_track)

    def insert_tempos(self, score_stream, offset_start, scale):
        """
        Insert tempo markings into the score with scaling.
        
        Args:
            score_stream: The music21 Stream to add tempo markings to
            offset_start: Starting offset for tempo calculations
            scale: Tempo scaling factor (1.0 = normal speed)
        """
        for metronome_boundary in self.score.metronomeMarkBoundaries():
            boundary_offset, boundary_end, metronome_mark = metronome_boundary
            
            # Skip if boundary is past the end of our segment
            if boundary_offset >= offset_start + score_stream.duration.quarterLength:
                return
                
            # Only process boundaries that overlap with our segment
            if boundary_end > offset_start:
                tempo_number = Music21TalkingScore.fix_tempo_number(tempo=metronome_mark).number
                scaled_tempo = tempo_number * scale
                
                if boundary_offset <= offset_start:
                    # Tempo change at or before segment start
                    score_stream.insert(0.001, tempo.MetronomeMark(
                        number=scaled_tempo, referent=metronome_mark.referent
                    ))
                else:
                    # Tempo change within the segment
                    insert_offset = boundary_offset - offset_start + self.tempo_shift
                    score_stream.insert(insert_offset, tempo.MetronomeMark(
                        number=scaled_tempo, referent=metronome_mark.referent
                    ))

    def make_midi_path_from_options(self, sel=None, part=None, ins=None, start=None, end=None, click=None, tempo=None):
        """
        Generate a MIDI file path based on playback options.
        
        Args:
            sel: Selection type ("all", "sel", "un")
            part: Specific part number
            ins: Instrument number
            start: Start measure
            end: End measure
            click: Click track type
            tempo: Tempo setting
            
        Returns:
            str: Full path to the MIDI file
        """
        midi_name = self.filename
        
        if sel is not None:
            midi_name += f"sel-{sel}"
        if part is not None:
            midi_name += f"p{part}"
        if ins is not None:
            midi_name += f"i{ins}"
        if start is not None:
            midi_name += f"s{start}"
        if end is not None:
            midi_name += f"e{end}"
        if click is not None:
            midi_name += f"c{click}"
        if tempo is not None:
            midi_name += f"t{tempo}"
            
        midi_name += ".mid"
        
        return os.path.join(MEDIA_ROOT, self.folder, midi_name)

    def get_or_make_midi_file(self):
        """
        Get an existing MIDI file or create it if it doesn't exist.
        
        Returns:
            str: Path to the MIDI file
        """
        midi_name = self.filename
        
        # Build filename from query parameters
        query_params = [
            ("sel", "sel-"),
            ("part", "p"),
            ("ins", "i"),
            ("start", "s"),
            ("end", "e"),
            ("c", "c"),
            ("t", "t")
        ]
        
        for param_name, prefix in query_params:
            param_value = self.query_string.GET.get(param_name)
            if param_value is not None:
                midi_name += f"{prefix}{param_value}"

        self.midi_name = midi_name + ".mid"
        midi_filepath = os.path.join(MEDIA_ROOT, self.folder, self.midi_name)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(midi_filepath), exist_ok=True)

        # Generate file if it doesn't exist
        if not os.path.exists(midi_filepath):
            logger.debug(f"MIDI file not found - {midi_filepath} - making it...")
            self.make_midi_files()

        return midi_filepath