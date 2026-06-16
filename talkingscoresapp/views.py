from django import forms
from django.http import HttpResponse, FileResponse, JsonResponse
from django.template import loader
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib import messages
from django.utils.text import slugify
from pathvalidate import sanitize_filename
import os
import json
import logging
import re
import tempfile
from urllib.parse import urlparse
from talkingscores.settings import BASE_DIR
from lib.midiHandler import MidiHandler

from talkingscoresapp.models import TSScore, TSScoreState
from talkingscoresapp.models import remove_file_quietly

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

logger = logging.getLogger("TSScore")

ALLOWED_MUSICXML_EXTENSIONS = ('.xml', '.musicxml', '.mxl')
MAX_UPLOADED_SCORE_BYTES = 10 * 1024 * 1024

ACCESSIBLE_PALETTE = [
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


def safe_export_basename(filename):
    base_name = os.path.splitext(os.path.basename(filename))[0]
    return slugify(sanitize_filename(base_name)) or "talking-score"


def clean_export_theme(theme):
    return theme if theme in ("light", "dark") else None


def clean_html_export(html):
    """Remove controls that only work on the Django-served score page."""
    html = re.sub(
        r"\s*<script[^>]+src=['\"][^'\"]*midijs\.net[^'\"]*['\"][^>]*>\s*</script>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"\s*<a[^>]+id=['\"]stop-playback-btn['\"][^>]*>.*?</a>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<div[^>]+class=['\"][^'\"]*\bdownload-controls\b[^'\"]*['\"][^>]*>.*?</div>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<div[^>]+id=['\"]global-controls['\"][^>]*>.*?</div>\s*</div>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<div[^>]+class=['\"][^'\"]*\bplayback-controls\b[^'\"]*['\"][^>]*>.*?</div>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<div[^>]+class=['\"][^'\"]*\bplay-buttons-container\b[^'\"]*['\"][^>]*>.*?</div>\s*</div>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<div[^>]+class=['\"][^'\"]*\binstrument-midi-section\b[^'\"]*['\"][^>]*>.*?</div>\s*</div>\s*</div>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\s*<a[^>]+class=['\"][^'\"]*\blnkPlay\b[^'\"]*['\"][^>]*>.*?</a>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = html.replace("Music segment descriptions and playback", "Music segment descriptions")
    return html


def add_rhythm_colour_defaults(score_info):
    if not score_info.get('rhythm_range'):
        return score_info

    score_info['rhythm_range'] = [
        {
            'name': rhythm_name,
            'id_name': slugify(rhythm_name),
            'default_color': ACCESSIBLE_PALETTE[index % len(ACCESSIBLE_PALETTE)],
        }
        for index, rhythm_name in enumerate(score_info['rhythm_range'])
    ]
    return score_info


def parse_selected_instruments(post_data, instrument_count):
    selected = post_data.getlist("instruments")
    if not selected:
        raise forms.ValidationError("Please select at least one instrument to describe.")

    try:
        instrument_ids = [int(instrument_id) for instrument_id in selected]
    except (TypeError, ValueError):
        raise forms.ValidationError("Invalid instrument selection.")

    valid_ids = set(range(1, instrument_count + 1))
    if any(instrument_id not in valid_ids for instrument_id in instrument_ids):
        raise forms.ValidationError("Invalid instrument selection.")

    return instrument_ids


def validate_midi_query_params(query_params):
    for required_param in ("bsi", "bpi"):
        if query_params.get(required_param) is None:
            raise forms.ValidationError(f"Missing MIDI parameter: {required_param}.")

    integer_params = ("bsi", "bpi", "start", "end", "part", "ins")
    for param in integer_params:
        value = query_params.get(param)
        if value is None:
            continue
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            raise forms.ValidationError(f"Invalid MIDI parameter: {param}.")
        if parsed_value < 0:
            raise forms.ValidationError(f"Invalid MIDI parameter: {param}.")

    tempo_value = query_params.get("t")
    if tempo_value is not None and tempo_value not in ("50", "100", "150"):
        raise forms.ValidationError("Invalid MIDI tempo.")

    click_value = query_params.get("c")
    if click_value is not None and click_value not in ("n", "be"):
        raise forms.ValidationError("Invalid MIDI click setting.")

    selection_value = query_params.get("sel")
    if selection_value is not None and selection_value not in ("all", "sel", "un"):
        raise forms.ValidationError("Invalid MIDI selection.")

    start_value = query_params.get("start")
    end_value = query_params.get("end")
    if (start_value is None) != (end_value is None):
        raise forms.ValidationError("MIDI start and end parameters must be provided together.")
    if start_value is not None and int(start_value) > int(end_value):
        raise forms.ValidationError("MIDI start parameter cannot be after end.")


def get_example_scores():
    example_score_path = os.path.join(BASE_DIR, 'talkingscoresapp', 'static', 'data')
    try:
        return sorted(f for f in os.listdir(example_score_path) if f.endswith('.html'))
    except OSError:
        logger.warning("Could not list example scores from %s", example_score_path)
        return []


def write_json_file_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=os.path.dirname(path),
        delete=False,
    ) as options_file:
        json.dump(data, options_file)
        temp_path = options_file.name
    try:
        os.replace(temp_path, path)
    except OSError:
        remove_file_quietly(temp_path)
        raise


class MusicXMLSubmissionForm(forms.Form):
    filename = forms.FileField(label='MusicXML file', widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xml,.musicxml,.mxl'}),
                               required=False)
    url = forms.URLField(label='URL to MusicXML file', widget=forms.URLInput(attrs={'class': 'form-control'}),
                         required=False)

    def clean_filename(self):
        uploaded_file = self.cleaned_data.get('filename')
        if uploaded_file:
            file_extension = os.path.splitext(uploaded_file.name)[1].lower()
            if file_extension not in ALLOWED_MUSICXML_EXTENSIONS:
                raise forms.ValidationError(
                    f"Invalid file type. Please upload a MusicXML file (.xml, .musicxml, or .mxl)."
                )
            if uploaded_file.size > MAX_UPLOADED_SCORE_BYTES:
                raise forms.ValidationError(
                    "MusicXML file is too large. Please upload a file smaller than 10 MB."
                )
        return uploaded_file

    def clean_url(self):
        url = self.cleaned_data.get('url')
        if url:
            parsed_url = urlparse(url)
            file_extension = os.path.splitext(parsed_url.path)[1].lower()
            if file_extension not in ALLOWED_MUSICXML_EXTENSIONS:
                raise forms.ValidationError(
                    "Invalid URL file type. Please provide a URL ending in .xml, .musicxml, or .mxl."
                )
        return url

    def clean(self):
        cleaned_data = super().clean()
        filename = cleaned_data.get("filename")
        url = cleaned_data.get("url")

        if not filename and not url:
            raise forms.ValidationError(
                "Please upload a MusicXML file or provide a URL.", code='required'
            )

        if filename and url:
            raise forms.ValidationError(
                "Please provide either a file or a URL, not both.", code='conflict'
            )

        return cleaned_data


class MusicXMLUploadForm(forms.Form):
    filename = forms.FileField(label='MusicXML file', widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xml,.musicxml,.mxl'}))


class TalkingScoreGenerationOptionsForm(forms.Form):
    chk_playAll = forms.BooleanField(required=False)
    chk_playSelected = forms.BooleanField(required=False)
    chk_playUnselected = forms.BooleanField(required=False)
    chk_include_rests = forms.BooleanField(required=False)
    chk_include_ties = forms.BooleanField(required=False)
    chk_include_arpeggios = forms.BooleanField(required=False)
    chk_describe_chords = forms.BooleanField(required=False)
    

    bars_at_a_time = forms.ChoiceField(choices=(('1', 1), ('2', 2), ('4', 4), ('8', 8)), initial=4,
                                        label="Bars at a time")

    beat_division = forms.CharField(widget=forms.Select, required=False)

    pitch_description = forms.CharField(widget=forms.Select, required=False)
    rhythm_description = forms.CharField(widget=forms.Select, required=False)
    dot_position = forms.CharField(widget=forms.Select, required=False)
    rhythm_announcement = forms.CharField(widget=forms.Select, required=False)
    octave_description = forms.CharField(widget=forms.Select, required=False)
    octave_position = forms.CharField(widget=forms.Select, required=False)
    octave_announcement = forms.CharField(widget=forms.Select, required=False)

    chk_include_dynamics = forms.BooleanField(required=False)
    accidental_style = forms.CharField(widget=forms.Select, required=False)
    key_signature_accidentals = forms.CharField(widget=forms.Select, required=False)

    colour_position = forms.CharField(widget=forms.Select, required=False)
    chk_colourPitch = forms.BooleanField(required=False)
    chk_colourRhythm = forms.BooleanField(required=False)
    chk_colourOctave = forms.BooleanField(required=False)


class NotifyEmailForm(forms.Form):
    notify_email = forms.EmailField()


def send_error_email(error_message):
    password = os.environ.get('EMAIL_PASSWORD')
    if not password:
        return False

    msg = MIMEMultipart()
    msg['From'] = "talkingscores@gmail.com"
    msg['To'] = "talkingscores@gmail.com"
    msg['Subject'] = "Talking Scores Error"
    msg.attach(MIMEText(error_message, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as server:
            server.starttls()
            server.login(msg['From'], password)
            server.sendmail(msg['From'], msg['To'], msg.as_string())
    except Exception:
        logger.exception("Failed to send Talking Scores error notification email.")
        return False

    return True


def process(request, id, filename):
    score_obj = TSScore(id=id, filename=filename)
    if score_obj.state() == TSScoreState.PROCESSED:
        score_obj.start_background_processing()
    template = loader.get_template('processing.html')
    context = {'id': id, 'filename': filename}
    return HttpResponse(template.render(context, request))


def process_status(request, id, filename):
    score_obj = TSScore(id=id, filename=filename)
    status = score_obj.processing_status()
    if status.get("status") == "complete":
        status["score_url"] = reverse('score', args=[id, filename])
    elif status.get("status") in ("pending", "unknown") and score_obj.state() == TSScoreState.PROCESSED:
        score_obj.start_background_processing()
        status = score_obj.processing_status()
    return JsonResponse(status)


def score(request, id, filename):
    score_obj = TSScore(id=id, filename=filename)

    if score_obj.state() == TSScoreState.AWAITING_OPTIONS:
        return redirect('options', id, filename)
    elif score_obj.state() == TSScoreState.FETCHING:
        messages.error(request, "The requested score could not be found. It may have expired.")
        return redirect('index')
    else:
        try:
            html = score_obj.html()
            return HttpResponse(html)
        except Exception:
            logger.exception("Unable to process score: http://%s%s " % (request.get_host(), reverse('score', args=[id, filename])))
            return redirect('error', id, filename)


def midi(request, id, filename):
    try:
        validate_midi_query_params(request.GET)
    except forms.ValidationError as exc:
        return HttpResponse(exc.messages[0], status=400)

    mh = MidiHandler(request, id, filename)

    try:
        midi_file_path = mh.get_or_make_midi_file()
    except Exception:
        logger.exception("Unable to generate MIDI: http://%s%s" % (request.get_host(), request.get_full_path()))
        return HttpResponse("MIDI generation failed.", status=500)
    
    if os.path.exists(midi_file_path):
        fr = FileResponse(
            open(midi_file_path, "rb"),
            content_type="audio/midi",
            as_attachment=False,
            filename=os.path.basename(midi_file_path),
        )
        fr['Access-Control-Allow-Origin'] = '*'
        fr['X-Robots-Tag'] = "noindex"
        return fr
    else:
        logger.error(f"MIDI file not found at path: {midi_file_path}")
        return HttpResponse("MIDI file not found.", status=404)


def download_html(request, id, filename):
    score_obj = TSScore(id=id, filename=filename)

    if score_obj.state() != TSScoreState.PROCESSED:
        messages.error(request, "The requested score is not ready to download.")
        return redirect('index')

    try:
        export_theme = clean_export_theme(request.GET.get("theme"))
        html = score_obj.html(export_theme=export_theme, export_mode=True)
        response = HttpResponse(
            clean_html_export(html),
            content_type="text/html; charset=utf-8",
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{safe_export_basename(filename)}-talking-score.html"'
        )
        response['X-Robots-Tag'] = "noindex"
        return response
    except Exception:
        logger.exception("Unable to generate HTML download: http://%s%s" % (request.get_host(), request.get_full_path()))
        return redirect('error', id, filename)


def error(request, id, filename):
    if request.method == 'POST':
        form = NotifyEmailForm(request.POST)
        if form.is_valid():
            notification_message = "Notifications about score http://%s%s should go to %s" % (
                request.get_host(), reverse('score', args=[id, filename]), form.cleaned_data['notify_email'])
            logger.error(notification_message)
            send_error_email(notification_message)
        else:
            logger.warning(str(form.errors))
    else:
        form = NotifyEmailForm()

    template = loader.get_template('error.html')
    context = {'id': id, 'filename': filename, 'form': form}
    return HttpResponse(template.render(context, request))


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
        form = TalkingScoreGenerationOptionsForm(request.POST)
        if not form.is_valid():
            add_rhythm_colour_defaults(score_info)
            context = {'form': form, 'score_info': score_info}
            return render(request, 'options.html', context)

        try:
            instruments = parse_selected_instruments(request.POST, len(score_info.get('instruments', [])))
        except forms.ValidationError as exc:
            form.add_error(None, exc)
            add_rhythm_colour_defaults(score_info)
            context = {'form': form, 'score_info': score_info}
            return render(request, 'options.html', context)

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

        options_data = {
            "bars_at_a_time": int(form.cleaned_data.get("bars_at_a_time", 2)),
            "beat_division": request.POST.get("beat_division"),
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
            "include_rests": "chk_include_rests" in request.POST,
            "include_ties": "chk_include_ties" in request.POST,
            "include_arpeggios": "chk_include_arpeggios" in request.POST,
            "describe_chords": "chk_describe_chords" in request.POST,
            "include_dynamics": "chk_include_dynamics" in request.POST,
            "accidental_style": request.POST.get("accidental_style", "words"),
            "repetition_mode": request.POST.get("repetition_mode", "learning"),
            "colour_position": request.POST.get("colour_style", "none"),
            "colour_pitch": "chk_colourPitch" in request.POST,
            "rhythm_colour_mode": request.POST.get("rhythm_colour_mode", "none"),
            "octave_colour_mode": request.POST.get("octave_colour_mode", "none"),
            "key_signature_accidentals": request.POST.get("key_signature_accidentals", "applied"),
            "advanced_rhythm_colours": {slugify(key.replace('color_rhythm_', '')): value for key, value in request.POST.items() if key.startswith('color_rhythm_')},
            "advanced_octave_colours": {key.replace('color_octave_', ''): value for key, value in request.POST.items() if key.startswith('color_octave_')},
            "figureNoteColours": figure_note_colours
        }

        write_json_file_atomic(options_path, options_data)

        score_obj.clear_generated_html_state()
        return redirect('process', id, filename)

    else:
        add_rhythm_colour_defaults(score_info)

        form = TalkingScoreGenerationOptionsForm()
        context = {'form': form, 'score_info': score_info}
        return render(request, 'options.html', context)


def index(request):
    if request.method == 'POST':
        form = MusicXMLSubmissionForm(request.POST, request.FILES)
        
        if form.is_valid():
            try:
                score = None
                uploaded_file = form.cleaned_data.get('filename')
                url = form.cleaned_data.get('url')

                if uploaded_file:
                    uploaded_file.seek(0)
                    score = TSScore.from_uploaded_file(uploaded_file)
                elif url:
                    score = TSScore.from_url(url)
                
                if score:
                    return redirect('score', id=score.id, filename=score.filename)

            except Exception as ex:
                error_message = "The MusicXML file could not be processed. Please ensure it is a valid MusicXML file and try again."
                logger.error(f"File Processing Error: {ex}", exc_info=True)
                messages.error(request, error_message)
                return redirect('index')
        else:
            for field, error_list in form.errors.items():
                for error in error_list:
                    messages.error(request, error)
            return redirect('index')

    else:
        form = MusicXMLSubmissionForm()

    example_scores = get_example_scores()
    context = {'form': form, 'example_scores': example_scores}
    return render(request, 'index.html', context)
