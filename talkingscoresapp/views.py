"""
Django Views for Talking Scores Application

This module handles all web requests for the Talking Scores application, including
file uploads, options processing, score generation, and MIDI file serving.

Key Components:
- File upload and URL processing for MusicXML files
- Score options form handling with color customization
- MIDI file generation and serving
- Error handling and user notifications
"""

import os
import sys
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django import forms
from django.http import HttpResponse, FileResponse
from django.template import loader
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib import messages
from django.utils.text import slugify

from talkingscores.settings import BASE_DIR, MEDIA_ROOT
from lib.midiHandler import MidiHandler
from talkingscoreslib import Music21TalkingScore
from talkingscoresapp.models import TSScore, TSScoreState

logger = logging.getLogger("TSScore")

# Constants
ACCESSIBLE_COLOR_PALETTE = [
    '#E6194B',  # Red
    '#3CB44B',  # Green
    '#4363D8',  # Blue
    '#F58231',  # Orange
    '#911EB4',  # Purple
    '#46F0F0',  # Cyan
    '#FABEBE',  # Pink
    '#008080',  # Teal
    '#F032E6',  # Magenta
    '#FFE119',  # Yellow
    '#BFEF45',  # Lime
    '#9A6324',  # Brown
]

COLOR_PROFILES = {
    "default": {
        "C": "#FF0000", "D": "#A52A2A", "E": "#808080", "F": "#0000FF",
        "G": "#000000", "A": "#FFFF00", "B": "#008000"
    },
    "classic": {
        "C": "#FF0000", "D": "#FFA500", "E": "#FFFF00", "F": "#008000",
        "G": "#0000FF", "A": "#4B0082", "B": "#EE82EE"
    }
}


class MusicXMLSubmissionForm(forms.Form):
    """Form for uploading MusicXML files or providing URLs."""
    
    filename = forms.FileField(
        label='MusicXML file',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        required=False
    )
    url = forms.URLField(
        label='URL to MusicXML file',
        widget=forms.URLInput(attrs={'class': 'form-control'}),
        required=False
    )

    def clean(self):
        """Validate that exactly one of filename or url is provided."""
        cleaned_data = super().clean()
        filename = cleaned_data.get("filename")
        url = cleaned_data.get("url")

        if not filename and not url:
            raise forms.ValidationError(
                "Please upload a MusicXML file or provide a URL.",
                code='required'
            )

        if filename and url:
            raise forms.ValidationError(
                "Please provide either a file or a URL, not both.",
                code='conflict'
            )

        return cleaned_data


class TalkingScoreGenerationOptionsForm(forms.Form):
    """Form for configuring talking score generation options."""
    
    # Playback options
    chk_play_all = forms.BooleanField(required=False)
    chk_play_selected = forms.BooleanField(required=False)
    chk_play_unselected = forms.BooleanField(required=False)
    
    # Content options
    chk_include_rests = forms.BooleanField(required=False)
    chk_include_ties = forms.BooleanField(required=False)
    chk_include_arpeggios = forms.BooleanField(required=False)
    chk_describe_chords = forms.BooleanField(required=False)
    chk_include_dynamics = forms.BooleanField(required=False)
    chk_disable_all_coloring = forms.BooleanField(required=False)
    chk_enharmonic_conversion = forms.BooleanField(required=False)
    
    # Layout and display options
    bars_at_a_time = forms.ChoiceField(
        choices=(('1', 1), ('2', 2), ('4', 4), ('8', 8)),
        initial=4,
        label="Bars at a time"
    )
    beat_division = forms.CharField(widget=forms.Select, required=False)
    
    # Description options
    pitch_description = forms.CharField(widget=forms.Select, required=False)
    rhythm_description = forms.CharField(widget=forms.Select, required=False)
    dot_position = forms.CharField(widget=forms.Select, required=False)
    rhythm_announcement = forms.CharField(widget=forms.Select, required=False)
    octave_description = forms.CharField(widget=forms.Select, required=False)
    octave_position = forms.CharField(widget=forms.Select, required=False)
    octave_announcement = forms.CharField(widget=forms.Select, required=False)
    accidental_style = forms.CharField(widget=forms.Select, required=False)
    key_signature_accidentals = forms.CharField(widget=forms.Select, required=False)
    
    # Color options
    colour_position = forms.CharField(widget=forms.Select, required=False)
    chk_colour_pitch = forms.BooleanField(required=False)
    chk_colour_rhythm = forms.BooleanField(required=False)
    chk_colour_octave = forms.BooleanField(required=False)


