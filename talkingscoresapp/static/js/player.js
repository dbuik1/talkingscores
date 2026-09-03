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
                // Meta and system events cancel running status.
                running = status < 0xf0 ? status : 0;
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
                    // The end of the track falls at the end of the last bar, which is
                    // how a range finishing in rests keeps its full length.
                    events.push({ ticks: ticks, kind: "end" });
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
        var tracks = [];
        var lastTick = 0;
        midi.tracks.forEach(function (track) {
            var notes = [];
            var sounding = {};
            var trackEnd = 0;
            track.forEach(function (event) {
                trackEnd = Math.max(trackEnd, event.ticks);
                var key = event.channel + ":" + event.note;
                if (event.kind === "on") {
                    // Two voices in one part can hold the same pitch at once.
                    (sounding[key] = sounding[key] || []).push(event);
                } else if (event.kind === "off" && sounding[key] && sounding[key].length) {
                    notes.push(held(sounding[key].shift(), event.ticks));
                }
            });
            // A note left sounding at the end of the track is held to the end of the
            // range rather than dropped, so a tie out of the last bar is still heard.
            Object.keys(sounding).forEach(function (key) {
                sounding[key].forEach(function (started) {
                    notes.push(held(started, trackEnd));
                });
            });
            lastTick = Math.max(lastTick, trackEnd);
            notes.sort(function (a, b) { return a.start - b.start; });
            tracks.push(notes);
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

        // The file carries a conductor track holding the tempo and the time signature
        // before the parts, so a file with one track more than the score has parts
        // starts with a track belonging to no part. Any other count means the file
        // does not match the score, and lining the tracks up by guesswork would sound
        // the wrong instrument, so they are left in the order they were written.
        if (tracks.length === expectedParts + 1 && !tracks[0].length) {
            tracks.shift();
        }
        while (tracks.length < expectedParts) {
            tracks.push([]);
        }

        var clicks = beatGrid(midi, lastTick).map(function (beat) {
            return { start: seconds(beat.ticks), strong: beat.strong };
        });
        return { parts: tracks, clicks: clicks, duration: seconds(lastTick) };
    }

    /* Sounding the notes. */

    function makeNote(context, destination, note, start, end) {
        var frequency = 440 * Math.pow(2, (note.note - 69) / 12);
        var gain = context.createGain();
        var level = Math.min(0.28, 0.06 + note.velocity / 127 * 0.22);
        var attack = 0.012;
        var release = Math.min(0.18, Math.max(0.05, (end - start) * 0.4));
        var stopAt = end + release;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(level, start + attack);
        gain.gain.setTargetAtTime(level * 0.6, start + attack, 0.35);
        gain.gain.setTargetAtTime(0.0001, Math.max(start + attack, end - release), release / 3);
        // The decay never reaches zero on its own, so the tail is taken to silence
        // before the oscillator stops rather than being cut off with a click.
        gain.gain.linearRampToValueAtTime(0, stopAt);
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
        function reflectBalance(spoken) {
            if (!controls.forward) {
                return;
            }
            var voice = chosenVoice();
            Array.prototype.forEach.call(controls.forward.options, function (option) {
                if (option.value !== "") {
                    option.disabled = voice.parts.indexOf(parseInt(option.value, 10)) === -1;
                }
            });
            if (controls.forward.selectedOptions[0] && controls.forward.selectedOptions[0].disabled) {
                // Clearing the control in script raises no change event, so the choice
                // is written down and said here rather than reappearing on the next visit.
                controls.forward.value = "";
                if (controls.remember) {
                    controls.remember("forward", "");
                }
                if (spoken && controls.announce) {
                    controls.announce("Balance set to every part level.");
                }
            }
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
                        } else {
                            makeNote(context, partGains[part], note, Math.max(start, now), end);
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

        function start(parsed) {
            music = parsed;
            playing = true;
            origin = context.currentTime + 0.15;
            restart();
            report("Playing " + label(group) + ".");
        }

        function play() {
            if (!audio()) {
                report("This browser cannot sound the score. The bars are written out below.");
                return;
            }
            stop(false);
            var wanted = group;
            pending = true;
            report("Loading " + label(group) + ".");
            var loaded = fetchRange(group.start, group.end);
            // The browser holds the audio clock until a gesture releases it, so
            // playback waits for the resume as well as for the file.
            Promise.all([loaded, context.resume()]).then(function (results) {
                if (!pending || wanted !== group) {
                    return;
                }
                pending = false;
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
                start(results[0]);
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
            reflectBalance(true);
            if (playing || pending) {
                play();
            }
        }

        if (controls.play) {
            controls.play.addEventListener("click", play);
        }
        if (controls.stop) {
            controls.stop.addEventListener("click", function () { stop(true); });
        }
        [controls.speed, controls.voice, controls.forward, controls.click].forEach(function (control) {
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
})();
