from django import forms
from django.http import HttpResponse, FileResponse
from django.template import loader
from django.shortcuts import redirect, render # Import render
from django.urls import reverse
from django.contrib import messages
from django.utils.text import slugify
import os
import sys
import json
import logging
import logging.handlers
import logging.config
from talkingscores.settings import BASE_DIR, MEDIA_ROOT
from lib.midiHandler import *

from talkingscoreslib import Music21TalkingScore

from talkingscoresapp.models import TSScore, TSScoreState

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

logger = logging.getLogger("TSScore")


class MusicXMLSubmissionForm(forms.Form):
    filename = forms.FileField(label='MusicXML file', widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
                               required=False)
    url = forms.URLField(label='URL to MusicXML file', widget=forms.URLInput(attrs={'class': 'form-control'}),
                         required=False)

    def clean(self):
        # This method validates the form as a whole.
        cleaned_data = super().clean()
        filename = cleaned_data.get("filename")
        url = cleaned_data.get("url")

        # Raise an error if both fields are empty.
        if not filename and not url:
            raise forms.ValidationError(
                "Please upload a MusicXML file or provide a URL.", code='required'
            )

        # Raise an error if both fields are filled.
        if filename and url:
            raise forms.ValidationError(
                "Please provide either a file or a URL, not both.", code='conflict'
            )

        return cleaned_data


class MusicXMLUploadForm(forms.Form):
    filename = forms.FileField(label='MusicXML file', widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))


class TalkingScoreGenerationOptionsForm(forms.Form):
    # Note: The 'instruments' field is intentionally omitted here
    # because we handle it directly from the request for robustness.
    chk_playAll = forms.BooleanField(required=False)
    chk_playSelected = forms.BooleanField(required=False)
    chk_playUnselected = forms.BooleanField(required=False)

    bars_at_a_time = forms.ChoiceField(choices=(('1', 1), ('2', 2), ('4', 4), ('8', 8)), initial=4,
                                       label="Bars at a time")

    pitch_description = forms.CharField(widget=forms.Select, required=False)
    rhythm_description = forms.CharField(widget=forms.Select, required=False)
    dot_position = forms.CharField(widget=forms.Select, required=False)
    rhythm_announcement = forms.CharField(widget=forms.Select, required=False)
    octave_description = forms.CharField(widget=forms.Select, required=False)
    octave_position = forms.CharField(widget=forms.Select, required=False)
    octave_announcement = forms.CharField(widget=forms.Select, required=False)

    colour_position = forms.CharField(widget=forms.Select, required=False)
    chk_colourPitch = forms.BooleanField(required=False)
    chk_colourRhythm = forms.BooleanField(required=False)
    chk_colourOctave = forms.BooleanField(required=False)


class NotifyEmailForm(forms.Form):
    notify_email = forms.EmailField()


