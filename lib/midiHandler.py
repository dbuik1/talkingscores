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
    # Changed 'get' to 'request' for clarity, as the whole request object is passed in.
    # lib/midiHandler.py

    def __init__(self, request, folder, filename):
        self.queryString = request
        self.folder = folder
        self.filename = filename.replace(".mid", "")
        # This will hold a pre-parsed music21 score object to avoid re-parsing
        self.score = None

    def get_selected_instruments(self):
        # Corrected to use .GET
        bsi = int(self.queryString.GET.get("bsi"))
        self.selected_instruments = []
        while (bsi > 1):
            if (bsi & 1 == True):
                self.selected_instruments.append(True)
            else:
                self.selected_instruments.append(False)
            bsi = bsi >> 1
        self.selected_instruments.reverse()

        self.all_selected_parts = []
        self.all_unselected_parts = []
        self.selected_instruement_parts = {}

        instrument_index = -1
        prev_instrument = ""
        for part_index, part in enumerate(self.score.flat.getInstruments()):
            if part.partId != prev_instrument:
                instrument_index += 1
            
            if self.selected_instruments[instrument_index]:
                self.all_selected_parts.append(part_index)
                if instrument_index in self.selected_instruement_parts:
                    self.selected_instruement_parts[instrument_index].append(part_index)
                else:
                    self.selected_instruement_parts[instrument_index] = [part_index]
            else:
                self.all_unselected_parts.append(part_index)
                # This line was not needed and could cause issues.
                # self.selected_instruement_parts[instrument_index] = []
            prev_instrument = part.partId

        # Corrected typo from .Get to .GET
        bpi = int(self.queryString.GET.get("bpi"))
        self.play_together_unselected = bpi & 1
        bpi = bpi >> 1
        self.play_together_selected = bpi & 1
        bpi = bpi >> 1
        self.play_together_all = bpi & 1

    def make_midi_files(self):
        # If a score object wasn't passed in, parse it from the file.
        if not self.score:
            xml_file_path = os.path.join(MEDIA_ROOT, self.folder, self.filename)
            self.score = converter.parse(xml_file_path)

        self.get_selected_instruments()
        
        # FIX: Handle requests that may not specify a start/end (i.e., for the whole score)
        start_param = self.queryString.GET.get("start")
        if start_param is not None:
            start = int(start_param)
            end = int(self.queryString.GET.get("end"))
        else:
            # Default to the entire score if no range is given
            start = self.score.parts[0].getElementsByClass('Measure')[0].number
            end = self.score.parts[0].getElementsByClass('Measure')[-1].number

        # FIX: Hybrid Generation - Check if this is a fast upfront call
        is_upfront_call = self.queryString.GET.get("upfront_generate")
        if is_upfront_call:
            tempos_to_generate = [100]  # Only default tempo
            clicks_to_generate = ['n']    # Only default click track
        else:
            # For on-demand requests, generate all variations to be safe
            tempos_to_generate = [50, 100, 150]
            clicks_to_generate = ['n', 'be']

        # Determine the starting offset for tempo calculations
        offset = 0.0
        if self.score.parts and self.score.parts[0].measure(start):
            offset = self.score.parts[0].measure(start).offset

        # Create the score segment for the current bar range
        self.scoreSegment = stream.Score(id='tempSegment')
        for p in self.score.parts:
            if start == 0 and end == 0:
                measures_in_range = p.measures(0, 0)
            else:
                measures_in_range = p.measures(start, end)
            
            if measures_in_range:
                for m in measures_in_range.getElementsByClass('Measure'):
                    m.removeByClass('Repeat')
                self.scoreSegment.insert(0, measures_in_range)

        # Loop through the required variations and generate MIDI files
        for click in clicks_to_generate:
            self.tempo_shift = 0
            for tempo in tempos_to_generate:
                if self.play_together_all:
                    self.make_midi_together(start, end, offset, tempo, click, "all")
                if self.play_together_selected and self.all_selected_parts:
                    self.make_midi_together(start, end, offset, tempo, click, "sel")
                if self.play_together_unselected and self.all_unselected_parts:
                    self.make_midi_together(start, end, offset, tempo, click, "un")

                for index, parts_list in enumerate(self.selected_instruement_parts.values()):
                    if not parts_list: continue
                    s = stream.Score(id='temp')
                    for pi in parts_list:
                        if len(self.scoreSegment.parts) > pi: s.insert(0, self.scoreSegment.parts[pi])
                    if s.parts:
                        self.insert_tempos(s, offset, tempo/100)
                        self.insert_click_track(s, click)
                        s.write('midi', self.make_midi_path_from_options(start=start, end=end, ins=index+1, tempo=tempo, click=click))
                        if len(parts_list) > 1:
                            for pi in parts_list:
                                s_part = stream.Score(id='temp_part')
                                if len(self.scoreSegment.parts) > pi: s_part.insert(0, self.scoreSegment.parts[pi])
                                if s_part.parts:
                                    self.insert_tempos(s_part, offset, tempo/100)
                                    self.insert_click_track(s_part, click)
                                    s_part.write('midi', self.make_midi_path_from_options(start=start, end=end, part=pi, tempo=tempo, click=click))

    def make_midi_together(self, start, end, offset, tempo, click, which_parts):
        parts_in = []
        if (which_parts == "sel"): parts_in = self.all_selected_parts
        elif (which_parts == "un"): parts_in = self.all_unselected_parts
        
        s = stream.Score(id='temp')
        for part_index, p in enumerate(self.scoreSegment.parts):
            if which_parts == "all" or part_index in parts_in:
                s.insert(p.measures(start, end, collect=('Clef', 'TimeSignature', 'Instrument', 'KeySignature')))
        
        # --- FIX: Add a check to ensure the stream is not empty ---
        if not s.parts:
            logger.info(f"Skipping MIDI generation for '{which_parts}' because there are no parts to include.")
            return # Exit the function if there's nothing to write

        self.insert_tempos(s, offset, tempo/100)
        self.insert_click_track(s, click)
        s.write('midi', self.make_midi_path_from_options(start=start, end=end, sel=which_parts, tempo=tempo, click=click))

    def insert_click_track(self, s, click):
        # This method's internal logic did not have the bugs we are fixing.
        # It has been left as is from your provided file.
        if click == 'n':
            return
        clicktrack = stream.Stream()
        ins = instrument.Percussion()
        ins.midiChannel = 9
        clicktrack.insert(0, ins)
        ts: meter.TimeSignature = None
        shift_measure_offset = 0
        for m in s.getElementsByClass(stream.Part)[0].getElementsByClass(stream.Measure):
            if len(m.getElementsByClass(meter.TimeSignature)) > 0:
                ts = m.getElementsByClass(meter.TimeSignature)[0]
            else:
                if (ts == None):
                    ts: meter.TimeSignature = m.previous('TimeSignature')
                if (ts == None):
                    ts = meter.TimeSignature('1/4')
            clickmeasure = stream.Measure()
            clickmeasure.mergeAttributes(m)
            clickmeasure.duration = ts.barDuration
            clickNote = note.Note('D2')
            clickNote.duration = ts.getBeatDuration(0)
            clickmeasure.append(clickNote)
            beatpos = ts.getBeatDuration(0).quarterLength
            if (m.duration.quarterLength < ts.barDuration.quarterLength and len(m.getElementsByClass(['Note', 'Rest'])) > 0):
                rest_duration = ts.barDuration.quarterLength - m.duration.quarterLength
                r = note.Rest()
                r.duration.quarterLength = rest_duration
                for p in self.scoreSegment.parts:
                    r = note.Rest()
                    r.duration.quarterLength = rest_duration
                    p.getElementsByClass(stream.Measure)[0].insertAndShift(0, r)
                    for ms in p.getElementsByClass(stream.Measure)[1:]:
                        ms.offset += rest_duration
                for p in s.parts:
                    for ms in p.getElementsByClass(stream.Measure)[1:]:
                        ms.offset += rest_duration
                shift_measure_offset = rest_duration
                for t in s.getElementsByClass(tempo.MetronomeMark):
                    if (t.offset > 0):
                        t.offset += shift_measure_offset
                self.tempo_shift = rest_duration
            for b in range(0, ts.beatCount-1):
                clickNote = note.Note('F#2')
                clickNote.duration = ts.getBeatDuration(beatpos)
                beatpos += clickNote.duration.quarterLength
                clickmeasure.append(clickNote)
            clicktrack.append(clickmeasure)
        s.insert(clicktrack)

    def insert_tempos(self, stream, offset_start, scale):
        # This method's internal logic did not have the bugs we are fixing.
        # It has been left as is from your provided file.
        for mmb in self.score.metronomeMarkBoundaries():
            if (mmb[0] >= offset_start+stream.duration.quarterLength):
                return
            if (mmb[1] > offset_start):
                tempoNumber = Music21TalkingScore.fix_tempo_number(tempo=mmb[2]).number
                if (mmb[0]) <= offset_start:
                    stream.insert(0.001, tempo.MetronomeMark(number=tempoNumber*scale, referent=mmb[2].referent))
                else:
                    stream.insert(mmb[0]-offset_start + self.tempo_shift, tempo.MetronomeMark(number=tempoNumber*scale, referent=mmb[2].referent))

    def make_midi_path_from_options(self, sel=None, part=None, ins=None, start=None, end=None, click=None, tempo=None):
        midiname = self.filename
        if (sel is not None): midiname += "sel-"+str(sel)
        if (part is not None): midiname += "p"+str(part)
        if (ins is not None): midiname += "i"+str(ins)
        if (start is not None): midiname += "s"+str(start)
        if (end is not None): midiname += "e"+str(end)
        if (click is not None): midiname += "c"+str(click)
        if (tempo is not None): midiname += "t"+str(tempo)
        midiname += ".mid"
        
        # All generated files MUST be saved in MEDIA_ROOT
        return os.path.join(MEDIA_ROOT, self.folder, midiname)

    def get_or_make_midi_file(self):
        midiname = self.filename
        
        # Correctly access query parameters using .GET
        if (self.queryString.GET.get("sel") is not None): midiname += "sel-"+self.queryString.GET.get("sel")
        if (self.queryString.GET.get("part") is not None): midiname += "p"+self.queryString.GET.get("part")
        if (self.queryString.GET.get("ins") is not None): midiname += "i"+self.queryString.GET.get("ins")
        if (self.queryString.GET.get("start") is not None): midiname += "s"+self.queryString.GET.get("start")
        if (self.queryString.GET.get("end") is not None): midiname += "e"+self.queryString.GET.get("end")
        if (self.queryString.GET.get("c") is not None): midiname += "c"+self.queryString.GET.get("c")
        if (self.queryString.GET.get("t") is not None): midiname += "t"+self.queryString.GET.get("t")

        self.midiname = midiname + ".mid"
        
        midi_filepath = os.path.join(MEDIA_ROOT, self.folder, self.midiname)
        
        os.makedirs(os.path.dirname(midi_filepath), exist_ok=True)

        if not os.path.exists(midi_filepath):
            logger.debug(f"MIDI file not found - {midi_filepath} - making it...")
            self.make_midi_files()

        return midi_filepath