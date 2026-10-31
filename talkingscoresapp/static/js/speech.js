/* Reading bars aloud, in one of the device's own speech voices or in a natural
   voice the reader has downloaded to run in the browser. The words are the ones
   on the page, rewritten where a speech engine would misread them: accidental
   symbols, the abbreviated rhythm and accidental names, and punctuation that
   engines either skip or spell out. */
(function () {
    "use strict";

    // Engines read a symbol by its Unicode name ("music sharp sign") or not at all.
    var SYMBOLS = [
        [/♯/g, " sharp"],
        [/♭/g, " flat"],
        [/♮/g, " natural"],
        [/𝄪/g, " double sharp"],
        [/·/g, ","],
        [/…/g, "."],
        [/–|—/g, ", "]
    ];

    // The abbreviated style's names, matched as whole lower-case words so part
    // names such as "Fl." keep their own reading.
    var ABBREVIATIONS = {
        sb: "semibreve", mn: "minim", cr: "crotchet", qv: "quaver", sq: "semiquaver",
        dsq: "demisemiquaver", hdsq: "hemidemisemiquaver", br: "breve", gr: "grace note",
        sh: "sharp", fl: "flat", nat: "natural", dsh: "double sharp", dfl: "double flat"
    };
    var ABBREVIATED = new RegExp("\\b(" + Object.keys(ABBREVIATIONS).join("|") + ")\\b", "g");

    // Chrome stops an utterance that runs past about fifteen seconds, so long text
    // is spoken in pieces that end where a sentence or a list item does.
    var PIECE_LENGTH = 180;

    function speakable(text) {
        var spoken = String(text);
        SYMBOLS.forEach(function (pair) {
            spoken = spoken.replace(pair[0], pair[1]);
        });
        spoken = spoken.replace(ABBREVIATED, function (word) { return ABBREVIATIONS[word]; });
        return spoken.replace(/\s+/g, " ").replace(/ ([,.])/g, "$1").trim();
    }

    function pieces(text) {
        var result = [];
        var rest = text;
        while (rest.length > PIECE_LENGTH) {
            var cut = Math.max(rest.lastIndexOf(". ", PIECE_LENGTH), rest.lastIndexOf(", ", PIECE_LENGTH));
            if (cut < PIECE_LENGTH / 3) {
                cut = rest.lastIndexOf(" ", PIECE_LENGTH);
            }
            if (cut <= 0) {
                cut = PIECE_LENGTH;
            }
            result.push(rest.slice(0, cut + 1).trim());
            rest = rest.slice(cut + 1).trim();
        }
        if (rest) {
            result.push(rest);
        }
        return result;
    }

    function deviceSpeech() {
        return Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
    }

    function available() {
        return deviceSpeech() || natural.supported();
    }

    // English voices first, the page's own variety of English ahead of the rest.
    function deviceVoices() {
        if (!deviceSpeech()) {
            return [];
        }
        var language = (document.documentElement.getAttribute("lang") || "en-GB").toLowerCase();
        return window.speechSynthesis.getVoices().filter(function (voice) {
            return /^en\b/i.test(voice.lang);
        }).sort(function (a, b) {
            var rank = function (voice) { return voice.lang.toLowerCase().replace("_", "-") === language ? 0 : 1; };
            return rank(a) - rank(b) || a.name.localeCompare(b.name);
        }).map(function (voice) {
            return { id: "device:" + voice.voiceURI, label: voice.name + " (" + voice.lang + ")", voice: voice };
        });
    }

    function onVoicesChanged(handler) {
        if (deviceSpeech() && window.speechSynthesis.addEventListener) {
            window.speechSynthesis.addEventListener("voiceschanged", handler);
        }
    }

    // The natural voices: the Kokoro model run by kokoro-js, fetched from public
    // hosts only when the reader asks for it and then kept in the browser's cache,
    // so later visits load it without a connection. The words never leave the page.
    var NATURAL_MODULE = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js";
    var NATURAL_MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
    var NATURAL_KEPT = "talkingscores.naturalVoices";
    var NATURAL_VOICES = [
        ["bf_emma", "Emma, British English"],
        ["bm_george", "George, British English"],
        ["bf_isabella", "Isabella, British English"],
        ["bm_fable", "Fable, British English"],
        ["af_heart", "Heart, American English"],
        ["am_michael", "Michael, American English"]
    ];
    var natural = (function () {
        var model = null;
        var loading = null;
        var audio = null;

        // The server marks the page when the site offers the natural voices.
        function supported() {
            return document.documentElement.getAttribute("data-natural-voices") !== null
                && Boolean(window.AudioContext && window.WebAssembly && window.fetch);
        }

        function stored() {
            try {
                return window.localStorage.getItem(NATURAL_KEPT) === "1";
            } catch (error) {
                return false;
            }
        }

        // progress(percent) is told how much of the model has arrived.
        function load(progress) {
            if (model) {
                return Promise.resolve(model);
            }
            if (loading) {
                return loading;
            }
            var files = {};
            loading = import(NATURAL_MODULE).then(function (module) {
                return module.KokoroTTS.from_pretrained(NATURAL_MODEL, {
                    dtype: "q8",
                    device: window.navigator.gpu ? "webgpu" : "wasm",
                    progress_callback: function (event) {
                        if (!progress || event.status !== "progress" || !event.total) {
                            return;
                        }
                        files[event.file] = [event.loaded, event.total];
                        var loaded = 0;
                        var total = 0;
                        Object.keys(files).forEach(function (name) {
                            loaded += files[name][0];
                            total += files[name][1];
                        });
                        progress(Math.floor(100 * loaded / total));
                    }
                });
            }).then(function (loaded) {
                model = loaded;
                try {
                    window.localStorage.setItem(NATURAL_KEPT, "1");
                } catch (error) {
                    // The model is still cached; only the note to load it next time is lost.
                }
                return model;
            }, function (error) {
                loading = null;
                throw error;
            });
            return loading;
        }

        function voices() {
            return NATURAL_VOICES.map(function (pair) {
                return { id: "natural:" + pair[0], label: pair[1] };
            });
        }

        function context() {
            if (!audio) {
                audio = new window.AudioContext();
            }
            return audio;
        }

        // Plays one piece of text; resolves when it has been heard. stopped() is
        // asked before each step, so a cancelled reading stops between steps.
        function speak(text, voice, rate, stopped, sources) {
            return model.generate(text, { voice: voice, speed: rate }).then(function (spoken) {
                if (stopped()) {
                    return;
                }
                var ctx = context();
                var buffer = ctx.createBuffer(1, spoken.audio.length, spoken.sampling_rate);
                buffer.copyToChannel(spoken.audio, 0);
                var source = ctx.createBufferSource();
                source.buffer = buffer;
                source.connect(ctx.destination);
                sources.push(source);
                return ctx.resume().then(function () {
                    return new Promise(function (resolve) {
                        source.onended = resolve;
                        source.start();
                    });
                });
            });
        }

        return {
            supported: supported,
            stored: stored,
            load: load,
            ready: function () { return Boolean(model); },
            voices: voices,
            speak: speak
        };
    })();

    // rate() returns the speaking rate, 1 being the voice's usual pace; voice()
    // returns the chosen voice's id, empty for the device's usual voice; failed()
    // is told, in words for the reader, when a natural voice cannot speak.
    function create(options) {
        var engine = window.speechSynthesis;
        var language = document.documentElement.getAttribute("lang") || "en-GB";
        var run = 0;
        // Chrome can discard an utterance it still holds no reference to before its
        // end event fires, so the one being spoken is kept here.
        var speaking = null;
        // The caller waiting on the text being spoken, told false if it is cut short.
        var cancelled = null;

        var sources = [];

        function utterance(text, rate) {
            var said = new window.SpeechSynthesisUtterance(text);
            said.lang = language;
            said.rate = rate;
            var chosen = options && options.voice ? options.voice() : "";
            if (chosen.indexOf("device:") === 0) {
                var match = deviceVoices().filter(function (item) { return item.id === chosen; })[0];
                if (match) {
                    said.voice = match.voice;
                    said.lang = match.voice.lang;
                }
            }
            return said;
        }

        function naturalVoice() {
            var chosen = options && options.voice ? options.voice() : "";
            return chosen.indexOf("natural:") === 0 && natural.ready() ? chosen.slice(8) : "";
        }

        // The natural voice speaks the pieces in turn; if it fails, the rest is
        // read in the device's voice when there is one.
        function sayNaturally(queue, voice, rate, mine, finish) {
            function stopped() {
                return mine !== run;
            }
            function next() {
                if (stopped()) {
                    return;
                }
                if (!queue.length) {
                    finish();
                    return;
                }
                natural.speak(queue.shift(), voice, rate, stopped, sources).then(next, function () {
                    if (stopped()) {
                        return;
                    }
                    if (options && options.failed) {
                        options.failed("The natural voice stopped working, so the device’s voice reads instead.");
                    }
                    if (deviceSpeech()) {
                        sayWithDevice(queue, rate, mine, finish);
                    } else {
                        finish(false);
                    }
                });
            }
            next();
        }

        function sayWithDevice(queue, rate, mine, finish) {
            function next() {
                if (mine !== run) {
                    return;
                }
                if (!queue.length) {
                    finish();
                    return;
                }
                speaking = utterance(queue.shift(), rate);
                speaking.onend = next;
                speaking.onerror = function (event) {
                    if (mine !== run || event.error === "interrupted" || event.error === "canceled") {
                        return;
                    }
                    // A voice that fails on one piece still lets the rest be heard.
                    next();
                };
                engine.speak(speaking);
            }
            next();
        }

        // Speaks the text and calls done(true) once it has all been heard, or
        // done(false) when something else is spoken or the reading is cancelled.
        function say(text, done) {
            cancel();
            var mine = run;
            var queue = pieces(speakable(text));
            var rate = options && options.rate ? options.rate() : 1;
            function finish(heard) {
                if (mine !== run) {
                    return;
                }
                speaking = null;
                cancelled = null;
                if (done) {
                    done(heard !== false);
                }
            }
            cancelled = done || null;
            var voice = naturalVoice();
            if (voice) {
                sayNaturally(queue, voice, rate, mine, finish);
            } else {
                sayWithDevice(queue, rate, mine, finish);
            }
        }

        function cancel() {
            run++;
            speaking = null;
            var waiting = cancelled;
            cancelled = null;
            if (engine && (engine.speaking || engine.pending)) {
                engine.cancel();
            }
            sources.splice(0).forEach(function (source) {
                try {
                    source.stop();
                } catch (error) {
                    // Already finished.
                }
            });
            if (waiting) {
                waiting(false);
            }
        }

        return { say: say, cancel: cancel };
    }

    window.TalkingScoresSpeech = {
        available: available,
        create: create,
        speakable: speakable,
        pieces: pieces,
        deviceVoices: deviceVoices,
        onVoicesChanged: onVoicesChanged,
        natural: natural
    };
})();
