from django.db import models

import os
import errno
import hashlib
import requests
import logging
import logging.handlers
import logging.config
from talkingscores.settings import BASE_DIR, MEDIA_ROOT, STATIC_ROOT, STATIC_URL
from urllib.parse import urlparse
from urllib.request import url2pathname
import tempfile
from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
# the musicxml file is saved with its original filename - so needs to be sanitized.  Also, we remove apostrophes
from pathvalidate import sanitize_filename
import shutil

logger = logging.getLogger("TSScore")
logger.setLevel(logging.DEBUG)  # set the minimum level for the logger to the level of the lowest handler or some events could be missed!
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler(os.path.join(*(MEDIA_ROOT, "log1.txt")))
console_handler.setLevel(logging.DEBUG)
file_handler.setLevel(logging.INFO)
console_format = logging.Formatter("Ln %(lineno)d - %(message)s")
file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_format)
file_handler.setFormatter(file_format)
logger.addHandler(console_handler)
logger.addHandler(file_handler)


def hashfile(afile, hasher, blocksize=65536):
    buf = afile.read(blocksize)
    while len(buf) > 0:
        hasher.update(buf)
        buf = afile.read(blocksize)
    return hasher.hexdigest()


class TSScoreState(object):
    IDLE = "idle"
    FETCHING = "fetching"
    AWAITING_OPTIONS = "awaiting options"
    AWAITING_PROCESSING = "awaiting processing"
    PROCESSED = "processed"


class TSScore(object):

    logger = logging.getLogger("TSScore")

    def __init__(self, id=None, initial_state=TSScoreState.IDLE, url=None, filename=None):
        self._state = initial_state
        self.url = url
        self.id = id
        self.filename = filename

    def state(self):
        # This method remains the same
        data_filepath = self.get_data_file_path()
        opts_filepath = data_filepath + '.opts'
        
        # We no longer check for a cached HTML file, so the state logic is simplified.
        # Once options are submitted, we consider it ready for processing.
        if not os.path.exists(data_filepath):
            return TSScoreState.FETCHING
        elif not os.path.exists(opts_filepath):
            return TSScoreState.AWAITING_OPTIONS
        else:
            # If the XML and options exist, it's ready to be processed into HTML on request.
            return TSScoreState.PROCESSED


    def info(self):
        try:
            data_filepath = self.get_data_file_path()
            score = Music21TalkingScore(data_filepath)
            
            beat_options = score.get_beat_division_options()

            return {
                'title': score.get_title(),
                'composer': score.get_composer(),
                'time_signature': score.get_initial_time_signature(),
                'key_signature': score.get_initial_key_signature(),
                'tempo': score.get_initial_tempo(),
                'instruments': score.get_instruments(),
                'number_of_bars': score.get_number_of_bars(),
                'number_of_parts': score.get_number_of_parts(),
                'rhythm_range': score.get_rhythm_range(),
                'octave_range': score.get_octave_range(),
                'beat_division_options': beat_options
            }
        except Exception as e:
            self.logger.exception(f"Failed to parse MusicXML info: {e}")
            return {
                'title': 'Error reading title', 'composer': 'Unknown',
                'instruments': ['Error'], 'time_signature': '',
                'key_signature': '', 'tempo': '', 'number_of_bars': '',
                'rhythm_range': [], 'octave_range': {'min': 0, 'max': 0},
                'beat_division_options': []
            }

    def get_data_file_path(self, root=MEDIA_ROOT):
        # This method is simplified but the core logic is similar
        if not self.id or not self.filename:
            return None # Cannot determine path without id and filename
        
        path = os.path.join(root, self.id, self.filename)
        
        # Ensure the directory exists before returning the path
        dir_to_create = os.path.dirname(path)
        try:
            os.makedirs(dir_to_create, exist_ok=True)
        except OSError as e:
            self.logger.error(f"Could not create directory {dir_to_create}: {e}")
            raise
            
        return path

    def html(self):
        # --- MODIFIED: REMOVED HTML CACHING ---
        # This method now generates the HTML dynamically on every call.
        
        data_path = self.get_data_file_path()
        if not data_path:
            return "Error: Could not find score data file."

        # The web path for MIDI links.
        web_path = f"/midis/{self.id}/{self.filename}"
        
        # The output path for on-demand MIDI files is the media directory for this score.
        midi_output_path = os.path.join(MEDIA_ROOT, self.id)
        os.makedirs(midi_output_path, exist_ok=True)
        
        self.logger.info(f"Dynamically generating HTML for {data_path}")
        try:
            mxmlScore = Music21TalkingScore(data_path)
            tsf = HTMLTalkingScoreFormatter(mxmlScore)
            
            # The formatter will now handle MIDI generation as needed.
            html_content = tsf.generateHTML(output_path=midi_output_path, web_path=web_path)
            
            return html_content
            
        except Exception as e:
            self.logger.exception(f"Failed to generate HTML from score {data_path}")
            return f"<h1>Error Generating Score</h1><p>There was an error processing the MusicXML file: {e}</p>"
    
    @classmethod
    def from_uploaded_file(cls, uploaded_file):
        # --- NEW, SIMPLIFIED UPLOAD LOGIC ---
        score = cls()

        # 1. Determine ID and Filename
        uploaded_file.seek(0)
        score.id = hashfile(uploaded_file, hashlib.sha256())
        
        sanitized_name = sanitize_filename(uploaded_file.name.replace("'", "").replace("\"", ""))
        base_name = os.path.splitext(sanitized_name)[0]
        score.filename = f"{base_name}.musicxml"

        # 2. Get final destination path (this also creates the directory)
        destination_path = score.get_data_file_path()
        if not destination_path:
            raise Exception("Could not determine file destination path.")

        # --- START: New Cache Clearing Logic ---
        # Check for and delete any stale .opts file from a previous run.
        # This ensures the user is always presented with the options page on a new upload.
        opts_path = destination_path + '.opts'
        if os.path.exists(opts_path):
            try:
                os.remove(opts_path)
                score.logger.info(f"Removed stale options file: {opts_path}")
            except OSError as e:
                score.logger.error(f"Could not remove stale options file {opts_path}: {e}")
        # --- END: New Cache Clearing Logic ---

        # 3. Write the file DIRECTLY to the final destination
        uploaded_file.seek(0)
        with open(destination_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)
        
        # 4. Validate the final file
        try:
            Music21TalkingScore(destination_path)
        except Exception as e:
            logger.exception(f"Uploaded file failed validation at final destination: {destination_path}")
            raise e # Re-raise the exception to be caught by the view

        return score

    @classmethod
    def from_url(cls, url):
        # --- NEW, SIMPLIFIED URL LOGIC ---
        score = cls(url=url)
        
        # 1. Fetch the file into memory
        response = requests.get(url)
        response.raise_for_status() # Will raise an error for bad responses
        file_content = response.content
        
        # 2. Determine ID and Filename
        score.id = hashlib.sha256(file_content).hexdigest()
        
        parsed_url = urlparse(url)
        original_filename = os.path.basename(parsed_url.path)
        sanitized_name = sanitize_filename(original_filename.replace("'", "").replace("\"", ""))
        base_name = os.path.splitext(sanitized_name)[0]
        score.filename = f"{base_name}.musicxml"

        # 3. Get final path and write file directly
        destination_path = score.get_data_file_path()
        with open(destination_path, 'wb') as f:
            f.write(file_content)
        
        # 4. Validate the final file
        try:
            Music21TalkingScore(destination_path)
        except Exception as e:
            logger.exception(f"URL-fetched file failed validation at final destination: {destination_path}")
            raise e
            
        return score