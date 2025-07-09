# __author__ = 'PMarchant' # Author of this file [27]

import json # Not directly used in provided excerpts but often for data handling [27]
import math # Used for mathematical operations [27]
import pprint # Used for pretty-printing data structures, useful for debugging [27]
import logging # Used for logging messages [27]
import logging.handlers # Related to logging setup [27]
import logging.config # Related to logging setup [27]

from music21 import * # Imports all classes and functions from the music21 library, essential for music analysis [27]

logger = logging.getLogger("TSScore") # Configures a logger for the "TSScore" application [27]

"""
This module aims to identify common musical elements, their distribution,
and patterns of repetition within a musical score. [27]

The core idea is to create separate "indexes" or "buckets" for various musical attributes
like pitch, rhythm, interval, and chord name. [27]
For attributes suitable as dictionary keys (e.g., MIDI pitch), the dictionary key is the attribute value,
and the value is a list of all event indices where that attribute occurs. [28]
For attributes not suitable as dictionary keys (e.g., pitches in a chord), a list is used
to store these unique attributes. Then, a dictionary maps an index from this list to
a list of event indices where that particular unique attribute occurs. [28]

An `AnalyseIndex` class combines indexes for all musical attributes for a single event. [28]
A list of `AnalyseIndex` instances corresponds to each note, chord, or rest in a Part,
storing the type of musical attribute (e.g., A4 notes for pitch) and its occurrence index
within the respective attribute dictionary. [28]
This structure allows discerning previous/next matching events for any musical attribute. [29]

A similar technique is applied to `Measure` objects and groups of `Measure` objects
to identify repetitions. [29]
"""

class AnalyseIndex:
    """
    Represents an analysed musical event (note, chord, or rest)
    and stores various indexes related to its musical attributes. [29]
    """
    def __init__(self, ei):
        """
        Initialises an AnalyseIndex instance.
        Args:
            ei (int): The event index (its position within the part's flat stream). [29]
        """
        self.event_index = ei # Unique identifier for the event within its part. [29]
        self.event_type = '' # 'n' for note, 'c' for chord, 'r' for rest. [29]

        # Stores [index of particular attribute in a list, occurrence index in a dictionary] [29]
        self.chord_interval_index = [-1, -1] # Index for chord intervals. [30]
        self.chord_pitches_index = [-1, -1] # Index for chord pitches. [30]
        self.chord_name_index = ['', -1] # Index for chord common name. [30]
        self.pitch_number_index = [-1, -1] # Index for MIDI pitch number. [30]
        self.pitch_name_index = ['', -1] # Index for pitch name (e.g., 'C#'). [30]
        self.interval_index = [None, -1] # Index for melodic intervals from previous note. [30]

        # Rhythm indexes for different event types. Possibly only needs one. [30]
        self.rhythm_note_index = [-1, -1] # Index for note rhythm. [30]
        self.rhythm_chord_index = [-1, -1] # Index for chord rhythm. [30]
        self.rhythm_rest_index = [-1, -1] # Index for rest rhythm. [30]

    def print_info(self):
        """Prints detailed information about the AnalyseIndex for debugging."""
        print("EventIndex..." + str(self.event_index) + " - type " + self.event_type) [31]
        if (self.event_type == 'n'): # If it's a note [31]
            print(str(self.pitch_name_index) + str(self.pitch_number_index) + str(self.interval_index)) # Print pitch and interval info [31]
            print("rhythm " + str(self.rhythm_note_index)) # Print rhythm info [31]
        elif (self.event_type == 'c'): # If it's a chord [31]
            print(str(self.chord_pitches_index) + str(self.chord_interval_index) + str(self.chord_name_index)) # Print chord info [31]
            print("rhythm " + str(self.rhythm_chord_index)) # Print rhythm info [31]
        elif (self.event_type == 'r'): # If it's a rest [31]
            print("rhythm " + str(self.rhythm_rest_index)) # Print rhythm info [31]

class AnalyseSection:
    """
    Represents a section of music, typically a measure,
    containing a list of `AnalyseIndex` instances. [32, 33]
    """
    def __init__(self):
        self.analyse_indexes = [] # List of AnalyseIndex instances within this section. [31]
        self.section_start_event_indexes = [] # Event indexes each time this section starts (seems unused in source). [34]

    def print_info(self):
        """Prints the length of the section."""
        print("section length = " + str(len(self.analyse_indexes))) [34]
        # for ai in self.analyse_indexes: # Commented out, but would print info for each AnalyseIndex [34]
        # ai.print_info

class MusicAnalyser:
    """
    The main class for performing musical analysis, identifying patterns,
    and generating summaries of a score's characteristics and repetition. [34]
    """
    score = None # The music21 Score object to be analysed [34]
    analyse_parts = [] # List of AnalysePart instances, one for each part of the score [34]
    summary = "" # General summary string (seems unused globally, rather per-part) [34]
    repetition_parts = [] # List of repetition summaries for each part (seems unused globally) [34]
    repetition_right_hand = "" # Repetition summary for right hand (seems specific and unused globally) [34]
    repetition_left_hand = "" # Repetition summary for left hand (seems specific and unused globally) [34]

    def setScore(self, ts):
        """
        Sets the music21 score to be analysed and initiates the analysis for each part.
        Args:
            ts (Music21TalkingScore): An instance of Music21TalkingScore containing the score. [34]
        """
        self.ts = ts # Stores the Music21TalkingScore object [34]
        self.score = ts.score # Extracts the music21 Score object [34]
        part_index = 0 # Initialise part index (seems unused here as a direct counter) [34]
        self.analyse_parts = [] # Reset analysis parts list [34]
        self.repetition_parts = [] # Reset repetition parts list [34]
        self.summary_parts = [] # List to store summary strings for each part [35]
        self.repetition_in_contexts = {} # Dictionary to store repetition context strings, keyed by part index [35]
        self.general_summary = "" # String to store general score summary [35]
        analyse_index = 0 # Index for the analyse_parts list [35]

        # Iterates through selected instruments to analyse each part belonging to them [35]
        for ins in ts.part_instruments:
            if ins in ts.selected_instruments: # Only analyse selected instruments [35]
                start_part = ts.part_instruments[ins][1] # Get the 0-based index of the first part for this instrument [35]
                instrument_len = ts.part_instruments[ins][2] # Get the number of parts for this instrument [35]
                for part_index in range(start_part, start_part+instrument_len): # Iterate through each part [35]
                    self.analyse_parts.append(AnalysePart()) # Create a new AnalysePart instance for current part [35]
                    self.analyse_parts[analyse_index].set_part(self.score.parts[part_index]) # Set the music21 Part object for analysis [35]
                    summary = self.analyse_parts[analyse_index].describe_summary() # Get summary for the part [35]
                    summary += self.analyse_parts[analyse_index].describe_repetition_summary() # Add repetition summary to part summary [35]
                    # Get repetition in context for the part [35]
                    self.repetition_in_contexts[part_index] = (self.analyse_parts[analyse_index].describe_repetition_in_context())
                    self.summary_parts.append(summary) # Add combined summary to list of part summaries [36]
                    # self.repetition_parts.append(self.analyse_parts[analyse_index].describe_repetition()) # Commented out, likely an alternative way of getting repetition info [36]
                    analyse_index = analyse_index + 1 # Increment analyser index [36]

        self.general_summary += self.describe_general_summary() # Generate and append general score summary [36]

    def describe_general_summary(self):
        """Summarises overall score characteristics like number of bars, time/key/tempo changes."""
        num_measures = len(self.score.parts.getElementsByClass('Measure')) # Get total number of measures [36]
        generalSummary = "" # Initialise summary string [36]
        generalSummary += "There are " + str(num_measures) + " bars... " # Add bar count [37]

        timesigs = self.score.parts.flat.getElementsByClass('TimeSignature') # Get all time signatures [37]
        generalSummary += self.summarise_key_and_time_changes(timesigs, "time signature") # Summarise time signature changes [37]

        keysigs = self.score.parts.flat.getElementsByClass('KeySignature') # Get all key signatures [37]
        generalSummary += self.summarise_key_and_time_changes(keysigs, "key signature") # Summarise key signature changes [37]

        tempos = self.score.flat.getElementsByClass('MetronomeMark') # Get all metronome marks (tempos) [37]
        generalSummary += self.summarise_key_and_time_changes(tempos, "tempo") # Summarise tempo changes [37]
        return generalSummary # Return the full general summary [37]

    def summarise_key_and_time_changes(self, changes_dictionary: dict, changes_name: str):
        """
        Helper method to summarise changes in time signature, key signature, or tempo.
        It lists changes individually if few, or just counts them if many. [38]
        Args:
            changes_dictionary (dict): A dictionary-like object (e.g., music21 stream elements)
                                       containing time/key/tempo objects. [38]
            changes_name (str): The type of change (e.g., "time signature"). [38]
        Returns:
            str: A descriptive string of the changes.
        """
        print("summarise key and time changes") # Debugging print [38]
        changes = "" # Initialise change description string [38]
        numchanges = len(changes_dictionary) - 1 # Number of actual changes (excluding the initial one) [38]

        if numchanges > 4: # If too many changes, just state the count [38]
            changes = "There are " + str(numchanges) + " " + changes_name + " changes..."
        elif numchanges > 0: # If there are a few changes, list them out [38]
            changes = "The " + changes_name + " changes to "
            index = 0 # Counter for iteration [38]
            for ch in changes_dictionary: # Iterate through each change object [38]
                if (index > 0): # Skip the first (initial) entry [39]
                    if (changes_name == "time signature"):
                        changes += self.ts.describe_time_signature(ch) # Get time signature description [39]
                    elif (changes_name == "key signature"):
                        changes += self.ts.describe_key_signature(ch) # Get key signature description [39]
                    elif (changes_name == "tempo"):
                        changes += self.ts.describe_tempo(ch) # Get tempo description [39]
                    changes += " at bar " + str(ch.measureNumber) # Add bar number [39]
                    if index == numchanges-1: # Add " and " before the last item [39]
                        changes += " and "
                    elif index < numchanges-1: # Add ", " between items [39]
                        changes += ", "
                index += 1 # Increment index [39]

        if (changes != ""): # Add a period at the end if changes were described [39]
            changes += ". "
        return changes # Return the changes string [39]