class NotifyEmailForm(forms.Form):
    """Form for email notifications about score processing errors."""
    
    notify_email = forms.EmailField()


def send_error_email(error_message):
    """
    Send error notification email to the development team.
    
    Args:
        error_message (str): Description of the error that occurred
    """
    # Only send emails in production environment
    if 'EMAIL_PASSWORD' not in os.environ:
        return
        
    try:
        msg = MIMEMultipart()
        password = os.environ['EMAIL_PASSWORD']
        msg['From'] = "talkingscores@gmail.com"
        msg['To'] = "talkingscores@gmail.com"
        msg['Subject'] = "Talking Scores Error"

        msg.attach(MIMEText(error_message, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com: 587')
        server.starttls()
        server.login(msg['From'], password)
        server.sendmail(msg['From'], msg['To'], msg.as_string())
        server.quit()
        
        logger.info("Error notification email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send error notification email: {e}")


def generate_rhythm_colors_for_score(rhythm_range):
    """
    Generate color assignments for rhythm types found in the score.
    
    Args:
        rhythm_range (list): List of rhythm names found in the score
        
    Returns:
        list: List of dictionaries with rhythm info and assigned colors
    """
    rhythms_with_colors = []
    
    for index, rhythm_name in enumerate(rhythm_range):
        default_color = ACCESSIBLE_COLOR_PALETTE[index % len(ACCESSIBLE_COLOR_PALETTE)]
        rhythms_with_colors.append({
            'name': rhythm_name,
            'id_name': slugify(rhythm_name),
            'default_color': default_color
        })
    
    return rhythms_with_colors


def extract_color_settings_from_request(request):
    """
    Extract and process color settings from the POST request.
    
    Args:
        request: Django HTTP request object
        
    Returns:
        dict: Processed color settings
    """
    selected_profile = request.POST.get("colorProfile", "default")
    
    if selected_profile == "custom":
        # Extract custom colors from form fields
        figure_note_colours = {
            key.split('_')[1]: value
            for key, value in request.POST.items()
            if key.startswith('color_') 
            and not key.startswith('color_rhythm_')
            and not key.startswith('color_octave_')
        }
    else:
        # Use predefined color profile
        figure_note_colours = COLOR_PROFILES.get(selected_profile, {})
    
    # Extract advanced rhythm colors
    advanced_rhythm_colours = {
        slugify(key.replace('color_rhythm_', '')): value
        for key, value in request.POST.items()
        if key.startswith('color_rhythm_')
    }
    
    # Extract advanced octave colors
    advanced_octave_colours = {
        key.replace('color_octave_', ''): value
        for key, value in request.POST.items()
        if key.startswith('color_octave_')
    }
    
    return {
        'figure_note_colours': figure_note_colours,
        'advanced_rhythm_colours': advanced_rhythm_colours,
        'advanced_octave_colours': advanced_octave_colours
    }


def build_options_data_from_request(request):
    """
    Build the complete options data dictionary from the POST request.
    
    Args:
        request: Django HTTP request object
        
    Returns:
        dict: Complete options configuration
    """
    color_settings = extract_color_settings_from_request(request)
    
    options_data = {
        # Layout options
        "bars_at_a_time": int(request.POST.get("bars_at_a_time", 2)),
        "beat_division": request.POST.get("beat_division"),
        
        # Playback options
        "play_all": "chk_playAll" in request.POST,
        "play_selected": "chk_playSelected" in request.POST,
        "play_unselected": "chk_playUnselected" in request.POST,
        "instruments": [int(i) for i in request.POST.getlist("instruments")],
        
        # Description options
        "pitch_description": request.POST.get("pitch_description", "noteName"),
        "rhythm_description": request.POST.get("rhythm_description", "british"),
        "dot_position": request.POST.get("dot_position", "before"),
        "rhythm_announcement": request.POST.get("rhythm_announcement", "onChange"),
        "octave_description": request.POST.get("octave_description", "name"),
        "octave_position": request.POST.get("octave_position", "before"),
        "octave_announcement": request.POST.get("octave_announcement", "onChange"),
        "accidental_style": request.POST.get("accidental_style", "words"),
        "key_signature_accidentals": request.POST.get("key_signature_accidentals", "applied"),
        "repetition_mode": request.POST.get("repetition_mode", "learning"),
        
        # Content inclusion options
        "include_rests": "chk_include_rests" in request.POST,
        "include_ties": "chk_include_ties" in request.POST,
        "include_arpeggios": "chk_include_arpeggios" in request.POST,
        "describe_chords": "chk_describe_chords" in request.POST,
        "include_dynamics": "chk_include_dynamics" in request.POST,
        "enharmonic_conversion": "chk_enharmonic_conversion" in request.POST,
        
        # Color options
        "colour_position": request.POST.get("colour_style", "none"),
        "colour_pitch": "chk_colourPitch" in request.POST,
        "rhythm_colour_mode": request.POST.get("rhythm_colour_mode", "none"),
        "octave_colour_mode": request.POST.get("octave_colour_mode", "none"),
        "disable_all_coloring": "chk_disable_all_coloring" in request.POST,
        
        # Color settings from extracted data
        **color_settings
    }
    
    return options_data


def validate_instrument_selection(request, form, score_info):
    """
    Validate that at least one instrument is selected.
    
    Args:
        request: Django HTTP request object
        form: Form instance to add errors to
        score_info: Score information dictionary
        
    Returns:
        tuple: (is_valid, instruments_list, updated_score_info)
    """
    instruments = [int(i) for i in request.POST.getlist("instruments")]
    
    if not instruments:
        form.add_error(None, "Please select at least one instrument to describe.")
        
        # Prepare rhythm colors for re-rendering the form
        if score_info.get('rhythm_range'):
            score_info['rhythm_range'] = generate_rhythm_colors_for_score(
                score_info['rhythm_range']
            )
        
        return False, instruments, score_info
    
    return True, instruments, score_info


def process(request, id, filename):
    """
    Display the processing page while score generation is in progress.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the MusicXML file
        
    Returns:
        HttpResponse: Rendered processing page
    """
    template = loader.get_template('processing.html')
    context = {'id': id, 'filename': filename}
    return HttpResponse(template.render(context, request))


def score(request, id, filename):
    """
    Display the generated talking score or redirect to appropriate page.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the MusicXML file
        
    Returns:
        HttpResponse: Rendered score or redirect response
    """
    score_obj = TSScore(id=id, filename=filename)
    current_state = score_obj.state()

    if current_state == TSScoreState.AWAITING_OPTIONS:
        return redirect('options', id, filename)
    elif current_state == TSScoreState.FETCHING:
        messages.error(request, "The requested score could not be found. It may have expired.")
        return redirect('index')
    else:
        # Generate HTML dynamically
        try:
            html_content = score_obj.html()
            return HttpResponse(html_content)
        except Exception as e:
            logger.exception(f"Unable to process score: {request.get_host()}{reverse('score', args=[id, filename])}")
            return redirect('error', id, filename)


def midi(request, id, filename):
    """
    Serve MIDI files for audio playback.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the source MusicXML file
        
    Returns:
        FileResponse: MIDI file or 404 error
    """
    midi_handler = MidiHandler(request, id, filename)
    midi_file_path = midi_handler.get_or_make_midi_file()
    
    if os.path.exists(midi_file_path):
        file_response = FileResponse(open(midi_file_path, "rb"))
        file_response['Access-Control-Allow-Origin'] = '*'
        file_response['X-Robots-Tag'] = "noindex"
        return file_response
    else:
        logger.error(f"MIDI file not found at path: {midi_file_path}")
        return HttpResponse("MIDI file not found.", status=404)


def error(request, id, filename):
    """
    Display error page and handle error notifications.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the MusicXML file
        
    Returns:
        HttpResponse: Rendered error page
    """
    if request.method == 'POST':
        form = NotifyEmailForm(request.POST)
        if form.is_valid():
            notification_message = (
                f"Notifications about score http://{request.get_host()}"
                f"{reverse('score', args=[id, filename])} should go to "
                f"{form.cleaned_data['notify_email']}"
            )
            logger.error(notification_message)
            send_error_email(notification_message)
        else:
            logger.warning(f"Invalid notification form: {form.errors}")
    else:
        form = NotifyEmailForm()

    template = loader.get_template('error.html')
    context = {'id': id, 'filename': filename, 'form': form}
    return HttpResponse(template.render(context, request))


def options(request, id, filename):
    """
    Handle score options configuration.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the MusicXML file
        
    Returns:
        HttpResponse: Rendered options page or redirect to processing
    """
    try:
        score_obj = TSScore(id=id, filename=filename)
        data_path = score_obj.get_data_file_path()
        options_path = data_path + '.opts'
        
        logger.info(f"Reading score {data_path}")
        score_info = score_obj.info()
        
    except Exception as e:
        logger.exception(f"Unable to process score (before options screen!): {request.get_host()}{reverse('score', args=[id, filename])}")
        return redirect('error', id, filename)

    if request.method == 'POST':
        return handle_options_post_request(request, id, filename, score_info, options_path)
    else:
        return handle_options_get_request(request, score_info)


def handle_options_post_request(request, id, filename, score_info, options_path):
    """
    Handle POST request for options form submission.
    
    Args:
        request: Django HTTP request object
        id: Unique identifier for the score
        filename: Name of the MusicXML file
        score_info: Score information dictionary
        options_path: Path to save options file
        
    Returns:
        HttpResponse: Form with errors or redirect to processing
    """
    form = TalkingScoreGenerationOptionsForm(request.POST)
    
    # Validate instrument selection
    is_valid, instruments, updated_score_info = validate_instrument_selection(
        request, form, score_info
    )
    
    if not is_valid:
        context = {'form': form, 'score_info': updated_score_info}
        return render(request, 'options.html', context)
    
    # Build and save options data
    options_data = build_options_data_from_request(request)
    
    try:
        with open(options_path, "w") as options_file:
            json.dump(options_data, options_file)
        logger.info(f"Options saved to {options_path}")
    except Exception as e:
        logger.error(f"Failed to save options to {options_path}: {e}")
        form.add_error(None, "Failed to save options. Please try again.")
        context = {'form': form, 'score_info': score_info}
        return render(request, 'options.html', context)

    return redirect('process', id, filename)


def handle_options_get_request(request, score_info):
    """
    Handle GET request for options form display.
    
    Args:
        request: Django HTTP request object
        score_info: Score information dictionary
        
    Returns:
        HttpResponse: Rendered options form
    """
    # Prepare rhythm colors for display
    if score_info.get('rhythm_range'):
        score_info['rhythm_range'] = generate_rhythm_colors_for_score(
            score_info['rhythm_range']
        )

    form = TalkingScoreGenerationOptionsForm()
    context = {'form': form, 'score_info': score_info}
    return render(request, 'options.html', context)


def index(request):
    """
    Handle the main page for file upload and URL submission.
    
    Args:
        request: Django HTTP request object
        
    Returns:
        HttpResponse: Rendered index page or redirect to score
    """
    if request.method == 'POST':
        return handle_index_post_request(request)
    else:
        return handle_index_get_request(request)


def handle_index_post_request(request):
    """
    Handle POST request for file upload or URL submission.
    
    Args:
        request: Django HTTP request object
        
    Returns:
        HttpResponse: Redirect to score or back to index with errors
    """
    form = MusicXMLSubmissionForm(request.POST, request.FILES)
    
    if form.is_valid():
        try:
            score = None
            uploaded_file = form.cleaned_data.get('filename')
            url = form.cleaned_data.get('url')

            if uploaded_file:
                uploaded_file.seek(0)  # Ensure file pointer is at beginning
                score = TSScore.from_uploaded_file(uploaded_file)
            elif url:
                score = TSScore.from_url(url)
            
            if score:
                logger.info(f"Successfully processed score: {score.id}/{score.filename}")
                return redirect('score', id=score.id, filename=score.filename)

        except Exception as e:
            error_message = (
                "The MusicXML file could not be processed. "
                "Please ensure it is a valid file and try again."
            )
            logger.error(f"File Processing Error: {e}", exc_info=True)
            messages.error(request, error_message)
    else:
        # Add form validation errors as messages
        for field, error_list in form.errors.items():
            for error in error_list:
                messages.error(request, error)
    
    return redirect('index')


def handle_index_get_request(request):
    """
    Handle GET request for index page display.
    
    Args:
        request: Django HTTP request object
        
    Returns:
        HttpResponse: Rendered index page
    """
    form = MusicXMLSubmissionForm()
    
    # Get example scores for display
    example_scores_path = os.path.join(BASE_DIR, 'talkingscoresapp', 'static', 'data')
    example_scores = []
    
    if os.path.exists(example_scores_path):
        example_scores = [
            f for f in os.listdir(example_scores_path)
            if f.endswith('.html')
        ]
    
    context = {'form': form, 'example_scores': example_scores}
    return render(request, 'index.html', context)


def change_log(request):
    """Display the change log page."""
    template = loader.get_template('change-log.html')
    context = {}
    return HttpResponse(template.render(context, request))


def contact_us(request):
    """Display the contact us page."""
    template = loader.get_template('contact-us.html')
    context = {}
    return HttpResponse(template.render(context, request))


def privacy_policy(request):
    """Display the privacy policy page."""
    template = loader.get_template('privacy-policy.html')
    context = {}
    return HttpResponse(template.render(context, request))