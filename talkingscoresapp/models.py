import os
import hashlib
import ipaddress
import re
import requests
import json
import logging
import socket
from talkingscores.settings import MEDIA_ROOT
from urllib.parse import urlparse, urljoin
import tempfile
from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
from pathvalidate import sanitize_filename
import xml.etree.ElementTree as ElementTree
import zipfile
import threading
import time
import uuid
from contextlib import contextmanager

REMOTE_FETCH_TIMEOUT = 20
MAX_REMOTE_SCORE_BYTES = 10 * 1024 * 1024
MAX_REMOTE_REDIRECTS = 5

# A score id is the SHA-256 of the file content, so it is always 64 lower-case hex digits.
SCORE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# A generation run refreshes its lock file while it works. A lock that has not
# been refreshed for this long belongs to a dead run and is taken over.
GENERATION_LOCK_STALE_SECONDS = 180
GENERATION_HEARTBEAT_SECONDS = 15

# Sizes for the pieces of a compressed .mxl archive that are read into memory.
MAX_CONTAINER_MANIFEST_BYTES = 64 * 1024
MAX_EXTRACTED_SCORE_BYTES = 50 * 1024 * 1024

# NAT64 prefixes translate an IPv6 address into an IPv4 one, so a "public"
# IPv6 address in one of these ranges can reach a private IPv4 host.
NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))

# The remote fetch never goes through a proxy: the address check applies to
# the host the request actually connects to.
NO_PROXIES = {"http": None, "https": None}

GENERATION_FAILED_MESSAGE = "The score could not be generated from this file."


class ScoreGenerationInProgress(Exception):
    """Another process or thread holds the generation lock for this score."""


class RemoteAddressNotAllowed(ValueError):
    """The URL points at a host that is not a public internet address."""