class AnalysePart:
    """
    Manages the analysis for a single part of the musical score.
    It identifies and indexes various musical events (notes, chords, rests)
    and measures, then processes them to find repetition and summarise characteristics. [40]
    """
    # Maps for descriptive output [39, 41, 42]
    _position_map = { # Maps quarter positions of the score to descriptive strings [39]
        0: 'near the start', 1: 'in the 2nd quarter', 2: 'in the 3rd quarter', 3: 'near the end'
    }
    _interval_map = { # Maps semitone intervals to common interval names [41]
        0: 'unison', 1: 'minor 2nd', ..., 24: '2 octaves'
    }
    _DURATION_MAP = { # Maps quarter length durations to British rhythmic terms [42]
        4.0: 'semibreves', 3.0: 'dotted minims', ..., 0.0625: 'hemi-demi-semi-quavers', 0.0: 'grace notes'
    }

    def compare_sections(self, s1: AnalyseSection, s2: AnalyseSection, compare_type):
        """
        Compares two AnalyseSection objects to check if they are identical based on `compare_type`.
        Args:
            s1 (AnalyseSection): The first section to compare. [42]
            s2 (AnalyseSection): The second section to compare. [42]
            compare_type (int): 0 for all attributes, 1 for rhythm only, 2 for intervals only. [43]
        Returns:
            bool: True if sections match, False otherwise.
        """
        to_return = True
        if (len(s1.analyse_indexes) != len(s2.analyse_indexes)): # Sections must have the same number of events [43]
            to_return = False
        else:
            for i in range(len(s1.analyse_indexes)): # Iterate through events in sections [43]
                if (compare_type == 0 and self.compare_indexes(s1.analyse_indexes[i], s2.analyse_indexes[i]) == False): # Compare all attributes [43]
                    to_return = False; break
                elif (compare_type == 1 and self.compare_indexes_rhythm(s1.analyse_indexes[i], s2.analyse_indexes[i]) == False): # Compare rhythm only [43]
                    to_return = False; break
                elif (compare_type == 2 and self.compare_indexes_intervals(s1.analyse_indexes[i], s2.analyse_indexes[i]) == False): # Compare intervals only [43]
                    to_return = False; break
        return to_return [43]

    def compare_indexes_intervals(self, ai1: AnalyseIndex, ai2: AnalyseIndex):
        """
        Compares two AnalyseIndex instances based on their melodic interval. [44]
        Note: Might incorrectly flag non-matches if one has a chord/octaves and the other a single note. [44]
        """
        to_return = True
        if not (ai1.event_type == ai2.event_type): # Event types must match [44]
            to_return = False
        elif (ai1.event_type == 'n'): # Only compare intervals for notes [44]
            if (ai1.interval_index != ai2.interval_index): # Check if interval values match [44]
                to_return = False
        return to_return [44]

    def compare_indexes_rhythm(self, ai1: AnalyseIndex, ai2: AnalyseIndex):
        """
        Compares two AnalyseIndex instances based on their rhythm (duration).
        Rests must match rests; chords/single notes are interchangeable but their durations must match. [44]
        """
        to_return = True
        if (ai1.event_type == 'r' and not ai2.event_type == 'r'): # If one is a rest and other is not [45]
            to_return = False
        elif ((ai1.event_type == 'n' or ai1.event_type == 'c') and ai2.event_type == 'r'): # If one is note/chord and other is rest [45]
            to_return = False
        elif ((ai1.rhythm_chord_index != ai2.rhythm_chord_index)): # Compare chord rhythm index [45]
            to_return = False
        elif ((ai1.rhythm_note_index != ai2.rhythm_note_index)): # Compare note rhythm index [45]
            to_return = False
        elif ((ai1.rhythm_rest_index != ai2.rhythm_rest_index)): # Compare rest rhythm index [45]
            to_return = False
        return to_return [45]

    def compare_indexes(self, ai1: AnalyseIndex, ai2: AnalyseIndex):
        """
        Compares two AnalyseIndex instances based on all their important attributes
        (rhythm and pitch for notes; rhythm and pitches for chords; rhythm for rests). [46]
        """
        to_return = True
        if not (ai1.event_type == ai2.event_type): # Event types must match [46]
            to_return = False
        elif (ai1.event_type == 'n'): # If both are notes [46]
            if (ai1.rhythm_note_index != ai2.rhythm_note_index): to_return = False # Compare note rhythm [46]
            if (ai1.pitch_number_index != ai2.pitch_number_index): to_return = False # Compare pitch number [46]
        elif (ai1.event_type == 'c'): # If both are chords [46]
            if (ai1.rhythm_chord_index != ai2.rhythm_chord_index): to_return = False # Compare chord rhythm [46]
            if (ai1.chord_pitches_index != ai2.chord_pitches_index): to_return = False # Compare chord pitches [46]
        elif (ai1.event_type == 'r'): # If both are rests [32]
            if (ai1.rhythm_rest_index != ai2.rhythm_rest_index): to_return = False # Compare rest rhythm [32]
        return to_return [32]

    def __init__(self):
        """
        Initialises an AnalysePart instance, setting up numerous dictionaries and lists
        to store analysis data for pitches, rhythms, intervals, chords, and measure repetition. [10, 32, 33, 47-54]
        """
        self.analyse_indexes_list = [] # List of unique AnalyseIndex events found in the part. [32]
        self.analyse_indexes_dictionary = {} # Dictionary: key = index in analyse_indexes_list, value = list of event indexes where this unique event occurs. [32]
        self.analyse_indexes_all = {} # Dictionary: key = event index (from Part), value = [index from analyse_indexes_list, occurrence index within analyse_indexes_dictionary's list]. [32]
        self.measure_indexes = {} # Dictionary: key = measure number, value = event index of its first event. [32]
        self.measure_analyse_indexes_list = [] # List of unique measures (AnalyseSection objects) based on full content. [33]
        self.measure_analyse_indexes_dictionary = {} # Dictionary: key = index in measure_analyse_indexes_list, value = list of measure numbers where this unique measure occurs. [33]
        self.measure_analyse_indexes_all = {} # Dictionary: key = measure number, value = [index from measure_analyse_indexes_list, occurrence index within measure_analyse_indexes_dictionary's list]. [33]
        self.repeated_measures_lists = [] # List of lists of measure indexes where measures match fully (pitch and rhythm). [33]
        self.measure_groups_list = [] # List of groups of repeated measures (e.g., [[1, 5], [9, 15]] meaning bars 1-4 are repeated at 9-12). [33]
        self.repeated_measures_not_in_groups_dictionary = {} # Dictionary of repeated measures not part of a larger group. [47]
        self.measure_rhythm_analyse_indexes_list = [] # List of unique measures based on rhythm only. [47]
        self.measure_rhythm_analyse_indexes_dictionary = {} # Dictionary for rhythm-only measures. [47]
        self.measure_rhythm_analyse_indexes_all = {} # Dictionary for all rhythm-only measures. [47]
        self.repeated_measures_lists_rhythm = [] # List of lists where rhythm matches (but not necessarily full match). [48]
        self.measure_rhythm_not_full_match_groups_list = [] # Groups of repeated measures based on rhythm only. [48]
        self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary = {} # Rhythm-only repeated measures not in groups. [48]
        self.measure_intervals_analyse_indexes_list = [] # List of unique measures based on intervals only. [48]
        self.measure_intervals_analyse_indexes_dictionary = {} # Dictionary for interval-only measures. [49]
        self.measure_intervals_analyse_indexes_all = {} # Dictionary for all interval-only measures. [49]
        self.repeated_measures_lists_intervals = [] # List of lists where intervals match (but not necessarily full match). [49]
        self.measure_intervals_not_full_match_groups_list = [] # Groups of repeated measures based on intervals only. [49]
        self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary = {} # Interval-only repeated measures not in groups. [49]

        # Dictionaries for counting individual musical elements [50-52]
        self.pitch_number_dictionary = {} # Key = MIDI pitch number, value = list of event indexes. Initialised for all 128 MIDI pitches. [50]
        for i in range(128): self.pitch_number_dictionary[i] = []
        self.pitch_name_dictionary = {} # Key = pitch name (e.g., 'C#'), value = list of event indexes. [50]
        self.interval_dictionary = {} # Key = interval in semitones (+x/-x/0), value = list of event indexes. [50]
        self.rhythm_note_dictionary = {} # Key = note duration (quarter lengths), value = list of event indexes. [50]
        self.rhythm_rest_dictionary = {} # Key = rest duration (quarter lengths), value = list of event indexes. [51]
        self.rhythm_chord_dictionary = {} # Key = chord duration (quarter lengths), value = list of event indexes. [51]
        self.count_accidentals_in_measures = {} # Key = measure number, value = count of accidentals. [51]
        self.count_gracenotes_in_measures = {} # Key = measure number, value = count of grace notes. [51]
        self.count_rests_in_measures = {} # Key = measure number, value = count of rests. [51]
        self.chord_pitches_list = [] # List of unique chords (based on sorted MIDI pitches). [51]
        self.chord_pitches_dictionary = {} # Key = index in chord_pitches_list, value = list of event indexes. [51]
        self.chord_intervals_list = [] # List of unique chords (based on intervals from lowest note). [52]
        self.chord_intervals_dictionary = {} # Key = index in chord_intervals_list, value = list of event indexes. [52]
        self.chord_common_name_dictionary = {} # Key = chord common name (e.g., 'C major'), value = list of event indexes. [52]

        # Lists for sorted counts of musical elements [10, 52, 53]
        self.count_pitches = [] # [[pitch number, count]] ordered by descending count. [52]
        self.count_pitch_names = [] # [[pitch name, count]] ordered by descending count. [52]
        self.count_intervals = [] # [[interval, count]] ordered by descending count. [53]
        self.count_intervals_abs =  * 25 # Count of absolute intervals (unison to 2 octaves). [53]
        self.count_chord_pitches = [] # [[chord pitches index, count]]. [53]
        self.count_chord_intervals = [] # [[chord intervals index, count]]. [53]
        self.count_chord_common_names = [] # [[chord common name, count]]. [53]
        self.count_notes_in_chords = {i: 0 for i in range(2, 11)} # Counts chords by number of notes (2-10). [10]
        self.count_rhythm_note = [] # [[note duration, count]]. [10]
        self.count_rhythm_rest = [] # [[rest duration, count]]. [10]
        self.count_rhythm_chord = [] # [[chord duration, count]]. [10]

        # Totals for calculating percentages [54]
        self.total_note_duration = 0 # Total duration of all individual notes. [54]
        self.note_count = 0 # Total count of individual notes. [54]
        self.interval_count = 0 # Total count of intervals. [54]
        self.interval_ascending_count = 0 # Count of ascending intervals. [54]
        self.interval_descending_count = 0 # Count of descending intervals. [54]
        self.interval_unison_count = 0 # Count of unison intervals. [54]
        self.total_rest_duration = 0 # Total duration of all rests. [54]
        self.rest_count = 0 # Total count of rests. [54]
        self.total_chord_duration = 0 # Total duration of all chords. [54]
        self.chord_count = 0 # Total count of chords. [54]
        self.accidental_count = 0 # Count of displayed accidentals (not in key signature). [54]
        self.gracenote_count = 0 # Count of grace notes. [54]
        self.possible_accidental_count = 0 # Total count of notes/pitches that could have an accidental. [54]
        self.part = None # The music21 Part object currently being analysed. [54]

    def does_section_contain_intervals(self, section: AnalyseSection):
        """
        Checks if any event in a given section contains interval information.
        Used to avoid false positives when comparing interval-only matches for sections without intervals. [55]
        """
        for ai in section.analyse_indexes:
            if (ai.interval_index != None): # If an interval index is found [55]
                return True
        return False [55]

    def find_section(self, section_to_find: AnalyseSection, sections_to_search, compare_type):
        """
        Searches for a `section_to_find` within a list of `sections_to_search`
        using the specified `compare_type`. [55, 56]
        """
        i = 0
        for s in sections_to_search:
            if self.compare_sections(s, section_to_find, compare_type): # Compares sections [56]
                return i # Returns index if found [56]
            i += 1
        return -1 # Returns -1 if not found [56]

    def find_analyse_index(self, ai):
        """
        Finds the index of a given AnalyseIndex `ai` within `self.analyse_indexes_list`
        (the list of unique events). [56]
        """
        ai_index = 0
        for a in self.analyse_indexes_list:
            if self.compare_indexes(ai, a): # Compares individual AnalyseIndex objects [56]
                return ai_index
            ai_index += 1
        return -1 [56]

    def find_chord(self, chord):
        """
        Finds the index of a given music21 chord object within `self.chord_pitches_list`
        (list of unique chords based on MIDI pitches). [56]
        """
        chord_index = 0
        find = sorted(p.midi for p in chord.pitches) # Get sorted MIDI pitches for comparison [56]
        for c in self.chord_pitches_list:
            if c == find:
                return chord_index
            chord_index += 1
        return -1 [57]

    def find_chord_intervals(self, chord_intervals):
        """
        Finds the index of a given list of chord intervals within `self.chord_intervals_list`
        (list of unique chords based on their internal intervals). [57]
        """
        chord_index = 0
        for c in self.chord_intervals_list:
            if c == chord_intervals:
                return chord_index
            chord_index += 1
        return -1 [57]

    def make_chord_intervals(self, chord):
        """
        Calculates and returns a sorted list of ascending intervals (in semitones)
        from the lowest note of a given music21 chord. Excludes unison (0). [57]
        Example: Major triad [3, 5] [57]
        """
        p1 = chord.pitches.midi # MIDI pitch of the lowest note [57]
        pitches = sorted(p.midi for p in chord.pitches[1:]) # Sorted MIDI pitches of other notes [57]
        intervals = [p-p1 for p in pitches] # Calculate intervals relative to the lowest note [58]
        return intervals [58]

    def when_is_measure_next_used(self, measure_index, from_all, from_indexes_dictionary):
        """
        Determines the measure number where a given measure `measure_index` is next repeated. [58]
        Args:
            measure_index (int): The current measure number. [58]
            from_all (dict): A dictionary like `self.measure_analyse_indexes_all`
                             ({measure_index: [unique_measure_list_index, occurrence_index]}). [58]
            from_indexes_dictionary (dict): A dictionary like `self.measure_analyse_indexes_dictionary`
                                            ({unique_measure_list_index: [list of measure indexes]}). [59]
        Returns:
            int: The measure number of the next occurrence, or -1 if not found.
        """
        # Get the list of all occurrences for the unique measure type [59]
        mia = from_indexes_dictionary[from_all[measure_index]]
        # Check if there's a next occurrence in that list [59]
        if len(mia)-1 > from_all[measure_index][1]:
            return mia[from_all[measure_index][1]+1] # Return the next measure number [59]
        else:
            return -1 # No next occurrence [59]

    def are_measures_in(self, group_list, measure_index1, measure_index2):
        """
        Checks if two given measure indexes (`measure_index1`, `measure_index2`)
        are both present in the *same* group within a `group_list` (e.g., `repeated_measures_lists`). [59, 60]
        """
        for group in group_list:
            if measure_index1 in group and measure_index2 in group: # If both measures are in the current group [60]
                return True
        return False [60]

    def is_measure_used_at(self, indexes_all, current_measure_index, check_measure_index):
        """
        Checks if two measures have the same content (pitch/rhythm/intervals, depending on `indexes_all`). [60]
        Args:
            indexes_all (dict): A dictionary like `self.measure_analyse_indexes_all`. [60]
            current_measure_index (int): The first measure to check. [60]
            check_measure_index (int): The second measure to check. [60]
        Returns:
            bool: True if they match, False otherwise.
        """
        # Handles cases where a measure might not have notes/rests and thus not be in the dictionary [60]
        if not check_measure_index in indexes_all: return False
        elif not current_measure_index in indexes_all: return False
        else:
            # Compares the 'unique measure list index' (first element of the value tuple) [61]
            if (indexes_all[current_measure_index] == indexes_all[check_measure_index]):
                return True
            else:
                return False [61]

    def find_measure_group(self, mg, mg_lists):
        """
        Finds the index of a specific measure group `mg` (e.g., [1, 5]) within a list of measure group lists. [61]
        """
        mg_index = 0
        for measure_groups in mg_lists:
            for group in measure_groups:
                if mg == group:
                    return mg_index
            mg_index += 1
        return -1 [61]

    def calculate_repeated_measures_lists(self, from_measure_dictionary, not_full_match):
        """
        Calculates lists of repeated individual measures from a given measure dictionary.
        Optionally filters for measures that are *not* a full match (e.g., just rhythm or intervals). [62]
        Args:
            from_measure_dictionary (dict): A dictionary like `measure_analyse_indexes_dictionary`
                                            ({unique_measure_list_index: [list of measure indexes]}). [62]
            not_full_match (bool): If True, only includes measures that are not full matches. [62]
        Returns:
            list: A list of lists, where each inner list contains measure numbers that are identical
                  (e.g., [[1, 4, 6], [2, 5]]). Does not return measures used only once. [62]
        """
        to_list = []
        for measure_indexes in from_measure_dictionary.values(): # Iterate unique measure types [62]
            if len(measure_indexes) > 1: # Only consider measures used more than once [62]
                measures = []
                for measure_index in measure_indexes:
                    # If not_full_match is False OR if the measure is not a full match (i.e., its full match list has only one occurrence) [62]
                    if (not_full_match == False or len(self.measure_analyse_indexes_dictionary[self.measure_analyse_indexes_all[measure_index]]) == 1):
                        measures.append(measure_index)
                if len(measures) > 1: # If after filtering, there are still repetitions [63]
                    to_list.append(measures)
        return to_list [63]

    def calculate_repeated_measures_not_in_groups(self, measures_list, groups_list):
        """
        Identifies individual repeated measures that are *not* already part of a larger
        repeated measure group. [63]
        Args:
            measures_list (list): A list of lists of repeated measures (e.g., from `calculate_repeated_measures_lists`). [63]
            groups_list (list): A list of measure groups (e.g., `measure_groups_list`). [63]
        Returns:
            dict: A dictionary where key is the first occurrence of a repeated measure,
                  and value is a list of its other occurrences that are not in groups. [63, 64]
        """
        output_dictionary = {}
        for measure_indexes in measures_list:
            if len(measure_indexes) > 1: # Only consider measures used more than once [63]
                measures = []
                for measure_index in measure_indexes:
                    if not self.in_measure_groups(measure_index, groups_list): # Check if measure is NOT in a group [63]
                        measures.append(measure_index)
                if len(measures) > 1: # If after filtering, there are still repetitions [64]
                    output_dictionary[measures] = measures[1:] # Store the first occurrence as key and others as value [64]
        return output_dictionary [64]

    def in_measure_groups(self, measure_index, groups_list):
        """
        Checks if a given `measure_index` falls within any of the defined measure groups. [64]
        """
        for mgl in groups_list: # Iterate through each list of measure groups [64]
            for mg in mgl: # Iterate through each specific measure group (e.g., [start, end]) [64]
                if measure_index >= mg and measure_index <= mg[1]: # If measure falls within the group's range [64]
                    return True
        return False [64]

    def are_measures_in_same_group(self, measure_index1, measure_index2, groups_list):
        """
        Checks if two measures (`measure_index1`, `measure_index2`) are part of the *same*
        repeated measure group. Prevents redundant reporting of nested repetitions. [64, 65]
        """
        for mgl in groups_list:
            for mg in mgl:
                if measure_index1 >= mg and measure_index1 <= mg[1] and \
                   measure_index2 >= mg and measure_index2 <= mg[1]: # Check if both fall within the same group [65]
                    return True
        return False [65]

    def calculate_measure_groups(self, from_indexes_all, from_indexes_dictionary):
        """
        Calculates groups of consecutive repeated measures. [65, 66]
        Example output: `[[[1, 5], [9, 15]], [[6, 7], [3, 8]]]` [65]
        TODO: Improve to handle multiple repetitions of the *same* first measure in different groups. [66]
        """
        to_list = [] # List to store the measure groups [66]
        next_used_at = 1 # Placeholder for when a measure is next used [66]
        group_size = 1 # Initial group size [66]
        gap = 1 # Gap between repetitions [66]
        skip = 0 # Counter to skip already processed measures within a found group [66]

        for look_at_measure in from_indexes_all: # Iterate through all measures [66]
            if (skip > 0): # If current measure is part of a previously found group, skip it [66]
                skip -= 1
                continue

            next_used_at = self.when_is_measure_next_used(look_at_measure, from_indexes_all, from_indexes_dictionary) # Find next use [67]

            if next_used_at > -1: # If the measure is repeated [67]
                gap = next_used_at - look_at_measure # Calculate the gap between repetitions [67]
                if gap > 1: # If there's a gap (not direct consecutive repeat) [67]
                    group_size = 1 # Reset group size [67]
                    # Expand group as long as consecutive measures also show the same repetition pattern [67]
                    while (group_size < gap and (look_at_measure + group_size + gap) in from_indexes_all) and \
                          (self.is_measure_used_at(from_indexes_all, look_at_measure + group_size, look_at_measure + group_size + gap)):
                        group_size += 1
                    group_size -= 1 # Correct group size (last increment was past the end) [67]

                if (group_size > 0): # If a group of bars is actually repeated (group size > 0) [67]
                    measure_group = [look_at_measure, look_at_measure + group_size] # Define the measure group (start, end) [68]
                    measure_group_index = self.find_measure_group(measure_group, to_list) # Check if this specific group already exists [68]

                    if (measure_group_index == -1): # If it's a new group (first and second occurrence) [68]
                        to_list.append([measure_group]) # Add the first occurrence [68]
                        to_list[len(to_list)-1].append([look_at_measure + gap, look_at_measure + gap + group_size]) # Add the second occurrence [68]
                    else: # If the group already exists (subsequent occurrences) [68]
                        to_list[measure_group_index].append([look_at_measure + gap, look_at_measure + gap + group_size]) # Add the new occurrence [68]

                    skip = group_size # Skip measures already processed within this large group [68]
                    # This skip mechanism is noted as "not great" because it might overlook smaller groups nested within larger ones. [68]
        return to_list [69]

    def describe_repetition_percentage(self, percent):
        """
        Converts a repetition percentage into a descriptive string (e.g., "all", "almost all", "over half"). [69]
        """
        if percent > 99: return "all"
        elif percent > 85: return "almost all"
        elif percent > 75: return "over three quarters"
        elif percent > 50: return "over half"
        elif percent > 33: return "over a thrid"
        else: return "" [69]

    def comma_and_list(self, l):
        """
        Formats a list of items into a human-readable string with commas and "and".
        Example: `[1, 5, 6]` becomes "1, 4 and 6". [69, 70]
        """
        output = ""
        for index, v in enumerate(l):
            if index == len(l)-1 and index > 0: # Add " and " before the last item if there are multiple [70]
                output += " and "
            elif index < len(l)-1 and index > 0: # Add ", " between items [70]
                output += ", "
            output += str(v) # Add the current item [70]
        return output [70]

    def describe_distribution(self, count_in_measures, total):
        """
        Describes the distribution of an element (e.g., rests, accidentals) across measures.
        It identifies measures with high percentages and describes distribution across score quarters. [70]
        Args:
            count_in_measures (dict): Dictionary with measure number as key and count of elements as value. [70]
            total (int): Total count of the element in the part. [70]
        Returns:
            str: A descriptive string about the element's distribution.
        """
        distribution = ""
        measure_percents = {} # Dictionary to store percentage of elements per measure [70]
        for k, c in count_in_measures.items():
            if c > 0: # Only consider measures with elements [70]
                measure_percents[k] = (c/total)*100 # Calculate percentage [70]
        sorted_percent = dict(sorted(measure_percents.items(), reverse=True, key=lambda item: item[1])) # Sort by percentage descending [70]

        ms = [] # List to store measure numbers with high percentages (>20%) [71]
        to_pop = [] # List to track measures to remove from sorted_percent [71]
        for m, p in sorted_percent.items():
            if p > 20: # If a measure has more than 20% of the elements [71]
                ms.append(m)
                to_pop.append(m)
        percent_remaining = 100 # Remaining percentage for distribution across quarters [71]
        for tp in to_pop:
            percent_remaining -= measure_percents[tp] # Subtract percentage of high-concentration measures [71]
            measure_percents.pop(tp) # Remove processed measures [71]

        if len(ms) > 0: # If individual measures with high concentration were found [71]
            distribution += " mostly in bar"
            if len(ms) > 1: distribution += "s"
            distribution += " " + self.comma_and_list(ms) # List them out [71]

        if len(measure_percents) > 0: # If elements remain to be distributed across quarters [72]
            if not distribution == "": distribution += " and " # Add "and" if previous description exists [72]
            dist = {0: 0, 1: 0, 2: 0, 3: 0} # Dictionary to store distribution by quarters [72]
            # Calculate percentage of remaining elements in each quarter of the score [72]
            for index, mp in measure_percents.items():
                if (index > len(count_in_measures)*0.75): dist[4] += (mp/percent_remaining)*100
                elif (index > len(count_in_measures)*0.5): dist[2] += (mp/percent_remaining)*100
                elif (index > len(count_in_measures)*0.25): dist[1] += (mp/percent_remaining)*100
                else: dist += (mp/percent_remaining)*100
            sorted_dist = sorted(dist.items(), reverse=True, key=lambda item: item[1]) # Sort quarters by percentage [73]

            positions = " "
            if sorted_dist[1] > 50: # If over half are in one quarter [73]
                positions += self._position_map[sorted_dist]
            elif sorted_dist[1] + sorted_dist[1][1] > 70: # If over 70% are in two quarters [73]
                positions += self._position_map[sorted_dist] + " and " + self._position_map[sorted_dist[1]]
            else: # Otherwise, just say how many bars throughout [73]
                positions += "in " + str(len(measure_percents)) + " bars throughout"
            distribution += positions # Append to distribution string [73]
        return distribution.strip() # Return cleaned string [73]

    def describe_percentage(self, percent):
        """
        Converts a percentage to a general descriptive term (e.g., "all", "most", "some"). [74]
        Used for general event percentages.
        """
        if percent > 99: return "all"
        elif percent > 90: return "almost all"
        elif percent > 75: return "most"
        elif percent > 45: return "lots of"
        elif percent > 30: return "some"
        elif percent > 10: return "a few"
        elif percent > 1: return "very few"
        else: return "" [74]

    def describe_percentage_uncommon(self, percent):
        """
        Converts a percentage to a descriptive term for uncommon events (e.g., accidentals). [74]
        Uses different thresholds than `describe_percentage`.
        """
        if percent > 5: return "many"
        elif percent > 2: return "a lot of"
        elif percent > 1: return "quite a few"
        elif percent > 0.5: return "a few"
        else: return "some" [75]

    def describe_count_list(self, count_list, total):
        """
        Describes the distribution of items in a count list (e.g., rhythm types, pitch names).
        It identifies the most common items by percentage. [75]
        """
        description = ""
        if total > 0:
            for index, count_item in enumerate(count_list):
                if count_item[1]/total > 0.98: description += "all " + str(count_item) + ", " # If nearly all are one type [75]
                elif count_item[1]/total > 0.90: description += "almost all " + str(count_item) + ", " # If almost all are one type [75]
                elif count_item[1]/total > 0.6: description += "mostly " + str(count_item) + ", " # If mostly one type [76]
                elif count_item[1]/total > 0.3: description += "some " + str(count_item) + ", " # If some are one type [76]
            description = self.replace_end_with(description, ", ", "") # Remove trailing comma [76]
        return description [76]

    def describe_count_list_several(self, count_list, total, item_name):
        """
        Provides a more general description for count lists when no single item
        dominates (e.g., if no single rhythm type is over 30%). [76, 77]
        Lists up to 4 most common items and counts others.
        """
        description = ""
        if total > 0:
            upto_percent = [] # List to store the items that make up the initial percentage [77]
            remaining_count = 0 # Count of other less common items [77]
            progress_percent = 0 # Accumulated percentage [77]
            for index, count_item in enumerate(count_list):
                if progress_percent < 40: # Aim for ~40% coverage for the "mostly" list [77]
                    upto_percent.append(count_item)
                    progress_percent += (count_item[1]/total)*100
                else:
                    if count_item[1] > 0: remaining_count += 1
            if len(upto_percent) <= 4: # If the main items are few, list them out [77]
                description = "mostly " + self.comma_and_list(upto_percent)
                if remaining_count > 1: # Add count of other items [77]
                    description += "; plus " + str(remaining_count) + " other " + item_name
            else: # If many main items, just state count of main items and most common [77]
                description = str(len(upto_percent)) + " " + item_name
                description += ", the most common is " + count_list # Should be count_list not enumerate(count_list) [77]
        return description [77]

    def describe_summary(self):
        """
        Generates a summary of the musical content for the current part,
        including proportions of notes, chords, rests, accidentals, and grace notes. [78]
        """
        summary = ""
        event_count = self.chord_count + self.note_count + self.rest_count # Total number of events [78]
        event_duration = self.total_chord_duration + self.total_note_duration + self.total_rest_duration # Total duration of events [78]

        percent_dictionary = {} # Dictionary to store weighted percentages of event types [78]
        # Weighting: 50% for count, 150% for duration (duration is more important) [78]
        percent_dictionary["chords"] = ((self.chord_count/event_count*50) + (self.total_chord_duration/event_duration*150)) / 2
        percent_dictionary["individual notes"] = ((self.note_count/event_count*50) + (self.total_note_duration/event_duration*150)) / 2
        percent_dictionary["rests"] = ((self.rest_count/event_count*50) + (self.total_rest_duration/event_duration*150)) / 2

        # Iterate through event types sorted by their weighted percentage [79]
        for k, v in sorted(percent_dictionary.items(), key=lambda item: item[1], reverse=True):
            if v > 1: # Only describe if percentage is significant [79]
                summary += self.describe_percentage(v) + " " + k # Add general percentage description [79]

                if k == "chords": # If describing chords [79]
                    describe_count = self.describe_count_list(self.count_chord_common_names, self.chord_count) # Describe common chord names [79]
                    if describe_count != "": describe_count += ", "
                    chord_count = self.describe_count_list(self.count_rhythm_chord, self.chord_count) # Describe chord rhythms [79]
                    if chord_count != "": describe_count += chord_count + ", "
                    count_notes_in_chords_list = sorted(self.count_notes_in_chords.items(), reverse=True, key=lambda item: item[1]) # Sort notes in chords count [80]
                    note_count = self.describe_count_list(count_notes_in_chords_list, self.chord_count) # Describe number of notes per chord [80]
                    if note_count != "": describe_count += note_count + " notes, "
                    if describe_count != "": describe_count = self.replace_end_with(describe_count, ", ", "") # Clean trailing comma [80]
                    summary += " (" + describe_count + ")" # Add chord details to summary [80]

                elif k == "individual notes": # If describing individual notes [80]
                    describe_count = ""
                    temp = self.describe_count_list(self.count_rhythm_note, self.note_count) # Describe note rhythms [80]
                    if temp != "": describe_count += temp + ", "
                    temp = self.describe_count_list(self.count_pitch_names, self.note_count) # Describe pitch names [81]
                    if temp != "": describe_count += temp + ", "
                    sorted_abs_intervals = dict(sorted(enumerate(self.count_intervals_abs), reverse=True, key=lambda item: item[1])) # Sort absolute intervals by count [81]
                    named_abs_intervals = {} # Map interval numbers to names [81]
                    for index, count in sorted_abs_intervals.items(): named_abs_intervals[self._interval_map[index]] = count
                    temp = self.describe_count_list(named_abs_intervals.items(), self.interval_count) # Describe intervals [81]
                    temp = self.replace_end_with(temp, ", ", "")
                    if temp == "": temp = self.describe_count_list_several(named_abs_intervals.items(), self.interval_count, "intervals") # Use alternative description if no single dominant interval [82]

                    # Describe overall interval direction [82]
                    if self.interval_ascending_count > self.interval_descending_count*2: temp += ", mostly ascending"
                    elif self.interval_descending_count > self.interval_ascending_count*2: temp += ", mostly descending"
                    if temp != "": describe_count += temp # Add interval details to notes description [82]
                    summary += " (" + describe_count + ")" # Add note details to summary [82]

                elif k == "rests": # If describing rests [82]
                    describe_count = self.describe_count_list(self.count_rhythm_rest, self.rest_count) # Describe rest rhythms [82]
                    dist = (self.describe_distribution(self.count_rests_in_measures, self.rest_count)) # Describe rest distribution [83]
                    if describe_count != "": summary += " (" + describe_count + " - " + dist + ")" # Add rest details and distribution [83]
                summary += ", "
                dist = ""

        # Describe accidentals [83]
        if self.accidental_count > 1:
            accidental_percent = (self.accidental_count/self.possible_accidental_count)*100
            summary += self.describe_percentage_uncommon(accidental_percent) + " accidentals" # Use uncommon percentage description [83]
            dist = (self.describe_distribution(self.count_accidentals_in_measures, self.accidental_count)) # Describe accidental distribution [83]
            if not dist == "": summary += " (" + dist + "), " # Add distribution if present [83]

        # Describe grace notes [84]
        if self.gracenote_count > 1:
            gracenote_percent = (self.gracenote_count/self.possible_accidental_count)*100
            summary += self.describe_percentage_uncommon(gracenote_percent) + " grace notes" # Use uncommon percentage description [84]
            dist = (self.describe_distribution(self.count_gracenotes_in_measures, self.gracenote_count)) # Describe grace note distribution [84]
            if not dist == "": summary += " (" + dist + ")." # Add distribution if present [84]

        summary = self.replace_end_with(summary, ", ", ". ").capitalize() # Clean trailing comma/space and capitalise first letter [84]
        return summary [84]

    def replace_end_with(self, original: str, remove: str, add: str):
        """
        Replaces a string at the end of `original` if it matches `remove` with `add`. [84, 85]
        """
        to_return = original
        if original.endswith(remove): # Check if the string ends with 'remove' [85]
            to_return = original[0:original.rfind(remove)] # Remove the ending substring [85]
            to_return += add # Add the new ending [85]
        return to_return [85]

    def describe_measure_repeated_many(self, measures_dictionary: dict, description: str):
        """
        Describes individual measures that are repeated frequently (over 33% of the score). [85]
        """
        repetition = ""
        for key, ms in measures_dictionary.items(): # Iterate through dictionary of repeated measures [85]
            percent_usage = len(ms) / len(self.measure_indexes)*100 # Calculate percentage of usage [85]
            if percent_usage > 33: # If usage is significant [85]
                repetition += "The " + description + " in bar " + str(key) + " is used "
                repetition += self.describe_percentage(percent_usage) # Describe percentage [85]
                repetition += " of the way through. "
        return repetition [86]

    def describe_measure_group_repeated_many(self, measure_group_list: list, description: str):
        """
        Describes groups of measures that are repeated frequently (over 33% of the score). [86]
        """
        repetition = ""
        for group in measure_group_list: # Iterate through list of measure groups [86]
            group_repetition_percent = ((group[1]-group+1)*len(group)/len(self.measure_indexes))*100 # Calculate total usage percentage of the group [86]
            if group_repetition_percent > 33: # If usage is significant [86]
                if (group[1]-group == 1): # For two-bar groups, use "x and y" [86]
                    repetition += "The " + description + " in bars " + str(group) + " and " + str(group[1])
                else: # For longer groups, use "x to y" [87]
                    repetition += "The " + description + " in bars " + str(group) + " to " + str(group[1])
                repetition += " are used "
                repetition += self.describe_repetition_percentage(group_repetition_percent) # Describe percentage [87]
                repetition += " of the way through. "
        return repetition [87]

    def describe_repetition_summary(self):
        """
        Generates a summary of the score's repetition, considering full matches,
        rhythm-only matches, and interval-only matches. [88]
        It prioritises reporting significant repetitions (over 33% usage).
        """
        repetition = ""
        repetition += self.describe_measure_group_repeated_many(self.measure_groups_list, "pitch and rhythm") # Full match groups [88]
        repetition += self.describe_measure_repeated_many(self.repeated_measures_not_in_groups_dictionary, "pitch and rhythm") # Full match individual bars [88]
        repetition += self.describe_measure_group_repeated_many(self.measure_rhythm_not_full_match_groups_list, "rhythm") # Rhythm-only groups [88]
        repetition += self.describe_measure_repeated_many(self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary, "rhythm") # Rhythm-only individual bars [89]
        repetition += self.describe_measure_group_repeated_many(self.measure_intervals_not_full_match_groups_list, "intervals") # Interval-only groups [89]
        repetition += self.describe_measure_repeated_many(self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary, "intervals") # Interval-only individual bars [90]

        # If no significant repetition (over 33%) was found above, check for rhythm/interval matches with simpler descriptions [90]
        if repetition == "":
            check_rhythm_match = self.calculate_repeated_measures_lists(self.measure_rhythm_analyse_indexes_dictionary, False)
            check_rhythm_match.sort(reverse=True, key=lambda item: len(item)) # Sort by length of repetition list [91]
            for check in check_rhythm_match:
                percent_usage = (len(check) / len(self.measure_indexes))*100
                if percent_usage > 33: # If still a significant usage [91]
                    repetition += "The rhythm in bar " + str(check) + " is used "
                    repetition += self.describe_percentage(percent_usage) + " of the way through. "
                else: break # Stop if no more significant rhythm repetitions [91]

            check_intervals_match = self.calculate_repeated_measures_lists(self.measure_intervals_analyse_indexes_dictionary, False)
            check_intervals_match.sort(reverse=True, key=lambda item: len(item)) # Sort by length [92]
            for check in check_intervals_match:
                percent_usage = (len(check) / len(self.measure_indexes))*100
                if percent_usage > 33: # If still a significant usage [92]
                    repetition += "The intervals in bar " + str(check) + " is used "
                    repetition += self.describe_percentage(percent_usage) + " of the way through. "
                else: break [92]

        # Analyse and describe lengths of repeated sections [92, 93]
        repetition_lengths = {} # Key = length of repeated section, Value = number of unique sections of that length (full match) [92]
        rhythm_interval_repetition_lengths = {} # Same but for rhythm or interval only matches [93]
        total_lengths = 0 # Total count of unique repeated sections [93]

        for group in self.measure_groups_list: # Populate repetition_lengths for full matches [93]
            length = group[1]-group+1
            self.insert_or_plus_equals(repetition_lengths, length, 1)

        for group in self.measure_rhythm_not_full_match_groups_list: # Populate rhythm_interval_repetition_lengths for rhythm matches [93, 94]
            length = group[1]-group+1
            self.insert_or_plus_equals(rhythm_interval_repetition_lengths, length, 1)

        for group in self.measure_intervals_not_full_match_groups_list: # Populate rhythm_interval_repetition_lengths for interval matches [94]
            length = group[1]-group+1
            self.insert_or_plus_equals(rhythm_interval_repetition_lengths, length, 1)

        repetition_lengths[1] = len(self.repeated_measures_not_in_groups_dictionary) # Add individual full-match repetitions [94]
        rhythm_interval_repetition_lengths[1] = len(self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary) # Add individual rhythm-only repetitions [95]
        rhythm_interval_repetition_lengths[1] += len(self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary) # Add individual interval-only repetitions [95]

        print("repetition lengths = " + str(repetition_lengths)) # Debugging [95]
        print("rhythm and interval repetition lengths = " + str(rhythm_interval_repetition_lengths)) # Debugging [95]

        for k, v in repetition_lengths.items(): total_lengths += v # Sum up total unique lengths [95]
        sorted_repetition_lengths = sorted(repetition_lengths.items(), reverse=False, key=lambda item: item) # Sort by length ascending [96]
        temp = self.describe_count_list(sorted_repetition_lengths, total_lengths) # Describe lengths of full matches [96]
        temp = self.replace_end_with(temp, ", ", "")
        if temp == "": temp = self.describe_count_list_several(sorted_repetition_lengths, total_lengths, "lengths") # Fallback description [96]
        if temp != "": repetition += "The repeated sections are " + temp + " measures long. " [96]

        total_lengths = 0
        for k, v in rhythm_interval_repetition_lengths.items(): total_lengths += v # Sum up total unique lengths for rhythm/interval [96]
        sorted_repetition_lengths = sorted(rhythm_interval_repetition_lengths.items(), reverse=False, key=lambda item: item) # Sort by length [97]
        temp = self.describe_count_list(sorted_repetition_lengths, total_lengths) # Describe lengths of rhythm/interval matches [97]
        temp = self.replace_end_with(temp, ", ", "")
        if temp == "": temp = self.describe_count_list_several(sorted_repetition_lengths, total_lengths, "lengths") # Fallback description [97]
        if temp != "": repetition += "The repeated sections of just rhythm / intervals are " + temp + " measures long. " [97]

        if (len(self.part.getElementsByClass('Measure')) > 1): # If there's more than one measure [97]
            repetition += "There are " + str(len(self.measure_analyse_indexes_list)) + " unique measures - " # Total unique measures [97]
            repetition += " of these, " + str(len(self.measure_rhythm_analyse_indexes_list)) + " measures have unique rhythm " # Unique rhythm measures [98]
            repetition += " and " + str(len(self.measure_intervals_analyse_indexes_list)) + " measures have unique intervals... " # Unique interval measures [98]
        if repetition != "": repetition = "\n"+repetition.capitalize() # Add newline and capitalise [98]
        return repetition [98]

    def insert_or_plus_equals(self, dict, key, value):
        """
        Helper function to either add a new key-value pair to a dictionary
        or add `value` to an existing key's value. Useful for counting occurrences. [98]
        """
        if key in dict:
            dict[key] += value
        else:
            dict[key] = value [98]

    def describe_section_usage_in_context(self, groups_list, repeat_what, repetition_in_context):
        """
        Populates the `repetition_in_context` dictionary with descriptions of
        how measure groups are used throughout the score (first used, lately used, etc.). [99]
        """
        for group in groups_list:
            group_repetition_percent = ((group[1]-group+1)*len(group)/len(self.measure_indexes))*100 # Calculate usage percentage [99]
            used_lots = False # TODO: This variable is not used after calculation [100]
            if group_repetition_percent > 50: used_lots = True

            and_or_through = " through " # Default descriptor for measure ranges [100]
            if (group[1]-group == 1): and_or_through = " and " # For two-bar groups, use "and" [100]

            temp = ""
            for index, usage in enumerate(group): # Iterate through each occurrence of the group [100]
                if index >= 1: # For second and subsequent occurrences [100]
                    temp = repeat_what + str(usage) + and_or_through + str(usage[1]) # Describe current occurrence [100]
                    temp += " were first used at " + str(group) # State where it was first used [100]
                    if index >= 2: temp += " and lately used at " + str(group[index-1]) # State most recent previous use [101]
                else: # For the first occurrence [101]
                    temp = "Bars " + str(usage) + and_or_through + str(usage[1])
                    temp += " are used " + (str(len(group)-1)) + " more times. " # State how many more times it's used [101]
                self.insert_or_plus_equals(repetition_in_context, usage, temp + ". ") # Add to repetition_in_context [101]

    def describe_measure_usage_in_context(self, repeated_measures_not_in_groups_dictionary, repeat_what, repetition_in_context):
        """
        Populates the `repetition_in_context` dictionary with descriptions of
        how individual measures (not in groups) are used throughout the score. [101, 102]
        """
        for key, ms in repeated_measures_not_in_groups_dictionary.items(): # Iterate through individual repeated measures [102]
            temp = repeat_what + str(key) + " is used " + str(len(ms)) + " more times. " # Describe first occurrence [102]
            self.insert_or_plus_equals(repetition_in_context, key, temp)

            for index, m in enumerate(ms): # For each subsequent occurrence of this measure [102]
                temp = repeat_what + str(m)
                temp += " was first used at " + str(key) # State where it was first used [102]
                if index >= 1: temp += " and lately used at " + str(ms[index-1]) # State most recent previous use [102]
                self.insert_or_plus_equals(repetition_in_context, m, temp + ". ") # Add to repetition_in_context [102]

    def describe_repetition_in_context(self):
        """
        The main method for generating contextual repetition descriptions for each measure.
        It aggregates descriptions from both measure groups and individual repeated measures
        for full, rhythm-only, and interval-only matches. [11]
        """
        print("describe repetition in context...") # Debugging [11]
        repetition_in_context = {} # Dictionary to store descriptions, keyed by measure number [11]
        # TODO: A bar could be a full match for one, and rhythm-only for another. The current logic might miss linking these relationships. [11]
        self.describe_section_usage_in_context(self.measure_groups_list, "Bars ", repetition_in_context) # Full match groups [103]
        self.describe_measure_usage_in_context(self.repeated_measures_not_in_groups_dictionary, "Bar ", repetition_in_context) # Full match individual bars [103]
        self.describe_section_usage_in_context(self.measure_rhythm_not_full_match_groups_list, "The rhythm in bars ", repetition_in_context) # Rhythm-only groups [103]
        self.describe_measure_usage_in_context(self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary, "The rhythm in bar ", repetition_in_context) # Rhythm-only individual bars [103]
        self.describe_section_usage_in_context(self.measure_intervals_not_full_match_groups_list, "The intervals in bars ", repetition_in_context) # Interval-only groups [104]
        self.describe_measure_usage_in_context(self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary, "The intervals in bar ", repetition_in_context) # Interval-only individual bars [104]
        return repetition_in_context [104]

    def describe_repetition(self):
        """
        Generates a long string describing all repetitions found (full, rhythm, intervals).
        This method is noted as "not very useful" due to its output format. [104, 105]
        """
        repetition = ""

        # Describe full matches (pitch and rhythm) [105]
        if len(self.measure_groups_list) > 0:
            for group in self.measure_groups_list:
                group_repetition_percent = ((group[1]-group+1)*len(group)/len(self.measure_indexes))*100
                if group_repetition_percent > 50: # If group is repeated a lot [105]
                    if (group[1]-group == 1): repetition += "Bars " + str(group) + " and " + str(group[1])
                    else: repetition += "Bars " + str(group) + " to " + str(group[1])
                    repetition += " are used " + self.describe_repetition_percentage(group_repetition_percent) + " of the way through. "
                else: # Just describe where the group is repeated [106]
                    if (group[1]-group == 1): repetition += "Bars " + str(group) + " and " + str(group[1])
                    else: repetition += "Bars " + str(group) + " to " + str(group[1])
                    repetition += " are used at "
                    for index, ms in enumerate(group[1:]): # List all subsequent occurrences [106, 107]
                        if index == len(group)-2 and index > 0: repetition += " and "
                        elif index < len(group)-1 and index > 0: repetition += ", "
                        repetition += str(ms)
                    repetition += ". "
        # Describe individual full-match bars not in groups [107]
        for key, ms in self.repeated_measures_not_in_groups_dictionary.items():
            repetition += "Bar " + str(key) + " is used at "
            for index, m in enumerate(ms): # List all occurrences [107, 108]
                if index == len(ms)-1 and index > 0: repetition += " and "
                elif index < len(ms)-1 and index > 0: repetition += ", "
                repetition += str(m)
            repetition += ". "
        if repetition == "": repetition += "There are no repeated bars... "

        # Describe rhythm-only matches [108]
        rhythm_repetition = ""
        if len(self.measure_rhythm_not_full_match_groups_list) > 0:
            for group in self.measure_rhythm_not_full_match_groups_list:
                if (group[1]-group == 1): rhythm_repetition += "The rhythm in bars " + str(group) + " and " + str(group[1])
                else: rhythm_repetition += "The rhythm in bars " + str(group) + " to " + str(group[1])
                rhythm_repetition += " are used at "
                for index, ms in enumerate(group[1:]): # List all occurrences [108, 109]
                    if index == len(group)-1 and index > 0: rhythm_repetition += " and "
                    elif index < len(group)-1 and index > 0: rhythm_repetition += ", "
                    rhythm_repetition += str(ms)
                rhythm_repetition += ". "
        # Describe individual rhythm-only bars not in groups [109]
        for key, ms in self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary.items():
            rhythm_repetition += "The rhythm in bar " + str(key) + " is used at "
            for index, m in enumerate(ms): # List all occurrences [109, 110]
                if index == len(ms)-1 and index > 0: rhythm_repetition += " and "
                elif index < len(ms)-1 and index > 0: rhythm_repetition += ", "
                rhythm_repetition += str(m)
            rhythm_repetition += ". "
        if rhythm_repetition == "": rhythm_repetition = "There are no bars with just the same rhythm... "
        repetition += rhythm_repetition

        # Describe interval-only matches [110]
        interval_repetition = ""
        if len(self.measure_intervals_not_full_match_groups_list) > 0:
            for group in self.measure_intervals_not_full_match_groups_list:
                if (group[1]-group == 1): interval_repetition += "The intervals in bars " + str(group) + " and " + str(group[1])
                else: interval_repetition += "The intervals in bars " + str(group) + " to " + str(group[1])
                interval_repetition += " are used at "
                for index, ms in enumerate(group[1:]): # List all occurrences [111]
                    if index == len(group)-1 and index > 0: interval_repetition += " and "
                    elif index < len(group)-1 and index > 0: interval_repetition += ", "
                    interval_repetition += str(ms)
                interval_repetition += ". "
        # Describe individual interval-only bars not in groups [111]
        for key, ms in self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary.items():
            interval_repetition += "The intervals in bar " + str(key) + " are used at "
            for index, m in enumerate(ms): # List all occurrences [112]
                if index == len(ms)-1 and index > 0: interval_repetition += " and "
                elif index < len(ms)-1 and index > 0: interval_repetition += ", "
                interval_repetition += str(m)
            interval_repetition += ". "
        if interval_repetition == "": interval_repetition = "There are no bars with just the same intervals... "
        repetition += interval_repetition
        return repetition [112]

    def set_part(self, p):
        """
        Performs the detailed analysis for a single music21 Part object.
        This method iterates through notes, chords, and rests, collects data on
        pitches, rhythms, intervals, chords, and identifies measures for repetition analysis. [40]
        Args:
            p (music21.stream.Part): The music21 Part object to analyse. [40]
        """
        self.part = p # Stores the Part object [40]
        event_index = 0 # Running index for all events (notes, chords, rests) in the part [40]
        previous_note_pitch = -1 # Stores the MIDI pitch of the previous note for interval calculation [40]
        current_measure = -1 # Tracks the current measure number [40]
        measure_analyse_indexes = AnalyseSection() # Stores AnalyseIndex objects for the current measure [40]
        measure_accidentals = 0 # Counter for accidentals in the current measure [40]
        measure_gracenotes = 0 # Counter for grace notes in the current measure [40]
        measure_rests = 0 # Counter for rests in the current measure [40]

        for n in self.part.flat.notesAndRests: # Iterate through all notes and rests in the part [40]
            if (n.measureNumber > current_measure): # If it's a new measure [40]
                # TODO: Handle measures with no notes or rests to prevent errors later. [113]
                self.measure_indexes[n.measureNumber] = event_index # Store the starting event index for the new measure [113]
                current_measure = n.measureNumber # Update current measure [113]

                if (len(measure_analyse_indexes.analyse_indexes) > 0): # If it's not the very first measure [113]
                    # Store counts for the *previous* measure [113]
                    self.count_accidentals_in_measures[current_measure-1] = measure_accidentals
                    measure_accidentals = 0 # Reset counter
                    self.count_gracenotes_in_measures[current_measure-1] = measure_gracenotes
                    measure_gracenotes = 0 # Reset counter
                    self.count_rests_in_measures[current_measure-1] = measure_rests
                    measure_rests = 0 # Reset counter

                    # Process the `measure_analyse_indexes` (full match) [114]
                    index = self.find_section(measure_analyse_indexes, self.measure_analyse_indexes_list, 0)
                    if index == -1: # If this measure content is unique [114]
                        self.measure_analyse_indexes_list.append(measure_analyse_indexes) # Add it to unique list [114]
                        index = len(self.measure_analyse_indexes_list)-1 # Get its new index [114]
                        self.measure_analyse_indexes_dictionary[index] = [current_measure-1] # Store its first occurrence [114]
                        self.measure_analyse_indexes_all[current_measure-1] = [index, 0] # Map measure to unique type and occurrence index [114]
                    else: # If this measure content has been seen before [114]
                        self.measure_analyse_indexes_dictionary[index].append(current_measure-1) # Add current measure to its occurrences list [114]
                        self.measure_analyse_indexes_all[current_measure-1] = [index, len(self.measure_analyse_indexes_dictionary[index])-1] # Update map [115]

                    # Process `measure_analyse_indexes` (rhythm match) [115]
                    index = self.find_section(measure_analyse_indexes, self.measure_rhythm_analyse_indexes_list, 1)
                    if index == -1:
                        self.measure_rhythm_analyse_indexes_list.append(measure_analyse_indexes)
                        index = len(self.measure_rhythm_analyse_indexes_list)-1
                        self.measure_rhythm_analyse_indexes_dictionary[index] = [current_measure-1]
                        self.measure_rhythm_analyse_indexes_all[current_measure-1] = [index, 0]
                    else:
                        self.measure_rhythm_analyse_indexes_dictionary[index].append(current_measure-1)
                        self.measure_rhythm_analyse_indexes_all[current_measure-1] = [index, len(self.measure_rhythm_analyse_indexes_dictionary[index])-1]

                    # Process `measure_analyse_indexes` (interval match) [116]
                    if (self.does_section_contain_intervals(measure_analyse_indexes)): # Only if the section contains intervals [116]
                        index = self.find_section(measure_analyse_indexes, self.measure_intervals_analyse_indexes_list, 2)
                        if index == -1:
                            self.measure_intervals_analyse_indexes_list.append(measure_analyse_indexes)
                            index = len(self.measure_intervals_analyse_indexes_list)-1
                            self.measure_intervals_analyse_indexes_dictionary[index] = [current_measure-1]
                            self.measure_intervals_analyse_indexes_all[current_measure-1] = [index, 0]
                        else:
                            self.measure_intervals_analyse_indexes_dictionary[index].append(current_measure-1)
                            self.measure_intervals_analyse_indexes_all[current_measure-1] = [index, len(self.measure_intervals_analyse_indexes_dictionary[index])-1]

                    measure_analyse_indexes = AnalyseSection() # Reset for the new measure [117]
                    previous_note_pitch = -1 # Reset for interval comparison in new measure [117]

            ai = AnalyseIndex(event_index) # Create AnalyseIndex for the current event (note/chord/rest) [117]

            if n.isRest: # If the element is a rest [117]
                ai.event_type = 'r'
                measure_rests += 1 # Increment rest count for current measure [117]
                d = n.duration.quarterLength # Get duration in quarter lengths [117]
                self.insert_or_plus_equals(self.rhythm_rest_dictionary, d, [event_index]) # Store rhythm and event index [118]
                ai.rhythm_rest_index = [d, len(self.rhythm_rest_dictionary.get(d))-1] # Store its index within unique rests [118]
                previous_note_pitch = -1 # Reset previous pitch as a rest breaks melodic continuity [118]
                self.total_rest_duration += d # Add to total rest duration [118]
                self.rest_count += 1 # Increment total rest count [118]

            elif n.isChord and type(n).__name__ != 'ChordSymbol': # If the element is a chord (and not just a chord symbol) [118]
                # TODO: Consider analysing ChordSymbol too, as it currently might be miscounted as grace notes. [118]
                ai.event_type = 'c'
                d = n.duration.quarterLength
                if d == 0.0: # If it's a grace chord (duration 0) [119]
                    measure_gracenotes += len(n.pitches) # Count each pitch as a grace note [119]
                    self.gracenote_count += len(n.pitches) # Add to total grace note count [119]
                if d > 0.0: # If it's a regular chord [119]
                    self.insert_or_plus_equals(self.rhythm_chord_dictionary, d, [event_index]) # Store rhythm [119]
                    ai.rhythm_chord_index = [d, len(self.rhythm_chord_dictionary.get(d))-1] # Store its index [119]
                if len(n.pitches) < 11: # Count notes per chord (assuming max 10 notes) [119]
                    self.count_notes_in_chords[len(n.pitches)] += 1

                index = self.find_chord(n) # Find unique chord based on pitches [120]
                if index == -1: # If unique [120]
                    self.chord_pitches_list.append(sorted(p.midi for p in n.pitches)) # Add to unique list [120]
                    index = len(self.chord_pitches_list)-1
                    self.chord_pitches_dictionary[index] = [event_index]
                else: # If not unique [120]
                    self.chord_pitches_dictionary[index].append(event_index)
                ai.chord_pitches_index = [index, len(self.chord_pitches_dictionary.get(index))-1] # Store index for this chord [120]

                chord_intervals = self.make_chord_intervals(n) # Calculate chord intervals [120]
                index = self.find_chord_intervals(chord_intervals) # Find unique chord based on intervals [120]
                if index == -1: # If unique [121]
                    self.chord_intervals_list.append(chord_intervals) # Add to unique list [121]
                    index = len(self.chord_intervals_list)-1
                    self.chord_intervals_dictionary[index] = [event_index]
                else: # If not unique [121]
                    self.chord_intervals_dictionary[index].append(event_index)
                ai.chord_interval_index = [index, len(self.chord_intervals_dictionary.get(index))-1] # Store index for this chord interval type [121]

                common_name = n.commonName # Get music21 common name [121]
                # Custom common name mapping for specific interval patterns [121]
                if chord_intervals == [3, 7]: common_name = "Suspended 4th"
                elif chord_intervals == [2, 3]: common_name = "Suspended 2nd"
                self.insert_or_plus_equals(self.chord_common_name_dictionary, common_name, [event_index]) # Store common name [122]
                ai.chord_name_index = [common_name, len(self.chord_common_name_dictionary.get(common_name))-1] # Store index for this chord name [122]

                # Count accidentals in the chord [122]
                for p in n.pitches:
                    if p.accidental is not None and p.accidental.displayStatus == True:
                        measure_accidentals += 1
                        self.accidental_count += 1
                self.possible_accidental_count += len(n.pitches) # Count total pitches that could have accidentals [122]
                self.total_chord_duration += d # Add to total chord duration [123]
                self.chord_count += 1 # Increment total chord count [123]

            elif n.isChord == False: # If the element is a single note (not a chord) [123]
                if isinstance(n, note.Unpitched): # If it's an unpitched note [123]
                    ai.event_type = 'u'
                else: # If it's a pitched note [123]
                    ai.event_type = 'n'
                if n.pitch.accidental is not None and n.pitch.accidental.displayStatus == True: # Count accidentals [123]
                    measure_accidentals += 1
                    self.accidental_count += 1
                self.possible_accidental_count += 1 # Increment total possible accidental count [123]

                self.pitch_number_dictionary[n.pitch.midi].append(event_index) # Store MIDI pitch number [123]
                ai.pitch_number_index = [n.pitch.midi, len(self.pitch_number_dictionary[n.pitch.midi])-1] # Store index for pitch number [123]
                self.insert_or_plus_equals(self.pitch_name_dictionary, n.pitch.name, [event_index]) # Store pitch name [124]
                ai.pitch_name_index = [n.pitch.name, len(self.pitch_name_dictionary.get(n.pitch.name))-1] # Store index for pitch name [124]

                # Calculate and store intervals from the previous note [124]
                if (previous_note_pitch > -1): # Only if there was a previous pitched note [124]
                    interval = n.pitch.midi-previous_note_pitch # Calculate interval in semitones [124]
                    self.insert_or_plus_equals(self.interval_dictionary, interval, [event_index]) # Store interval [124]
                    ai.interval_index = [interval, len(self.interval_dictionary.get(interval))-1] # Store index for interval [124]
                    if interval > 0: self.interval_ascending_count += 1
                    elif interval < 0: self.interval_descending_count += 1
                    else: self.interval_unison_count += 1
                    self.interval_count += 1 # Increment total interval count [125]
                    interval_abs = abs(interval) # Absolute interval for counting [125]
                    if interval_abs < 24: self.count_intervals_abs[interval_abs] += 1 # Store absolute interval count [125]

                d = n.duration.quarterLength # Get note duration [125]
                if d == 0.0: # If it's a grace note [125]
                    measure_gracenotes += 1
                    self.gracenote_count += 1
                    print("I'm a grace note note...")
                    print(n)
                if d > 0.0: # If it's a regular note [126]
                    self.insert_or_plus_equals(self.rhythm_note_dictionary, d, [event_index]) # Store rhythm [126]
                    ai.rhythm_note_index = [d, len(self.rhythm_note_dictionary.get(d))-1] # Store index for rhythm [126]
                if isinstance(n, note.Unpitched): # If unpitched, no melodic continuity [126]
                    previous_note_pitch = -1
                else: # Otherwise, update previous pitch for next interval calculation [126]
                    previous_note_pitch = n.pitch.midi
                self.total_note_duration += d # Add to total note duration [126]
                self.note_count += 1 # Increment total note count [126]

            # Process the `AnalyseIndex` (whether it's a unique event or a repetition of a unique event) [126]
            index = self.find_analyse_index(ai)
            if index == -1: # If this is a new unique event type [127]
                self.analyse_indexes_list.append(ai)
                index = len(self.analyse_indexes_list)-1
                self.analyse_indexes_dictionary[index] = [event_index]
                self.analyse_indexes_all[event_index] = [index, 0]
            else: # If this event type has been seen before [127]
                self.analyse_indexes_dictionary[index].append(event_index)
                self.analyse_indexes_all[event_index] = [index, len(self.analyse_indexes_dictionary[index])-1]

            measure_analyse_indexes.analyse_indexes.append(ai) # Add the current AnalyseIndex to the current measure's section [127]
            event_index = event_index + 1 # Increment global event index [127]

        # After iterating through all notes and rests, process the very last measure [127]
        if (len(measure_analyse_indexes.analyse_indexes) > 0):
            self.count_accidentals_in_measures[current_measure-1] = measure_accidentals
            self.count_gracenotes_in_measures[current_measure-1] = measure_gracenotes
            self.count_rests_in_measures[current_measure-1] = measure_rests

            # Similar processing as above for the last measure's full match [128]
            index = self.find_section(measure_analyse_indexes, self.measure_analyse_indexes_list, 0)
            if index == -1:
                self.measure_analyse_indexes_list.append(measure_analyse_indexes)
                index = len(self.measure_analyse_indexes_list)-1
                self.measure_analyse_indexes_dictionary[index] = [current_measure]
                self.measure_analyse_indexes_all[current_measure] = [index, 0]
            else:
                self.measure_analyse_indexes_dictionary[index].append(current_measure)
                self.measure_analyse_indexes_all[current_measure] = [index, len(self.measure_analyse_indexes_dictionary[index])-1]

            # Last measure's rhythm match [129]
            index = self.find_section(measure_analyse_indexes, self.measure_rhythm_analyse_indexes_list, 1)
            if index == -1:
                self.measure_rhythm_analyse_indexes_list.append(measure_analyse_indexes)
                index = len(self.measure_rhythm_analyse_indexes_list)-1
                self.measure_rhythm_analyse_indexes_dictionary[index] = [current_measure]
                self.measure_rhythm_analyse_indexes_all[current_measure] = [index, 0]
            else:
                self.measure_rhythm_analyse_indexes_dictionary[index].append(current_measure)
                self.measure_rhythm_analyse_indexes_all[current_measure] = [index, len(self.measure_rhythm_analyse_indexes_dictionary[index])-1]

            # Last measure's interval match [130]
            if (self.does_section_contain_intervals(measure_analyse_indexes)):
                index = self.find_section(measure_analyse_indexes, self.measure_intervals_analyse_indexes_list, 2)
                if index == -1:
                    self.measure_intervals_analyse_indexes_list.append(measure_analyse_indexes)
                    index = len(self.measure_intervals_analyse_indexes_list)-1
                    self.measure_intervals_analyse_indexes_dictionary[index] = [current_measure]
                    self.measure_intervals_analyse_indexes_all[current_measure] = [index, 0]
                else:
                    self.measure_intervals_analyse_indexes_dictionary[index].append(current_measure)
                    self.measure_intervals_analyse_indexes_all[current_measure] = [index, len(self.measure_intervals_analyse_indexes_dictionary[index])-1]

        print("\n Done set_part() - note count = " + str(self.note_count) + " chord count = " + str(self.chord_count) + " rest count = " + str(self.rest_count) + "...") [131]
        print("self.measure_analyse_indexes_all") # Debugging [132]
        print(self.measure_analyse_indexes_all) # Debugging [132]

        # Calculate repetition lists and groups based on collected data [132-134]
        self.repeated_measures_lists = self.calculate_repeated_measures_lists(self.measure_analyse_indexes_dictionary, False) # Full match [132]
        self.measure_groups_list = self.calculate_measure_groups(self.measure_analyse_indexes_all, self.measure_analyse_indexes_dictionary) # Full match groups [132]
        self.repeated_measures_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(self.measure_analyse_indexes_dictionary.values(), self.measure_groups_list) # Individual full match not in groups [132]

        self.repeated_measures_lists_rhythm = self.calculate_repeated_measures_lists(self.measure_rhythm_analyse_indexes_dictionary, True) # Rhythm-only match [133]
        self.measure_rhythm_not_full_match_groups_list = self.calculate_measure_groups(self.measure_rhythm_analyse_indexes_all, self.measure_rhythm_analyse_indexes_dictionary) # Rhythm-only groups [133]
        self.repeated_rhythm_measures_not_full_match_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(self.repeated_measures_lists_rhythm, self.measure_rhythm_not_full_match_groups_list) # Individual rhythm-only not in groups [133]

        self.repeated_measures_lists_intervals = self.calculate_repeated_measures_lists(self.measure_intervals_analyse_indexes_dictionary, True) # Interval-only match [134]
        # These two lines are identical in the source, likely a copy-paste error; only one is needed. [134]
        self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(self.repeated_measures_lists_intervals, self.measure_intervals_not_full_match_groups_list)
        self.repeated_intervals_measures_not_full_match_not_in_groups_dictionary = self.calculate_repeated_measures_not_in_groups(self.repeated_measures_lists_intervals, self.measure_intervals_not_full_match_groups_list)

        # Generate sorted count lists for various musical elements [135, 136]
        self.count_pitches = self.count_dictionary(self.pitch_number_dictionary)
        self.count_pitch_names = self.count_dictionary(self.pitch_name_dictionary)
        self.count_intervals = self.count_dictionary(self.interval_dictionary)
        self.count_chord_common_names = self.count_dictionary(self.chord_common_name_dictionary)
        self.count_rhythm_note = self.count_dictionary(self.rhythm_note_dictionary)
        self.count_rhythm_rest = self.count_dictionary(self.rhythm_rest_dictionary)
        self.count_rhythm_chord = self.count_dictionary(self.rhythm_chord_dictionary)

        # Rename numeric duration keys to descriptive words using _DURATION_MAP [136]
        self.rename_count_list_keys(self.count_rhythm_note, self._DURATION_MAP)
        self.rename_count_list_keys(self.count_rhythm_rest, self._DURATION_MAP)
        self.rename_count_list_keys(self.count_rhythm_chord, self._DURATION_MAP)

        self.count_chord_pitches = self.count_dictionary(self.chord_pitches_dictionary) # Count unique chord pitch patterns [136]
        self.count_chord_intervals = self.count_dictionary(self.chord_intervals_dictionary) # Count unique chord interval patterns [137]

    def rename_count_list_keys(self, count_list, key_names):
        """
        Swaps numeric keys (e.g., duration in quarter notes) in a count list
        with more descriptive string names (e.g., "semibreves") using a mapping dictionary. [137]
        """
        for item in count_list:
            if item in key_names: # If the item's key is in the provided map [137]
                item = key_names.get(item) # Replace the key with its descriptive name [137]

    def count_dictionary(self, d):
        """
        Converts a dictionary (where values are lists of occurrences) into a sorted list
        of [key, count] pairs, ordered by descending count. [137]
        Example: `{key: [list]}` becomes `[[C#, 5], [A,3]]`. [138]
        """
        sorted_list = []
        for k, v in d.items():
            sorted_list.append([k, len(v)]) # Create [key, count] pair [138]
        sorted_list.sort(reverse=True, key=lambda item: item[1]) # Sort by count in descending order [138]
        return sorted_list [138]