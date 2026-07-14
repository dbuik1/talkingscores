# Talking Scores

An accessible web application that converts MusicXML files into spoken descriptions with synchronised MIDI playback — designed for blind, visually impaired, and print-impaired musicians.

This is an independently maintained fork of the original [Talking Scores project](https://github.com/bentimms/talkingscores) by Ben Timms. This fork is developed by David Buik and hosted at [talkingscores.davidbuik.com](https://talkingscores.davidbuik.com).

Contact: [contact@davidbuik.com](mailto:contact@davidbuik.com)

## Licence

MIT — see [LICENCE.txt](LICENCE.txt). Original work Copyright 2019 Ben Timms; modifications Copyright 2025-2026 David Buik.

## Prerequisites

1. A working Python 3 installation

## Installation

1. Create a virtual environment for the python requirements
   ``` 
   python -m venv .talkingscore-env
   ```
1. Install the required python modules
   ``` 
   pip install -r requirements
   ```

## Running a server

1. Ensure the virtual environment is active (you should see `(.talkingscores-env)` in your prompt).
    ```
    source .talkingscores-env/bin/activate
    ```
1. Run the local Django server.
    ```
    python ./manage.py runserver
    ```


