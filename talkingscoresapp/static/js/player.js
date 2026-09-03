/* Playback of the open group, from a MIDI file of that range played in the browser.

   The server sends one file per range of bars holding every part at its written
   speed. Choosing parts, the speed, the metronome click, the balance and
   repeating all happen here, so a range needs only that one file however it is
   played. */
(function () {
    "use strict";

    var TICKS_PER_QUARTER = 480;
    var DEFAULT_TEMPO = 500000;
    var LOOKAHEAD_SECONDS = 0.4;
    var SCHEDULER_MS = 100;
    var GAP_BEFORE_REPEAT = 0.6;

    /* Reading a standard MIDI file. */

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
            value = (value << 8) | this.bytes[this.at++];
        }
        return value >>> 0;
    };

    Reader.prototype.variable = function () {
        var value = 0;
        var byte;
        do {
            byte = this.bytes[this.at++];
            value = (value << 7) | (byte & 0x7f);
        } while (byte & 0x80);
        return value;
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
                if (status < 0xf0) {
                    running = status;
                }
            } else {
                status = running;
            }
            if (status === 0xff) {
                var type = reader.byte();
                var length = reader.variable();
                if (type === 0x51) {
                    events.push({ ticks: ticks, kind: "tempo", value: reader.word(length) });
                } else if (type === 0x58) {
                    var numerator = reader.byte();
                    var denominator = Math.pow(2, reader.byte());
                    reader.at += length - 2;
                    events.push({ ticks: ticks, kind: "time", beats: numerator, unit: denominator });
                } else {
                    reader.at += length;
                }
                if (type === 0x2f) {
                    break;
                }
            } else if (status === 0xf0 || status === 0xf7) {
                reader.at += reader.variable();
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
        if (reader.text(4) !== "MThd") {
            throw new Error("not a MIDI file");
        }
        reader.at += 4 + 2;
        var trackCount = reader.word(2);
        var division = reader.word(2);
        if (division & 0x8000) {
            division = TICKS_PER_QUARTER;
        }
        var tracks = [];
        for (var i = 0; i < trackCount && reader.at < reader.bytes.length; i++) {
            if (reader.text(4) !== "MTrk") {
                break;
            }
            var length = reader.word(4);
            tracks.push(readTrack(reader, reader.at + length));
        }
        return { division: division || TICKS_PER_QUARTER, tracks: tracks };
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
            if (change.ticks === last.ticks) {
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

    function beatTicks(midi) {
        var signature = { beats: 4, unit: 4 };
        midi.tracks.forEach(function (track) {
            track.forEach(function (event) {
                if (event.kind === "time" && event.ticks === 0) {
                    signature = { beats: event.beats, unit: event.unit };
                }
            });
        });
        return { step: midi.division * 4 / signature.unit, beats: signature.beats };
    }

    /* The notes of every part, in score order, with the click track alongside. */

    function collect(midi) {
        var seconds = tempoMap(midi);
        var parts = [];
        var lastTick = 0;
        midi.tracks.forEach(function (track) {
            var notes = [];
            var sounding = {};
            track.forEach(function (event) {
                if (event.kind === "on") {
                    sounding[event.channel + ":" + event.note] = event;
                } else if (event.kind === "off") {
                    var started = sounding[event.channel + ":" + event.note];
                    if (started) {
                        delete sounding[event.channel + ":" + event.note];
                        if (event.channel === 9) {
                            return;
                        }
                        notes.push({
                            start: seconds(started.ticks),
                            end: seconds(event.ticks),
                            note: started.note,
                            velocity: started.velocity
                        });
                        lastTick = Math.max(lastTick, event.ticks);
                    }
                }
            });
            if (notes.length) {
                notes.sort(function (a, b) { return a.start - b.start; });
                parts.push(notes);
            }
        });

        var beat = beatTicks(midi);
        var clicks = [];
        var index = 0;
        for (var ticks = 0; ticks < lastTick; ticks += beat.step) {
            clicks.push({ start: seconds(ticks), strong: index % beat.beats === 0 });
            index++;
        }
        return { parts: parts, clicks: clicks, duration: seconds(lastTick) };
    }

    /* Sounding the notes. */

    function makeVoice(context, destination, note, velocity, start, end) {
        var frequency = 440 * Math.pow(2, (note - 69) / 12);
        var gain = context.createGain();
        var level = Math.min(0.28, 0.06 + velocity / 127 * 0.22);
        var attack = 0.012;
        var release = Math.min(0.18, Math.max(0.05, (end - start) * 0.4));
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(level, start + attack);
        gain.gain.setTargetAtTime(level * 0.6, start + attack, 0.35);
        gain.gain.setTargetAtTime(0.0001, Math.max(start + attack, end - release), release / 3);
        gain.connect(destination);

        var stopAt = end + release + 0.05;
        [["triangle", 1], ["sine", 0.45]].forEach(function (shape) {
            var oscillator = context.createOscillator();
            oscillator.type = shape[0];
            oscillator.frequency.setValueAtTime(frequency, start);
            var mix = context.createGain();
            mix.gain.value = shape[1];
            oscillator.connect(mix);
            mix.connect(gain);
            oscillator.start(start);
            oscillator.stop(stopAt);
        });
        return stopAt;
    }

    function makeClick(context, destination, at, strong) {
        var oscillator = context.createOscillator();
        var gain = context.createGain();
        oscillator.type = "square";
        oscillator.frequency.setValueAtTime(strong ? 1600 : 1100, at);
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(strong ? 0.16 : 0.09, at + 0.002);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.045);
        oscillator.connect(gain);
        gain.connect(destination);
        oscillator.start(at);
        oscillator.stop(at + 0.06);
    }

    window.TalkingScoresPlayer = function (data, controls) {
        var group = null;
        var context = null;
        var master = null;
        var partGains = [];
        var scores = {};
        var timer = null;
        var playing = false;
        var pending = false;
        var music = null;
        var origin = 0;
        var cursor = { part: [], click: 0 };
        var stopAt = 0;

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

        function ready() {
            status("Stopped. " + capital(label(group)) + " ready.");
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

        function repeating() {
            return !!(controls.repeat && controls.repeat.checked);
        }

        function audio() {
            if (!context) {
                var Context = window.AudioContext || window.webkitAudioContext;
                if (!Context) {
                    return null;
                }
                context = new Context();
                master = context.createGain();
                master.gain.value = 0.9;
                master.connect(context.destination);
            }
            if (context.state === "suspended") {
                context.resume();
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
                master = context.createGain();
                master.gain.value = 0.9;
                master.connect(context.destination);
            }
            partGains = [];
        }

        function openGains() {
            var voice = chosenVoice();
            var forward = forwardPart();
            partGains = music.parts.map(function (notes, index) {
                var gain = context.createGain();
                var wanted = voice.parts.indexOf(index) !== -1;
                if (!wanted) {
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
            var click = controls.click && controls.click.checked;
            music.parts.forEach(function (notes, part) {
                var index = cursor.part[part];
                while (index < notes.length && origin + notes[index].start * factor < until) {
                    var note = notes[index];
                    if (partGains[part].gain.value > 0) {
                        makeVoice(context, partGains[part], note.note, note.velocity,
                            origin + note.start * factor,
                            origin + Math.max(note.end, note.start + 0.05) * factor);
                    }
                    index++;
                }
                cursor.part[part] = index;
            });
            if (click) {
                while (cursor.click < music.clicks.length && origin + music.clicks[cursor.click].start * factor < until) {
                    makeClick(context, master, origin + music.clicks[cursor.click].start * factor,
                        music.clicks[cursor.click].strong);
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
            ready();
        }

        function fetchRange(start, end) {
            var key = start + "-" + end;
            if (!scores[key]) {
                scores[key] = fetch(data.midi.base + "?start=" + start + "&end=" + end)
                    .then(function (response) {
                        if (!response.ok) {
                            throw { arrived: false };
                        }
                        return response.arrayBuffer();
                    }, function () {
                        throw { arrived: false };
                    })
                    .then(function (buffer) {
                        try {
                            return collect(parseMidi(buffer));
                        } catch (error) {
                            // The bytes came but are not a MIDI file this player can read.
                            throw { arrived: true };
                        }
                    })
                    .catch(function (error) {
                        delete scores[key];
                        throw error;
                    });
            }
            return scores[key];
        }

        function stop() {
            pending = false;
            if (playing) {
                playing = false;
                silence();
                ready();
            } else {
                silence();
            }
        }

        function play() {
            if (!audio()) {
                status("This browser cannot play the score. The bars are written out above.");
                return;
            }
            stop();
            var wanted = group;
            pending = true;
            status("Loading " + label(group) + ".");
            fetchRange(group.start, group.end).then(function (parsed) {
                if (!pending || wanted !== group) {
                    return;
                }
                pending = false;
                if (!parsed.parts.length) {
                    status("Nothing is written to play in " + label(group) + ".");
                    return;
                }
                music = parsed;
                playing = true;
                origin = context.currentTime + 0.15;
                restart();
                status("Playing " + label(group) + ".");
            }, function (error) {
                pending = false;
                if (error && error.arrived) {
                    status("The audio for " + label(wanted) + " could not be read. Reload the page and try again.");
                } else {
                    status("The audio for " + label(wanted) + " did not arrive. Check your connection and press Play this group again.");
                }
            });
        }

        function replayIfPlaying() {
            if (playing || pending) {
                play();
            }
        }

        if (controls.play) {
            controls.play.addEventListener("click", play);
        }
        if (controls.stop) {
            controls.stop.addEventListener("click", stop);
        }
        if (controls.speed) {
            controls.speed.addEventListener("change", replayIfPlaying);
        }
        if (controls.voice) {
            controls.voice.addEventListener("change", replayIfPlaying);
        }
        if (controls.forward) {
            controls.forward.addEventListener("change", replayIfPlaying);
        }
        if (controls.click) {
            controls.click.addEventListener("change", replayIfPlaying);
        }

        return {
            groupChanged: function (next) {
                if (group && next !== group) {
                    stop();
                }
                group = next;
                ready();
            }
        };
    };
})();
