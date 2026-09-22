/* Reading bars aloud with the device's own speech voice. The words are the ones
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

    function available() {
        return Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
    }

    // rate() returns the speaking rate, 1 being the voice's usual pace.
    function create(options) {
        var engine = window.speechSynthesis;
        var language = document.documentElement.getAttribute("lang") || "en-GB";
        var run = 0;
        // Chrome can discard an utterance it still holds no reference to before its
        // end event fires, so the one being spoken is kept here.
        var speaking = null;
        // The caller waiting on the text being spoken, told false if it is cut short.
        var cancelled = null;

        function utterance(text, rate) {
            var said = new window.SpeechSynthesisUtterance(text);
            said.lang = language;
            said.rate = rate;
            return said;
        }

        // Speaks the text and calls done(true) once it has all been heard, or
        // done(false) when something else is spoken or the reading is cancelled.
        function say(text, done) {
            cancel();
            var mine = run;
            var queue = pieces(speakable(text));
            var rate = options && options.rate ? options.rate() : 1;
            function next() {
                if (mine !== run) {
                    return;
                }
                if (!queue.length) {
                    speaking = null;
                    cancelled = null;
                    if (done) {
                        done(true);
                    }
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
            cancelled = done || null;
            next();
        }

        function cancel() {
            run++;
            speaking = null;
            var waiting = cancelled;
            cancelled = null;
            if (engine.speaking || engine.pending) {
                engine.cancel();
            }
            if (waiting) {
                waiting(false);
            }
        }

        return { say: say, cancel: cancel };
    }

    window.TalkingScoresSpeech = { available: available, create: create, speakable: speakable, pieces: pieces };
})();
