import base64
import os
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger("TSScore")

def midi_file_to_base64(midi_file_path: str) -> str:
    """
    Convert a MIDI file to a base64 data URL.
    
    Args:
        midi_file_path (str): Path to the MIDI file
        
    Returns:
        str: Base64 data URL for the MIDI file
    """
    try:
        with open(midi_file_path, 'rb') as midi_file:
            midi_data = midi_file.read()
            base64_data = base64.b64encode(midi_data).decode('utf-8')
            return f"data:audio/midi;base64,{base64_data}"
    except FileNotFoundError:
        logger.warning(f"MIDI file not found: {midi_file_path}")
        return None
    except Exception as e:
        logger.error(f"Error converting MIDI file to base64: {e}")
        return None

def collect_score_midi_files(score_directory: str) -> Dict[str, str]:
    """
    Collect all MIDI files in a score directory and convert them to base64.
    
    Args:
        score_directory (str): Directory containing the score's MIDI files
        
    Returns:
        Dict[str, str]: Mapping of relative file paths to base64 data URLs
    """
    midi_files = {}
    
    if not os.path.exists(score_directory):
        logger.warning(f"Score directory not found: {score_directory}")
        return midi_files
    
    for root, dirs, files in os.walk(score_directory):
        for file in files:
            if file.lower().endswith('.mid'):
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, score_directory)
                
                base64_data = midi_file_to_base64(file_path)
                if base64_data:
                    # Use forward slashes for web compatibility
                    web_relative_path = relative_path.replace(os.sep, '/')
                    midi_files[web_relative_path] = base64_data
                    logger.debug(f"Embedded MIDI file: {web_relative_path}")
    
    logger.info(f"Collected {len(midi_files)} MIDI files for embedding")
    return midi_files

def generate_midi_mapping_script(midi_files: Dict[str, str], base_web_path: str) -> str:
    """
    Generate JavaScript code to map web URLs to embedded base64 data.
    
    Args:
        midi_files (Dict[str, str]): Mapping of file paths to base64 data
        base_web_path (str): Base web path used in the original URLs
        
    Returns:
        str: JavaScript code for the MIDI mapping
    """
    mapping_entries = []
    
    for file_path, base64_data in midi_files.items():
        # Create the original web URL pattern
        original_url = f"{base_web_path.rstrip('/')}/{file_path}"
        mapping_entries.append(f"    '{original_url}': '{base64_data}'")
    
    # Create the join string outside the f-string to avoid backslash issues
    mapping_entries_joined = ',\n'.join(mapping_entries)
    
    js_code = f"""
// MIDI file mapping for standalone talking score
window.EMBEDDED_MIDI_FILES = {{
{mapping_entries_joined}
}};

// Override MIDIjs.play to use embedded data
if (typeof MIDIjs !== 'undefined') {{
    const originalPlay = MIDIjs.play;
    MIDIjs.play = function(url) {{
        // Extract the base URL without query parameters
        const baseUrl = url.split('?')[0];
        
        // Check if we have an embedded version
        if (window.EMBEDDED_MIDI_FILES[baseUrl]) {{
            console.log('Using embedded MIDI data for:', baseUrl);
            return originalPlay.call(this, window.EMBEDDED_MIDI_FILES[baseUrl]);
        }}
        
        // Check if the URL contains query parameters and try to match the base MIDI file
        for (const [embeddedUrl, embeddedData] of Object.entries(window.EMBEDDED_MIDI_FILES)) {{
            if (url.includes(embeddedUrl.split('/').pop())) {{
                console.log('Using embedded MIDI data (matched by filename):', embeddedUrl);
                return originalPlay.call(this, embeddedData);
            }}
        }}
        
        console.warn('No embedded MIDI data found for URL:', url);
        return originalPlay.call(this, url);
    }};
}}
"""
    
    return js_code