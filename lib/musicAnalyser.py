"""
Music Analysis Module for Talking Scores

This module provides comprehensive analysis of musical scores to identify patterns,
repetition, and structural elements. It creates indexes and buckets for different
musical attributes (pitch, rhythm, intervals, chords) to enable pattern recognition
and generate descriptive summaries of musical content.

The analysis works by:
1. Creating separate indexes for each musical attribute (pitch, rhythm, intervals, etc.)
2. Using dictionaries where keys are musical values and values are lists of event indexes
3. Combining indexes to create an AnalyseIndex for each musical event
4. Analyzing measures and groups of measures for repetition patterns
5. Generating human-readable descriptions of musical structure and patterns
"""

__author__ = 'PMarchant'

import json
import math
import pprint
import logging
import logging.handlers
import logging.config
from music21 import *

logger = logging.getLogger("TSScore")


class AnalyseIndex:
    """
    Represents analysis data for a single musical event (note, chord, or rest).
    
    This class stores indexes that link a musical event to various analytical
    categories like pitch, rhythm, intervals, and chord information. Each index
    is a pair: [category_identifier, occurrence_number_in_category].
    """

    def __init__(self, event_index):
        """
        Initialize analysis index for a musical event.
        
        Args:
            event_index (int): The position of this event in the musical part
        """
        self.event_index = event_index
        self.event_type = ''  # 'n' = note, 'c' = chord, 'r' = rest, 'u' = unpitched

        # Chord analysis indexes [category_id, occurrence_index]
        self.chord_interval_index = [-1, -1]
        self.chord_pitches_index = [-1, -1]
        self.chord_name_index = ['', -1]

        # Pitch analysis indexes
        self.pitch_number_index = [-1, -1]
        self.pitch_name_index = ['', -1]
        self.interval_index = [None, -1]
        
        # Rhythm analysis indexes for different event types
        self.rhythm_note_index = [-1, -1]
        self.rhythm_chord_index = [-1, -1]
        self.rhythm_rest_index = [-1, -1]

    def print_info(self):
        """Print detailed information about this analysis index for debugging."""
        print(f"EventIndex: {self.event_index} - type: {self.event_type}")
        
        if self.event_type == 'n':
            print(f"Pitch: {self.pitch_name_index}, MIDI: {self.pitch_number_index}, Interval: {self.interval_index}")
            print(f"Rhythm: {self.rhythm_note_index}")
        elif self.event_type == 'c':
            print(f"Chord pitches: {self.chord_pitches_index}, Intervals: {self.chord_interval_index}, Name: {self.chord_name_index}")
            print(f"Rhythm: {self.rhythm_chord_index}")
        elif self.event_type == 'r':
            print(f"Rest rhythm: {self.rhythm_rest_index}")


class AnalyseSection:
    """
    Represents a section of music (typically a measure) containing multiple musical events.
    
    This class groups together AnalyseIndex objects that belong to the same musical
    section and tracks where this section pattern appears throughout the piece.
    """

    def __init__(self):
        """Initialize an empty musical section for analysis."""
        self.analyse_indexes = []  # List of AnalyseIndex objects in this section
        self.section_start_event_indexes = []  # Event indexes where this section pattern starts

    def print_info(self):
        """Print information about this section for debugging."""
        print(f"Section length: {len(self.analyse_indexes)} events")
        print(f"Section appears at event indexes: {self.section_start_event_indexes}")


class MusicAnalyser:
    """
    Main class for analyzing musical scores to identify patterns, repetition, and structure.
    
    This class processes a musical score to create comprehensive indexes of musical
    elements and generates human-readable descriptions of the music's structure,
    including repetition patterns, rhythmic content, and harmonic analysis.
    """

    def __init__(self):
        """Initialize the music analyzer with empty analysis containers."""
        self.score = None
        self.ts = None  # TalkingScore instance
        self.analyse_parts = []
        self.summary = ""
        self.repetition_parts = []
        self.repetition_right_hand = ""
        self.repetition_left_hand = ""
        self.repetition_in_contexts = {}  # key = part index
        self.immediate_repetition_contexts = {}  # key = part index 
        self.summary_parts = []
        self.general_summary = ""
    def set_score(self, talking_score):
        """
        Set the musical score and perform comprehensive analysis on all selected parts.
        
        Args:
            talking_score: TalkingScore instance containing the musical score and configuration
        """
        self.ts = talking_score
        self.score = talking_score.score
        
        # Initialize analysis containers
        part_index = 0
        self.analyse_parts = []
        self.repetition_parts = []
        self.summary_parts = []
        self.repetition_in_contexts = {}
        self.immediate_repetition_contexts = {}
        self.general_summary = ""

        analyse_index = 0
        
        # Analyze each selected instrument and its parts
        for instrument in talking_score.part_instruments:
            if instrument in talking_score.selected_instruments:
                start_part = talking_score.part_instruments[instrument][1]
                instrument_length = talking_score.part_instruments[instrument][2]
                
                # Process each part within this instrument
                for part_index in range(start_part, start_part + instrument_length):
                    analyse_part = AnalysePart()
                    analyse_part.set_part(self.score.parts[part_index])
                    self.analyse_parts.append(analyse_part)
                    
                    # Generate summaries for this part
                    summary = analyse_part.describe_summary()
                    summary += analyse_part.describe_repetition_summary()
                    self.summary_parts.append(summary)
                    
                    # Generate contextual repetition information
                    self.repetition_in_contexts[part_index] = analyse_part.describe_repetition_in_context()
                    self.immediate_repetition_contexts[part_index] = analyse_part.describe_immediate_repetition()
                    
                    analyse_index += 1

        self.general_summary += self.describe_general_summary()

    def describe_general_summary(self):
        """
        Generate a summary of overall musical characteristics (time, key, tempo changes).
        
        Returns:
            str: Human-readable description of general musical characteristics
        """
        if not self.score or not self.score.parts:
            return ""
            
        num_measures = len(self.score.parts[0].getElementsByClass('Measure'))
        general_summary = f"There are {num_measures} bars. "

        # Analyze time signature changes
        time_signatures = self.score.parts[0].flatten().getElementsByClass('TimeSignature')
        general_summary += self._summarise_musical_changes(time_signatures, "time signature")
        
        # Analyze key signature changes
        key_signatures = self.score.parts[0].flatten().getElementsByClass('KeySignature')
        general_summary += self._summarise_musical_changes(key_signatures, "key signature")
        
        # Analyze tempo changes
        tempos = self.score.flatten().getElementsByClass('MetronomeMark')
        general_summary += self._summarise_musical_changes(tempos, "tempo")

        return general_summary

    def _summarise_musical_changes(self, changes_collection, change_type):
        """
        Summarize changes in musical elements (time sig, key sig, tempo).
        
        Args:
            changes_collection: Collection of musical change objects
            change_type (str): Type of change ("time signature", "key signature", "tempo")
            
        Returns:
            str: Description of the changes
        """
        num_changes = len(changes_collection) - 1  # First one isn't a change
        
        if num_changes > 4:
            return f"There are {num_changes} {change_type} changes. "
        elif num_changes > 0:
            changes_description = f"The {change_type} changes to "
            
            for index, change in enumerate(changes_collection):
                if index > 0:  # Skip the first one as it's the initial state
                    if change_type == "time signature":
                        changes_description += self.ts.describe_time_signature(change)
                    elif change_type == "key signature":
                        changes_description += self.ts.describe_key_signature(change)
                    elif change_type == "tempo":
                        changes_description += self.ts.describe_tempo(change)

                    changes_description += f" at bar {change.measureNumber}"
                    
                    if index == num_changes - 1:
                        changes_description += " and "
                    elif index < num_changes - 1:
                        changes_description += ", "

            return changes_description + ". "
        
        return ""


