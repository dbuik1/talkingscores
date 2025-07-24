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
from pathvalidate import sanitize_filename
import shutil
import zipfile
import xml.etree.ElementTree as ET

logger = logging.getLogger("TSScore")
logger.setLevel(logging.DEBUG)
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


def extract_musicxml_from_mxl(mxl_path, output_path):
    """
    Extract MusicXML content from a .mxl file (compressed MusicXML).
    Returns the path to the extracted .musicxml file.
    """
    try:
        with zipfile.ZipFile(mxl_path, 'r') as zip_ref:
            # List all files in the archive
            file_list = zip_ref.namelist()
            logger.info(f"Files in MXL archive: {file_list}")
            
            # Look for the main MusicXML file
            # Common patterns: could be named *.xml, *.musicxml, or sometimes just the filename without extension
            musicxml_candidates = []
            
            for filename in file_list:
                # Skip metadata folders and files
                if filename.startswith('META-INF/') or filename.startswith('__MACOSX/'):
                    continue
                
                # Look for XML files
                if filename.lower().endswith(('.xml', '.musicxml')):
                    musicxml_candidates.append(filename)
            
            if not musicxml_candidates:
                # If no obvious XML files, look for the largest file that might be XML
                non_meta_files = [f for f in file_list if not f.startswith(('META-INF/', '__MACOSX/'))]
                if non_meta_files:
                    # Try the first non-metadata file
                    musicxml_candidates = [non_meta_files[0]]
            
            if not musicxml_candidates:
                raise Exception("No MusicXML content found in .mxl file")
            
            # Use the first candidate (or the one that looks most like a main file)
            musicxml_file = musicxml_candidates[0]
            logger.info(f"Extracting MusicXML file: {musicxml_file}")
            
            # Extract the MusicXML content
            with zip_ref.open(musicxml_file) as source:
                content = source.read()
            
            # Write to output path
            with open(output_path, 'wb') as target:
                target.write(content)
            
            logger.info(f"Successfully extracted MusicXML to: {output_path}")
            return output_path
            
    except zipfile.BadZipFile:
        raise Exception("Invalid .mxl file: not a valid ZIP archive")
    except Exception as e:
        logger.error(f"Error extracting MXL file: {e}")
        raise Exception(f"Failed to extract MusicXML from .mxl file: {e}")


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
        data_filepath = self.get_data_file_path()
        opts_filepath = data_filepath + '.opts'
        
        if not os.path.exists(data_filepath):
            return TSScoreState.FETCHING
        elif not os.path.exists(opts_filepath):
            return TSScoreState.AWAITING_OPTIONS
        else:
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
        if not self.id or not self.filename:
            return None
        
        # SECURITY FIX: Sanitize the filename to prevent path traversal
        safe_filename = os.path.basename(self.filename)  # Removes any path components
        safe_filename = sanitize_filename(safe_filename)  # Already imported, use it properly
        
        path = os.path.join(root, self.id, safe_filename)
        
        # Ensure the directory exists before returning the path
        dir_to_create = os.path.dirname(path)
        try:
            os.makedirs(dir_to_create, exist_ok=True)
        except OSError as e:
            self.logger.error(f"Could not create directory {dir_to_create}: {e}")
            raise
            
        return path

    def html(self):
        data_path = self.get_data_file_path()
        if not data_path:
            return "Error: Could not find score data file."

        web_path = f"/midis/{self.id}/{self.filename}"
        midi_output_path = os.path.join(MEDIA_ROOT, self.id)
        os.makedirs(midi_output_path, exist_ok=True)
        
        self.logger.info(f"Dynamically generating HTML for {data_path}")
        try:
            mxmlScore = Music21TalkingScore(data_path)
            tsf = HTMLTalkingScoreFormatter(mxmlScore)
            html_content = tsf.generateHTML(output_path=midi_output_path, web_path=web_path)
            return html_content
            
        except Exception as e:
            self.logger.exception(f"Failed to generate HTML from score {data_path}")
            return f"<h1>Error Generating Score</h1><p>There was an error processing the MusicXML file: {e}</p>"
    
    @classmethod
    def from_uploaded_file(cls, uploaded_file):
        score = cls()

        uploaded_file.seek(0)
        score.id = hashfile(uploaded_file, hashlib.sha256())
        
        sanitized_name = sanitize_filename(uploaded_file.name.replace("'", "").replace("\"", ""))
        base_name = os.path.splitext(sanitized_name)[0]
        original_extension = os.path.splitext(sanitized_name)[1].lower()
        
        # Always store as .musicxml regardless of input format
        score.filename = f"{base_name}.musicxml"

        destination_path = score.get_data_file_path()
        if not destination_path:
            raise Exception("Could not determine file destination path.")

        # Clear any stale .opts file
        opts_path = destination_path + '.opts'
        if os.path.exists(opts_path):
            try:
                os.remove(opts_path)
                score.logger.info(f"Removed stale options file: {opts_path}")
            except OSError as e:
                score.logger.error(f"Could not remove stale options file {opts_path}: {e}")

        uploaded_file.seek(0)
        
        if original_extension == '.mxl':
            # Handle .mxl files: extract to temporary location, then move to final destination
            score.logger.info(f"Processing .mxl file: {uploaded_file.name}")
            
            # Create temporary file for the uploaded .mxl
            with tempfile.NamedTemporaryFile(suffix='.mxl', delete=False) as temp_mxl:
                for chunk in uploaded_file.chunks():
                    temp_mxl.write(chunk)
                temp_mxl_path = temp_mxl.name
            
            try:
                # Extract MusicXML from the .mxl file
                extract_musicxml_from_mxl(temp_mxl_path, destination_path)
                score.logger.info(f"Successfully extracted MusicXML from .mxl to {destination_path}")
            finally:
                # Clean up temporary .mxl file
                try:
                    os.unlink(temp_mxl_path)
                except OSError:
                    pass
        else:
            # Handle regular .xml/.musicxml files
            with open(destination_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
        
        # Validate the final file
        try:
            Music21TalkingScore(destination_path)
        except Exception as e:
            logger.exception(f"Uploaded file failed validation at final destination: {destination_path}")
            raise e

        return score

    @classmethod
    def from_url(cls, url):
        score = cls(url=url)
        
        response = requests.get(url)
        response.raise_for_status()
        file_content = response.content
        
        score.id = hashlib.sha256(file_content).hexdigest()
        
        parsed_url = urlparse(url)
        original_filename = os.path.basename(parsed_url.path)
        sanitized_name = sanitize_filename(original_filename.replace("'", "").replace("\"", ""))
        base_name = os.path.splitext(sanitized_name)[0]
        original_extension = os.path.splitext(sanitized_name)[1].lower()
        
        # Always store as .musicxml regardless of input format
        score.filename = f"{base_name}.musicxml"

        destination_path = score.get_data_file_path()
        
        if original_extension == '.mxl':
            # Handle .mxl files from URL
            score.logger.info(f"Processing .mxl file from URL: {url}")
            
            # Create temporary file for the downloaded .mxl
            with tempfile.NamedTemporaryFile(suffix='.mxl', delete=False) as temp_mxl:
                temp_mxl.write(file_content)
                temp_mxl_path = temp_mxl.name
            
            try:
                # Extract MusicXML from the .mxl file
                extract_musicxml_from_mxl(temp_mxl_path, destination_path)
                score.logger.info(f"Successfully extracted MusicXML from URL .mxl to {destination_path}")
            finally:
                # Clean up temporary .mxl file
                try:
                    os.unlink(temp_mxl_path)
                except OSError:
                    pass
        else:
            # Handle regular .xml/.musicxml files from URL
            with open(destination_path, 'wb') as f:
                f.write(file_content)
        
        # Validate the final file
        try:
            Music21TalkingScore(destination_path)
        except Exception as e:
            logger.exception(f"URL-fetched file failed validation at final destination: {destination_path}")
            raise e
            
        return score