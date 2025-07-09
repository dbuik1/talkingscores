from datetime import datetime # Used for timing, e.g., `start_time = datetime.now()` [139]
import time # Used for measuring elapsed time, e.g., `time.time()` [139]
from jinja2 import Template # Used for rendering HTML templates [139]
from abc import ABCMeta, abstractmethod # Used for defining Abstract Base Classes (ABCs) [139]
from collections import OrderedDict # Used for ordered dictionaries, though not explicitly used in these snippets. [139]
from jinja2.loaders import FileSystemLoader # Used to load Jinja2 templates from the file system [139]

# __author__ = 'BTimms' # Author of this file [139]

import os # Used for operating system interactions, such as file paths [139]
import json # Used for handling JSON data, particularly for loading settings [139, 140]
import math # Used for mathematical operations [139]
import pprint # Used for pretty-printing data structures, useful for debugging [139]
import logging # Used for logging messages [139]
import logging.handlers # Related to logging setup [139]
import logging.config # Related to logging setup [139]

from music21 import * # Imports all classes and functions from the music21 library, central to music notation handling [139]
from lib.musicAnalyser import * # Imports everything from the musicAnalyser module for music analysis features [139]

us = environment.UserSettings() # music21 user settings [139]
us['warnings'] = 0 # Disables music21 warnings [139]

logger = logging.getLogger("TSScore") # Configures a logger for the "TSScore" application [139]

global settings # Declares 'settings' as a global variable, which will hold application-wide configuration [12, 140-145]

class TSEvent(object, metaclass=ABCMeta):
    """
    Abstract Base Class for all musical events (notes, rests, chords, dynamics)
    that will be rendered by Talking Scores. [141]
    Defines common attributes and an abstract `render` method.
    """
    duration = None # The duration of the event (e.g., 'quarter', 'half') [141]
    tuplets = "" # String to describe tuplet start (e.g., "triplets") [141]
    endTuplets = "" # String to describe tuplet end [141]
    beat = None # The beat number where the event starts [141]
    bar = None # The bar number where the event starts [141]
    part = None # The part (instrument) to which the event belongs [141]
    tie = None # Describes if the note is tied (e.g., 'start', 'stop', 'continue') [141]

    def render_colourful_output(self, text, pitchLetter, elementType):
        """
        Renders text with HTML span tags for colour coding, based on global settings.
        Colours can be applied to pitch, rhythm, or octave descriptions. [141, 146]
        """
        # Dictionary mapping pitch letters to specific colours (for 'figureNotes' style) [141]
        figureNoteColours = {"C": "red", "D": "brown", "E": "grey", "F": " if colours should be applied based on element type and settings [146]
            if (elementType == "pitch" and settings["colourPitch"] == True): doColours = True
            if (elementType == "rhythm" and settings["colourRhythm"] == True): doColours = True
            if (elementType == "octave" and settings["colourOctave"] == True): doColours = True

            if doColours == True:
                if settings["colourPosition"] == "background": # Apply colour as background [146]
                    toRender = f"<span style=\"background-color:{figureNoteColours.get(pitchLetter, 'black')}; color:{figureNoteContrastTextColours.get(pitchLetter, 'white')};\">{text}</span>"
                elif settings["colourPosition"] == "text": # Apply colour to text [146]
                    toRender = f"<span style=\"color:{figureNoteColours.get(pitchLetter, 'black')};\">{text}</span>"
        return toRender [146]

    @abstractmethod
    def render(self, context=None, noteLetter=None):
        """
        Abstract method to be implemented by subclasses for rendering the event into HTML-friendly text. [147]
        Args:
            context (TSEvent): The previous event, used for contextual rendering (e.g., not repeating octave if same). [147]
            noteLetter (str): The letter name of the note (e.g., 'C', 'D') for colour mapping. [147]
        """
        rendered_elements = []
        # Render duration only if it's different from the context's duration, or if tuplets are present, or if rhythm is always announced [147]
        if (context is None or context.duration != self.duration or self.tuplets != "" or settings['rhythmAnnouncement'] == "everyNote"):
            rendered_elements.append(self.tuplets) # Add tuplet description [147]
            if (noteLetter != None): # Apply colour to rhythm description if noteLetter is provided [147]
                rendered_elements.append(self.render_colourful_output(self.duration, noteLetter, "rhythm"))
            else: # Otherwise, just add duration [147]
                rendered_elements.append(self.duration)
            rendered_elements.append(self.endTuplets) # Add end tuplet description [147]
        if self.tie: # If there's a tie, add its type [147]
            rendered_elements.append(f"tie {self.tie}")
        return rendered_elements [147]

class TSDynamic(TSEvent):
    """Represents a dynamic marking (e.g., 'p', 'f', 'crescendo')."""
    short_name = None # Short name (e.g., 'p', 'f') [148]
    long_name = None # Long name (e.g., 'piano', 'forte') [148]

    def __init__(self, long_name=None, short_name=None):
        """Initialises TSDynamic, preferring long_name if available."""
        if (long_name != None): self.long_name = long_name.capitalize() # Capitalise long name [148]
        else: self.long_name = short_name # Fallback to short name [148]
        self.short_name = short_name [148]

    def render(self, context=None):
        """Renders the dynamic marking as its long name."""
        return [self.long_name] [148]

class TSPitch(TSEvent):
    """Represents a pitch with its name, octave, and MIDI number."""
    pitch_name = None # Full pitch name (e.g., 'C#4') [12]
    octave = None # Octave number [12]
    pitch_letter = None # Base letter (e.g., 'C', 'D') used for colour lookups [12]

    def __init__(self, pitch_name, octave, pitch_number, pitch_letter):
        self.pitch_name = pitch_name # 'C#4' [12]
        self.octave = octave # 4 [12]
        self.pitch_number = pitch_number # MIDI pitch number (e.g., 61 for C#4) [12]
        self.pitch_pitch_letter, "pitch")) # Render pitch name with colour [12]
        if settings['octavePosition'] == "after": # Render octave after pitch name [12]
            rendered_elements.append(self.render_octave(context))
        return rendered_elements [12]

    def render_octave(self, context=None):
        """
        Determines whether to announce the octave based on user settings
        ('brailleRules', 'everyNote', 'firstNote', 'onChange') and renders it. [149]
        """
        show_octave = False
        if settings['octaveAnnouncement'] == "brailleRules": # Follows Braille rules for octave announcement [149]
            if context == None: # Always show octave for the first note [149]
                show_octave = True
            else:
                pitch_difference = abs(context.pitch_number - self.pitch_number) # Difference from previous pitch [149]
                if pitch_difference <= 4: # If interval is 3rd or less, don't say octave [149]
                    show_octave = False
                elif pitch_difference >= 5 and pitch_difference <= 7: # If 4th or 5th, say octave only if it changes [149]
                    if context.octave != self.octave:
                        show_octave = True
                else: # If more than a 5th, always say octave [150]
                    show_octave = True
        elif settings['octaveAnnouncement'] == "everyNote": # Announce octave for every note [150]
            show_octave = True
        elif settings['octaveAnnouncement'] == "firstNote" and context == None: # Announce octave only for the very first note [150]
            show_octave = True
        elif settings['octaveAnnouncement'] == "onChange": # Announce octave only when it changes from the previous note [150]
            if context == None or (context != None and context.octave != self.octave):
                show_octave = True
        if show_octave: # If octave should be shown, render it with colour [150]
            return self.render_ '.join(super(TSUnpitched, self).render(context))) # Render duration using parent's method [151]
        rendered_elements.append(' unpitched') # Add 'unpitched' description [151]
        return rendered_elements [151]

