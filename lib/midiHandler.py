"""
MIDI Handler for Talking Scores

This module handles the generation of MIDI files from MusicXML scores,
creating various combinations of tempo, click tracks, and instrument selections
for the Talking Scores application.
"""

__author__ = 'PMarchant'

import os
import json
import math
import logging
import logging.handlers
import logging.config
from tracemalloc import BaseFilter
from music21 import *
from talkingscores.settings import BASE_DIR, MEDIA_ROOT, STATIC_ROOT, STATIC_URL
from talkingscoreslib import Music21TalkingScore

logger = logging.getLogger("TSScore")


class MidiHandler:
    """
    Handles MIDI file generation for musical scores with various playback options.
    
    This class manages the creation of MIDI files from MusicXML scores, supporting
    different tempo variations, click tracks, and instrument combinations.
    """

    def __init__(self, request, folder, filename):
        """
        Initialize the MIDI handler.

        Args:
            request: Django request object containing query parameters
            folder (str): Directory name where files are stored
            filename (str): Base filename of the MusicXML file (without .mid extension)
        """
        self.request = request
        self.folder = folder
        self.filename = filename.replace(".mid", "")
        self.score = None  # Pre-parsed music21 score object to avoid re-parsing
        
        # Initialize collections for instrument and part management
        self.selected_instruments = []
        self.all_selected_parts = []
        self.all_unselected_parts = []
        self.selected_instrument_parts = {}
        
        # Playback option flags
        self.play_together_unselected = False
        self.play_together_selected = False
        self.play_together_all = False
        
        # Score processing attributes
        self.score_segment = None
        self.tempo_shift = 0

    def get_selected_instruments(self):
        """
        Parse the binary selected instruments parameter and determine which parts to include.
        
        The 'bsi' parameter is a bitwise representation of selected instruments.
        This method decodes it and sets up the various instrument and part collections.
        """
        try:
            binary_selected_instruments = int(self.request.GET.get("bsi", 0))
        except (ValueError, TypeError):
            logger.error("Invalid binary selected instruments parameter")
            binary_selected_instruments = 0

        # Decode binary representation to boolean list
        self.selected_instruments = []
        current_value = binary_selected_instruments
        while current_value > 1:
            self.selected_instruments.append(bool(current_value & 1))
            current_value = current_value >> 1
        self.selected_instruments.reverse()

        # Initialize part collections
        self.all_selected_parts = []
        self.all_unselected_parts = []
        self.selected_instrument_parts = {}

        # Map instruments to their corresponding parts
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

        # Parse playback options from binary parameter
        try:
            binary_playback_info = int(self.request.GET.get("bpi", 0))
        except (ValueError, TypeError):
            logger.error("Invalid binary playback info parameter")
            binary_playback_info = 0

        self.play_together_unselected = bool(binary_playback_info & 1)
        binary_playback_info = binary_playback_info >> 1
        self.play_together_selected = bool(binary_playback_info & 1)
        binary_playback_info = binary_playback_info >> 1
        self.play_together_all = bool(binary_playback_info & 1)

    def _validate_parameters(self):
        """
        Validate request parameters and score availability.
        
        Returns:
            tuple: (start_bar, end_bar) if valid, (None, None) if invalid
        """
        if not self.score:
            xml_file_path = os.path.join(MEDIA_ROOT, self.folder, self.filename)
            if not os.path.exists(xml_file_path):
                logger.error(f"MusicXML file not found: {xml_file_path}")
                return None, None
            
            try:
                self.score = converter.parse(xml_file_path)
            except Exception as e:
                logger.error(f"Failed to parse MusicXML file: {e}")
                return None, None

        # Determine bar range
        start_param = self.request.GET.get("start")
        if start_param is not None:
            try:
                start_bar = int(start_param)
                end_bar = int(self.request.GET.get("end"))
            except (ValueError, TypeError):
                logger.error("Invalid start/end bar parameters")
                return None, None
        else:
            try:
                start_bar = self.score.parts[0].getElementsByClass('Measure')[0].number
                end_bar = self.score.parts[0].getElementsByClass('Measure')[-1].number
            except (IndexError, AttributeError):
                logger.error("Could not determine bar range from score")
                return None, None

        return start_bar, end_bar

    def _check_cache_flag(self, start_bar, end_bar, is_upfront_call):
        """
        Check if MIDI files for this segment have already been generated.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            is_upfront_call (bool): Whether this is an upfront generation call
            
        Returns:
            bool: True if cache hit (files already generated), False otherwise
        """
        flag_mode = "upfront" if is_upfront_call else "ondemand"
        flag_name = f"s{start_bar}e{end_bar}_{flag_mode}.generated"
        flag_path = os.path.join(MEDIA_ROOT, self.folder, flag_name)

        if os.path.exists(flag_path):
            logger.info(f"MIDI cache hit for {flag_name}. Skipping generation.")
            return True
        return False

    def _create_cache_flag(self, start_bar, end_bar, is_upfront_call):
        """
        Create a flag file indicating MIDI generation is complete for this segment.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            is_upfront_call (bool): Whether this is an upfront generation call
        """
        flag_mode = "upfront" if is_upfront_call else "ondemand"
        flag_name = f"s{start_bar}e{end_bar}_{flag_mode}.generated"
        flag_path = os.path.join(MEDIA_ROOT, self.folder, flag_name)

        try:
            with open(flag_path, 'w') as f:
                f.write("generated")
            logger.info(f"Created MIDI cache flag: {flag_name}")
        except OSError as e:
            logger.error(f"Could not write cache flag file {flag_path}: {e}")

    def _get_tempo_click_combinations(self, is_upfront_call):
        """
        Determine which tempo and click track combinations to generate.
        
        Args:
            is_upfront_call (bool): Whether this is an upfront generation call
            
        Returns:
            tuple: (tempos_to_generate, clicks_to_generate)
        """
        if is_upfront_call:
            return [100], ['n']
        else:
            return [50, 100, 150], ['n', 'be']

    def _create_score_segment(self, start_bar, end_bar):
        """
        Create a score segment for the specified bar range.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
        """
        offset = 0.0
        if self.score.parts and self.score.parts[0].measure(start_bar):
            offset = self.score.parts[0].measure(start_bar).offset

        self.score_segment = stream.Score(id='tempSegment')
        for part in self.score.parts:
            measures_in_range = part.measures(start_bar, end_bar)
            if measures_in_range:
                # Remove repeat marks to avoid music21 expansion issues
                for measure in measures_in_range.getElementsByClass('Measure'):
                    measure.removeByClass('Repeat')
                self.score_segment.insert(0, measures_in_range)

    def _generate_group_midis(self, start_bar, end_bar, offset, tempo, click):
        """
        Generate MIDI files for different groupings (all, selected, unselected).
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            offset (float): Time offset for the segment
            tempo (int): Tempo as percentage of original
            click (str): Click track type ('n' for none, 'be' for bars/beats)
        """
        if self.play_together_all:
            self._make_midi_together(start_bar, end_bar, offset, tempo, click, "all")
        
        if self.play_together_selected and self.all_selected_parts:
            self._make_midi_together(start_bar, end_bar, offset, tempo, click, "sel")
        
        if self.play_together_unselected and self.all_unselected_parts:
            self._make_midi_together(start_bar, end_bar, offset, tempo, click, "un")

    def _generate_individual_instrument_midis(self, start_bar, end_bar, offset, tempo, click):
        """
        Generate MIDI files for individual instruments and their parts.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            offset (float): Time offset for the segment
            tempo (int): Tempo as percentage of original
            click (str): Click track type
        """
        for index, parts_list in enumerate(self.selected_instrument_parts.values()):
            if not parts_list:
                continue
                
            # Generate MIDI for the entire instrument
            instrument_path = self._make_midi_path_from_options(
                start=start_bar, end=end_bar, ins=index+1, tempo=tempo, click=click
            )
            
            if not os.path.exists(instrument_path):
                instrument_score = stream.Score(id='temp')
                for part_index in parts_list:
                    if len(self.score_segment.parts) > part_index:
                        instrument_score.insert(0, self.score_segment.parts[part_index])
                
                if instrument_score.parts:
                    self._insert_tempos(instrument_score, offset, tempo/100)
                    self._insert_click_track(instrument_score, click)
                    try:
                        instrument_score.write('midi', instrument_path)
                    except Exception as e:
                        logger.error(f"Failed to write instrument MIDI {instrument_path}: {e}")

            # Generate MIDI files for individual parts if instrument has multiple parts
            if len(parts_list) > 1:
                for part_index in parts_list:
                    part_path = self._make_midi_path_from_options(
                        start=start_bar, end=end_bar, part=part_index, tempo=tempo, click=click
                    )
                    
                    if not os.path.exists(part_path):
                        part_score = stream.Score(id='temp_part')
                        if len(self.score_segment.parts) > part_index:
                            part_score.insert(0, self.score_segment.parts[part_index])
                        
                        if part_score.parts:
                            self._insert_tempos(part_score, offset, tempo/100)
                            self._insert_click_track(part_score, click)
                            try:
                                part_score.write('midi', part_path)
                            except Exception as e:
                                logger.error(f"Failed to write part MIDI {part_path}: {e}")

    def make_midi_files(self):
        """
        Main method to generate all required MIDI files for the current request.
        
        This method orchestrates the entire MIDI generation process, including
        validation, caching checks, and creation of all tempo/click/instrument combinations.
        """
        # Validate parameters and get bar range
        start_bar, end_bar = self._validate_parameters()
        if start_bar is None:
            logger.error("Invalid parameters for MIDI generation")
            return

        # Set up instrument selections
        self.get_selected_instruments()
        
        # Check if this segment has already been generated
        is_upfront_call = bool(self.request.GET.get("upfront_generate"))
        if self._check_cache_flag(start_bar, end_bar, is_upfront_call):
            return

        # Determine tempo and click combinations to generate
        tempos_to_generate, clicks_to_generate = self._get_tempo_click_combinations(is_upfront_call)

        # Calculate segment offset
        offset = 0.0
        if self.score.parts and self.score.parts[0].measure(start_bar):
            offset = self.score.parts[0].measure(start_bar).offset

        # Create the score segment for this bar range
        self._create_score_segment(start_bar, end_bar)

        # Generate MIDI files for all combinations
        try:
            for click in clicks_to_generate:
                self.tempo_shift = 0
                for tempo in tempos_to_generate:
                    # Generate group MIDI files (all, selected, unselected)
                    self._generate_group_midis(start_bar, end_bar, offset, tempo, click)
                    
                    # Generate individual instrument and part MIDI files
                    self._generate_individual_instrument_midis(start_bar, end_bar, offset, tempo, click)

            # Create flag file on successful completion
            self._create_cache_flag(start_bar, end_bar, is_upfront_call)
            
        except Exception as e:
            logger.error(f"Failed to generate MIDI files for segment {start_bar}-{end_bar}: {e}")
            raise

    def _make_midi_together(self, start_bar, end_bar, offset, tempo, click, which_parts):
        """
        Create a MIDI file combining multiple parts together.
        
        Args:
            start_bar (int): Starting bar number
            end_bar (int): Ending bar number
            offset (float): Time offset for the segment
            tempo (int): Tempo as percentage of original
            click (str): Click track type
            which_parts (str): "all", "sel" (selected), or "un" (unselected)
        """
        midi_path = self._make_midi_path_from_options(
            start=start_bar, end=end_bar, sel=which_parts, tempo=tempo, click=click
        )
        
        if os.path.exists(midi_path):
            return

        # Determine which parts to include
        if which_parts == "sel":
            parts_to_include = self.all_selected_parts
        elif which_parts == "un":
            parts_to_include = self.all_unselected_parts
        else:  # "all"
            parts_to_include = None

        combined_score = stream.Score(id='temp')
        
        for part_index, part in enumerate(self.score_segment.parts):
            if which_parts == "all" or part_index in parts_to_include:
                # Re-fetch measures for this specific stream to avoid cloning issues
                part_measures = self.score.parts[part_index].measures(
                    start_bar, end_bar, 
                    collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')
                )
                combined_score.insert(0, part_measures)
        
        if not combined_score.parts:
            logger.info(f"Skipping MIDI generation for '{which_parts}' because there are no parts to include.")
            return

        self._insert_tempos(combined_score, offset, tempo/100)
        self._insert_click_track(combined_score, click)
        
        try:
            combined_score.write('midi', midi_path)
        except Exception as e:
            logger.error(f"Failed to write combined MIDI {midi_path}: {e}")

    def _insert_click_track(self, score, click_type):
        """
        Add a click track (metronome) to the score.
        
        Args:
            score: The music21 score to add the click track to
            click_type (str): Type of click track ('n' for none, 'be' for bars/beats)
        """
        if click_type == 'n':
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
            if measure_time_sigs:
                current_time_signature = measure_time_sigs[0]
            elif current_time_signature is None:
                previous_time_sig = measure.previous('TimeSignature')
                current_time_signature = previous_time_sig if previous_time_sig else meter.TimeSignature('4/4')
            
            # Create click measure
            click_measure = stream.Measure()
            click_measure.mergeAttributes(measure)
            click_measure.duration = current_time_signature.barDuration
            
            # Add downbeat click (stronger sound)
            downbeat_click = note.Note('D2')
            downbeat_click.duration = current_time_signature.getBeatDuration(0)
            click_measure.append(downbeat_click)
            
            # Add beat clicks for remaining beats
            beat_position = current_time_signature.getBeatDuration(0).quarterLength
            if (measure.duration.quarterLength < current_time_signature.barDuration.quarterLength and 
                len(measure.getElementsByClass(['Note', 'Rest'])) > 0):
                
                # Handle short measures by adding rests
                rest_duration = current_time_signature.barDuration.quarterLength - measure.duration.quarterLength
                rest = note.Rest()
                rest.duration.quarterLength = rest_duration
                
                # Add rests to all parts
                for part in self.score_segment.parts:
                    rest_copy = note.Rest()
                    rest_copy.duration.quarterLength = rest_duration
                    part.getElementsByClass(stream.Measure)[0].insertAndShift(0, rest_copy)
                    for subsequent_measure in part.getElementsByClass(stream.Measure)[1:]:
                        subsequent_measure.offset += rest_duration
                
                # Adjust offsets in the combined score
                for part in score.parts:
                    for subsequent_measure in part.getElementsByClass(stream.Measure)[1:]:
                        subsequent_measure.offset += rest_duration
                
                # Adjust tempo marks
                for tempo_mark in score.getElementsByClass(tempo.MetronomeMark):
                    if tempo_mark.offset > 0:
                        tempo_mark.offset += rest_duration
                
                shift_measure_offset = rest_duration
                self.tempo_shift = rest_duration
            
            # Add remaining beat clicks
            for beat_num in range(0, current_time_signature.beatCount - 1):
                beat_click = note.Note('F#2')
                beat_click.duration = current_time_signature.getBeatDuration(beat_position)
                beat_position += beat_click.duration.quarterLength
                click_measure.append(beat_click)
            
            click_track.append(click_measure)
        
        score.insert(click_track)

    def _insert_tempos(self, score_stream, offset_start, scale):
        """
        Insert tempo markings into a score stream.
        
        Args:
            score_stream: The music21 stream to add tempos to
            offset_start (float): Starting offset of the stream
            scale (float): Tempo scaling factor (e.g., 0.5 for half speed)
        """
        for metronome_boundary in self.score.metronomeMarkBoundaries():
            boundary_start, boundary_end, tempo_mark = metronome_boundary
            
            # Skip if this tempo boundary is completely after our stream
            if boundary_start >= offset_start + score_stream.duration.quarterLength:
                return
            
            # Only process if the boundary overlaps with our stream
            if boundary_end > offset_start:
                fixed_tempo = Music21TalkingScore.fix_tempo_number(tempo=tempo_mark)
                scaled_tempo_number = fixed_tempo.number * scale
                
                if boundary_start <= offset_start:
                    # Tempo starts before our stream, so insert it at the beginning
                    score_stream.insert(0.001, tempo.MetronomeMark(
                        number=scaled_tempo_number, 
                        referent=tempo_mark.referent
                    ))
                else:
                    # Tempo starts within our stream
                    insert_offset = boundary_start - offset_start + self.tempo_shift
                    score_stream.insert(insert_offset, tempo.MetronomeMark(
                        number=scaled_tempo_number, 
                        referent=tempo_mark.referent
                    ))

    def _make_midi_path_from_options(self, sel=None, part=None, ins=None, start=None, end=None, click=None, tempo=None):
        """
        Generate a file path for a MIDI file based on the given options.
        
        Args:
            sel (str, optional): Selection type ("all", "sel", "un")
            part (int, optional): Part number
            ins (int, optional): Instrument number
            start (int, optional): Starting bar
            end (int, optional): Ending bar
            click (str, optional): Click track type
            tempo (int, optional): Tempo percentage
            
        Returns:
            str: Complete file path for the MIDI file
        """
        midi_filename = self.filename
        
        # Build filename based on options
        if sel is not None:
            midi_filename += f"sel-{sel}"
        if part is not None:
            midi_filename += f"p{part}"
        if ins is not None:
            midi_filename += f"i{ins}"
        if start is not None:
            midi_filename += f"s{start}"
        if end is not None:
            midi_filename += f"e{end}"
        if click is not None:
            midi_filename += f"c{click}"
        if tempo is not None:
            midi_filename += f"t{tempo}"
        
        midi_filename += ".mid"
        
        return os.path.join(MEDIA_ROOT, self.folder, midi_filename)

    def get_or_make_midi_file(self):
        """
        Get an existing MIDI file or create it if it doesn't exist.
        
        This method builds the MIDI filename from request parameters and either
        returns the path to an existing file or triggers generation of a new one.
        
        Returns:
            str: Path to the MIDI file
        """
        # Build MIDI filename from request parameters
        midi_filename = self.filename
        
        # Add parameters to filename in consistent order
        param_mapping = [
            ("sel", "sel"),
            ("part", "p"),
            ("ins", "i"),
            ("start", "s"),
            ("end", "e"),
            ("c", "c"),
            ("t", "t")
        ]
        
        for param_name, prefix in param_mapping:
            param_value = self.request.GET.get(param_name)
            if param_value is not None:
                midi_filename += f"{prefix}{param_value}"

        self.midi_filename = midi_filename + ".mid"
        
        # Construct full file path
        midi_file_path = os.path.join(MEDIA_ROOT, self.folder, self.midi_filename)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(midi_file_path), exist_ok=True)

        # Generate MIDI file if it doesn't exist
        if not os.path.exists(midi_file_path):
            logger.debug(f"MIDI file not found - {midi_file_path} - generating it...")
            try:
                self.make_midi_files()
            except Exception as e:
                logger.error(f"Failed to generate MIDI file {midi_file_path}: {e}")
                raise

        return midi_file_path