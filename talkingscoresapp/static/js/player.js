/* Playback of the open group, from a MIDI file of that range played in the browser.

   The server sends one file per range of bars holding every part at its written
   speed. Choosing parts, the speed, the metronome click, the balance and
   repeating all happen here, so a range needs only that one file however it is
   played. */
(function () {
    "use strict";

    var DEFAULT_TEMPO = 500000;
    var LOOKAHEAD_SECONDS = 1.2;
    var SCHEDULER_MS = 200;
    var GAP_BEFORE_REPEAT = 0.6;
    var REMEMBERED_RANGES = 4;
    var LATE_TOLERANCE = 0.02;

    /* Reading a standard MIDI file. */

    function unreadable(reason) {
        var error = new Error(reason);
        error.arrived = true;
        return error;
    }

    function Reader(bytes) {
        this.bytes = bytes;
        this.at = 0;
    }

    Reader.prototype.byte = function () {
        return this.bytes[this.at++];
    };

    Reader.prototype.word = function (length) {
        var value = 0;
        for (var i = 0; i < length; i++) {
            value = value * 256 + (this.bytes[this.at++] || 0);
        }
        return value;
    };

    Reader.prototype.variable = function () {
        var value = 0;
        var byte;
        // Four bytes is the most the format allows, and stopping there keeps a
        // corrupt file from producing a negative delta.
        for (var read = 0; read < 4; read++) {
            byte = this.bytes[this.at++];
            if (byte === undefined) {
                throw unreadable("the file ends inside an event");
            }
            value = value * 128 + (byte & 0x7f);
            if (!(byte & 0x80)) {
                return value;
            }
        }
        throw unreadable("a delta time is too long");
    };

    Reader.prototype.text = function (length) {
        var out = "";
        for (var i = 0; i < length; i++) {
            out += String.fromCharCode(this.bytes[this.at++]);
        }
        return out;
    };

    function readTrack(reader, end) {
        var events = [];
        var ticks = 0;
        var running = 0;
        while (reader.at < end) {
            ticks += reader.variable();
            var status = reader.bytes[reader.at];
            if (status & 0x80) {
                reader.at++;
                // Meta and system common events cancel running status; the real-time
                // bytes above them may fall between two events without disturbing it.
                if (status < 0xf0 || status === 0xff) {
                    running = status < 0xf0 ? status : 0;
                } else if (status <= 0xf7) {
                    running = 0;
                }
            } else {
                if (!running) {
                    throw unreadable("an event has no status byte");
                }
                status = running;
            }
            if (status === 0xff) {
                var type = reader.byte();
                var length = reader.variable();
                var after = reader.at + length;
                if (type === 0x51 && length >= 3) {
                    events.push({ ticks: ticks, kind: "tempo", value: reader.word(3) });
                } else if (type === 0x58 && length >= 2) {
                    events.push({
                        ticks: ticks,
                        kind: "time",
                        beats: reader.byte(),
                        unit: Math.pow(2, reader.byte())
                    });
                }
                reader.at = after;
                if (type === 0x2f) {
                    break;
                }
            } else if (status === 0xf0 || status === 0xf7) {
                reader.at += reader.variable();
            } else if (status > 0xf0) {
                // System messages carry no music. Their length is fixed by the status
                // byte, and reading the wrong number of bytes would lose the track.
                reader.at += status === 0xf2 ? 2 : (status === 0xf1 || status === 0xf3 ? 1 : 0);
            } else {
                var command = status & 0xf0;
                var channel = status & 0x0f;
                if (command === 0x90 || command === 0x80) {
                    var note = reader.byte();
                    var velocity = reader.byte();
                    events.push({
                        ticks: ticks,
                        kind: command === 0x90 && velocity > 0 ? "on" : "off",
                        note: note,
                        velocity: velocity,
                        channel: channel
                    });
                } else if (command === 0xc0 || command === 0xd0) {
                    reader.at++;
                } else {
                    reader.at += 2;
                }
            }
        }
        reader.at = end;
        return events;
    }

    function parseMidi(buffer) {
        var reader = new Reader(new Uint8Array(buffer));
        if (reader.bytes.length < 14 || reader.text(4) !== "MThd") {
            throw unreadable("the file does not start with a MIDI header");
        }
        var headerLength = reader.word(4);
        var headerEnd = reader.at + headerLength;
        var format = reader.word(2);
        var trackCount = reader.word(2);
        var division = reader.word(2);
        if (format === 2) {
            // Format 2 tracks are separate pieces, not parts sounding together.
            throw unreadable("the file holds independent sequences");
        }
        if (division & 0x8000 || division === 0) {
            // Frame timing carries no relation to the metronome marks this player follows.
            throw unreadable("the file is timed in frames");
        }
        reader.at = headerEnd;
        var tracks = [];
        for (var i = 0; i < trackCount && reader.at + 8 <= reader.bytes.length; i++) {
            if (reader.text(4) !== "MTrk") {
                break;
            }
            var length = reader.word(4);
            tracks.push(readTrack(reader, Math.min(reader.at + length, reader.bytes.length)));
        }
        if (!tracks.length) {
            throw unreadable("the file holds no tracks");
        }
        return { division: division, tracks: tracks };
    }

    /* Turning ticks into seconds, following the metronome marks in the file. */

    function tempoMap(midi) {
        var changes = [];
        midi.tracks.forEach(function (track) {
            track.forEach(function (event) {
                if (event.kind === "tempo") {
                    changes.push({ ticks: event.ticks, value: event.value });
                }
            });
        });
        changes.sort(function (a, b) { return a.ticks - b.ticks; });
        var points = [{ ticks: 0, seconds: 0, value: DEFAULT_TEMPO }];
        changes.forEach(function (change) {
            var last = points[points.length - 1];
            if (change.ticks <= last.ticks) {
                last.value = change.value;
                return;
            }
            points.push({
                ticks: change.ticks,
                seconds: last.seconds + (change.ticks - last.ticks) * last.value / 1000000 / midi.division,
                value: change.value
            });
        });
        return function (ticks) {
            var point = points[0];
            for (var i = 1; i < points.length && points[i].ticks <= ticks; i++) {
                point = points[i];
            }
            return point.seconds + (ticks - point.ticks) * point.value / 1000000 / midi.division;
        };
    }

    /* The beat the metronome counts, which follows every change of time signature.
       A compound meter is counted in dotted beats, the way players count it. */
    function beatGrid(midi, lastTick) {
        var changes = [];
        midi.tracks.forEach(function (track) {
            track.forEach(function (event) {
                if (event.kind === "time" && event.beats > 0 && event.unit > 0) {
                    changes.push(event);
                }
            });
        });
        changes.sort(function (a, b) { return a.ticks - b.ticks; });
        if (!changes.length || changes[0].ticks > 0) {
            changes.unshift({ ticks: 0, beats: 4, unit: 4 });
        }
        var beats = [];
        changes.forEach(function (change, index) {
            var compound = change.unit >= 8 && change.beats % 3 === 0 && change.beats > 3;
            var step = midi.division * 4 / change.unit * (compound ? 3 : 1);
            var perBar = compound ? change.beats / 3 : change.beats;
            var until = index + 1 < changes.length ? changes[index + 1].ticks : lastTick;
            var counted = 0;
            for (var ticks = change.ticks; ticks < until; ticks += step) {
                beats.push({ ticks: ticks, strong: counted % perBar === 0 });
                counted++;
            }
        });
        return beats;
    }

    /* The notes of every part, in the order the reading page names them, with the
       click track alongside. */

    function collect(midi, expectedParts) {
        var seconds = tempoMap(midi);
        // The written file stops at the last note, and the end-of-track mark that
        // follows it sits a beat further on, so neither says where the range ends.
        // The closing speed the server writes on the final barline does.
        var lastTick = 0;
        midi.tracks.forEach(function (track) {
            track.forEach(function (event) {
                lastTick = Math.max(lastTick, event.ticks);
            });
        });

        function held(started, endTicks) {
            return {
                start: seconds(started.ticks),
                end: seconds(Math.max(endTicks, started.ticks)),
                note: started.note,
                velocity: started.velocity,
                percussion: started.channel === 9
            };
        }

        var tracks = midi.tracks.map(function (track) {
            var notes = [];
            var sounding = {};
            track.forEach(function (event) {
                var key = event.channel + ":" + event.note;
                if (event.kind === "on") {
                    // Two voices in one part can hold the same pitch at once.
                    (sounding[key] = sounding[key] || []).push(event);
                } else if (event.kind === "off" && sounding[key] && sounding[key].length) {
                    notes.push(held(sounding[key].shift(), event.ticks));
                }
            });
            // A note left sounding at the end of the file is held to the end of the
            // range rather than dropped, so a tie out of the last bar is still heard.
            Object.keys(sounding).forEach(function (key) {
                sounding[key].forEach(function (started) {
                    notes.push(held(started, lastTick));
                });
            });
            notes.sort(function (a, b) { return a.start - b.start; });
            return notes;
        });

        // The file carries a conductor track holding the speed and the time signature
        // before the parts, so a leading track with no notes belongs to no part. Every
        // other track keeps its place, even when the part rests through the range.
        while (tracks.length > expectedParts && tracks.length && !tracks[0].length) {
            tracks.shift();
        }
        while (tracks.length < expectedParts) {
            tracks.push([]);
        }

        var clicks = beatGrid(midi, lastTick).map(function (beat) {
            return { start: seconds(beat.ticks), strong: beat.strong };
        });
        return {
            parts: tracks,
            clicks: clicks,
            duration: seconds(lastTick),
            // A file with a track for every part is the only one the parts can be
            // named from, so a reader is told when it does not line up.
            matches: tracks.length === expectedParts
        };
    }

    /* Sounding the notes.

       A piano is a struck string, not a held tone: it is loudest at the moment the
       hammer lands and quieter from then on, never levelling off, and its upper
       partials fade first, so the sound dulls as it falls away. A wave held at one
       level for the length of the note has the shape of an organ instead, which is
       why a plain sustained wave reads as anything but a piano.

       Each note is sounded as three waves under one damper. The body carries the
       fundamental and the low partials and rings on; a second body a few cents away
       gives the slow beating of strings tuned in unison; the strike carries the
       upper partials and is gone within a fraction of a second. */

    var BODY_PARTIALS = [0, 1, 0.4, 0.18, 0.09, 0.05, 0.028, 0.016];
    var STRIKE_PARTIALS = [0, 0, 0, 0.22, 0.32, 0.28, 0.22, 0.17, 0.13, 0.1, 0.08, 0.06, 0.045, 0.03];
    var UNISON_CENTS = 3.2;
    // A ring is followed to this fraction of its loudest, which is far enough below
    // hearing that the wave can be stopped there without the end being heard.
    var INAUDIBLE = 0.0005;
    var DAMPER = 0.11;
    var waveCache = null;

    /* The shape of one struck note. Kept apart from the audio nodes so the numbers
       behind the sound can be checked without a browser. */
    function pianoVoice(number, velocity) {
        // Middle C is note 60. A bass string rings for many seconds and the top of
        // the keyboard is gone in under one, so the ring is taken from the pitch.
        var above = (number - 60) / 12;
        var force = Math.min(1, Math.max(0, velocity / 127));
        return {
            level: 0.045 + force * 0.16,
            bodyRing: Math.min(11, Math.max(0.6, 8 * Math.pow(0.56, above))),
            // A string struck harder sounds brighter as well as louder, and the
            // higher the string the less there is above it left to hear.
            strikeLevel: (0.14 + force * 0.42) * Math.pow(0.78, Math.max(0, above)),
            strikeRing: Math.min(0.9, Math.max(0.07, 0.4 * Math.pow(0.62, above))),
            attack: 0.003
        };
    }

    function partialWave(context, partials) {
        return context.createPeriodicWave(new Float32Array(partials.length), new Float32Array(partials));
    }

    function waves(context) {
        // Building the two waves costs as much as sounding a note does, so they are
        // built once and kept for as long as the context they belong to lives.
        if (!waveCache || waveCache.context !== context) {
            waveCache = {
                context: context,
                body: partialWave(context, BODY_PARTIALS),
                strike: partialWave(context, STRIKE_PARTIALS)
            };
        }
        return waveCache;
    }

    /* A bowed, blown or driven instrument does none of that: it holds a note at
       whatever level the player gives it and stops when they stop. Sounding one as
       a struck string would let a held note die away under the reader. */
    function sustainNote(context, destination, note, start, end) {
        var frequency = 440 * Math.pow(2, (note.note - 69) / 12);
        var level = Math.min(0.24, 0.05 + note.velocity / 127 * 0.19);
        var attack = 0.03;
        var release = Math.min(0.16, Math.max(0.05, (end - start) * 0.35));
        var stopAt = end + release;
        var gain = context.createGain();
        gain.gain.setValueAtTime(level * INAUDIBLE, start);
        gain.gain.linearRampToValueAtTime(level, start + attack);
        gain.gain.setValueAtTime(level, Math.max(start + attack, end));
        gain.gain.exponentialRampToValueAtTime(level * INAUDIBLE, stopAt);
        gain.connect(destination);

        [["triangle", 1], ["sine", 0.45]].forEach(function (shape) {
            var oscillator = context.createOscillator();
            oscillator.type = shape[0];
            oscillator.frequency.setValueAtTime(frequency, start);
            var mix = context.createGain();
            mix.gain.value = shape[1];
            oscillator.connect(mix);
            mix.connect(gain);
            oscillator.start(start);
            oscillator.stop(stopAt + 0.02);
        });
    }

    function synthNote(context, destination, note, start, end) {
        var frequency = 440 * Math.pow(2, (note.note - 69) / 12);
        var voice = pianoVoice(note.note, note.velocity);
        var shapes = waves(context);
        // The damper lands when the written note ends, so a note stops there even
        // while the string still has sound left in it.
        var stopAt = end + DAMPER;
        var damper = context.createGain();
        damper.gain.setValueAtTime(1, start);
        damper.gain.setValueAtTime(1, end);
        damper.gain.exponentialRampToValueAtTime(INAUDIBLE, stopAt);
        damper.connect(destination);

        function ring(shape, level, seconds, cents) {
            var gain = context.createGain();
            gain.gain.setValueAtTime(level * INAUDIBLE, start);
            gain.gain.linearRampToValueAtTime(level, start + voice.attack);
            // An exponential ramp is the ring itself, not an approach to it, so the
            // fall is the same shape whatever else is written on this parameter.
            gain.gain.exponentialRampToValueAtTime(level * INAUDIBLE, start + voice.attack + seconds);
            gain.connect(damper);
            var oscillator = context.createOscillator();
            oscillator.setPeriodicWave(shape);
            oscillator.frequency.setValueAtTime(frequency, start);
            if (cents) {
                oscillator.detune.setValueAtTime(cents, start);
            }
            oscillator.connect(gain);
            oscillator.start(start);
            oscillator.stop(stopAt + 0.02);
        }

        ring(shapes.body, voice.level, voice.bodyRing, 0);
        ring(shapes.body, voice.level * 0.5, voice.bodyRing * 0.9, UNISON_CENTS);
        ring(shapes.strike, voice.level * voice.strikeLevel, voice.strikeRing, 0);
    }

    /* A recorded piano, for a reader who wants the instrument rather than a
       likeness of it. One recording every three semitones covers the keyboard, and
       a note between two of them is the nearer recording played a semitone faster
       or slower, which is close enough that the join cannot be heard. The
       recordings are fetched rather than played from an audio element, so they
       arrive under the connection rule the site already sets. */

    var SAMPLE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
    var SAMPLE_STEP = 3;
    var LOWEST_SAMPLE = 21;
    var HIGHEST_SAMPLE = 108;

    function sampleName(number) {
        return SAMPLE_NAMES[number % 12] + (Math.floor(number / 12) - 1);
    }

    function nearestSample(number) {
        var sampled = LOWEST_SAMPLE + Math.round((number - LOWEST_SAMPLE) / SAMPLE_STEP) * SAMPLE_STEP;
        return Math.min(HIGHEST_SAMPLE, Math.max(LOWEST_SAMPLE, sampled));
    }

    function decode(context, bytes) {
        return new Promise(function (resolve, reject) {
            // Older decoders answer through callbacks rather than returning a promise.
            var answered = context.decodeAudioData(bytes, resolve, reject);
            if (answered && typeof answered.then === "function") {
                answered.then(resolve, reject);
            }
        });
    }

    function loadPiano(context, base) {
        var wanted = [];
        for (var number = LOWEST_SAMPLE; number <= HIGHEST_SAMPLE; number += SAMPLE_STEP) {
            wanted.push(number);
        }
        return Promise.all(wanted.map(function (number) {
            return fetch(base + sampleName(number) + ".mp3").then(function (response) {
                if (!response.ok) {
                    throw new Error("a recording is missing");
                }
                return response.arrayBuffer();
            }).then(function (bytes) {
                return decode(context, bytes);
            }).then(function (buffer) {
                return [number, buffer];
            });
        })).then(function (pairs) {
            var buffers = {};
            pairs.forEach(function (pair) {
                buffers[pair[0]] = pair[1];
            });
            return buffers;
        });
    }

    function sampleNote(context, destination, piano, note, start, end) {
        var sampled = nearestSample(note.note);
        var buffer = piano[sampled];
        if (!buffer) {
            synthNote(context, destination, note, start, end);
            return;
        }
        var force = Math.min(1, Math.max(0, note.velocity / 127));
        var level = 0.12 + force * 0.5;
        // The recording carries its own ring, so all that is written on it is how
        // hard the note was struck and the damper landing at the end of it.
        var stopAt = end + DAMPER;
        var gain = context.createGain();
        gain.gain.setValueAtTime(level, start);
        gain.gain.setValueAtTime(level, end);
        gain.gain.exponentialRampToValueAtTime(level * INAUDIBLE, stopAt);
        gain.connect(destination);
        var source = context.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = Math.pow(2, (note.note - sampled) / 12);
        source.connect(gain);
        source.start(start);
        source.stop(stopAt + 0.02);
    }

    /* Percussion has no pitch to sound, so it is struck as a short tap that keeps
       the written rhythm audible. A higher note number taps higher. */
    function makeTap(context, destination, note, start) {
        var oscillator = context.createOscillator();
        var gain = context.createGain();
        oscillator.type = "square";
        oscillator.frequency.setValueAtTime(120 + (note.note % 24) * 22, start);
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(Math.min(0.2, 0.05 + note.velocity / 127 * 0.15), start + 0.003);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.07);
        gain.gain.linearRampToValueAtTime(0, start + 0.09);
        oscillator.connect(gain);
        gain.connect(destination);
        oscillator.start(start);
        oscillator.stop(start + 0.1);
    }

    function makeClick(context, destination, at, strong) {
        var oscillator = context.createOscillator();
        var gain = context.createGain();
        oscillator.type = "square";
        oscillator.frequency.setValueAtTime(strong ? 1600 : 1100, at);
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(strong ? 0.16 : 0.09, at + 0.002);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.045);
        gain.gain.linearRampToValueAtTime(0, at + 0.06);
        oscillator.connect(gain);
        gain.connect(destination);
        oscillator.start(at);
        oscillator.stop(at + 0.07);
    }

    window.TalkingScoresPlayer = function (data, controls) {
        var group = null;
        var context = null;
        var master = null;
        var limiter = null;
        var piano = null;
        var pianoLoading = null;
        var pianoRefused = false;
        var pianoTold = false;
        var partGains = [];
        var scores = {};
        var order = [];
        var timer = null;
        var playing = false;
        var pending = false;
        var music = null;
        var origin = 0;
        var cursor = { part: [], click: 0 };
        var stopAt = 0;

        // Which voice each part is sounded with. The audio carries no instrument, so
        // the page says which parts hold a note and which let it ring away.
        var sustaining = (data.midi.parts || []).map(function (part) {
            return Boolean(part.sustains);
        });

        function label(item) {
            return controls.rangeLabel(item.start, item.end, false);
        }

        function capital(text) {
            return text.charAt(0).toUpperCase() + text.slice(1);
        }

        function status(text) {
            if (controls.status) {
                controls.status.textContent = text;
            }
        }

        // The reading page has one place where messages are spoken, so playback
        // reports through it rather than announcing from the toolbar as well.
        function report(text) {
            status(text);
            if (controls.announce) {
                controls.announce(text);
            }
        }

        function waiting() {
            status(capital(label(group)) + " ready to play.");
        }

        function speedFactor() {
            var chosen = controls.speed ? parseInt(controls.speed.value, 10) : 100;
            return 100 / (chosen > 0 ? chosen : 100);
        }

        function chosenVoice() {
            if (!controls.voice) {
                return data.midi.voices[0];
            }
            return data.midi.voices[parseInt(controls.voice.value, 10)] || data.midi.voices[0];
        }

        function forwardPart() {
            if (!controls.forward || controls.forward.value === "") {
                return -1;
            }
            return parseInt(controls.forward.value, 10);
        }

        // Only a part being played can be brought forward, so the rest are closed off.
        // Says whether it had to let the chosen part go, which the reader is told.
        function reflectBalance() {
            if (!controls.forward) {
                return false;
            }
            var voice = chosenVoice();
            Array.prototype.forEach.call(controls.forward.options, function (option) {
                if (option.value !== "") {
                    option.disabled = voice.parts.indexOf(parseInt(option.value, 10)) === -1;
                }
            });
            if (controls.forward.selectedOptions[0] && controls.forward.selectedOptions[0].disabled) {
                // Clearing the control in script raises no change event, so the choice
                // is written down here rather than reappearing on the next visit.
                controls.forward.value = "";
                if (controls.remember) {
                    controls.remember("forward", "");
                }
                return true;
            }
            return false;
        }

        // Several parts sounding at once add up past what the output can carry, and
        // the overflow is heard as a crackle over the notes. Everything passes
        // through one compressor, which holds the loudest moments down instead.
        function openMaster() {
            master = context.createGain();
            master.gain.value = 0.75;
            master.connect(limiter);
        }

        function audio() {
            if (!context) {
                var Context = window.AudioContext || window.webkitAudioContext;
                if (!Context) {
                    return null;
                }
                context = new Context();
                limiter = context.createDynamicsCompressor();
                limiter.threshold.value = -12;
                limiter.knee.value = 6;
                limiter.ratio.value = 8;
                limiter.attack.value = 0.004;
                limiter.release.value = 0.18;
                limiter.connect(context.destination);
                openMaster();
            }
            return context;
        }

        function silence() {
            if (timer) {
                window.clearInterval(timer);
                timer = null;
            }
            if (master && context) {
                master.disconnect();
                openMaster();
            }
            partGains = [];
        }

        function pianoWanted() {
            return Boolean(data.midi.piano && controls.piano && controls.piano.checked);
        }

        /* The recordings are several hundred kilobytes, so they are fetched only once
           the reader has asked for them, and only once for the life of the page. */
        function pianoIfWanted() {
            if (!pianoWanted() || pianoRefused) {
                return Promise.resolve(null);
            }
            if (piano) {
                return Promise.resolve(piano);
            }
            if (!pianoLoading) {
                pianoLoading = loadPiano(context, data.midi.piano).then(function (buffers) {
                    piano = buffers;
                    return buffers;
                }, function () {
                    // Recordings that will not load are not worth refusing to play
                    // over: the written sound stands in and the reader is told once.
                    pianoRefused = true;
                    pianoLoading = null;
                    return null;
                });
            }
            return pianoLoading;
        }

        function openGains() {
            var voice = chosenVoice();
            var forward = forwardPart();
            partGains = music.parts.map(function (notes, index) {
                var gain = context.createGain();
                if (voice.parts.indexOf(index) === -1) {
                    gain.gain.value = 0;
                } else if (forward === -1) {
                    gain.gain.value = 1;
                } else {
                    gain.gain.value = index === forward ? 1 : 0.32;
                }
                gain.connect(master);
                return gain;
            });
        }

        function scheduleUpTo(until) {
            var factor = speedFactor();
            var now = context.currentTime;
            var click = controls.click && controls.click.checked;
            music.parts.forEach(function (notes, part) {
                var index = cursor.part[part];
                while (index < notes.length && origin + notes[index].start * factor < until) {
                    var note = notes[index];
                    var start = origin + note.start * factor;
                    var end = origin + Math.max(note.end, note.start + 0.05) * factor;
                    // A tab left in the background stalls the timer while the audio
                    // clock runs on. Notes whose moment has passed are let go rather
                    // than sounded together on the next pass.
                    if (partGains[part].gain.value > 0 && start >= now - LATE_TOLERANCE) {
                        if (note.percussion) {
                            makeTap(context, partGains[part], note, Math.max(start, now));
                        } else if (sustaining[part]) {
                            sustainNote(context, partGains[part], note, Math.max(start, now), end);
                        } else if (piano && pianoWanted()) {
                            sampleNote(context, partGains[part], piano, note, Math.max(start, now), end);
                        } else {
                            synthNote(context, partGains[part], note, Math.max(start, now), end);
                        }
                    }
                    index++;
                }
                cursor.part[part] = index;
            });
            if (click) {
                while (cursor.click < music.clicks.length && origin + music.clicks[cursor.click].start * factor < until) {
                    var at = origin + music.clicks[cursor.click].start * factor;
                    if (at >= now - LATE_TOLERANCE) {
                        makeClick(context, master, Math.max(at, now), music.clicks[cursor.click].strong);
                    }
                    cursor.click++;
                }
            } else {
                cursor.click = music.clicks.length;
            }
        }

        function restart() {
            cursor = { part: music.parts.map(function () { return 0; }), click: 0 };
            silence();
            openGains();
            stopAt = origin + music.duration * speedFactor() + 0.6;
            timer = window.setInterval(tick, SCHEDULER_MS);
            tick();
        }

        function tick() {
            if (!playing) {
                return;
            }
            scheduleUpTo(context.currentTime + LOOKAHEAD_SECONDS);
            if (context.currentTime < stopAt) {
                return;
            }
            if (repeating()) {
                origin = context.currentTime + GAP_BEFORE_REPEAT;
                restart();
                return;
            }
            playing = false;
            silence();
            report("Reached the end of " + label(group) + ".");
        }

        function repeating() {
            return Boolean(controls.repeat && controls.repeat.checked);
        }

        function remember(key, promise) {
            scores[key] = promise;
            order.push(key);
            while (order.length > REMEMBERED_RANGES) {
                delete scores[order.shift()];
            }
            return promise;
        }

        function fetchRange(start, end) {
            var key = start + "-" + end;
            if (scores[key]) {
                return scores[key];
            }
            return remember(key, fetch(data.midi.base + "?start=" + start + "&end=" + end)
                .then(function (response) {
                    if (!response.ok) {
                        var refused = new Error("the server refused the range");
                        refused.refused = true;
                        throw refused;
                    }
                    return response.arrayBuffer();
                })
                .then(function (buffer) {
                    return collect(parseMidi(buffer), data.midi.parts.length);
                })
                .catch(function (error) {
                    delete scores[key];
                    throw error;
                }));
        }

        function stop(spoken) {
            var wasSounding = playing || pending;
            pending = false;
            playing = false;
            silence();
            // Stop answers every press, so a reader who cannot see the button knows
            // it reached the player whether or not anything was sounding.
            if (spoken) {
                report((wasSounding ? "Playback stopped. " : "") + capital(label(group)) + " ready to play.");
            }
        }

        function start(parsed, said) {
            music = parsed;
            playing = true;
            origin = context.currentTime + 0.15;
            restart();
            report((said || "") + "Playing " + label(group) + ".");
        }

        // A note said before the state is a note the next message would wipe out, so
        // anything to say about the settings goes in front of the state itself.
        function play(note) {
            var said = typeof note === "string" ? note : "";
            if (!audio()) {
                report(said + "This browser cannot sound the score. The bars are written out below.");
                return;
            }
            stop(false);
            var wanted = group;
            pending = true;
            report(said + "Loading " + label(group) + ".");
            var loaded = fetchRange(group.start, group.end);
            // The browser holds the audio clock until a gesture releases it, so
            // playback waits for the resume as well as for the file.
            Promise.all([loaded, context.resume(), pianoIfWanted()]).then(function (results) {
                if (!pending || wanted !== group) {
                    return;
                }
                pending = false;
                var sounding = "";
                if (pianoRefused && !pianoTold) {
                    pianoTold = true;
                    sounding = "The recorded piano did not load, so the built-in sound is playing instead. ";
                }
                if (context.state !== "running") {
                    report("The audio has not started. Press Play this group again.");
                    return;
                }
                // A range of rests still has a length, so it plays as silence with the
                // click and only a range holding nothing at all is refused.
                if (!results[0].duration && !results[0].parts.some(function (notes) { return notes.length; })) {
                    report("There is nothing to play in " + label(group) + ".");
                    return;
                }
                if (!results[0].matches) {
                    report("The audio for " + label(group) + " does not match this score. Reload the page and try again.");
                    return;
                }
                start(results[0], sounding);
            }, function (error) {
                pending = false;
                if (error && error.refused) {
                    report("The server would not send the audio for " + label(wanted) + ". Reload the page and try again.");
                } else if (error && error.arrived) {
                    report("The audio for " + label(wanted) + " could not be read. Reload the page and try again.");
                } else {
                    report("The audio for " + label(wanted) + " did not arrive. Check your connection and press Play this group again.");
                }
            });
        }

        function replayIfPlaying() {
            var said = reflectBalance() ? "Balance set to every part level. " : "";
            if (playing || pending) {
                play(said);
            } else if (said) {
                report(said + capital(label(group)) + " ready to play.");
            }
        }

        if (controls.play) {
            controls.play.addEventListener("click", function () { play(); });
        }
        if (controls.stop) {
            controls.stop.addEventListener("click", function () { stop(true); });
        }
        [controls.speed, controls.voice, controls.forward, controls.click, controls.piano].forEach(function (control) {
            if (control) {
                control.addEventListener("change", replayIfPlaying);
            }
        });
        reflectBalance();

        return {
            groupChanged: function (next) {
                if (next === group) {
                    return;
                }
                var wasSounding = playing || pending;
                stop(false);
                group = next;
                if (wasSounding) {
                    report("Playback stopped. " + capital(label(group)) + " ready to play.");
                } else {
                    waiting();
                }
            }
        };
    };
    // Reading a file and laying its tracks against the parts is checked on its own.
    window.TalkingScoresPlayer.reading = { parseMidi: parseMidi, collect: collect };
    // The numbers behind the sounded note, which no browser is needed to check.
    window.TalkingScoresPlayer.voice = { pianoVoice: pianoVoice };
    // Which recording a note is played from, which no browser is needed to check.
    window.TalkingScoresPlayer.samples = { sampleName: sampleName, nearestSample: nearestSample };
})();