class AnalysePart:
    """
    Analyzes a single musical part to identify patterns, repetition, and musical characteristics.
    
    This class performs detailed analysis of individual musical parts, creating indexes
    for various musical attributes and identifying repetition patterns at different levels
    (exact matches, rhythm-only matches, interval-only matches).
    """

    # Position descriptors for different quarters of the musical score
    _POSITION_MAP = {
        0: 'near the start',
        1: 'in the 2nd quarter',
        2: 'in the 3rd quarter',
        3: 'near the end'
    }

    # Interval names mapped to semitone distances
    _INTERVAL_MAP = {
        0: 'unison', 1: 'minor 2nd', 2: 'major 2nd', 3: 'minor 3rd',
        4: 'major 3rd', 5: 'perfect 4th', 6: 'augmented 4th / tritone',
        7: 'perfect 5th', 8: 'minor 6th', 9: 'major 6th', 10: 'minor 7th',
        11: 'major 7th', 12: 'octave', 13: 'minor 9th', 14: 'major 9th',
        15: 'minor 10th', 16: 'major 10th', 17: 'perfect 11th',
        18: 'augmented 11th', 19: 'perfect 12th', 20: 'minor 13th',
        21: 'major 13th', 22: 'minor 14th', 23: 'major 14th', 24: '2 octaves',
    }

    # Duration names mapped to quarter note values
    _DURATION_MAP = {
        4.0: 'semibreves', 3.0: 'dotted minims', 2.0: 'minims',
        1.5: 'dotted crotchets', 1.0: 'crotchets', 0.75: 'dotted quavers',
        0.5: 'quavers', 0.375: 'dotted semi-quavers', 0.25: 'semi-quavers',
        0.1875: 'dotted demi-semi-quavers', 0.125: 'demi-semi-quavers',
        0.09375: 'dotted hemi-demi-semi-quavers', 0.0625: 'hemi-demi-semi-quavers',
        0.0: 'grace notes',
    }

    def __init__(self):
        """Initialize analysis containers for a musical part."""
        # Event analysis containers
        self.analyse_indexes_list = []  # List of unique AnalyseIndex objects
        self.analyse_indexes_dictionary = {}  # {index: [list of event indexes]}
        self.analyse_indexes_all = {}  # {event_index: [list_index, dict_index]}

        # Measure analysis containers
        self.measure_indexes = {}  # {measure_number: first_event_index}
        self.measure_analyse_indexes_list = []  # List of unique AnalyseSection objects
        self.measure_analyse_indexes_dictionary = {}  # {index: [list of measure numbers]}
        self.measure_analyse_indexes_all = {}  # {measure_number: [list_index, dict_index]}

        # Repetition tracking
        self.repeated_measures_lists = []  # Lists of repeated measure groups
        self.measure_groups_list = []  # Groups of consecutive repeated measures
        self.repeated_measures_not_in_groups_dictionary = {}  # Individual repeated measures

        # Rhythm-only analysis containers
        self.measure_rhythm_analyse_indexes_list = []
        self.measure_rhythm_analyse_indexes_dictionary = {}
        self.measure_rhythm_analyse_indexes_all = {}
        self.repeated_measures_lists_rhythm = []
        self.measure_rhythm_not_full_match_groups_list = []
        self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary = {}

        # Interval-only analysis containers
        self.measure_intervals_analyse_indexes_list = []
        self.measure_intervals_analyse_indexes_dictionary = {}
        self.measure_intervals_analyse_indexes_all = {}
        self.repeated_measures_lists_intervals = []
        self.measure_intervals_not_full_match_groups_list = []
        self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary = {}

        # Musical attribute dictionaries
        self._initialize_musical_attribute_containers()
        
        # Statistics and counts
        self._initialize_statistics_containers()

        self.part = None

    def _initialize_musical_attribute_containers(self):
        """Initialize containers for different musical attributes."""
        # Pitch analysis
        self.pitch_number_dictionary = {i: [] for i in range(128)}  # MIDI pitch numbers
        self.pitch_name_dictionary = {}  # Pitch names without octave
        self.interval_dictionary = {}  # Intervals in semitones
        
        # Rhythm analysis
        self.rhythm_note_dictionary = {}  # Note durations
        self.rhythm_rest_dictionary = {}  # Rest durations
        self.rhythm_chord_dictionary = {}  # Chord durations
        
        # Chord analysis
        self.chord_pitches_list = []  # Unique chords by MIDI pitches
        self.chord_pitches_dictionary = {}  # {chord_index: [event_indexes]}
        self.chord_intervals_list = []  # Unique chords by intervals
        self.chord_intervals_dictionary = {}  # {chord_index: [event_indexes]}
        self.chord_common_name_dictionary = {}  # {chord_name: [event_indexes]}

    def _initialize_statistics_containers(self):
        """Initialize containers for musical statistics and counts."""
        # Count containers for special elements per measure
        self.count_accidentals_in_measures = {}
        self.count_gracenotes_in_measures = {}
        self.count_rests_in_measures = {}
        
        # Count containers for musical elements (populated later)
        self.count_pitches = []
        self.count_pitch_names = []
        self.count_intervals = []
        self.count_intervals_abs = [0] * 25  # Unison to 2 octaves
        self.count_chord_pitches = []
        self.count_chord_intervals = []
        self.count_chord_common_names = []
        self.count_notes_in_chords = {i: 0 for i in range(2, 11)}
        self.count_rhythm_note = []
        self.count_rhythm_rest = []
        self.count_rhythm_chord = []

        # Overall statistics
        self.total_note_duration = 0
        self.note_count = 0
        self.interval_count = 0
        self.interval_ascending_count = 0
        self.interval_descending_count = 0
        self.interval_unison_count = 0
        self.total_rest_duration = 0
        self.rest_count = 0
        self.total_chord_duration = 0
        self.chord_count = 0
        self.accidental_count = 0
        self.gracenote_count = 0
        self.possible_accidental_count = 0
    def describe_immediate_repetition(self):
        """
        Identify immediately consecutive bars that repeat (exact or rhythm-only matches).
        
        Returns:
            dict: {bar_number: {'type': 'exact'|'rhythm', 'text': description}}
        """
        context = {}
        bar_numbers = sorted(self.measure_indexes.keys())
        
        for i, current_bar in enumerate(bar_numbers):
            if i > 0:  # Can only compare if not the first bar
                previous_bar = bar_numbers[i-1]
                
                # Only announce for immediately sequential bars
                if current_bar == previous_bar + 1:
                    # Check for exact match first (highest priority)
                    if self.is_measure_used_at(self.measure_analyse_indexes_all, previous_bar, current_bar):
                        context[current_bar] = {'type': 'exact', 'text': 'Same as previous bar.'}
                    # If not exact, check for rhythm-only match
                    elif self.is_measure_used_at(self.measure_rhythm_analyse_indexes_all, previous_bar, current_bar):
                        context[current_bar] = {'type': 'rhythm', 'text': 'Same rhythm as previous bar.'}
        
        return context

    def compare_sections(self, section1, section2, compare_type):
        """
        Compare two musical sections based on specified criteria.
        
        Args:
            section1 (AnalyseSection): First section to compare
            section2 (AnalyseSection): Second section to compare
            compare_type (int): 0=all attributes, 1=rhythm only, 2=intervals only
            
        Returns:
            bool: True if sections match according to compare_type
        """
        if len(section1.analyse_indexes) != len(section2.analyse_indexes):
            return False
            
        for i in range(len(section1.analyse_indexes)):
            if compare_type == 0 and not self.compare_indexes(section1.analyse_indexes[i], section2.analyse_indexes[i]):
                return False
            elif compare_type == 1 and not self.compare_indexes_rhythm(section1.analyse_indexes[i], section2.analyse_indexes[i]):
                return False
            elif compare_type == 2 and not self.compare_indexes_intervals(section1.analyse_indexes[i], section2.analyse_indexes[i]):
                return False
                
        return True

    def compare_indexes_intervals(self, index1, index2):
        """
        Compare two AnalyseIndex objects based on intervals only.
        
        Args:
            index1 (AnalyseIndex): First analysis index
            index2 (AnalyseIndex): Second analysis index
            
        Returns:
            bool: True if intervals match
        """
        if index1.event_type != index2.event_type:
            return False
            
        if index1.event_type == 'n':
            return index1.interval_index[0] == index2.interval_index[0]
            
        return True

    def compare_indexes_rhythm(self, index1, index2):
        """
        Compare two AnalyseIndex objects based on rhythm only.
        
        Rest durations must match. Chords and single notes are interchangeable
        if their durations match.
        
        Args:
            index1 (AnalyseIndex): First analysis index
            index2 (AnalyseIndex): Second analysis index
            
        Returns:
            bool: True if rhythms match
        """
        # Rest vs non-rest mismatch
        if (index1.event_type == 'r') != (index2.event_type == 'r'):
            return False
            
        # Compare rhythm indexes based on event type
        if (index1.rhythm_chord_index[0] != index2.rhythm_chord_index[0] or
            index1.rhythm_note_index[0] != index2.rhythm_note_index[0] or
            index1.rhythm_rest_index[0] != index2.rhythm_rest_index[0]):
            return False
            
        return True

    def compare_indexes(self, index1, index2):
        """
        Compare two AnalyseIndex objects for exact match (all attributes).
        
        Args:
            index1 (AnalyseIndex): First analysis index
            index2 (AnalyseIndex): Second analysis index
            
        Returns:
            bool: True if all relevant attributes match
        """
        if index1.event_type != index2.event_type:
            return False
            
        if index1.event_type == 'n':
            return (index1.rhythm_note_index[0] == index2.rhythm_note_index[0] and
                    index1.pitch_number_index[0] == index2.pitch_number_index[0])
        elif index1.event_type == 'c':
            return (index1.rhythm_chord_index[0] == index2.rhythm_chord_index[0] and
                    index1.chord_pitches_index[0] == index2.chord_pitches_index[0])
        elif index1.event_type == 'r':
            return index1.rhythm_rest_index[0] == index2.rhythm_rest_index[0]
            
        return True

    def does_section_contain_intervals(self, section):
        """
        Check if a section contains any interval information.
        
        Args:
            section (AnalyseSection): Section to check
            
        Returns:
            bool: True if section contains intervals
        """
        return any(ai.interval_index[0] is not None for ai in section.analyse_indexes)

    def find_section(self, target_section, sections_list, compare_type):
        """
        Find a matching section in a list of sections.
        
        Args:
            target_section (AnalyseSection): Section to find
            sections_list (list): List of sections to search
            compare_type (int): Comparison type (0=all, 1=rhythm, 2=intervals)
            
        Returns:
            int: Index of matching section, or -1 if not found
        """
        for i, section in enumerate(sections_list):
            if self.compare_sections(section, target_section, compare_type):
                return i
        return -1

    def find_analyse_index(self, target_index):
        """
        Find a matching AnalyseIndex in the list of unique indexes.
        
        Args:
            target_index (AnalyseIndex): Index to find
            
        Returns:
            int: Index in analyse_indexes_list, or -1 if not found
        """
        for i, existing_index in enumerate(self.analyse_indexes_list):
            if self.compare_indexes(existing_index, target_index):
                return i
        return -1

    def find_chord(self, chord):
        """
        Find a chord in the list based on MIDI pitches.
        
        Args:
            chord: Music21 chord object
            
        Returns:
            int: Index in chord_pitches_list, or -1 if not found
        """
        target_pitches = sorted(p.midi for p in chord.pitches)
        
        for i, existing_pitches in enumerate(self.chord_pitches_list):
            if existing_pitches == target_pitches:
                return i
        return -1

    def find_chord_intervals(self, chord_intervals):
        """
        Find a chord in the list based on interval structure.
        
        Args:
            chord_intervals (list): List of intervals from lowest note
            
        Returns:
            int: Index in chord_intervals_list, or -1 if not found
        """
        for i, existing_intervals in enumerate(self.chord_intervals_list):
            if existing_intervals == chord_intervals:
                return i
        return -1

    def make_chord_intervals(self, chord):
        """
        Create interval structure for a chord from its lowest note.
        
        Args:
            chord: Music21 chord object
            
        Returns:
            list: Ascending intervals from lowest note (e.g., major triad = [4, 7])
        """
        lowest_pitch = chord.pitches[0].midi
        other_pitches = sorted(p.midi for p in chord.pitches[1:])
        return [p - lowest_pitch for p in other_pitches]

    def when_is_measure_next_used(self, measure_index, indexes_all, indexes_dictionary):
        """
        Find when a measure pattern is next used after the current occurrence.
        
        Args:
            measure_index (int): Current measure number
            indexes_all (dict): All measure indexes mapping
            indexes_dictionary (dict): Dictionary of measure occurrences
            
        Returns:
            int: Next measure number where pattern is used, or -1 if not found
        """
        if measure_index not in indexes_all:
            return -1
            
        measure_info = indexes_all[measure_index]
        pattern_occurrences = indexes_dictionary[measure_info[0]]
        current_occurrence_index = measure_info[1]
        
        if len(pattern_occurrences) - 1 > current_occurrence_index:
            return pattern_occurrences[current_occurrence_index + 1]
        
        return -1

    def are_measures_in(self, group_list, measure_index1, measure_index2):
        """
        Check if two measures are in the same repetition group.
        
        Args:
            group_list (list): List of measure groups
            measure_index1 (int): First measure number
            measure_index2 (int): Second measure number
            
        Returns:
            bool: True if both measures are in the same group
        """
        for group in group_list:
            if measure_index1 in group and measure_index2 in group:
                return True
        return False

    def is_measure_used_at(self, indexes_all, current_measure, check_measure):
        """
        Check if two measures have the same pattern.
        
        Args:
            indexes_all (dict): Measure indexes mapping
            current_measure (int): First measure number
            check_measure (int): Second measure number
            
        Returns:
            bool: True if measures have the same pattern
        """
        if check_measure not in indexes_all or current_measure not in indexes_all:
            return False
            
        return indexes_all[current_measure][0] == indexes_all[check_measure][0]
    def find_measure_group(self, target_group, groups_list):
        """
        Find a measure group in the list of measure groups.
        
        Args:
            target_group (list): [start_measure, end_measure] to find
            groups_list (list): List of measure group lists
            
        Returns:
            int: Index of matching group, or -1 if not found
        """
        for i, measure_groups in enumerate(groups_list):
            for group in measure_groups:
                if target_group == group:
                    return i
        return -1

    def calculate_repeated_measures_lists(self, measure_dictionary, not_full_match):
        """
        Calculate lists of measures that share the same pattern.
        
        Args:
            measure_dictionary (dict): Dictionary mapping pattern to measure lists
            not_full_match (bool): If True, exclude measures that are full matches
            
        Returns:
            list: Lists of measure numbers that share patterns
        """
        repeated_lists = []
        
        for measure_indexes in measure_dictionary.values():
            if len(measure_indexes) > 1:  # Pattern used more than once
                measures = []
                
                for measure_index in measure_indexes:
                    # Filter out full matches if requested
                    if (not not_full_match or 
                        len(self.measure_analyse_indexes_dictionary[
                            self.measure_analyse_indexes_all[measure_index][0]]) == 1):
                        measures.append(measure_index)
                
                if len(measures) > 1:
                    repeated_lists.append(measures)
                    
        return repeated_lists

    def calculate_repeated_measures_not_in_groups(self, measures_lists, groups_list):
        """
        Find repeated measures that aren't already part of a larger group.
        
        Args:
            measures_lists (list): Lists of repeated measures
            groups_list (list): Existing measure groups
            
        Returns:
            dict: {first_measure: [other_occurrences]}
        """
        output_dictionary = {}
        
        for measure_indexes in measures_lists:
            if len(measure_indexes) > 1:
                measures_not_in_groups = []
                
                for measure_index in measure_indexes:
                    if not self.in_measure_groups(measure_index, groups_list):
                        measures_not_in_groups.append(measure_index)

                if len(measures_not_in_groups) > 1:
                    first_measure = measures_not_in_groups[0]
                    output_dictionary[first_measure] = measures_not_in_groups[1:]
                    
        return output_dictionary

    def in_measure_groups(self, measure_index, groups_list):
        """
        Check if a measure is already part of any measure group.
        
        Args:
            measure_index (int): Measure number to check
            groups_list (list): List of measure groups
            
        Returns:
            bool: True if measure is in any group
        """
        for group_list in groups_list:
            for group in group_list:
                if group[0] <= measure_index <= group[1]:
                    return True
        return False

    def are_measures_in_same_group(self, measure1, measure2, groups_list):
        """
        Check if two measures are in the same group.
        
        Args:
            measure1 (int): First measure number
            measure2 (int): Second measure number
            groups_list (list): List of measure groups
            
        Returns:
            bool: True if both measures are in the same group
        """
        for group_list in groups_list:
            for group in group_list:
                if (group[0] <= measure1 <= group[1] and 
                    group[0] <= measure2 <= group[1]):
                    return True
        return False

    def calculate_measure_groups(self, indexes_all, indexes_dictionary):
        """
        Calculate groups of consecutive measures that repeat together.
        
        Args:
            indexes_all (dict): All measure indexes mapping
            indexes_dictionary (dict): Dictionary of measure pattern occurrences
            
        Returns:
            list: Groups of repeated measure ranges [[start, end], [start, end]]
        """
        groups_list = []
        skip = 0
        
        for look_at_measure in indexes_all:
            if skip > 0:
                skip -= 1
                continue

            # Find when this measure is next used
            next_used_at = self.when_is_measure_next_used(
                look_at_measure, indexes_all, indexes_dictionary
            )
            
            if next_used_at > -1:
                gap = next_used_at - look_at_measure
                
                if gap > 1:
                    # Check for consecutive measure patterns
                    group_size = 1
                    while (group_size < gap and 
                           (look_at_measure + group_size + gap) in indexes_all and
                           self.is_measure_used_at(indexes_all, 
                                                 look_at_measure + group_size,
                                                 look_at_measure + group_size + gap)):
                        group_size += 1

                    group_size -= 1

                    # If we found a group of consecutive repeated measures
                    if group_size > 0:
                        measure_group = [look_at_measure, look_at_measure + group_size]
                        group_index = self.find_measure_group(measure_group, groups_list)
                        
                        if group_index == -1:
                            # Add new group with first and second occurrence
                            groups_list.append([measure_group])
                            groups_list[-1].append([
                                look_at_measure + gap, 
                                look_at_measure + gap + group_size
                            ])
                        else:
                            # Add additional occurrence to existing group
                            groups_list[group_index].append([
                                look_at_measure + gap,
                                look_at_measure + gap + group_size
                            ])

                        skip = group_size
                        
        return groups_list
    def describe_repetition_percentage(self, percent):
        """
        Convert a percentage to descriptive text.
        
        Args:
            percent (float): Percentage value
            
        Returns:
            str: Descriptive text for the percentage
        """
        if percent > 99:
            return "all"
        elif percent > 85:
            return "almost all"
        elif percent > 75:
            return "over three quarters"
        elif percent > 50:
            return "over half"
        elif percent > 33:
            return "over a third"
        else:
            return ""

    def comma_and_list(self, items_list):
        """
        Format a list with proper comma and "and" placement.
        
        Args:
            items_list (list): List of items to format
            
        Returns:
            str: Formatted string (e.g., "1, 4 and 6")
        """
        if not items_list:
            return ""
            
        output = ""
        for index, value in enumerate(items_list):
            if index == len(items_list) - 1 and index > 0:
                output += " and "
            elif index < len(items_list) - 1 and index > 0:
                output += ", "
            output += str(value)
        return output

    def describe_distribution(self, count_in_measures, total):
        """
        Describe how musical elements are distributed across measures.
        
        Args:
            count_in_measures (dict): {measure_number: count}
            total (int): Total count of elements
            
        Returns:
            str: Description of distribution pattern
        """
        if total == 0:
            return ""
            
        distribution = ""

        # Calculate percentages and sort by highest concentration
        measure_percents = {}
        for measure_num, count in count_in_measures.items():
            if count > 0:
                measure_percents[measure_num] = (count / total) * 100
                
        sorted_percents = dict(sorted(measure_percents.items(), 
                                    key=lambda item: item[1], reverse=True))

        # Identify measures with high concentration (>20%)
        high_concentration_measures = []
        measures_to_remove = []
        
        for measure_num, percent in sorted_percents.items():
            if percent > 20:
                high_concentration_measures.append(measure_num)
                measures_to_remove.append(measure_num)

        # Remove high concentration measures from further analysis
        percent_remaining = 100
        for measure_num in measures_to_remove:
            percent_remaining -= measure_percents[measure_num]
            measure_percents.pop(measure_num)

        # Describe high concentration measures
        if high_concentration_measures:
            distribution += " mostly in bar"
            if len(high_concentration_measures) > 1:
                distribution += "s"
            distribution += f" {self.comma_and_list(high_concentration_measures)}"

        # Analyze remaining measures by quarters of the piece
        if measure_percents:
            if distribution:
                distribution += " and "
                
            total_measures = len(count_in_measures)
            quarter_distribution = {0: 0, 1: 0, 2: 0, 3: 0}
            
            for measure_num, percent in measure_percents.items():
                if measure_num > total_measures * 0.75:
                    quarter_distribution[3] += (percent / percent_remaining) * 100
                elif measure_num > total_measures * 0.5:
                    quarter_distribution[2] += (percent / percent_remaining) * 100
                elif measure_num > total_measures * 0.25:
                    quarter_distribution[1] += (percent / percent_remaining) * 100
                else:
                    quarter_distribution[0] += (percent / percent_remaining) * 100

            sorted_quarters = sorted(quarter_distribution.items(), 
                                   key=lambda item: item[1], reverse=True)

            # Describe quarter-based distribution
            if sorted_quarters[0][1] > 50:
                distribution += f" {self._POSITION_MAP[sorted_quarters[0][0]]}"
            elif sorted_quarters[0][1] + sorted_quarters[1][1] > 70:
                distribution += f" {self._POSITION_MAP[sorted_quarters[0][0]]} and {self._POSITION_MAP[sorted_quarters[1][0]]}"
            else:
                distribution += f" in {len(measure_percents)} bars throughout"

        return distribution.strip()

    def describe_percentage(self, percent):
        """
        Convert percentage to descriptive text for common elements.
        
        Args:
            percent (float): Percentage value
            
        Returns:
            str: Descriptive text
        """
        if percent > 99:
            return "all"
        elif percent > 90:
            return "almost all"
        elif percent > 75:
            return "most"
        elif percent > 45:
            return "lots of"
        elif percent > 30:
            return "some"
        elif percent > 10:
            return "a few"
        elif percent > 1:
            return "very few"
        else:
            return ""

    def describe_percentage_uncommon(self, percent):
        """
        Convert percentage to descriptive text for uncommon elements (accidentals, etc.).
        
        Args:
            percent (float): Percentage value
            
        Returns:
            str: Descriptive text weighted for uncommon elements
        """
        if percent > 5:
            return "many"
        elif percent > 2:
            return "a lot of"
        elif percent > 1:
            return "quite a few"
        elif percent > 0.5:
            return "a few"
        else:
            return "some"

    def describe_count_list(self, count_list, total):
        """
        Describe a list of counted items with appropriate quantifiers.
        
        Args:
            count_list (list): [(item, count)] sorted by count
            total (int): Total count of all items
            
        Returns:
            str: Description of the count distribution
        """
        if total == 0:
            return ""
            
        description = ""
        for item, count in count_list:
            percentage = count / total
            
            if percentage > 0.98:
                description += f"all {item}, "
            elif percentage > 0.90:
                description += f"almost all {item}, "
            elif percentage > 0.6:
                description += f"mostly {item}, "
            elif percentage > 0.3:
                description += f"some {item}, "

        return self.replace_end_with(description, ", ", "")

    def describe_count_list_several(self, count_list, total, item_name):
        """
        Describe count list when no single item dominates.
        
        Args:
            count_list (list): [(item, count)] sorted by count
            total (int): Total count
            item_name (str): Name for the type of items
            
        Returns:
            str: Description focusing on variety
        """
        if total == 0:
            return ""
            
        top_items = []
        remaining_count = 0
        progress_percent = 0
        
        for item, count in count_list:
            if progress_percent < 40:
                top_items.append(item)
                progress_percent += (count / total) * 100
            else:
                if count > 0:
                    remaining_count += 1

        if len(top_items) <= 4:
            description = f"mostly {self.comma_and_list(top_items)}"
            if remaining_count > 1:
                description += f"; plus {remaining_count} other {item_name}"
        else:
            description = f"{len(top_items)} {item_name}, the most common is {count_list[0][0]}"
            
        return description

    def replace_end_with(self, original, remove, add):
        """
        Replace the end of a string with different text.
        
        Args:
            original (str): Original string
            remove (str): Text to remove from end
            add (str): Text to add to end
            
        Returns:
            str: Modified string
        """
        if original.endswith(remove):
            return original[:-len(remove)] + add
        return original

    def describe_summary(self):
        """
        Generate a comprehensive summary of the musical part.
        
        Returns:
            str: Human-readable summary of musical characteristics
        """
        summary = ""
        event_count = self.chord_count + self.note_count + self.rest_count
        event_duration = self.total_chord_duration + self.total_note_duration + self.total_rest_duration

        if event_count == 0 or event_duration == 0:
            return summary

        # Calculate weighted percentages (50% count, 150% duration weighting)
        percent_dictionary = {}
        percent_dictionary["chords"] = ((self.chord_count / event_count * 50) + 
                                      (self.total_chord_duration / event_duration * 150)) / 2
        percent_dictionary["individual notes"] = ((self.note_count / event_count * 50) + 
                                                (self.total_note_duration / event_duration * 150)) / 2
        percent_dictionary["rests"] = ((self.rest_count / event_count * 50) + 
                                     (self.total_rest_duration / event_duration * 150)) / 2

        # Describe each element type in order of prevalence
        for element_type, percentage in sorted(percent_dictionary.items(), 
                                             key=lambda item: item[1], reverse=True):
            if percentage > 1:
                summary += f"{self.describe_percentage(percentage)} {element_type}"
                
                # Add specific details for each element type
                if element_type == "chords":
                    summary += self._describe_chord_details()
                elif element_type == "individual notes":
                    summary += self._describe_note_details()
                elif element_type == "rests":
                    summary += self._describe_rest_details()
                    
                summary += ", "

        # Describe accidentals if present
        if self.accidental_count > 1:
            accidental_percent = (self.accidental_count / self.possible_accidental_count) * 100
            summary += f"{self.describe_percentage_uncommon(accidental_percent)} accidentals"
            
            distribution = self.describe_distribution(self.count_accidentals_in_measures, 
                                                    self.accidental_count)
            if distribution:
                summary += f" ({distribution}), "

        # Describe grace notes if present
        if self.gracenote_count > 1:
            gracenote_percent = (self.gracenote_count / self.possible_accidental_count) * 100
            summary += f"{self.describe_percentage_uncommon(gracenote_percent)} grace notes"
            
            distribution = self.describe_distribution(self.count_gracenotes_in_measures, 
                                                    self.gracenote_count)
            if distribution:
                summary += f" ({distribution})."

        # Clean up and format the summary
        summary = self.replace_end_with(summary, ", ", ". ").capitalize()
        return summary

    def _describe_chord_details(self):
        """Generate detailed description of chord characteristics."""
        details = ""
        
        # Chord names
        chord_names = self.describe_count_list(self.count_chord_common_names, self.chord_count)
        if chord_names:
            details += f" ({chord_names}, "
        else:
            details += " ("
            
        # Chord durations
        chord_durations = self.describe_count_list(self.count_rhythm_chord, self.chord_count)
        if chord_durations:
            details += f"{chord_durations}, "
            
        # Number of notes in chords
        notes_in_chords_list = sorted(self.count_notes_in_chords.items(), 
                                    key=lambda item: item[1], reverse=True)
        note_count_desc = self.describe_count_list(notes_in_chords_list, self.chord_count)
        if note_count_desc:
            details += f"{note_count_desc} notes, "
            
        details = self.replace_end_with(details, ", ", ")")
        return details

    def _describe_note_details(self):
        """Generate detailed description of note characteristics."""
        details = " ("
        
        # Note durations
        duration_desc = self.describe_count_list(self.count_rhythm_note, self.note_count)
        if duration_desc:
            details += f"{duration_desc}, "
            
        # Pitch names
        pitch_desc = self.describe_count_list(self.count_pitch_names, self.note_count)
        if pitch_desc:
            details += f"{pitch_desc}, "
            
        # Intervals
        interval_desc = self._describe_intervals()
        if interval_desc:
            details += interval_desc
            
        details += ")"
        return details

    def _describe_intervals(self):
        """Generate description of interval patterns."""
        # Convert absolute interval counts to named intervals
        sorted_abs_intervals = dict(sorted(enumerate(self.count_intervals_abs), 
                                         key=lambda item: item[1], reverse=True))
        named_abs_intervals = {}
        for index, count in sorted_abs_intervals.items():
            if index in self._INTERVAL_MAP:
                named_abs_intervals[self._INTERVAL_MAP[index]] = count

        interval_desc = self.describe_count_list(list(named_abs_intervals.items()), 
                                               self.interval_count)
        interval_desc = self.replace_end_with(interval_desc, ", ", "")
        
        if not interval_desc:
            interval_desc = self.describe_count_list_several(list(named_abs_intervals.items()), 
                                                           self.interval_count, "intervals")

        # Add directional information
        if self.interval_ascending_count > self.interval_descending_count * 2:
            interval_desc += ", mostly ascending"
        elif self.interval_descending_count > self.interval_ascending_count * 2:
            interval_desc += ", mostly descending"
            
        return interval_desc

    def _describe_rest_details(self):
        """Generate detailed description of rest characteristics."""
        rest_desc = self.describe_count_list(self.count_rhythm_rest, self.rest_count)
        distribution = self.describe_distribution(self.count_rests_in_measures, self.rest_count)
        
        if rest_desc:
            return f" ({rest_desc} - {distribution})"
        return ""
    def describe_measure_repeated_many(self, measures_dictionary, description):
        """
        Describe individual measures that are repeated frequently.
        
        Args:
            measures_dictionary (dict): {measure_number: [list_of_occurrences]}
            description (str): Type of repetition ("pitch and rhythm", "rhythm", etc.)
            
        Returns:
            str: Description of frequently repeated measures
        """
        repetition = ""
        
        for key, measure_list in measures_dictionary.items():
            percent_usage = len(measure_list) / len(self.measure_indexes) * 100
            
            if percent_usage > 33:
                repetition += f"The {description} in bar {key} is used "
                repetition += f"{self.describe_percentage(percent_usage)} of the way through. "
                
        return repetition

    def describe_measure_group_repeated_many(self, measure_group_list, description):
        """
        Describe groups of measures that are repeated frequently.
        
        Args:
            measure_group_list (list): List of measure groups with their occurrences
            description (str): Type of repetition being described
            
        Returns:
            str: Description of frequently repeated measure groups
        """
        repetition = ""
        
        for group in measure_group_list:
            group_length = group[0][1] - group[0][0] + 1
            group_repetition_percent = (group_length * len(group) / len(self.measure_indexes)) * 100
            
            if group_repetition_percent > 33:
                if group[0][1] - group[0][0] == 1:  # Two consecutive bars
                    repetition += f"The {description} in bars {group[0][0]} and {group[0][1]}"
                else:  # Range of bars
                    repetition += f"The {description} in bars {group[0][0]} to {group[0][1]}"
                    
                repetition += f" are used {self.describe_repetition_percentage(group_repetition_percent)} "
                repetition += "of the way through. "
                
        return repetition

    def describe_repetition_summary(self):
        """
        Generate a comprehensive summary of repetition patterns in the musical part.
        
        Returns:
            str: HTML-formatted description of repetition patterns
        """
        repetition = ""

        # Describe major repetition patterns (over 33% of the score)
        repetition += self.describe_measure_group_repeated_many(
            self.measure_groups_list, "pitch and rhythm"
        )
        repetition += self.describe_measure_repeated_many(
            self.repeated_measures_not_in_groups_dictionary, "pitch and rhythm"
        )
        repetition += self.describe_measure_group_repeated_many(
            self.measure_rhythm_not_full_match_groups_list, "rhythm"
        )
        repetition += self.describe_measure_repeated_many(
            self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary, "rhythm"
        )
        repetition += self.describe_measure_group_repeated_many(
            self.measure_intervals_not_full_match_groups_list, "intervals"
        )
        repetition += self.describe_measure_repeated_many(
            self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary, "intervals"
        )

        # If no major patterns found, look for smaller patterns
        if not repetition:
            repetition += self._describe_smaller_repetition_patterns()

        # Describe repetition lengths and structure
        repetition += self._describe_repetition_structure()

        # Add measure uniqueness information
        if len(self.part.getElementsByClass('Measure')) > 1:
            total_measures = len(self.part.getElementsByClass('Measure'))
            unique_measures = len(self.measure_analyse_indexes_list)
            unique_rhythms = len(self.measure_rhythm_analyse_indexes_list)
            unique_intervals = len(self.measure_intervals_analyse_indexes_list)
            
            repetition += f"There are {unique_measures} unique measures - "
            repetition += f"of these, {unique_rhythms} measures have unique rhythm "
            repetition += f"and {unique_intervals} measures have unique intervals. "

        if repetition:
            repetition = "<br/>" + repetition.capitalize()
            
        return repetition

    def _describe_smaller_repetition_patterns(self):
        """
        Describe smaller repetition patterns when no major ones are found.
        
        Returns:
            str: Description of smaller patterns
        """
        repetition = ""
        
        # Check rhythm matches
        rhythm_matches = self.calculate_repeated_measures_lists(
            self.measure_rhythm_analyse_indexes_dictionary, False
        )
        rhythm_matches.sort(key=lambda item: len(item), reverse=True)
        
        for match_group in rhythm_matches:
            percent_usage = (len(match_group) / len(self.measure_indexes)) * 100
            if percent_usage > 33:
                repetition += f"The rhythm in bar {match_group[0]} is used "
                repetition += f"{self.describe_percentage(percent_usage)} of the way through. "
                break

        # Check interval matches
        interval_matches = self.calculate_repeated_measures_lists(
            self.measure_intervals_analyse_indexes_dictionary, False
        )
        interval_matches.sort(key=lambda item: len(item), reverse=True)
        
        for match_group in interval_matches:
            percent_usage = (len(match_group) / len(self.measure_indexes)) * 100
            if percent_usage > 33:
                repetition += f"The intervals in bar {match_group[0]} are used "
                repetition += f"{self.describe_percentage(percent_usage)} of the way through. "
                break
                
        return repetition

    def _describe_repetition_structure(self):
        """
        Describe the structure of repetition lengths.
        
        Returns:
            str: Description of repetition length patterns
        """
        repetition = ""
        
        # Analyze repetition lengths for full matches
        repetition_lengths = {}
        for group in self.measure_groups_list:
            length = group[0][1] - group[0][0] + 1
            repetition_lengths[length] = repetition_lengths.get(length, 0) + 1

        # Add individual measure repetitions
        repetition_lengths[1] = len(self.repeated_measures_not_in_groups_dictionary)

        # Analyze rhythm/interval repetition lengths
        rhythm_interval_lengths = {}
        for group in self.measure_rhythm_not_full_match_groups_list:
            length = group[0][1] - group[0][0] + 1
            rhythm_interval_lengths[length] = rhythm_interval_lengths.get(length, 0) + 1

        for group in self.measure_intervals_not_full_match_groups_list:
            length = group[0][1] - group[0][0] + 1
            rhythm_interval_lengths[length] = rhythm_interval_lengths.get(length, 0) + 1

        rhythm_interval_lengths[1] = (
            len(self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary) +
            len(self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary)
        )

        # Describe repetition lengths
        if repetition_lengths:
            total_lengths = sum(repetition_lengths.values())
            sorted_lengths = sorted(repetition_lengths.items())
            length_description = self.describe_count_list(sorted_lengths, total_lengths)
            length_description = self.replace_end_with(length_description, ", ", "")
            
            if not length_description:
                length_description = self.describe_count_list_several(
                    sorted_lengths, total_lengths, "lengths"
                )
                
            if length_description:
                repetition += f"The repeated sections are {length_description} measures long. "

        # Describe rhythm/interval repetition lengths
        if rhythm_interval_lengths:
            total_lengths = sum(rhythm_interval_lengths.values())
            sorted_lengths = sorted(rhythm_interval_lengths.items())
            length_description = self.describe_count_list(sorted_lengths, total_lengths)
            length_description = self.replace_end_with(length_description, ", ", "")
            
            if not length_description:
                length_description = self.describe_count_list_several(
                    sorted_lengths, total_lengths, "lengths"
                )
                
            if length_description:
                repetition += f"The repeated sections of just rhythm/intervals are {length_description} measures long. "

        return repetition

    def insert_or_plus_equals(self, dictionary, key, value):
        """
        Add value to dictionary key, creating the key if it doesn't exist.
        
        Args:
            dictionary (dict): Dictionary to modify
            key: Dictionary key
            value: Value to add
        """
        if key in dictionary:
            dictionary[key] += value
        else:
            dictionary[key] = value

    def describe_section_usage_in_context(self, groups_list, repeat_what, repetition_in_context):
        """
        Describe how section groups are used throughout the piece.
        
        Args:
            groups_list (list): List of measure groups
            repeat_what (str): Description prefix (e.g., "Bars ", "The rhythm in bars ")
            repetition_in_context (dict): Dictionary to update with context info
        """
        for group in groups_list:
            group_length = group[0][1] - group[0][0] + 1
            group_repetition_percent = (group_length * len(group) / len(self.measure_indexes)) * 100
            used_lots = group_repetition_percent > 50

            # Determine "and" vs "through" connector
            connector = " and " if (group[0][1] - group[0][0] == 1) else " through "

            for index, usage in enumerate(group):
                if index >= 1:  # Not the first occurrence
                    text = f"{repeat_what}{usage[0]}{connector}{usage[1]}"
                    text += f" were first used at {group[0][0]}"
                    
                    if index >= 2:
                        text += f" and lately used at {group[index-1][0]}"
                else:  # First occurrence
                    text = f"Bars {usage[0]}{connector}{usage[1]}"
                    text += f" are used {len(group)-1} more times. "

                self.insert_or_plus_equals(repetition_in_context, usage[0], text + ". ")

    def describe_measure_usage_in_context(self, repeated_measures_dict, repeat_what, repetition_in_context):
        """
        Describe how individual measures are used throughout the piece.
        
        Args:
            repeated_measures_dict (dict): {first_measure: [other_occurrences]}
            repeat_what (str): Description prefix (e.g., "Bar ", "The rhythm in bar ")
            repetition_in_context (dict): Dictionary to update with context info
        """
        for key, measure_list in repeated_measures_dict.items():
            # First occurrence description
            text = f"{repeat_what}{key} is used {len(measure_list)} more times. "
            self.insert_or_plus_equals(repetition_in_context, key, text)

            # Subsequent occurrence descriptions
            for index, measure_num in enumerate(measure_list):
                text = f"{repeat_what}{measure_num} was first used at {key}"
                
                if index >= 1:
                    text += f" and lately used at {measure_list[index-1]}"
                    
                self.insert_or_plus_equals(repetition_in_context, measure_num, text + ". ")

    def describe_repetition_in_context(self):
        """
        Generate contextual repetition information for each measure.
        
        Returns:
            dict: {measure_number: context_string} describing repetition context
        """
        repetition_in_context = {}

        # Describe section groups
        self.describe_section_usage_in_context(
            self.measure_groups_list, "Bars ", repetition_in_context
        )
        self.describe_section_usage_in_context(
            self.measure_rhythm_not_full_match_groups_list, 
            "The rhythm in bars ", repetition_in_context
        )
        self.describe_section_usage_in_context(
            self.measure_intervals_not_full_match_groups_list,
            "The intervals in bars ", repetition_in_context
        )

        # Describe individual measures
        self.describe_measure_usage_in_context(
            self.repeated_measures_not_in_groups_dictionary,
            "Bar ", repetition_in_context
        )
        self.describe_measure_usage_in_context(
            self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary,
            "The rhythm in bar ", repetition_in_context
        )
        self.describe_measure_usage_in_context(
            self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary,
            "The intervals in bar ", repetition_in_context
        )

        return repetition_in_context

    def describe_repetition(self):
        """
        Generate a detailed description of all repetition patterns (legacy method).
        
        This method provides a comprehensive but verbose description of repetition
        patterns. It's kept for compatibility but describe_repetition_summary()
        is preferred for user-facing descriptions.
        
        Returns:
            str: Detailed repetition description
        """
        repetition = ""
        
        # Describe measure groups
        if self.measure_groups_list:
            for group in self.measure_groups_list:
                group_length = group[0][1] - group[0][0] + 1
                group_repetition_percent = (group_length * len(group) / len(self.measure_indexes)) * 100
                
                if group_repetition_percent > 50:
                    # High repetition - describe percentage
                    if group[0][1] - group[0][0] == 1:
                        repetition += f"Bars {group[0][0]} and {group[0][1]}"
                    else:
                        repetition += f"Bars {group[0][0]} to {group[0][1]}"
                    repetition += f" are used {self.describe_repetition_percentage(group_repetition_percent)} "
                    repetition += "of the way through. "
                else:
                    # Lower repetition - list occurrences
                    if group[0][1] - group[0][0] == 1:
                        repetition += f"Bars {group[0][0]} and {group[0][1]}"
                    else:
                        repetition += f"Bars {group[0][0]} to {group[0][1]}"
                    repetition += " are used at "
                    
                    for index, occurrence in enumerate(group[1:]):
                        if index == len(group) - 2 and index > 0:
                            repetition += " and "
                        elif index < len(group) - 1 and index > 0:
                            repetition += ", "
                        repetition += str(occurrence[0])
                    repetition += ". "

        # Describe individual repeated measures
        for key, measure_list in self.repeated_measures_not_in_groups_dictionary.items():
            repetition += f"Bar {key} is used at "
            for index, measure_num in enumerate(measure_list):
                if index == len(measure_list) - 1 and index > 0:
                    repetition += " and "
                elif index < len(measure_list) - 1 and index > 0:
                    repetition += ", "
                repetition += str(measure_num)
            repetition += ". "

        if not repetition:
            repetition += "There are no repeated bars. "

        # Add rhythm-only and interval-only repetition descriptions
        repetition += self._describe_rhythm_repetition()
        repetition += self._describe_interval_repetition()

        return repetition

    def _describe_rhythm_repetition(self):
        """Generate description of rhythm-only repetition patterns."""
        rhythm_repetition = ""
        
        # Describe rhythm groups
        if self.measure_rhythm_not_full_match_groups_list:
            for group in self.measure_rhythm_not_full_match_groups_list:
                if group[0][1] - group[0][0] == 1:
                    rhythm_repetition += f"The rhythm in bars {group[0][0]} and {group[0][1]}"
                else:
                    rhythm_repetition += f"The rhythm in bars {group[0][0]} to {group[0][1]}"
                rhythm_repetition += " are used at "
                
                for index, occurrence in enumerate(group[1:]):
                    if index == len(group) - 1 and index > 0:
                        rhythm_repetition += " and "
                    elif index < len(group) - 1 and index > 0:
                        rhythm_repetition += ", "
                    rhythm_repetition += str(occurrence[0])
                rhythm_repetition += ". "

        # Describe individual rhythm repetitions
        for key, measure_list in self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary.items():
            rhythm_repetition += f"The rhythm in bar {key} is used at "
            for index, measure_num in enumerate(measure_list):
                if index == len(measure_list) - 1 and index > 0:
                    rhythm_repetition += " and "
                elif index < len(measure_list) - 1 and index > 0:
                    rhythm_repetition += ", "
                rhythm_repetition += str(measure_num)
            rhythm_repetition += ". "

        if not rhythm_repetition:
            rhythm_repetition = "There are no bars with just the same rhythm. "

        return rhythm_repetition

    def _describe_interval_repetition(self):
        """Generate description of interval-only repetition patterns."""
        interval_repetition = ""
        
        # Describe interval groups
        if self.measure_intervals_not_full_match_groups_list:
            for group in self.measure_intervals_not_full_match_groups_list:
                if group[0][1] - group[0][0] == 1:
                    interval_repetition += f"The intervals in bars {group[0][0]} and {group[0][1]}"
                else:
                    interval_repetition += f"The intervals in bars {group[0][0]} to {group[0][1]}"
                interval_repetition += " are used at "
                
                for index, occurrence in enumerate(group[1:]):
                    if index == len(group) - 1 and index > 0:
                        interval_repetition += " and "
                    elif index < len(group) - 1 and index > 0:
                        interval_repetition += ", "
                    interval_repetition += str(occurrence[0])
                interval_repetition += ". "

        # Describe individual interval repetitions
        for key, measure_list in self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary.items():
            interval_repetition += f"The intervals in bar {key} are used at "
            for index, measure_num in enumerate(measure_list):
                if index == len(measure_list) - 1 and index > 0:
                    interval_repetition += " and "
                elif index < len(measure_list) - 1 and index > 0:
                    interval_repetition += ", "
                interval_repetition += str(measure_num)
            interval_repetition += ". "

        if not interval_repetition:
            interval_repetition = "There are no bars with just the same intervals. "

        return interval_repetition
    def set_part(self, part):
        """
        Analyze a musical part comprehensively, creating indexes and identifying patterns.
        
        This is the main analysis method that processes every note, chord, and rest
        in the musical part to create comprehensive indexes for pattern recognition.
        
        Args:
            part: Music21 Part object to analyze
        """
        self.part = part

        event_index = 0
        previous_note_pitch = -1
        current_measure = -1
        measure_analyse_indexes = AnalyseSection()
        measure_accidentals = 0
        measure_gracenotes = 0
        measure_rests = 0

        # Process each note and rest in the part
        for musical_element in self.part.flatten().notesAndRests:
            # Handle new measure
            if musical_element.measureNumber > current_measure:
                current_measure = musical_element.measureNumber
                self.measure_indexes[current_measure] = event_index
                
                # Process completed measure (if not the first iteration)
                if measure_analyse_indexes.analyse_indexes:
                    self._process_completed_measure(
                        measure_analyse_indexes, current_measure - 1,
                        measure_accidentals, measure_gracenotes, measure_rests
                    )
                    
                    # Reset for new measure
                    measure_analyse_indexes = AnalyseSection()
                    previous_note_pitch = -1
                    measure_accidentals = 0
                    measure_gracenotes = 0
                    measure_rests = 0

            # Analyze the current musical element
            analyse_index = AnalyseIndex(event_index)
            
            if musical_element.isRest:
                self._process_rest(analyse_index, musical_element)
                measure_rests += 1
                previous_note_pitch = -1
            elif musical_element.isChord and type(musical_element).__name__ != 'ChordSymbol':
                accidentals_in_chord = self._process_chord(analyse_index, musical_element)
                measure_accidentals += accidentals_in_chord
                if musical_element.duration.quarterLength == 0.0:
                    measure_gracenotes += len(musical_element.pitches)
                previous_note_pitch = -1
            elif not musical_element.isChord:
                if isinstance(musical_element, note.Unpitched):
                    analyse_index.event_type = 'u'
                    previous_note_pitch = -1
                else:
                    interval_info = self._process_note(
                        analyse_index, musical_element, previous_note_pitch
                    )
                    if musical_element.pitch.accidental and musical_element.pitch.accidental.displayStatus:
                        measure_accidentals += 1
                    if musical_element.duration.quarterLength == 0.0:
                        measure_gracenotes += 1
                    previous_note_pitch = interval_info

            # Add to measure analysis
            self._add_to_analysis_indexes(analyse_index, event_index)
            measure_analyse_indexes.analyse_indexes.append(analyse_index)
            event_index += 1

        # Process the final measure
        if measure_analyse_indexes.analyse_indexes:
            self._process_completed_measure(
                measure_analyse_indexes, current_measure,
                measure_accidentals, measure_gracenotes, measure_rests
            )

        logger.info(f"Analysis complete: {self.note_count} notes, {self.chord_count} chords, {self.rest_count} rests")

        # Calculate all repetition patterns
        self._calculate_all_repetition_patterns()
        
        # Generate count statistics
        self._generate_count_statistics()

    def _process_rest(self, analyse_index, rest_element):
        """Process a rest element and update analysis data."""
        analyse_index.event_type = 'r'
        duration = rest_element.duration.quarterLength
        
        if duration not in self.rhythm_rest_dictionary:
            self.rhythm_rest_dictionary[duration] = []
        self.rhythm_rest_dictionary[duration].append(analyse_index.event_index)
        
        analyse_index.rhythm_rest_index = [duration, len(self.rhythm_rest_dictionary[duration]) - 1]
        
        self.total_rest_duration += duration
        self.rest_count += 1

    def _process_chord(self, analyse_index, chord_element):
        """
        Process a chord element and update analysis data.
        
        Returns:
            int: Number of accidentals in the chord
        """
        analyse_index.event_type = 'c'
        duration = chord_element.duration.quarterLength
        accidental_count = 0

        # Handle grace notes separately
        if duration == 0.0:
            self.gracenote_count += len(chord_element.pitches)
        else:
            # Process chord duration
            if duration not in self.rhythm_chord_dictionary:
                self.rhythm_chord_dictionary[duration] = []
            self.rhythm_chord_dictionary[duration].append(analyse_index.event_index)
            analyse_index.rhythm_chord_index = [duration, len(self.rhythm_chord_dictionary[duration]) - 1]

        # Count notes in chord
        if len(chord_element.pitches) <= 10:
            self.count_notes_in_chords[len(chord_element.pitches)] += 1

        # Process chord pitches
        chord_index = self.find_chord(chord_element)
        if chord_index == -1:
            self.chord_pitches_list.append(sorted(p.midi for p in chord_element.pitches))
            chord_index = len(self.chord_pitches_list) - 1
            self.chord_pitches_dictionary[chord_index] = []
        self.chord_pitches_dictionary[chord_index].append(analyse_index.event_index)
        analyse_index.chord_pitches_index = [chord_index, len(self.chord_pitches_dictionary[chord_index]) - 1]

        # Process chord intervals
        chord_intervals = self.make_chord_intervals(chord_element)
        interval_index = self.find_chord_intervals(chord_intervals)
        if interval_index == -1:
            self.chord_intervals_list.append(chord_intervals)
            interval_index = len(self.chord_intervals_list) - 1
            self.chord_intervals_dictionary[interval_index] = []
        self.chord_intervals_dictionary[interval_index].append(analyse_index.event_index)
        analyse_index.chord_interval_index = [interval_index, len(self.chord_intervals_dictionary[interval_index]) - 1]

        # Process chord name
        common_name = self._get_chord_common_name(chord_element, chord_intervals)
        if common_name not in self.chord_common_name_dictionary:
            self.chord_common_name_dictionary[common_name] = []
        self.chord_common_name_dictionary[common_name].append(analyse_index.event_index)
        analyse_index.chord_name_index = [common_name, len(self.chord_common_name_dictionary[common_name]) - 1]

        # Count accidentals
        for pitch in chord_element.pitches:
            if pitch.accidental and pitch.accidental.displayStatus:
                accidental_count += 1
                self.accidental_count += 1
        self.possible_accidental_count += len(chord_element.pitches)

        self.total_chord_duration += duration
        self.chord_count += 1
        
        return accidental_count

    def _get_chord_common_name(self, chord_element, chord_intervals):
        """
        Get a human-readable name for a chord, with custom naming for some chords.
        
        Args:
            chord_element: Music21 chord object
            chord_intervals (list): Interval structure of the chord
            
        Returns:
            str: Common name for the chord
        """
        common_name = chord_element.commonName
        
        # Custom naming for specific chord types
        if chord_intervals == [5, 7]:  # Perfect 4th + Perfect 5th from root
            common_name = "Suspended 4th"
        elif chord_intervals == [2, 7]:  # Major 2nd + Perfect 5th from root
            common_name = "Suspended 2nd"
            
        return common_name

    def _process_note(self, analyse_index, note_element, previous_note_pitch):
        """
        Process a note element and update analysis data.
        
        Args:
            analyse_index: AnalyseIndex object to update
            note_element: Music21 note object
            previous_note_pitch: MIDI pitch of previous note (-1 if none)
            
        Returns:
            int: MIDI pitch of this note for next interval calculation
        """
        analyse_index.event_type = 'n'
        
        # Count accidentals and possible accidentals
        if note_element.pitch.accidental and note_element.pitch.accidental.displayStatus:
            self.accidental_count += 1
        self.possible_accidental_count += 1

        # Process pitch information
        midi_pitch = note_element.pitch.midi
        self.pitch_number_dictionary[midi_pitch].append(analyse_index.event_index)
        analyse_index.pitch_number_index = [midi_pitch, len(self.pitch_number_dictionary[midi_pitch]) - 1]

        # Process pitch name (without octave)
        pitch_name = note_element.pitch.name
        if pitch_name not in self.pitch_name_dictionary:
            self.pitch_name_dictionary[pitch_name] = []
        self.pitch_name_dictionary[pitch_name].append(analyse_index.event_index)
        analyse_index.pitch_name_index = [pitch_name, len(self.pitch_name_dictionary[pitch_name]) - 1]

        # Process intervals
        if previous_note_pitch > -1:
            interval = midi_pitch - previous_note_pitch
            if interval not in self.interval_dictionary:
                self.interval_dictionary[interval] = []
            self.interval_dictionary[interval].append(analyse_index.event_index)
            analyse_index.interval_index = [interval, len(self.interval_dictionary[interval]) - 1]

            # Update interval statistics
            if interval > 0:
                self.interval_ascending_count += 1
            elif interval < 0:
                self.interval_descending_count += 1
            else:
                self.interval_unison_count += 1
            self.interval_count += 1

            # Update absolute interval counts
            abs_interval = abs(interval)
            if abs_interval < 25:
                self.count_intervals_abs[abs_interval] += 1

        # Process note duration
        duration = note_element.duration.quarterLength
        if duration == 0.0:
            self.gracenote_count += 1
        else:
            if duration not in self.rhythm_note_dictionary:
                self.rhythm_note_dictionary[duration] = []
            self.rhythm_note_dictionary[duration].append(analyse_index.event_index)
            analyse_index.rhythm_note_index = [duration, len(self.rhythm_note_dictionary[duration]) - 1]

        self.total_note_duration += duration
        self.note_count += 1
        
        return midi_pitch

    def _add_to_analysis_indexes(self, analyse_index, event_index):
        """Add an AnalyseIndex to the comprehensive index system."""
        # Find or create entry in unique indexes list
        index = self.find_analyse_index(analyse_index)
        if index == -1:
            self.analyse_indexes_list.append(analyse_index)
            index = len(self.analyse_indexes_list) - 1
            self.analyse_indexes_dictionary[index] = []
            
        self.analyse_indexes_dictionary[index].append(event_index)
        self.analyse_indexes_all[event_index] = [index, len(self.analyse_indexes_dictionary[index]) - 1]

    def _process_completed_measure(self, measure_analyse_indexes, measure_number, 
                                   accidentals, gracenotes, rests):
        """
        Process a completed measure and add it to various analysis indexes.
        
        Args:
            measure_analyse_indexes: AnalyseSection for the completed measure
            measure_number: The measure number
            accidentals: Number of accidentals in the measure
            gracenotes: Number of grace notes in the measure
            rests: Number of rests in the measure
        """
        # Store measure statistics
        self.count_accidentals_in_measures[measure_number] = accidentals
        self.count_gracenotes_in_measures[measure_number] = gracenotes
        self.count_rests_in_measures[measure_number] = rests

        # Process full measure analysis
        self._add_measure_to_analysis(measure_analyse_indexes, measure_number, 
                                    self.measure_analyse_indexes_list,
                                    self.measure_analyse_indexes_dictionary,
                                    self.measure_analyse_indexes_all, 0)

        # Process rhythm-only analysis
        self._add_measure_to_analysis(measure_analyse_indexes, measure_number,
                                    self.measure_rhythm_analyse_indexes_list,
                                    self.measure_rhythm_analyse_indexes_dictionary,
                                    self.measure_rhythm_analyse_indexes_all, 1)

        # Process interval-only analysis (if measure contains intervals)
        if self.does_section_contain_intervals(measure_analyse_indexes):
            self._add_measure_to_analysis(measure_analyse_indexes, measure_number,
                                        self.measure_intervals_analyse_indexes_list,
                                        self.measure_intervals_analyse_indexes_dictionary,
                                        self.measure_intervals_analyse_indexes_all, 2)

    def _add_measure_to_analysis(self, measure_section, measure_number, 
                               analysis_list, analysis_dict, analysis_all, compare_type):
        """
        Add a measure to a specific type of analysis (full, rhythm, or intervals).
        
        Args:
            measure_section: AnalyseSection for the measure
            measure_number: The measure number
            analysis_list: List to store unique patterns
            analysis_dict: Dictionary mapping patterns to occurrences
            analysis_all: Dictionary mapping measures to pattern info
            compare_type: Type of comparison (0=all, 1=rhythm, 2=intervals)
        """
        index = self.find_section(measure_section, analysis_list, compare_type)
        
        if index == -1:
            # New unique pattern
            analysis_list.append(measure_section)
            index = len(analysis_list) - 1
            analysis_dict[index] = [measure_number]
            analysis_all[measure_number] = [index, 0]
        else:
            # Existing pattern
            analysis_dict[index].append(measure_number)
            analysis_all[measure_number] = [index, len(analysis_dict[index]) - 1]

    def _calculate_all_repetition_patterns(self):
        """Calculate all types of repetition patterns after analysis is complete."""
        # Calculate full match repetitions
        self.repeated_measures_lists = self.calculate_repeated_measures_lists(
            self.measure_analyse_indexes_dictionary, False
        )
        self.measure_groups_list = self.calculate_measure_groups(
            self.measure_analyse_indexes_all, self.measure_analyse_indexes_dictionary
        )
        self.repeated_measures_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(
            self.measure_analyse_indexes_dictionary.values(), self.measure_groups_list
        )

        # Calculate rhythm-only repetitions
        self.repeated_measures_lists_rhythm = self.calculate_repeated_measures_lists(
            self.measure_rhythm_analyse_indexes_dictionary, True
        )
        self.measure_rhythm_not_full_match_groups_list = self.calculate_measure_groups(
            self.measure_rhythm_analyse_indexes_all, self.measure_rhythm_analyse_indexes_dictionary
        )
        self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(
            self.repeated_measures_lists_rhythm, self.measure_rhythm_not_full_match_groups_list
        )

        # Calculate interval-only repetitions
        self.repeated_measures_lists_intervals = self.calculate_repeated_measures_lists(
            self.measure_intervals_analyse_indexes_dictionary, True
        )
        self.measure_intervals_not_full_match_groups_list = self.calculate_measure_groups(
            self.measure_intervals_analyse_indexes_all, self.measure_intervals_analyse_indexes_dictionary
        )
        self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(
            self.repeated_measures_lists_intervals, self.measure_intervals_not_full_match_groups_list
        )

    def _generate_count_statistics(self):
        """Generate sorted count statistics for all musical elements."""
        # Generate count lists from dictionaries
        self.count_pitches = self.count_dictionary(self.pitch_number_dictionary)
        self.count_pitch_names = self.count_dictionary(self.pitch_name_dictionary)
        self.count_intervals = self.count_dictionary(self.interval_dictionary)
        self.count_chord_common_names = self.count_dictionary(self.chord_common_name_dictionary)
        self.count_rhythm_note = self.count_dictionary(self.rhythm_note_dictionary)
        self.count_rhythm_rest = self.count_dictionary(self.rhythm_rest_dictionary)
        self.count_rhythm_chord = self.count_dictionary(self.rhythm_chord_dictionary)
        self.count_chord_pitches = self.count_dictionary(self.chord_pitches_dictionary)
        self.count_chord_intervals = self.count_dictionary(self.chord_intervals_dictionary)

        # Convert duration values to readable names
        self.rename_count_list_keys(self.count_rhythm_note, self._DURATION_MAP)
        self.rename_count_list_keys(self.count_rhythm_rest, self._DURATION_MAP)
        self.rename_count_list_keys(self.count_rhythm_chord, self._DURATION_MAP)

    def rename_count_list_keys(self, count_list, key_names):
        """
        Replace numeric keys in count list with human-readable names.
        
        Args:
            count_list: List of [key, count] pairs
            key_names: Dictionary mapping numeric keys to names
        """
        for item in count_list:
            if item[0] in key_names:
                item[0] = key_names[item[0]]

    def count_dictionary(self, dictionary):
        """
        Convert a dictionary to a sorted count list.
        
        Args:
            dictionary: Dictionary with values being lists
            
        Returns:
            list: [(key, count)] sorted by count descending
        """
        count_list = []
        for key, value_list in dictionary.items():
            count_list.append([key, len(value_list)])
        count_list.sort(key=lambda item: item[1], reverse=True)
        return count_list