class TSRest(TSEvent):
    """Represents a musical rest."""
    pitch = None # Rests don't have a pitch [151]

    def render(self, context=None):
        """Renders the duration and then 'rest'."""
        rendered_elements = []
        rendered_elements.append(' '.join(super(TSRest, self).render(context))) # Render duration using parent's method [151]
        rendered_elements.append(' rest') # Add 'rest' description [151]
        return rendered_elements [151]

class TSNote(TSEvent):
    """Represents a single musical note."""
    pitch = None # The TSPitch object for this note [152]
    expressions = [] # List of expressions (e.g., staccato, accent) [152]

    def render(self, context=None):
        """
        Renders expressions, then duration, then pitch for the note. [152]
        """
        rendered_elements = []
        for exp in self.expressions: # Render each expression [152]
            rendered_elements.append(exp.name + ', ')
        rendered_elements.append(' '.join(super(TSNote, self).render(context, self.pitch.pitch_letter))) # Render duration, passing pitch letter for colour [152]
        rendered_elements.append(' '.join(self starting with the number of notes, then duration,
        then each pitch within the chord in ascending order. [153]
        """
        rendered_elements = [f'{len(self.pitches)}-note chord'] # e.g., "3-note chord" [153]
        rendered_elements.append(' '.join(super(TSChord, self).render(context))) # Render chord duration [153]
        previous_pitch = None
        for pitch in sorted(self.pitches, key=lambda TSPitch: TSPitch.pitch_number): # Iterate through pitches in ascending order [153]
            rendered_elements.append(' '.join(pitch.render(previous_pitch))) # Render each pitch, passing previous pitch as context [153]
            previous_pitch = pitch # Update previous pitch for next iteration [153]
        return [', '.join(rendered_elements)] # Join all elements with commas [153]

class TalkingScoreBase(object, metaclass=ABCMeta):
    """Abstract Base Class defining the basic interface for any Talking Score implementation."""
    @abstractmethod
    def get_title(self):
        """Abstract method to get the title of the score."""
        pass
    @abstractmethod
    def get_composer(self):
        """Abstract method to get the composer of the score."""
        pass

class Music21TalkingScore(TalkingScoreBase):
    """
    Implements the TalkingScoreBase using the music21 library.
    It provides methods to parse MusicXML, extract musical information,
    and generate descriptions and MIDI files. [154]
    """
    # Mappings for descriptive output based on user settings [154, 155]
    _OCTAVE_MAP = {1: 'bottom', 2: 'lower', 3: 'low', 4: 'mid', 5: 'high', 6: 'higher', 7: 'top'} # Octave names [154]
    _OCTAVE_FIGURENOTES_MAP = {1: 'bottom', 2: 'cross', 3: 'square', 4: 'circle', 5: 'triangle', 6: 'higher', 7: 'top'} # Figurenotes style octave names [154]
    _DOTS_MAP = {0    _PITCH_FIGURENOTES_MAP = {'C': 'red', 'D': 'brown', 'E': 'grey', 'F': 'blue', 'G': 'black', 'A': 'yellow', 'B': 'green',} # Figurenotes colours for pitches [155]
    _PITCH_PHONETIC_MAP = {'C': 'charlie', 'D': 'bravo', 'E': 'echo', 'F': 'foxtrot', 'G': 'golf', 'A': 'alpha', 'B': 'bravo',} # Phonetic alphabet for pitches [155]

    last_tempo_inserted_index = 0 # Optimisation for `insert_tempos()` to avoid re-checking all tempo boundaries [155]
    music_analyser = None # Instance of MusicAnalyser for the score [155]

    def __init__(self, musicxml_filepath):
        """
        Initialises Music21TalkingScore by parsing the MusicXML file. [155]
        """
        self.filepath = os.path.realpath(musicxml_filepath) # Stores the absolute path to the MusicXML file [155]
        self.score = converter.parse(musicxml_filepath) # Parses the MusicXML file into a music21 Score object [155]
        super(Music21TalkingScore, self).__init__() # Calls the constructor of the base class [156]

    def get_title(self):
        """
        Retrieves the title of the musical score.
        First tries `score.metadata.title`, then looks for a large, centered text box. [156]
        """
        if self.score.metadata.title is not None: return self.score.metadata.title # Get title from metadata [156]
        for tb in self.score.flat.getElementsByClass('TextBox'): # Iterate through text boxes [156]
            # Heuristic: large, centered text box at the top is likely the title [156]
            if hasattr(tb, 'justifty') and tb.justify == 'center' and hasattr(tb, 'alignVertical') and tb.alignVertical == 'top' and hasattr(tb, 'size') and tb.size > 18:
                return tb.content
right': return tb.content # Heuristic: right-justified text box is likely the composer [157]
        return "Unknown" [157]

    def get_initial_time_signature(self):
        """
        Retrieves and describes the initial time signature of the score (from the first part, first measure). [157]
        """
        m1 = self.score.parts.measures(1, 1) # Get the first measure of the first part [157]
        initial_time_signature = None
        # Check if the very first measure contains a time signature [158]
        if (len(self.score.parts.getElementsByClass('Measure').getElementsByClass(meter.TimeSignature)) > 0):
            initial_time_signature = self.score.parts.getElementsByClass('Measure').getElementsByClass(meter.TimeSignature)
        return self.describe_time_signature(initial_time_signature) [158]

    def describe_time_signature(self, ts):
        """
        Converts a music21 Time        """
        m1 = self.score.parts.measures(1, 1) # Get the first measure of the first part [158]
        if len(m1.flat.getElementsByClass('KeySignature')) == 0: ks = key.KeySignature(0) # Default to C major if none found [159]
        else: ks = m1.flat.getElementsByClass('KeySignature') # Get the first key signature [159]
        return self.describe_key_signature(ks) [159]

    def describe_key_signature(self, ks):
        """
        Converts a music21 KeySignature object into a human-readable string (e.g., "3 sharps", "2 flats"). [159]
        """
        strKeySig = "No sharps or flats"
        if (ks.sharps > 0): strKeySig = str(ks.sharps) + " sharps"
        elif (ks.sharps < 0): strKeySig = str(abs(ks.sharps)) + " flats"
        return strKeySig [159]

    def get_initial_text_expression(self):
        """
        Retrieves the content of the first text expression in the score (e.g., tempo indications). [159]
        Note: The `get_initial_tempo` method uses `MetronomeMarkBoundary` which is generally better. [142]
        """
        m1 = self.score.parts.measures(1, 1) # Get the first measure of the first part [159]
        text_expressions = m1.flat.getElementsByClass('TextExpression') # Get text expressions [142]
        for te in text_expressions: return te.content [142]

    def get_initial_tempo(self):
        """
        Retrieves and describes the initial tempo of the score. [142]
        It first attempts to load global settings (if not already loaded) and then describes
        the first metronome mark boundary.
        """
        global settings
        try: settings # Checks if 'settings' global variable is defined [142]
        except NameError: settings = None # If not, set to None [142]
        if settings == None: # If settings not loaded, set some defaults [142]
            settings = {}; settings['dotPosition'] = "before"; settings['rhythmDescription'] = "british"
        # Describes the tempo from the first metronome mark boundary [142]
        return self.describe_tempo(self.score.metronomeMarkBoundaries()[2])

    @staticmethod
    def fix_tempo_number(tempo):
        """
        Static method to ensure a music21 MetronomeMark object has a valid `number` attribute.
        tempo(self, tempo):
        """
        Converts a music21 MetronomeMark object into a human-readable string,
        including text, BPM, and the referent (e.g., "crotchet"). [160]
        """
        tempo_text = ""
        tempo = self.fix_tempo_number(tempo) # Ensure tempo number is valid [160]
        if (tempo.text != None): # If there's textual description (e.g., "Allegro") [160]
            tempo_text += tempo.text + " (" + str(math.floor(tempo.number)) + " bpm @ " + self.describe_tempo_referent(tempo) + ")"
        else: # Otherwise, just BPM and referent [160]
            tempo_text += str(math.floor(tempo.number)) + " bpm @ " + self.describe_tempo_referent(tempo)
        return tempo_text [161]

    def describe_tempo_referent(self, tempo):
        """
        Describes the rhythmic unit of a tempo (e.g., "crotchet", "dotted [161]
            tempo_text += " " + self._DOTS_MAP.get(tempo.referent.dots)
        return tempo_text [161]

    def get_number_of_bars(self):
        """
        Returns the total number of measures in the first part of the score. [161]
        """
        return len(self.score.parts.getElementsByClass('Measure')) [161]

    def get_instruments(self):
        """
        Identifies and organises instruments and their parts within the score.
        It populates `self.part_instruments` and `self.part_names`. [162, 163]
        `part_instruments`: {1: ['Flute', 0, 1, 'P1'], 2: ['Piano', 1, 2, 'P2']} (instrument index: [name, 1st part index, num parts, music21 partId]) [162, 163]
        `part_names`: {1: 'Right hand', 2: 'Left hand'} (part index: part name if multiple parts for one instrument) [162, 163]
        """
        self.part_instruments = {} # Stores information about each instrument [163]
        self.part_names = {} # Stores names for individual parts (e.g., "Right hand" for piano) [163]
        instrument_names = [] # List of unique instrument names [163]
        ins_count = 1 # 1-based counter for instruments [163]

        for c, instrument in enumerate(self.score.flat.getInstruments()): # Iterate through all instrumentscount] = [pname, c, 1, instrument.partId] # Store instrument info [164]
                instrument_names.append(pname) # Add to unique instrument names [164]
                ins_count += 1
            else: # If it's another part of the *same* instrument [164]
                self.part_instruments[ins_count-1][2] += 1 # Increment part count for that instrument [164]

        # Assign default "Right hand" / "Left hand" or "Part X" names for multi-part instruments [164]
        # TODO: There's a more efficient way to do this, or allow user input for part names. [164]
        for c, instrument in enumerate(self.score.flat.getInstruments()): # Re-iterate to assign names based on final part counts
            for ins_key, ins_info in self.part_instruments.items():
                if ins_info[1] <= c < ins_info[1] + ins_info[2]: # If current part `c` belongs to this instrument `ins_key`
_info[1]+2] = "Part 3"
                    else: # For other multi-part instruments
                        self.part_names[c] = f"Part {c - ins_info[1] + 1}"
                    break

        logger.debug(f"part instruments = {self.part_instruments}") # Debugging [143]
        print("part names = " + str(self.part_names)) # Print for debugging [143]
        print("instrument names = " + str(instrument_names)) # Print for debugging [143]
        return instrument_names [143]

    def compare_parts_with_selected_instruments(self):
        """
        Compares the detected parts with user-selected instruments (from global settings)
        to determine which parts are selected/unselected for MIDI playback.
        It also calculates binary representations for selected instruments and play options. [143, 165]
        """
        global settings
        self.selected_instruments = [] # 1-based list of selected instrument keys (from part_instruments) [165]
        self.unselected_instruments = [] # List of unselected instrument keys [165]
        self.binary_selected_instruments = 1 # Bitwise representation of selected instruments (0=not included, 1=included) [165]
        self.selected_part_names = [] # List of names for selected parts (e.g., "recorder", "piano - left hand") [165]

        for ins in self.part_instruments.keys(): # Iterate through all identified instruments [165]
            self.binary_selected_instruments = self.binary_selected_instruments << 1 # Shift bit `selected_part_names` [166]
            ins_name = self.part_instruments[ins] # Get instrument name [166]
            if self.part_instruments[ins][2] == 1: # If instrument has only one part [166]
                self.selected_part_names.append(ins_name)
            else: # If instrument has multiple parts [166]
                pn1index = self.part_instruments[ins][1] # Get first part's 0-based index [166]
                for pni in range(pn1index, pn1index+self.part_instruments[ins][2]): # Iterate through its parts [166]
                    self.selected_part_names.append(ins_name + " - " + self.part_names[pni]) # Append with part name (e.g., "piano - Left hand") [166]
        print("selected_part_names = " + str(self.selected_part_names)) # Print for debugging [166]

        # Adjust global playback settings based on instrument selection [1 False # If only one instrument selected, it can be played individually [167]
        if len(self.part_instruments) == 1: settings['playAll'] = False # If only one instrument total, "playAll" is redundant [167]
        # TODO: These adjustments should perhaps not be part of the score object directly. [167]

        # Calculate binary representation for 'play all/selected/unselected' options [167, 168]
        self.binary_play_all = 1 # Placeholder bit [167]
        self.binary_play_all = self.binary_play_all << 1
        if settings['playAll'] == True: self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if settings['playSelected'] == True: self.binary_play_all += 1
        self.binary_play_all = self.binary_play_all << 1
        if settings['playUnselected'] == True: self.binary_play_all += 1
        print("selected for all parts. [168]
        Returns a dictionary mapping part IDs to lists of their measures.
        """
        measures = self.score.measures(range_start, range_end) # Get measures from the score [168]
        bars_for_parts = {}
        for part in measures.parts: # Iterate through parts in the retrieved measures [169]
            bars_for_parts.setdefault(part.id, []).extend(part.getElementsByClass('Measure')) # Add measures to part's list [169]
        return bars_for_parts [169]

    def get_events_for_bar_range(self, start_bar, end_bar, part_index):
        """
        Extracts and organises musical events (notes, rests, chords, dynamics, spanners)
        from a specific part within a given bar range. [169]
        """
        events_by_bar = {} # Dictionary to store events, structured by bar -> beat -> voice -> order -> list of events [169]

        measures = self.score.parts[part_index].measures(start_bar, end
        logger.info(f'Processing part - {part_index} - bars {start_bar} to {end_bar}') # Log processing progress [170]

        # Special handling for pickup bar (bar 0) [170]
        if start_bar == 0 and end_bar == 1: end_bar = 0

        for bar_index in range(start_bar, end_bar + 1): # Iterate through bars in the range [170]
            measure = measures.measure(bar_index) # Get the current measure [170]
            if measure is not None: self.update_events_for_measure(measure, events_by_bar) # Update events if measure exists [170]

        # Process spanners (e.g., crescendos, diminuendos) [171]
        # TODO: Consider mentioning slurs, possibly as an option. [171]
        # TODO: Spanners are processed per-part, so a crescendo in one hand of a piano won't affect the other. [171]
        # TODO: This is somewhat inefficient as it re-iterates spanners from the start for each segment. [171]
        for spanner in self.score.parts[part_index].spanners.elements: # Iterate through spanners in the part [171]
            first = spanner.getFirst() # Get the first element of the spanner [171]
            last = spanner.getLast() # Get the last element of the spanner [171]
            if first.measureNumber is None or last.measureNumber is None: continue # Skip if measure numbers are missing [171]
            elif first.measureNumber > endlong_name=f'{spanner_type} start')
                    # Add event to events_by_bar structure [172]
                    events_by_bar.setdefault(first.measureNumber, {}).setdefault(first.beat, {}).setdefault(voice, {}).setdefault(description_order, []).append(event)
                if last.measureNumber >= start_bar and last.measureNumber <= end_bar: # If spanner ends within the segment [173]
                    event = TSDynamic(long_name=f'{spanner_type} end')
                    # TODO: Current logic will not handle crescendos/diminuendos that span multiple measures correctly for 'end' event placement. [173]
                    events_by_bar.setdefault(last.measureNumber, {}).setdefault(last.beat + last.duration.quarterLength - 1, {}).setdefault(voice, {}).setdefault(description_order, []).append(event)
        return events_by_bar [173]

    def update_events_for_measure(self, measure, events, voice: int = 1):
        """
        Helper method to extract()
                # Create TSPitch object from music21 pitch [174]
                event.pitch = TSPitch(self.map_pitch(element.pitch), self.map_octave(element.pitch.octave), element.pitch.ps, element.pitch.name)
                description_order = 1 # Order of description for notes [174]
                if element.tie: event.tie = element.tie.type # Add tie information [174]
                event.expressions = element.expressions # Add expressions [174]
            _pitch(element_pitch), self.map_octave(element_pitch.octave), element_pitch.ps, element_pitch.name) for element_pitch in element.pitches]
                description_order = 1
                if element.tie: event.tie = element.tie.type
            elif element_type == 'Dynamic': # If dynamic marking [175]
                event = TSDynamic(long_name=element.longName, short_name=element.value)
                description_order = 0 # Dynamics are spoken first [175]
            elif element_type == 'Voice': # If nested voices are found [175]
                self.update_events_for_measure(element, events, int(element.id)) # Recursively call for the voice stream [175]
                continue # Skip further processing for this element (handled by recursive call) [176]

            if event is None: continue # Skip if no valid event type was found [176]

            # Process duration and tuplets [176]
            event.duration = "" # Initialise duration string
            if (len(element.duration.tuplets) > 0): # If tuplets are present [176]
                if (element.duration.tuplets.type == "start"):
                    if (element.duration.tuplets.fullName == "Triplet"): event.tuplets = "triplets "
                    else: event.tuplets = f"{element.duration.tuplets.fullName} ({element.duration.tuplets.tupletActual} in {element.duration.tuplets.tupletNormal}) "
                elif (element.duration.duration += " " + self.map_dots(element.duration.dots)

            # Determine the beat for event placement (handles decimal beats for off-beat starts) [177]
            if (math.floor(element.beat) == math.floor(previous_beat)): # Same beat number (e.g., 1 to 1.5) [177]
                beat = previous_beat
            elif (math.floor(element.beat) == element.beat): # Start of a new integer beat (e.g., 1.5 to 2.0) [177]
                beat = math.floor(element.beat)
            else: # Partway through a new beat (e.g., 1 to 2.5) [178]
                beat = element.beat
            previous_beat = beat # Update previous beat [178]

            # Add the event to the nested dictionary structure [178]
            events.setdefault(measure.measureNumber, {}).setdefault(beat, {}).setdefault(voice, {}).setdefault(description_order, []).append(event)

    def group_chord_pitches_by_oct(str(pitch.octave), '?'), []).append(pitch.name)
        return chord_pitches_by_octave [178]

    # --- MIDI Generation Helper Methods (some overlap with midiHandler.py) ---
    # The presence of these methods here suggests that `talkingscoreslib.py` might
    # have originally handled MIDI generation or that there's some redundancy/refactoring.

    def generate_midi_filename_sel(self, prefix, range_start=None, range_end=None, output_path="", sel=""):
        """
        Generates a MIDI filename for 'all', 'selected', or 'unselected' parts playback. [179]
        """
        base_filename = os.path.splitext(os.path.basename(self.filepath)) # Get base filename without extension [179]
        if (range_start != None): # If a bar range is specified [179]
            midi_filename = os.path.join(output_path, f"{base_filename}.mid?sel={sel}&start={range_start}&end={range_end}&tpart_descriptions = []
        for pi in range(self.part_instruments[instrument][1], self.part_instruments[instrument][1]+self.part_instruments[instrument][2]): # Iterate through parts of the instrument [180]
            part_descriptions.append(self.get_events_for_bar_range(start_bar, end_bar, pi)) # Get events for each part [180]
        return part_descriptions [180]

    def generate_midi_filenames(self, prefix, range_start=None, range_end=1]+self.part_instruments[ins][2]): # For each part of the instrument [181]
                    if self.part_instruments[ins][2] > 1: # If instrument has multiple parts, name by part [181]
                        base_filename = os.path.splitext(os.path.basename(self.filepath))
                        midi_filename = os.path.join(output_path, f"{base_filename}.mid?part={pi}&t=100&c=n")
                        part_midis.append(midi_filename)
                    # Else branch not explicitly present for single-part instruments for filename generation in source.
        else: # For specific measures [181]
            for ins in add_instruments:
                for pi in range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    if self.part_instruments[ins][2] > 1:
                        base_filename = os.path.splitext(os.path.basename(self.filepath))
                        midi_filename = os.path.join(output):
            midi_filename = os.path.join(output_path, f"{base_filename}.mid?ins={ins}&start={range_start}&end={range_end}&t=100&c=n")
        else:
            midi_filename = os.path.join(output_path, f"{base_filename}.mid?ins={ins}&t=100&c=n")
        part_midis = [prefix + os.path.basename(s) for s in part_midis] # Add prefix to part midis [182] range_end is None: # For full score [183]
            for ins in add_instruments:
                for pi in range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    s.insert(self.score.parts[pi]) # Insert all parts of the instrument into the stream [183]
                if self.part_instruments[ins][2] > 1: # If multiple parts, generate individual part midis too [183]
                    part_mid range(self.part_instruments[ins][1], self.part_instruments[ins][1]+self.part_instruments[ins][2]):
                    if self.part_instruments[ins][2] > 1: # Generate individual part midis if multiple parts [184]
                        part_midis.append(self.generate_midi_parts_for_instrument(range_start, range_end, ins, pi-self.part_instruments[ins][1], output_path, postfix_filename))
                    pi_measures = self.score.parts[pi].measures(range_start, range_end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature', 'TempoIndication')) # Get measures for part [184]
                    if firstPart:
                        if pi != 0: self.insert_tempos(pi_measures, self.score.parts.measure(range_start).offset) # Insert tempos if not part 0 [185]
                        firstPart = False
                    for m in pi_measures.getElementsByClass('Measure'): m.removeByClass('Repeat') # Remove repeats [185]
                    s_filename) # Write MIDI if it doesn't exist [186]
        part_midis = [prefix + os.path.basename(s) for s in part_midis]
        return (prefix+os.path.basename(midi_filename), part_midis) [186]

    def generate_midi_parts_for_instrument(self, range_start=None, range_end=None, instrument=0, part=0, output_path="", postfix_filename=""):
        """
        Generates a MIDI file for a specific part of, f"{base_filename}{postfix_filename}_p{(part+1)}.mid") # Generate part-specific filename [187]
            if not os.path.exists(midi_filename): s.write('midi', midi_filename) # Write MIDI [187]
        else: # For specific measures of the part [187]
            postfix_filename += "_" + str(range_start) + str(range_end)
            s = stream.Score(id='temp')
            print("506 instrument = " + str(instrument) + " part = " +92]
            for m in pi_measures.getElementsByClass('Measure'): m.removeByClass('Repeat') # Remove repeats [188]
            s.insert(pi_measures) # Insert into stream [188]
            base_filename = os.path.splitext(os.path.basename(self.filepath))
            midi_filename = os.path.join(output_path, f"{base_filename}{postfix_filename}_p{(part+1)}.mid") # Generate part-specific filename [188]
            if not os.path.exists(.path.basename(self.filepath))
        if range_start is None and range_end is None: # Export whole score [189]
            midi_filename = os.path.join(output_path, f"{base_filename}.mid")
            if not os.path.exists(midi_filename): self.score.write('midi', midi_filename) # Write MIDI [189]
            return midi_filename
        elif len(parts) > 0: # Export individual parts [190]
            for p in self.score.parts: [190]
                    if p != self.score.parts: self.insert_tempos(midi_stream, self.score.parts.measure(range_start).offset) # Insert tempos [190]
                    for m in midi_stream.getElementsByClass('Measure'): m.removeByClass('Repeat') # Remove repeats [191]
                    midi_stream.write('midi', midi_filename) # Write MIDI [191]
            return midi_filename
        else: # Export combined stream (e.g., both hands) [191]
'): m.removeByClass('Repeat') # Remove repeats [192]
                midi_stream.write('midi', midi_filename) # Write MIDI [192]
            return midi_filename
        return None [192]

    # --- Tempo Insertion ---
    # TODO: Make more efficient when working with multiple parts. [192]
    # Music21 might have a better way; if part 0 is included, tempos are already present. [192]
    def insert_tempos(self, stream, offset_start):
        """0] >= offset_start+stream.duration.quarterLength): return # Ignore tempos starting after stream ends [193]
            if (mmb[1] > offset_start): # If tempo ends during the segment [193]
                if (mmb) <= offset_start: stream.insert(0, tempo.MetronomeMark(number=mmb[2].number)) # Insert at start of stream [193]
                else: stream.insert(mmb-offset_start, tempo.MetronomeMark(number=mmb[2]..get(octave, "?")
        elif settings['octaveDescription'] == "name": return self._OCTAVE_MAP.get(octave, "?")
        elif settings['octaveDescription'] == "none": return ""
        elif settings['octaveDescription'] == "number": return str(octave) [144]

    def map_pitch(self, pitch):
        """
        Maps a music21 Pitch object to a descriptive string based on `pitchDescription` setting. [194]
        Options: 'colourNotes', 'noteName', 'none', 'phoneticpitchDescription'] == "phonetic": pitch_name = self._PITCH_PHONETIC_MAP.get(pitch.name, "?") # Phonetic name [194]
        if pitch.accidental and pitch.accidental.displayStatus and pitch_name != "": # Add accidental description if present and visible [194]
            pitch_name = f"{pitch_name} {pitch.accidental.fullName}"
        return pitch_name [195]

    def map_duration(self, duration):
        """
        Maps a music21 Duration objecthythmDescription'] == "none": return "" [195]

    def map_dots(self, dots):
        """
        Maps the number of dots on a note/rest to a descriptive string (e.g., 'dotted '). [195]
        """
        if settings['rhythmDescription'] == "none": return ""
        else: return self._DOTS_MAP.get(dots) [195]

class HTMLTalkingScoreFormatter():
    """
    Formats the music21 score and its analysis into an HTML output,
    integrating various settings and generatedopts' # Path to the options file [140]
        with open(options_path, "r") as options_fh:
            options = json.load(options_fh) # Load options from JSON file [140]
        # Populate the global 'settings' dictionary with options from the file [140, 196]
        settings = {
            'pitchBeforeDuration': False, 'describeBy': 'beat', 'handsTogether': True,
            'barsAtATime': int(options["bars_at_a_time"]),
            'playAll': options["play_all"], 'playSelected': options["play_selected"], 'playUnselected': options["play_unselected"],
            'instruments': options["instruments"], 'pitchDescription': options["pitch_description"],
            'rhythmDescription': options["rhythm_description"], 'dotPosition': options["dot_position"],
            'rhythmAnnouncement': options["rhythm_announcement"], 'octaveDescription': options["octave_description"],
            'octavePosition': options["octave_position"], 'octaveAnnouncement': options["octave_announcement"],
            'colourPosition2 import Environment, FileSystemLoader # Re-importing here might be redundant if imported globally [145]
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__))) # Set up Jinja2 environment [145]
        template = env.get_template('talkingscore.html') # Load the main HTML template [145]

        self.score.get_instruments() # Get instrument and part information [145]
        self.score.compare_parts_with_selected_instruments() # Determine selected/unselected instruments [20Measure')[-1].number # Last measure number [197]

        selected_instruments_midis = {} # Dictionary to store MIDI filenames for selected instruments [197]
        for index, ins in enumerate(self.score.selected_instruments): # Generate MIDI filenames for each selected instrument [197]
            midis = self.score.generate_midi_filenames(prefix="/midis/" + os.path.basename(web_path) + "/", range_start=start, range_end=end, output_path=output_path, add_instruments=[ins], postfix_filename="="all")
        midiSelected = self.score.generate_midi_filename_sel(prefix="/midis/" + os.path.basename(web_path) + "/", output_path=output_path, range_start=start, range_end=end, sel="sel")
        midiUnselected = self.score.generate_midi_filename_sel(prefix="/midis/" + os.path.basename(web_path) + "/", output_path=output_path, range_start=start, range_end=end, sel="un")

        full_score_midis =key/tempo, bar/part counts [198, 199]
            'full_score_midis': full_score_midis, # MIDI files for whole score [200]
            'music_segments': self.get_music_segments(output_path, web_path, ), # Music broken into segments [200]
            'instruments': self.score.part_instruments, # Detailed instrument info [200]
            'part_names': self.score.part_names, # Part names (e.g., Right Hand) [200]/key signature changes per bar [198]
            'parts_summary': self.music_analyser.summary_parts, # Analysis summary for each part [198]
            'general_summary': self.music_analyser.general_summary, # General score summary [198]
            'repetition_in_contexts': self.music_analyser.repetition_in_contexts, # Repetition context per bar [198]
            'selected_part_names': self.score.selected_part_names, # Names of currently selected parts [207_initial_time_signature(),
            'key_signature': self.score.get_initial_key_signature(),
            'tempo': self.score.get_initial_tempo(),
            'number_of_bars': self.score.get_number_of_bars(),
            'number_of_parts': self.score.get_number_of_parts(),
        }

    def get_music_segments(self, output_path, web_path):
        ""
        Divides the score into segments (e.g., by 4 bars), generates descriptions Total number of bars in score [199]
        t1s = time.time() # Start time for performance measurement [201]

        self.time_and_keys = {} # Dictionary to store time/key signature changes, keyed by bar number [201]
        total = len(self.score.score.parts.flat.getElementsByClass('TimeSignature')) # Total time signatures [201]
        for count, ts in enumerate(self.score.score.parts.flat.getElementsByClass('TimeSignature')): # Iterate time signatures [201].flat.getElementsByClass('KeySignature')): # Iterate key signatures [202]
            description = "Key signature - " + str(count+1) + " of " + str(total) + " is " + self.score.describe_key_signature(ks) + ". "
            self.time_and_keys.setdefault(ks.measureNumber, []).append(description) # Add to time_and_keys [202]

        self.score.timeSigs = {} # Dictionary to store time signatures for each bar (used by get_events_for_bar('Measure').getElementsByClass(meter.TimeSignature)
        self.score.timeSigs = previous_ts # Store time signature for bar 0 [203]

        # Process pickup bar segment (if present) [203]
        # TODO: Decide where spanners and dynamics should be described. [203]
        selected_instruments_descriptions = {} # Descriptions for selected instruments [203]
        selected_instruments_midis = {} # MIDI files for selected instruments [204]
        for index, ins in enumerateins": ins, "midi": midis, "midi_parts": midis[1]}
            selected_instruments_descriptions[ins] = self.score.generate_part_descriptions(instrument=ins, start_bar=0, end_bar=1)

        # Generate MIDI filenames for combined playback for pickup bar [204, 205]
        midiAll = self.score.generate_midi_filename_sel(prefix="/midis/" + os.path.basename(web_path) + "/", output_path=output_path, range_start=0,        # Add pickup bar segment to `music_segments` [205]
        music_segment = {'start_bar': '0 - pickup', 'end_bar': '0 - pickup', 'selected_instruments_descriptions': selected_instruments_descriptions, 'selected_instruments_midis': selected_instruments_midis, 'midi_all': midiAll, 'midi_sel': midiSelected, 'midi_un': midiUnselected}
        music_segments.append(music_segment)
        number_of_bars -= 1 # Decrement total bars if pickup bar was processed separately4]

            # Cludge to handle cases where `measure(bar_index)` returns None (e.g., non-consecutive bar numbers, or Finale's re-used bar numbers) [206]
            # TODO: Need a better way to get each bar to avoid ignoring some. [206]
            if (self.score.score.parts.measure(bar_index) == None):
                print("start bar is none...") # Debugging [206]
                break # Break loop if start bar is invalid

            # Adjust end_bar_index if single non-pickup bar [207]

            for checkts in range(bar_index, end_bar_index+1): # Update timeSigs dictionary for this segment's bars [207]
                if (self.score.score.parts.measure(bar_index) == None):
                    print("bar " + str(bar_index) + " is None...") # Debugging [207]
                elif len(self.score.score.parts.measure(bar_index).getElementsByClass(meter.TimeSignature)) > 0:
_midis = {} # MIDI files for selected instruments for current segment [208]

            for index, ins in enumerate(self.score.selected_instruments): # Generate MIDI and descriptions for selected instruments for current segment [208]
                logger.debug(f"adding to selected_instruments_descriptions - index = {index} and ins = {ins}")
                midis = self.score.generate_midi_filenames(prefix="/midis/" + os.path.basename(web_path) + "/", range_start=bar_index, range_end=end_bar_.score.generate_midi_filename_sel(prefix="/midis/" + os.path.basename(web_path) + "/", output_path=output_path, range_start=bar_index, range_end=end_bar_index, sel="all")
            midiSelected = self.score.generate_midi_filename_sel(prefix="/midis/" + os.path.basename(web_path) + "/", output_path=output_path, range_start=bar_index, range_end=end_bar_index, sel="sel")
            midiUnselected = self.midi_all': midiAll, 'midi_sel': midiSelected, 'midi_un': midiUnselected}
            music_segments.append(music_segment)

        logger.info("End of get_music_segments") # Log end of function [209]
        t1e = time.time() # End time for performance measurement [209]
        print("described parts etc = " + str(t1e-t1s)) # Print elapsed time [209]
        return music_segments [209]

if __name__ == '__mainf63a0a2ebaddd92d569980fb402811b9cd5cce4a/MozartPianoSonata.xml'
    # testScoreFilePath = '../talkingscores/talkingscoresapp/static/data/bach-2-part-invention-no-13.xml'
    testScoreOutputFilePath = testScoreFilePath.replace('.xml', '.html') # Define output HTML file path [210]

    testScore = Music21TalkingScore(testScoreFilePath) # Create a Music21TalkingScore instance a browser (assuming a web server is running) [210]