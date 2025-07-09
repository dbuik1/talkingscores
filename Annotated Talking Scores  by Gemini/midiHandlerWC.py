# __author__ = 'PMarchant' # Author of this file [2]

import os # Used for operating system interactions, such as file paths [2]
import json # Used for handling JSON data, though not directly used in the provided snippets for this file, it's often used for configuration or data serialization. [2]
import math # Used for mathematical operations, not explicitly seen in these excerpts for midi handling. [2]
import logging # Used for logging messages, such as debug information [2]
import logging.handlers # Related to logging setup [2]
import logging.config # Related to logging setup [2]

from tracemalloc import BaseFilter # This import appears in the source but is not used in the provided code snippets. [2]
from music21 import * # Imports all classes and functions from the music21 library, which is crucial for music notation manipulation [2]
from talkingscores.settings import BASE_DIR, MEDIA_ROOT, STATIC_ROOT, STATIC_URL # Imports Django settings for file paths [2]
from talkingscoreslib import Music21TalkingScore # Imports the Music21TalkingScore class, likely for score parsing and initial setup [2]

logger = logging.getLogger("TSScore") # Configures a logger for the "TSScore" application, enabling debug messages. [2]

class MidiHandler:
    """
    This class is responsible for handling the creation and management of MIDI files
    from MusicXML scores within the Talking Scores project. It can generate MIDI for
    different combinations of instruments, parts, bar ranges, and tempos,
    including an optional click track.
    """
    def __init__(self, get, folder, filename):
        """
        Initialises the MidiHandler with query parameters, folder, and filename.
        Args:
            get (dict): A dictionary-like object (e.g., request.GET in Django)
                        containing query parameters for MIDI generation options. [2]
            folder (str): The folder path where the MusicXML file resides. [2]
            filename (str): The base filename of the MusicXML score (without extension). [2]
        """
        self.queryString = get # Stores query parameters, such as selected instruments, start/end bars, tempo, and click track options [2]
        self.folder = folder # Stores the folder name for the music file [2]
        self.filename = filename.replace(".mid", "") # Ensures the filename does not have a .mid extension, as it will be added later [2]
        # self.score will be populated later by converter.parse() [3]

    def get_selected_instruments(self):
        """
        Parses the 'bsi' (binary selected instruments) query string parameter
        to determine which instruments and their corresponding parts are selected
        for MIDI generation. It also distinguishes between selected and unselected parts. [4, 5]
        """
        bsi = int(self.queryString.get("bsi")) # 'bsi' is a binary string representation of selected instruments [4]
        self.selected_instruments = [] # A list to store boolean indicating if an instrument (by its index) is selected [4]

        # Loops through the binary string 'bsi' to populate self.selected_instruments [4]
        while (bsi > 1): # The loop continues as long as bsi has bits to check (rightmost bit is for the first instrument) [4, 6]
            logger.debug(f"bsi = {bsi}") # Debugging: shows current bsi value [4, 6]
            if (bsi & 1 == True): # Checks if the last bit is 1 (meaning the current instrument is selected) [4, 6]
                self.selected_instruments.append(True) # Adds True if selected [4, 6]
            else:
                self.selected_instruments.append(False) # Adds False if not selected [4, 6]
            bsi = bsi >> 1 # Shifts bits to the right to check the next instrument [4, 6]
        self.selected_instruments.reverse() # Reverses the list to match the order of instruments (leftmost bit was for the first instrument) [4]
        logger.debug(f"selected_instruments = {self.selected_instruments}") # Debugging: shows the final list of selected instruments [4]

        self.all_selected_parts = [] # List to store indices of all selected *parts* (0-based) [4]
        self.all_unselected_parts = [] # List to store indices of all unselected *parts* (0-based) [5]
        self.selected_instruement_parts = {} # Dictionary: key = instrument index, value = list of part indices belonging to that instrument [5]

        instrument_index = -1 # Initialise instrument counter [5]
        prev_instrument = "" # Tracks the previous instrument ID to group parts under one instrument [5]

        # Iterates through all parts in the score to determine selection status [5]
        for part_index, part in enumerate(self.score.flat.getInstruments()):
            logger.debug(f"part_index = {part_index}") # Debugging: current part index [5]
            logger.debug(part) # Debugging: current part object [5]
            if part.partId != prev_instrument: # If it's a new instrument (based on partId) [5]
                instrument_index += 1 # Increment instrument index [5]
                self.selected_instruement_parts.get(instrument_index) # Not actually used for value, just gets it. [5]

            # Checks if the current instrument (based on its index in selected_instruments) is selected [5]
            if (self.selected_instruments[instrument_index] == True):
                self.all_selected_parts.append(part_index) # Add current part to all selected parts list [5]
                if (instrument_index in self.selected_instruement_parts.keys()): # If instrument already exists in dictionary [7]
                    self.selected_instruement_parts[instrument_index].append(part_index) # Add current part to its list [7]
                else: # If it's a new instrument entry [7]
                    self.selected_instruement_parts[instrument_index] = [part_index] # Create new list for its parts [7]
            else: # If the current instrument is NOT selected [7]
                self.all_unselected_parts.append(part_index) # Add current part to all unselected parts list [7]
                self.selected_instruement_parts[instrument_index] = [] # Ensure selected_instruement_parts has an empty list for unselected instruments [7]

            prev_instrument = part.partId # Update previous instrument ID for next iteration [7]

        logger.debug(f"all_selected_parts = {self.all_selected_parts}") # Debugging: final list of selected parts [7]
        logger.debug(f"all_unselected_parts = {self.all_unselected_parts}") # Debugging: final list of unselected parts [7]
        logger.debug(f"selected_instruement_parts = {self.selected_instruement_parts}") # Debugging: final instrument-to-parts mapping [7]

        # Process 'bpi' (binary play options) query string parameter [6]
        # This determines whether to play all parts together, only selected, or only unselected. [6]
        bpi = int(self.queryString.get("bpi")) # 'bpi' is a binary representation for play options [6]
        self.play_together_unselected = bpi & 1 # Checks the last bit for 'play unselected together' option [6]
        bpi = bpi >> 1 # Shifts bits for the next option [6]
        self.play_together_selected = bpi & 1 # Checks for 'play selected together' option [6]
        bpi = bpi >> 1 # Shifts bits [6]
        self.play_together_all = bpi & 1 # Checks for 'play all together' option [6]
        bpi = bpi >> 1 # Shifts bits (the `while (bsi > 1)` loop below seems like a copy-paste error from line 3, as 'bpi' is already fully processed) [6]

    def make_midi_files(self):
        """
        The main method to generate various MIDI files based on the parsed options.
        It handles the parsing of the MusicXML, determines bar ranges, and orchestrates
        the creation of different MIDI output types (all, selected, unselected, individual). [3]
        TODO: Optimisation needed for large MusicXML files [6]
        """
        # Constructs the full path to the MusicXML file [3]
        # TODO: The security of this path construction might need review [3]
        xml_file_path = os.path.join(*(MEDIA_ROOT, self.folder, self.filename))

        # Parses the MusicXML file into a music21 Score object [3]
        # TODO: Should also handle '.xml' extension, not just '.musicxml' [3]
        self.score = converter.parse(xml_file_path+".musicxml")

        self.get_selected_instruments() # Populates instrument and part selection based on query string [3]

        # s = stream.Score(id='temp') # This line is present in the source but unused here. [3]

        # Determines the start and end bar for MIDI generation [3, 8]
        if self.queryString.get("start") is None and self.queryString.get("end") is None:
            # If no specific range is given, use the full score [3]
            # TODO: Test for pickup bar scenario [3]
            start = self.score.parts.getElementsByClass('Measure').number # First measure number [3]
            end = self.score.parts.getElementsByClass('Measure')[-1].number # Last measure number [3]
        else:
            # Uses the specified start and end bars from the query string [8]
            start = int(self.queryString.get("start"))
            end = int(self.queryString.get("end"))

        # Calculates the offset of the starting measure, important for tempo alignment [8]
        offset = self.score.parts.measure(start).offset

        # Creates a score segment for processing, potentially for performance improvement [8]
        # In rough tests, this approach can save 1-2 seconds for large files. [8]
        # A deep copy might be a better approach. [8]
        self.scoreSegment = stream.Score(id='tempSegment')

        # Populates the scoreSegment with measures from each part within the specified range [8]
        for p in self.score.parts:
            # Fix for pickup bar scenario (bar 0) [8, 9]
            if start == 0 and end == 0:
                end = 1 # Temporarily sets end to 1 to include bar 0 [9]
            # Gets measures for the part within the range and removes repeat marks [9]
            for m in p.measures(start, end).getElementsByClass('Measure'):
                # TODO: Test with repeats [9]
                m.removeByClass('Repeat') # Removes repeat marks to avoid expansion issues [9]
                self.scoreSegment.insert(p.measures(start, end, )) # Inserts the measures into the segment [9]
            # Resets end if it was modified for pickup bar [9]
            if start == 0 and end == 1:
                end = 0

        # Iterates through click track options ('n' for none, 'be' for beat) [9]
        for click in ['n', 'be']:
            self.tempo_shift = 0 # Initialises tempo shift for pickup bars [9]
            # Iterates through different tempo options (50, 100, 150 BPM) [9]
            for tempo in [10-12]:
                # Generates MIDI for all parts together if option is enabled [9]
                if self.play_together_all:
                    self.make_midi_together(start, end, offset, tempo, click, "all") # Calls helper function [9]
                # Generates MIDI for all selected parts together [13]
                if self.play_together_selected:
                    self.make_midi_together(start, end, offset, tempo, click, "sel") # Calls helper function [13]
                # Generates MIDI for all unselected parts together [13]
                if self.play_together_unselected:
                    self.make_midi_together(start, end, offset, tempo, click, "un") # Calls helper function [13]

                # Generates MIDI for each individual selected instrument (which might have multiple parts) [13]
                for index, parts_list in enumerate(self.selected_instruement_parts.values()):
                    if (len(parts_list) > 0): # Only if the instrument has selected parts [13]
                        s = stream.Score(id='temp') # Creates a new temporary score stream [13]
                        for pi in parts_list: # For each part belonging to the current instrument [13]
                            # Inserts measures from the score segment into the temporary stream, collecting relevant musical elements [13]
                            s.insert(self.scoreSegment.parts[pi].measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')))
                        self.insert_tempos(s, offset, tempo/100) # Inserts tempo marks into the stream [14]
                        self.insert_click_track(s, click) # Inserts click track if enabled [14]
                        # Writes the MIDI file with specific naming convention [14]
                        s.write('midi', self.make_midi_path_from_options(start=start, end=end, ins=index+1, tempo=tempo, click=click))

                        # If the instrument has more than one part, also generate MIDI for each separate part [14]
                        if (len(parts_list) > 1):
                            for pi in parts_list: # For each individual part [14]
                                s = stream.Score(id='temp') # New temporary score stream [14]
                                # Inserts measures for just this single part [14]
                                s.insert(self.scoreSegment.parts[pi].measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')))
                                self.insert_tempos(s, offset, tempo/100) # Inserts tempos [15]
                                self.insert_click_track(s, click) # Inserts click track [15]
                                # Writes the MIDI file for the individual part [15]
                                s.write('midi', self.make_midi_path_from_options(start=start, end=end, part=pi, tempo=tempo, click=click))

    def make_midi_together(self, start, end, offset, tempo, click, which_parts):
        """
        Helper method to generate a single MIDI file for parts played together
        (all parts, only selected parts, or only unselected parts). [15]
        """
        parts_in = [] # List to hold indices of parts to include [15]
        if (which_parts == "sel"): # If generating for selected parts [15]
            parts_in = self.all_selected_parts # Use the pre-populated list of selected parts [15]
        elif (which_parts == "un"): # If generating for unselected parts [15]
            parts_in = self.all_unselected_parts # Use the pre-populated list of unselected parts [15]

        s = stream.Score(id='temp') # Create a temporary score stream [15]
        for part_index, p in enumerate(self.scoreSegment.parts): # Iterate through parts in the segment [15]
            if which_parts == "all" or part_index in parts_in: # If 'all' or the part is in the specified list [16]
                # Insert measures for the current part, collecting relevant musical elements [16]
                s.insert(p.measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')))
        self.insert_tempos(s, offset, tempo/100) # Inserts tempos [16]
        self.insert_click_track(s, click) # Inserts click track [16]
        # Writes the MIDI file with appropriate naming [16]
        s.write('midi', self.make_midi_path_from_options(start=start, end=end, sel=which_parts, tempo=tempo, click=click))

    def insert_click_track(self, s, click):
        """
        Inserts a click track (metronome) into the provided score stream.
        This ensures the click track starts on beat 1, even with pickup bars. [16]
        """
        if click == 'n': # If click track is 'none', do nothing [16]
            return

        clicktrack = stream.Stream() # Create a new stream for the click track [17]
        # TODO: Consider using specific instrument sounds like instrument.HiHatCymbal() after music21 updates [17]
        ins = instrument.Percussion() # Use a generic percussion instrument [17]
        ins.midiChannel = 9 # Set MIDI channel 9, common for percussion [17]
        clicktrack.insert(0, ins) # Insert the instrument into the click track stream [17]

        ts: meter.TimeSignature = None # Variable to hold the current time signature [17]
        shift_measure_offset = 0 # Offset for measures due to pickup bars [17]

        # Iterates through each measure in the first part of the score stream [17]
        for m in s.getElementsByClass(stream.Part).getElementsByClass(stream.Measure):
            # Updates time signature if one is found in the current measure [17]
            if len(m.getElementsByClass(meter.TimeSignature)) > 0:
                ts = m.getElementsByClass(meter.TimeSignature)
            else:
                # If no time signature in current measure, try to get the previous one [17]
                if (ts == None):
                    ts: meter.TimeSignature = m.previous('TimeSignature')
            # If still no time signature (e.g., in a score without one), default to 1/4 [18]
            if (ts == None):
                ts = meter.TimeSignature('1/4')

            clickmeasure = stream.Measure() # Create a measure for the click notes [18]
            clickmeasure.mergeAttributes(m) # Copies attributes from the current measure [18]
            clickmeasure.duration = ts.barDuration # Sets duration of the click measure to the bar duration [18]

            clickNote = note.Note('D2') # First click note (strong beat) [18]
            clickNote.duration = ts.getBeatDuration(0) # Duration of the first beat [18]
            clickmeasure.append(clickNote) # Add the note to the click measure [18]
            beatpos = ts.getBeatDuration(0).quarterLength # Tracks the current beat position [18]

            # Handles pickup bars: if the current measure is shorter than a full bar and contains content [19]
            # TODO: This logic might need refinement for edge cases. [19]
            if (m.duration.quarterLength < ts.barDuration.quarterLength and len(m.getElementsByClass(['Note', 'Rest'])) > 0):
                rest_duration = ts.barDuration.quarterLength - m.duration.quarterLength # Calculate needed rest duration [19]
                r = note.Rest() # Create a rest object [19]
                r.duration.quarterLength = rest_duration # Set rest duration [19]
                logger.debug(f"pickup bar - rest_duration = {rest_duration}") # Debugging: pickup bar rest duration [19]

                # Add rests to the beginning of the first measure in all parts of the original score segment [19, 20]
                for p in self.scoreSegment.parts:
                    r = note.Rest()
                    r.duration.quarterLength = rest_duration
                    p.getElementsByClass(stream.Measure).insertAndShift(0, r) # Inserts rest and shifts subsequent elements [20]
                    # Shift offsets for all subsequent measures in the part [20]
                    for ms in p.getElementsByClass(stream.Measure)[1:]:
                        ms.offset += rest_duration
                    logger.debug(f"now added rest to parts - duration = {rest_duration} and measure 0 duration = {p.getElementsByClass(stream.Measure).duration.quarterLength}") # Debugging [20]

                # Also shift offsets for measures in the *current* stream `s` [20]
                for p in s.parts:
                    for ms in p.getElementsByClass(stream.Measure)[1:]:
                        ms.offset += rest_duration
                shift_measure_offset = rest_duration # Store the total offset from pickup bar [21]

            # Update tempo offsets in the stream to account for pickup bar rests [21]
            for t in s.getElementsByClass(tempo.MetronomeMark):
                if (t.offset > 0): # Only shift if tempo is not at the very beginning [21]
                    t.offset += shift_measure_offset
            self.tempo_shift = rest_duration # Store the tempo shift (used for future tempo insertions) [21]

            # Add click notes for subsequent beats within the measure [21]
            for b in range(0, ts.beatCount-1): # For each beat after the first [21]
                clickNote = note.Note('F#2') # Regular click note (weaker beat) [21]
                clickNote.duration = ts.getBeatDuration(beatpos) # Duration based on time signature [21]
                beatpos += clickNote.duration.quarterLength # Advance beat position [21]
                clickmeasure.append(clickNote) # Add note to click measure [21]

            clicktrack.append(clickmeasure) # Add the filled click measure to the click track stream [22]
        s.insert(clicktrack) # Insert the complete click track into the main score stream [22]

    def insert_tempos(self, stream, offset_start, scale):
        """
        Inserts metronome marks (tempos) into a given stream.
        This function iterates through the score's metronome mark boundaries to find
        relevant tempos for the current stream segment and inserts them. [22]
        """
        # Iterates through metronome mark boundaries from the main score [22]
        for mmb in self.score.metronomeMarkBoundaries():
            # If the tempo starts after the stream ends, ignore it [22]
            if (mmb >= offset_start+stream.duration.quarterLength):
                return
            # If the tempo ends during the segment [22]
            if (mmb[1] > offset_start):
                tempoNumber = Music21TalkingScore.fix_tempo_number(tempo=mmb[2]).number # Gets fixed tempo number [22]
                if (mmb) <= offset_start: # If tempo starts before or at the beginning of the segment [23]
                    # Insert it at the start of the stream (0.001 to avoid conflict with existing offset 0 tempos) [23]
                    stream.insert(0.001, tempo.MetronomeMark(number=tempoNumber*scale, referent=mmb[2].referent))
                else: # If tempo starts during the segment [23]
                    # Insert it relative to the segment's start, adjusted for tempo shift from pickup bars [23]
                    stream.insert(mmb-offset_start + self.tempo_shift, tempo.MetronomeMark(number=tempoNumber*scale, referent=mmb[2].referent))

    def make_midi_path_from_options(self, sel=None, part=None, ins=None, start=None, end=None, click=None, tempo=None):
        """
        Constructs a unique MIDI filename based on the selected options (e.g., selected/unselected parts,
        specific part/instrument, bar range, click track, tempo). [23]
        """
        self.midiname = self.filename # Start with the base filename [23]
        if (sel != None): # Add selection (all, sel, un) to filename [24]
            self.midiname += "sel-"+str(sel)
        if (part != None): # Add part index to filename [24]
            self.midiname += "p"+str(part)
        if (ins != None): # Add instrument index to filename [24]
            self.midiname += "i"+str(ins)
        if (start != None): # Add start bar to filename [24]
            self.midiname += "s"+str(start)
        if (end != None): # Add end bar to filename [24]
            self.midiname += "e"+str(end)
        if (click != None): # Add click track option to filename [24]
            self.midiname += "c"+str(click)
        if (tempo != None): # Add tempo to filename [24]
            self.midiname += "t"+str(tempo)
        self.midiname += ".mid" # Add the .mid extension [24]
        logger.debug(f"midifilename = {self.midiname}") # Debugging: show the generated MIDI filename [24]
        # Constructs the full path to the MIDI file within the static data directory [24]
        return os.path.join(BASE_DIR, STATIC_ROOT, "data", self.folder, self.midiname)

    def get_or_make_midi_file(self):
        """
        Checks if a MIDI file with the current options already exists.
        If not, it calls `make_midi_files` to generate it. [25]
        """
        self.midiname = self.filename # Start with the base filename [25]
        # Append various options to construct the specific MIDI filename, similar to make_midi_path_from_options [25, 26]
        if (self.queryString.get("sel") != None):
            self.midiname += "sel-"+self.queryString.get("sel")
        if (self.queryString.get("part") != None):
            self.midiname += "p"+self.queryString.get("part")
        if (self.queryString.get("ins") != None):
            self.midiname += "i"+self.queryString.get("ins")
        if (self.queryString.get("start") != None):
            self.midiname += "s"+self.queryString.get("start")
        if (self.queryString.get("end") != None):
            self.midiname += "e"+self.queryString.get("end")
        if (self.queryString.get("c") != None): # 'c' for click track [26]
            self.midiname += "c"+self.queryString.get("c")
        if (self.queryString.get("t") != None): # 't' for tempo [26]
            self.midiname += "t"+self.queryString.get("t")
        self.midiname += ".mid" # Add .mid extension [26]

        toReturn = self.midiname # Store the generated filename to return [26]
        midi_filepath = os.path.join(BASE_DIR, STATIC_ROOT, "data", self.folder, "%s" % (self.midiname)) # Full path to MIDI file [26]

        if not os.path.exists(midi_filepath): # Check if the MIDI file already exists [26]
            logger.debug(f"midi file not found - {self.midiname} - making it...") # Log if not found [26]
            self.make_midi_files() # Generate the MIDI files if it doesn't exist [26]
        return toReturn # Return the MIDI filename [26]