def is_public_ip(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif any(ip in network for network in NAT64_NETWORKS):
            return False
    # is_global also excludes the shared address space 100.64.0.0/10 and the
    # IETF protocol ranges that is_private alone lets through.
    return ip.is_global and not (
        ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def check_url_targets_public_host(url):
    """Raise unless every address the URL's host resolves to is a public internet address.

    The lookup here and the lookup inside the HTTP request are separate, so a
    host whose DNS answer changes between them (DNS rebinding) is not caught.
    Closing that gap needs the request pinned to the checked address, which
    the HTTP client does not support without replacing its connection pool.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS MusicXML URLs are supported.")
    host = parsed.hostname
    if not host:
        raise RemoteAddressNotAllowed("The URL has no host name.")
    try:
        results = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise RemoteAddressNotAllowed(f"The host {host} could not be found.") from exc
    addresses = {result[4][0] for result in results}
    if not addresses:
        raise RemoteAddressNotAllowed(f"The host {host} could not be found.")
    for address in addresses:
        if not is_public_ip(address):
            raise RemoteAddressNotAllowed(f"The host {host} is not a public internet address.")
    return parsed


def fetch_remote_score(url):
    """Download a score over HTTP, checking every redirect hop against the public-host rule."""
    current_url = url
    for _ in range(MAX_REMOTE_REDIRECTS + 1):
        check_url_targets_public_host(current_url)
        response = requests.get(
            current_url,
            timeout=REMOTE_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=False,
            proxies=NO_PROXIES,
        )
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("The server redirected without saying where.")
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        file_chunks = []
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > MAX_REMOTE_SCORE_BYTES:
                raise ValueError("Remote MusicXML file is too large.")
            file_chunks.append(chunk)
        return b"".join(file_chunks), current_url
    raise ValueError("The URL redirected too many times.")


def configure_score_logger():
    score_logger = logging.getLogger("TSScore")
    score_logger.setLevel(logging.DEBUG)

    if getattr(score_logger, "_talkingscores_configured", False):
        return score_logger

    console_handler = logging.StreamHandler()
    os.makedirs(MEDIA_ROOT, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(MEDIA_ROOT, "log1.txt"))
    console_handler.setLevel(logging.DEBUG)
    file_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("Ln %(lineno)d - %(message)s")
    file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_format)
    file_handler.setFormatter(file_format)
    score_logger.addHandler(console_handler)
    score_logger.addHandler(file_handler)
    score_logger._talkingscores_configured = True
    return score_logger


logger = configure_score_logger()


def remove_file_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def hashfile(afile, hasher, blocksize=65536):
    buf = afile.read(blocksize)
    while len(buf) > 0:
        hasher.update(buf)
        buf = afile.read(blocksize)
    return hasher.hexdigest()


def rootfile_from_container(zip_ref):
    """Return the score path named by META-INF/container.xml, or None when the archive has no usable manifest."""
    try:
        manifest_info = zip_ref.getinfo("META-INF/container.xml")
    except KeyError:
        return None
    if manifest_info.file_size > MAX_CONTAINER_MANIFEST_BYTES:
        return None
    container_xml = zip_ref.read(manifest_info)
    # Entity declarations can expand to far more than the manifest's size.
    if b"<!ENTITY" in container_xml or b"<!DOCTYPE" in container_xml:
        return None
    try:
        root = ElementTree.fromstring(container_xml)
    except ElementTree.ParseError:
        return None
    for element in root.iter():
        if element.tag.split("}")[-1] == "rootfile":
            full_path = element.get("full-path")
            if full_path and full_path in zip_ref.namelist():
                return full_path
    return None


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

            # The manifest names the score; the name-based search is only a fallback for archives without one.
            manifest_rootfile = rootfile_from_container(zip_ref)
            musicxml_candidates = [manifest_rootfile] if manifest_rootfile else []
            
            if not manifest_rootfile:
                for filename in file_list:
                    # Skip metadata folders and files
                    if filename.startswith('META-INF/') or filename.startswith('__MACOSX/'):
                        continue

                    # Look for XML files
                    if filename.lower().endswith(('.xml', '.musicxml')):
                        musicxml_candidates.append(filename)
                        break
            
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
            # The archive header can lie about the uncompressed size, so the
            # cap is applied to the bytes actually read.
            with zip_ref.open(musicxml_file) as source:
                content = source.read(MAX_EXTRACTED_SCORE_BYTES + 1)
            if len(content) > MAX_EXTRACTED_SCORE_BYTES:
                raise Exception("The MusicXML inside the .mxl file is too large")
            
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


def write_text_file_atomic(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=os.path.dirname(path),
        delete=False,
    ) as temp_file:
        temp_file.write(content)
        temp_path = temp_file.name
    try:
        os.replace(temp_path, path)
    except OSError:
        remove_file_quietly(temp_path)
        raise


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
        if not SCORE_ID_PATTERN.match(self.id):
            raise ValueError("Score id must be 64 lower-case hex digits.")

        # The filename is user supplied, so path components are stripped before it is joined.
        safe_filename = os.path.basename(self.filename)
        safe_filename = sanitize_filename(safe_filename)
        if not safe_filename or safe_filename.strip(".") == "":
            raise ValueError("Score filename is empty after sanitising.")

        # Only the code paths that write a file create its directory.
        return os.path.join(root, self.id, safe_filename)

    def get_html_cache_file_path(self):
        data_path = self.get_data_file_path()
        return data_path + ".html" if data_path else None

    def get_processing_status_file_path(self):
        data_path = self.get_data_file_path()
        return data_path + ".status" if data_path else None

    def get_generation_lock_file_path(self):
        data_path = self.get_data_file_path()
        return data_path + ".lock" if data_path else None

    def options_epoch(self):
        """A digest of the current options file, so a run started under older options can tell they changed."""
        data_path = self.get_data_file_path()
        if not data_path:
            return None
        try:
            with open(data_path + ".opts", "rb") as options_file:
                return hashlib.sha256(options_file.read()).hexdigest()
        except OSError:
            return None

    # The lock is a file holding a random token. Only the holder of the token
    # refreshes, releases or reports a result under that lock, so a run that
    # was taken over as stale cannot disturb its successor.
    _lock_token = None

    def _read_generation_lock(self):
        lock_path = self.get_generation_lock_file_path()
        if not lock_path:
            return None
        try:
            with open(lock_path, "r", encoding="utf-8") as lock_file:
                data = json.load(lock_file)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _generation_lock_is_stale(self):
        lock_path = self.get_generation_lock_file_path()
        lock = self._read_generation_lock() or {}
        last_updated = lock.get("updated")
        if not isinstance(last_updated, (int, float)):
            try:
                last_updated = os.path.getmtime(lock_path)
            except OSError:
                return True
        return time.time() - last_updated > GENERATION_LOCK_STALE_SECONDS

    def generation_is_live(self):
        """True while some run holds a lock that is still being refreshed."""
        lock_path = self.get_generation_lock_file_path()
        if not lock_path or not os.path.exists(lock_path):
            return False
        return not self._generation_lock_is_stale()

    def _write_generation_lock_file(self, lock_path, token, exclusive):
        flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
        if exclusive:
            flags |= os.O_EXCL
        fd = os.open(lock_path, flags)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            json.dump({"token": token, "pid": os.getpid(), "updated": time.time()}, lock_file)

    def acquire_generation_lock(self):
        """Take the per-score lock. Returns False when a live run already holds it."""
        lock_path = self.get_generation_lock_file_path()
        if not lock_path:
            return False
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        token = uuid.uuid4().hex
        for _ in range(2):
            try:
                self._write_generation_lock_file(lock_path, token, exclusive=True)
            except FileExistsError:
                if not self._generation_lock_is_stale():
                    return False
                self.logger.warning(f"Taking over a stale generation lock for {self.id}/{self.filename}")
                remove_file_quietly(lock_path)
                continue
            self._lock_token = token
            return True
        return False

    def _owns_generation_lock(self):
        if not self._lock_token:
            return False
        lock = self._read_generation_lock()
        return bool(lock) and lock.get("token") == self._lock_token

    def refresh_generation_lock(self):
        """Mark the lock as live. Does nothing once another run has taken it over."""
        if not self._owns_generation_lock():
            return False
        lock_path = self.get_generation_lock_file_path()
        temp_path = f"{lock_path}.{uuid.uuid4().hex}.tmp"
        try:
            self._write_generation_lock_file(temp_path, self._lock_token, exclusive=True)
            os.replace(temp_path, lock_path)
        except OSError:
            remove_file_quietly(temp_path)
            return False
        return True

    def release_generation_lock(self):
        """Remove the lock, but only when this object holds it."""
        if self._owns_generation_lock():
            remove_file_quietly(self.get_generation_lock_file_path())
        self._lock_token = None

    @contextmanager
    def _generation_heartbeat(self, epoch=None, with_status=False):
        """Refresh the lock (and optionally the status file) while a run is in progress."""
        stop = threading.Event()

        def beat():
            while not stop.wait(GENERATION_HEARTBEAT_SECONDS):
                if not self.refresh_generation_lock():
                    return
                if with_status:
                    self._write_processing_status("processing", "Generating score.", epoch=epoch)

        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
        try:
            yield
        finally:
            # The thread must be finished before a terminal status is written,
            # or a late heartbeat could overwrite it with "processing".
            stop.set()
            thread.join()

    def _is_html_cache_fresh(self, html_path, data_path):
        if not html_path or not os.path.exists(html_path):
            return False

        html_mtime = os.path.getmtime(html_path)
        source_paths = [data_path, data_path + ".opts"]
        return all(not os.path.exists(path) or os.path.getmtime(path) <= html_mtime for path in source_paths)

    def _write_processing_status(self, status, message="", epoch=None):
        """Write the status file, unless the options changed since the run identified by epoch began."""
        status_path = self.get_processing_status_file_path()
        if not status_path:
            return
        if epoch is not None and self.options_epoch() != epoch:
            return
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        status_data = {
            "status": status,
            "message": message,
            "updated": time.time(),
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=os.path.dirname(status_path),
            delete=False,
        ) as status_file:
            json.dump(status_data, status_file)
            temp_status_path = status_file.name
        try:
            os.replace(temp_status_path, status_path)
        except OSError:
            remove_file_quietly(temp_status_path)
            raise

    def processing_status(self):
        status_path = self.get_processing_status_file_path()
        if not status_path or not os.path.exists(status_path):
            return {"status": "pending", "message": ""}
        try:
            with open(status_path, "r", encoding="utf-8") as status_file:
                return json.load(status_file)
        except (OSError, json.JSONDecodeError):
            return {"status": "unknown", "message": "Could not read processing status."}

    def clear_generated_html_state(self):
        for path in (self.get_html_cache_file_path(), self.get_processing_status_file_path()):
            if path and os.path.exists(path):
                os.remove(path)

    def start_background_processing(self):
        """Generate the score on a background thread. Returns False when a run is already under way."""
        if not self.acquire_generation_lock():
            return False

        try:
            epoch = self.options_epoch()
            if self._is_html_cache_fresh(self.get_html_cache_file_path(), self.get_data_file_path()):
                self._write_processing_status("complete", "Score ready.", epoch=epoch)
                self.release_generation_lock()
                return True
            self._write_processing_status("processing", "Generating score.", epoch=epoch)

            def generate():
                try:
                    with self._generation_heartbeat(epoch=epoch, with_status=True):
                        self._generate_html(export_theme=None, export_mode=False, epoch=epoch)
                    status, message = "complete", "Score ready."
                except Exception:
                    self.logger.exception(f"Background score generation failed for {self.id}/{self.filename}")
                    status, message = "failed", GENERATION_FAILED_MESSAGE
                # A run that lost its lock to a takeover must not report over the newer run.
                if self._owns_generation_lock():
                    self._write_processing_status(status, message, epoch=epoch)
                self.release_generation_lock()

            threading.Thread(target=generate, daemon=True).start()
        except Exception:
            self.release_generation_lock()
            raise
        return True

    def html(self, export_theme=None, export_mode=False, force_refresh=False, raise_errors=False):
        """Return the score HTML, generating it under the per-score lock when the cache is missing or stale."""
        data_path = self.get_data_file_path()
        if not data_path:
            return "Error: Could not find score data file."

        html_cache_path = self.get_html_cache_file_path()
        if not export_mode and not force_refresh and self._is_html_cache_fresh(html_cache_path, data_path):
            with open(html_cache_path, "r", encoding="utf-8") as html_file:
                return html_file.read()

        if not self.acquire_generation_lock():
            raise ScoreGenerationInProgress(f"Score {self.id} is already being generated.")
        try:
            with self._generation_heartbeat():
                return self._generate_html(export_theme=export_theme, export_mode=export_mode, epoch=self.options_epoch())
        except Exception:
            if raise_errors:
                raise
            return f"<h1>Error Generating Score</h1><p>{GENERATION_FAILED_MESSAGE}</p>"
        finally:
            self.release_generation_lock()

    def _generate_html(self, export_theme, export_mode, epoch):
        """Render the score. The caller holds the generation lock."""
        data_path = self.get_data_file_path()
        html_cache_path = self.get_html_cache_file_path()

        web_path = f"/midis/{self.id}/{self.filename}"
        download_html_url = f"/download/html/{self.id}/{self.filename}"
        midi_output_path = os.path.join(MEDIA_ROOT, self.id)
        os.makedirs(midi_output_path, exist_ok=True)
        
        self.logger.info(f"Dynamically generating HTML for {data_path}")
        try:
            mxmlScore = Music21TalkingScore(data_path)
            tsf = HTMLTalkingScoreFormatter(mxmlScore)
            html_content = tsf.generateHTML(
                output_path=midi_output_path,
                web_path=web_path,
                download_html_url=download_html_url,
                export_theme=export_theme,
                export_mode=export_mode,
            )
            # Options that changed during the run belong to a newer run, which writes its own cache.
            if not export_mode and html_cache_path and self.options_epoch() == epoch:
                write_text_file_atomic(html_cache_path, html_content)
            return html_content
            
        except Exception:
            self.logger.exception(f"Failed to generate HTML from score {data_path}")
            raise
    
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
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)

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
                remove_file_quietly(temp_mxl_path)
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

        file_content, final_url = fetch_remote_score(url)
        parsed_url = urlparse(final_url)

        score.id = hashlib.sha256(file_content).hexdigest()
        
        original_filename = os.path.basename(parsed_url.path)
        sanitized_name = sanitize_filename(original_filename.replace("'", "").replace("\"", ""))
        base_name = os.path.splitext(sanitized_name)[0]
        original_extension = os.path.splitext(sanitized_name)[1].lower()
        
        # Always store as .musicxml regardless of input format
        score.filename = f"{base_name}.musicxml"

        destination_path = score.get_data_file_path()
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)

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
                remove_file_quietly(temp_mxl_path)
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
