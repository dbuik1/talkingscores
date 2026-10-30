// Plays a MIDI file the reader chooses, with the same synthesizer and sound bank
// as the talking score page. The file is read in the browser and never sent anywhere.
(function () {
    "use strict";

    var input = document.getElementById("midi-file");
    var field = document.getElementById("midi-field");
    var controls = document.getElementById("midi-controls");
    var nameLine = document.getElementById("midi-name");
    var playButton = document.getElementById("midi-play");
    var restartButton = document.getElementById("midi-restart");
    var speed = document.getElementById("midi-speed");
    var position = document.getElementById("midi-position");
    var repeat = document.getElementById("midi-repeat");
    var status = document.getElementById("midi-status-text");
    var sounds = window.TalkingScoresSounds;

    var context = null;
    var synth = null;
    var sequencer = null;
    var loading = null;
    var song = null;
    var loaded = false;
    var playing = false;
    var timer = null;
    var dragging = false;

    function say(text) {
        status.textContent = text;
    }

    function minutesAndSeconds(seconds) {
        var whole = Math.max(0, Math.round(seconds));
        var minutes = Math.floor(whole / 60);
        var rest = whole % 60;
        return minutes + ":" + (rest < 10 ? "0" : "") + rest;
    }

    // Read out as words, since "1:05" is read as a ratio or a time of day by some screen readers.
    function spokenLength(seconds) {
        var whole = Math.max(0, Math.round(seconds));
        var minutes = Math.floor(whole / 60);
        var rest = whole % 60;
        var parts = [];
        if (minutes) {
            parts.push(minutes + (minutes === 1 ? " minute" : " minutes"));
        }
        if (rest || !minutes) {
            parts.push(rest + (rest === 1 ? " second" : " seconds"));
        }
        return parts.join(" ");
    }

    function showPosition() {
        if (!sequencer || !loaded) {
            return;
        }
        var now = Math.min(sequencer.currentTime, sequencer.duration);
        if (!dragging) {
            position.value = String(Math.floor(now));
        }
        position.setAttribute("aria-valuetext", spokenLength(now) + " of " + spokenLength(sequencer.duration));
        nameLine.textContent = song.name + ", " + minutesAndSeconds(now) + " of " + minutesAndSeconds(sequencer.duration);
    }

    function setPlaying(now) {
        playing = now;
        playButton.textContent = now ? "Pause" : "Play";
        window.clearInterval(timer);
        timer = now ? window.setInterval(showPosition, 500) : null;
        showPosition();
    }

    function looksLikeMidi(buffer) {
        var head = new Uint8Array(buffer, 0, Math.min(4, buffer.byteLength));
        return head.length === 4 && head[0] === 0x4d && head[1] === 0x54 && head[2] === 0x68 && head[3] === 0x64;
    }

    // The audio can only start inside a key press or click, so the synthesizer
    // is made on the first press of Play rather than when the file is chosen.
    function ready() {
        if (loading) {
            return loading;
        }
        var Context = window.AudioContext || window.webkitAudioContext;
        if (!Context || !window.SpessaSynth || !sounds) {
            return Promise.reject(new Error("no audio"));
        }
        context = new Context();
        if (!context.audioWorklet) {
            return Promise.reject(new Error("no audio worklet"));
        }
        say("Loading the instrument sounds.");
        loading = Promise.all([
            context.audioWorklet.addModule(sounds.processor),
            fetch(sounds.bank).then(function (response) {
                if (!response.ok) {
                    throw new Error("the sound bank was refused");
                }
                return response.arrayBuffer();
            })
        ]).then(function (results) {
            synth = new window.SpessaSynth.WorkletSynthesizer(context);
            synth.connect(context.destination);
            return synth.soundBankManager.addSoundBank(results[1], "main").then(function () {
                return synth.isReady;
            });
        }).then(function () {
            sequencer = new window.SpessaSynth.Sequencer(synth);
            sequencer.loopCount = 0;
            sequencer.eventHandler.addEvent("songChange", "midi-player", function () {
                loaded = true;
                position.max = String(Math.max(1, Math.floor(sequencer.duration)));
                showPosition();
            });
            sequencer.eventHandler.addEvent("songEnded", "midi-player", function () {
                if (repeat.checked) {
                    sequencer.currentTime = 0;
                    sequencer.play();
                    say("Playing " + song.name + " again from the start.");
                    return;
                }
                setPlaying(false);
                sequencer.currentTime = 0;
                say("Finished. Press Play to hear it again.");
            });
        }).catch(function (error) {
            loading = null;
            throw error;
        });
        return loading;
    }

    function loadSong() {
        loaded = false;
        sequencer.loadNewSongList([{ binary: song.buffer.slice(0), fileName: song.name }]);
        sequencer.playbackRate = Number(speed.value);
    }

    function start() {
        context.resume();
        sequencer.play();
        setPlaying(true);
        say("Playing " + song.name + ".");
    }

    playButton.addEventListener("click", function () {
        if (!song) {
            return;
        }
        if (playing) {
            sequencer.pause();
            setPlaying(false);
            say("Paused at " + spokenLength(sequencer.currentTime) + ". Press Play to carry on.");
            return;
        }
        ready().then(function () {
            if (!loaded && song.fresh) {
                song.fresh = false;
                loadSong();
            }
            start();
        }, function () {
            say("This browser cannot play the file. Try a current version of Chrome, Edge, Firefox or Safari.");
        });
    });

    restartButton.addEventListener("click", function () {
        if (!sequencer || !loaded) {
            return;
        }
        sequencer.currentTime = 0;
        showPosition();
        say(playing ? "Playing from the start." : "Back at the start. Press Play to begin.");
    });

    speed.addEventListener("change", function () {
        if (sequencer) {
            sequencer.playbackRate = Number(speed.value);
        }
    });

    position.addEventListener("input", function () {
        dragging = true;
        var target = Number(position.value);
        position.setAttribute("aria-valuetext", spokenLength(target) + (sequencer ? " of " + spokenLength(sequencer.duration) : ""));
    });
    position.addEventListener("change", function () {
        dragging = false;
        if (sequencer && loaded) {
            sequencer.currentTime = Number(position.value);
            showPosition();
        }
    });

    function choose(file) {
        if (!file) {
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            if (!looksLikeMidi(reader.result)) {
                controls.hidden = !song;
                fileProblem(file.name + " could not be read as a MIDI file. Choose a different file.");
                return;
            }
            fileProblem("");
            if (sequencer && playing) {
                sequencer.pause();
                setPlaying(false);
            }
            song = { name: file.name.replace(/\.midi?$/i, ""), buffer: reader.result, fresh: true };
            loaded = false;
            position.value = "0";
            position.max = "0";
            nameLine.textContent = song.name;
            controls.hidden = false;
            if (sequencer) {
                song.fresh = false;
                loadSong();
            }
            say(song.name + " is ready. Press Play.");
            playButton.focus();
        };
        reader.onerror = function () {
            fileProblem(file.name + " could not be read. Choose the file again.");
        };
        reader.readAsArrayBuffer(file);
    }

    var problem = document.createElement("p");
    problem.className = "error";
    problem.id = "midi-file-error";
    problem.setAttribute("role", "alert");
    field.appendChild(problem);

    function fileProblem(text) {
        problem.textContent = text;
        if (text) {
            input.setAttribute("aria-invalid", "true");
        } else {
            input.removeAttribute("aria-invalid");
        }
    }

    input.addEventListener("change", function () {
        choose(input.files && input.files[0]);
    });

    ["dragenter", "dragover"].forEach(function (eventName) {
        field.addEventListener(eventName, function (event) {
            event.preventDefault();
            field.classList.add("drag-over");
        });
    });
    ["dragleave", "dragend", "drop"].forEach(function (eventName) {
        field.addEventListener(eventName, function () {
            field.classList.remove("drag-over");
        });
    });
    field.addEventListener("drop", function (event) {
        event.preventDefault();
        var files = event.dataTransfer && event.dataTransfer.files;
        if (files && files.length) {
            choose(files[0]);
        }
    });
})();