def send_error_email(error_message):
    if 'EMAIL_PASSWORD' in os.environ:  # don't try to send an email from a development environment
        msg = MIMEMultipart()
        password = os.environ['EMAIL_PASSWORD']  # in pythonanywhere this can be set in wsgi.py
        msg['From'] = "talkingscores@gmail.com"
        msg['To'] = "talkingscores@gmail.com"
        msg['Subject'] = "Talking Scores Error"

        msg.attach(MIMEText(error_message, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com: 587')
        server.starttls()
        server.login(msg['From'], password)
        server.sendmail(msg['From'], msg['To'], msg.as_string())
        server.quit()


def process(request, id, filename):
    template = loader.get_template('processing.html')
    context = {'id': id, 'filename': filename}
    return HttpResponse(template.render(context, request))


def score(request, id, filename):
    score_obj = TSScore(id=id, filename=filename)

    if score_obj.state() == TSScoreState.AWAITING_OPTIONS:
        return redirect('options', id, filename)
    elif score_obj.state() == TSScoreState.FETCHING:
        return redirect('index')
    else:
        try:
            html = score_obj.html()
            return HttpResponse(html)
        except Exception:
            logger.exception("Unable to process score: http://%s%s " % (request.get_host(), reverse('score', args=[id, filename])))
            # The redirect to 'error' will handle showing the error page.
            # Code after a return or redirect statement is unreachable.
            return redirect('error', id, filename)


def midi(request, id, filename):
    # 'filename' is now the source XML filename (e.g., Liebestraum.musicxml)
    # The specific MIDI details are in the request's query parameters (request.GET)
    mh = MidiHandler(request, id, filename)
    
    midi_file_path = mh.get_or_make_midi_file()
    
    if os.path.exists(midi_file_path):
        fr = FileResponse(open(midi_file_path, "rb"))
        fr['Access-Control-Allow-Origin'] = '*'
        fr['X-Robots-Tag'] = "noindex"
        return fr
    else:
        logger.error(f"MIDI file not found at path: {midi_file_path}")
        return HttpResponse("MIDI file not found.", status=404)


def error(request, id, filename):
    # The error email should be triggered when the exception occurs, not on page load.
    # Moving the send_error_email call to the 'except' block in the 'score' view is recommended.
    # For now, I've left the POST handling for the notification form.
    if request.method == 'POST':
        form = NotifyEmailForm(request.POST)
        if form.is_valid():
            notification_message = "Notifications about score http://%s%s should go to %s" % (
                request.get_host(), reverse('score', args=[id, filename]), form.cleaned_data['notify_email'])
            logger.error(notification_message)
            send_error_email(notification_message)
        else:
            logger.warn(str(form.errors))
    else:
        form = NotifyEmailForm()

    template = loader.get_template('error.html')
    context = {'id': id, 'filename': filename, 'form': form}
    return HttpResponse(template.render(context, request))

# ... (change_log, contact_us, privacy_policy views remain the same) ...
def change_log(request):
    template = loader.get_template('change-log.html')
    context = {}
    return HttpResponse(template.render(context, request))


def contact_us(request):
    template = loader.get_template('contact-us.html')
    context = {}
    return HttpResponse(template.render(context, request))


def privacy_policy(request):
    template = loader.get_template('privacy-policy.html')
    context = {}
    return HttpResponse(template.render(context, request))


# View for the a particular score - REFACTORED AND CORRECTED
def options(request, id, filename):
    try:
        score_obj = TSScore(id=id, filename=filename)
        data_path = score_obj.get_data_file_path()
        options_path = data_path + '.opts'
        logger.info("Reading score %s" % data_path)
        score_info = score_obj.info()
    except Exception:
        logger.exception("Unable to process score (before options screen!): http://%s%s " % (request.get_host(), reverse('score', args=[id, filename])))
        return redirect('error', id, filename)

    if request.method == 'POST':
        # 1. Get the list of selected instruments from the form submission.
        instruments = [int(i) for i in request.POST.getlist("instruments")]

        # 2. VALIDATION FIRST: Check if any instruments were selected.
        if not instruments:
            form = TalkingScoreGenerationOptionsForm(request.POST)
            form.add_error(None, "Please select at least one instrument to describe.")
            # We need to pre-process the rhythm range here too for the error page to render correctly
            if score_info.get('rhythm_range'):
                rhythms_with_colors = []
                for i, rhythm_name in enumerate(score_info['rhythm_range']):
                    color_val = (i + 1) * 203040
                    default_color = f"#{color_val:06x}"
                    rhythms_with_colors.append({
                        'name': rhythm_name,
                        'id_name': slugify(rhythm_name),
                        'default_color': default_color
                    })
                score_info['rhythm_range'] = rhythms_with_colors
            context = {'form': form, 'score_info': score_info}
            return render(request, 'options.html', context)

        # 3. If validation passes, build the options dictionary.
        # Handle color profiles
        color_profiles = {
            "default": {"C": "#FF0000", "D": "#A52A2A", "E": "#808080", "F": "#0000FF", "G": "#000000", "A": "#FFFF00", "B": "#008000"},
            "classic": {"C": "#FF0000", "D": "#FFA500", "E": "#FFFF00", "F": "#008000", "G": "#0000FF", "A": "#4B0082", "B": "#EE82EE"}
        }
        selected_profile = request.POST.get("colorProfile", "default")
        figure_note_colours = {}
        if selected_profile == "custom":
            figure_note_colours = {key.split('_')[1]: val for key, val in request.POST.items() if key.startswith('color_') and not key.startswith('color_rhythm_') and not key.startswith('color_octave_')}
        else:
            figure_note_colours = color_profiles.get(selected_profile, {})

        # Dynamically build the advanced color dictionaries from the request
        advanced_rhythm_colours = {slugify(key.replace('color_rhythm_', '')): value
                                 for key, value in request.POST.items()
                                 if key.startswith('color_rhythm_')}

        advanced_octave_colours = {key.replace('color_octave_', ''): value
                                 for key, value in request.POST.items()
                                 if key.startswith('color_octave_')}
        
        # Build the complete options dictionary
        options_data = {
            "bars_at_a_time": int(request.POST.get("bars_at_a_time", 2)),
            "play_all": "chk_playAll" in request.POST,
            "play_selected": "chk_playSelected" in request.POST,
            "play_unselected": "chk_playUnselected" in request.POST,
            "instruments": instruments,
            "pitch_description": request.POST.get("pitch_description", "noteName"),
            "rhythm_description": request.POST.get("rhythm_description", "british"),
            "dot_position": request.POST.get("dot_position", "before"),
            "rhythm_announcement": request.POST.get("rhythm_announcement", "onChange"),
            "octave_description": request.POST.get("octave_description", "name"),
            "octave_position": request.POST.get("octave_position", "before"),
            "octave_announcement": request.POST.get("octave_announcement", "onChange"),
            "repetition_mode": request.POST.get("repetition_mode", "learning"),
            "colour_position": request.POST.get("colour_style", "none"),
            
            # --- FIX: Independent colouring settings ---
            "colour_pitch": "chk_colourPitch" in request.POST,
            "rhythm_colour_mode": request.POST.get("rhythm_colour_mode", "none"),
            "octave_colour_mode": request.POST.get("octave_colour_mode", "none"),
            
            # --- FIX: Keep advanced dictionaries ---
            "advanced_rhythm_colours": advanced_rhythm_colours,
            "advanced_octave_colours": advanced_octave_colours,
            "figureNoteColours": figure_note_colours
        }

        # 4. Write the new options to the .opts file.
        with open(options_path, "w") as options_fh:
            json.dump(options_data, options_fh)

        # 5. CLEAR THE CACHE: Delete the old HTML file to force regeneration.
        html_cache_path = score_obj.get_data_file_path(
            root=os.path.join(STATIC_ROOT, 'data')
        ) + '.html'

        if os.path.exists(html_cache_path):
            try:
                os.remove(html_cache_path)
                logger.info(f"Cleared cached HTML file at {html_cache_path}")
            except OSError as e:
                logger.error(f"Error removing cached file {html_cache_path}: {e}")

        # 6. REDIRECT: Send the user to the processing page.
        return redirect('process', id, filename)

    else:  # This block runs for GET requests.
        # --- START: Pre-calculate colors for the template ---
        if score_info.get('rhythm_range'):
            rhythms_with_colors = []
            for i, rhythm_name in enumerate(score_info['rhythm_range']):
                color_val = (i + 1) * 203040
                default_color = f"#{color_val:06x}"
                rhythms_with_colors.append({
                    'name': rhythm_name,
                    'id_name': slugify(rhythm_name),
                    'default_color': default_color
                })
            score_info['rhythm_range'] = rhythms_with_colors
        # --- END: Pre-calculation logic ---

        form = TalkingScoreGenerationOptionsForm()
        context = {'form': form, 'score_info': score_info}
        return render(request, 'options.html', context)




# View for the main page
def index(request):
    if request.method == 'POST':
        # Instantiate the form with POST and FILES data.
        form = MusicXMLSubmissionForm(request.POST, request.FILES)
        
        # The form's clean() method handles all validation.
        if form.is_valid():
            try:
                score = None
                # We can now safely access cleaned_data.
                uploaded_file = form.cleaned_data.get('filename')
                url = form.cleaned_data.get('url')

                if uploaded_file:
                    # --- THIS IS THE FIX ---
                    # Rewind the file stream to the beginning before processing.
                    uploaded_file.seek(0)
                    # ----------------------
                    score = TSScore.from_uploaded_file(uploaded_file)
                elif url:
                    score = TSScore.from_url(url)
                
                # On success, redirect to the score page.
                if score:
                    return redirect('score', id=score.id, filename=score.filename)

            except Exception as ex:
                # Catch any errors during file processing and display them.
                error_message = "The MusicXML file could not be processed. Please ensure it is a valid file and try again."
                logger.error(f"File Processing Error: {ex}", exc_info=True)
                messages.error(request, error_message)
                # Always redirect back to the index page
                return redirect('index')
        else:
            # If the form itself is invalid, add the errors as messages
            for field, error_list in form.errors.items():
                for error in error_list:
                    messages.error(request, error)
            # Always redirect back to the index page
            return redirect('index')

    else: # GET request
        form = MusicXMLSubmissionForm()

    example_scores = [f for f in os.listdir(os.path.join(BASE_DIR, 'talkingscoresapp', 'static', 'data')) if f.endswith('.html')]
    context = {'form': form, 'example_scores': example_scores}
    return render(request, 'index.html', context)