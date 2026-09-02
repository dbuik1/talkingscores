/* Playback of the open group through the MIDI player loaded on the page. */
(function () {
    "use strict";

    window.TalkingScoresPlayer = function (data, controls) {
        var group = null;
        var playing = false;

        function label(item) {
            return controls.rangeLabel(item.start, item.end, false);
        }

        function status(text) {
            if (controls.status) {
                controls.status.textContent = text;
            }
        }

        function midiUrl() {
            var speed = controls.speed ? controls.speed.value : "100";
            var voice = controls.voice ? controls.voice.value : data.midi.voices[0].query;
            var click = controls.click && controls.click.checked ? "be" : "n";
            return data.midi.base + "?" + data.midi.query + "&" + voice + "&start=" + group.start + "&end=" + group.end + "&t=" + speed + "&c=" + click;
        }

        function stop() {
            if (window.MIDIjs) {
                window.MIDIjs.stop();
            }
            if (playing) {
                playing = false;
                status("Stopped. " + capital(label(group)) + " ready.");
            }
        }

        function play() {
            if (!window.MIDIjs) {
                status("The player has not loaded. Check your connection and reload the page.");
                return;
            }
            stop();
            playing = true;
            status("Playing " + label(group) + ".");
            window.MIDIjs.play(midiUrl());
        }

        function capital(text) {
            return text.charAt(0).toUpperCase() + text.slice(1);
        }

        if (controls.play) {
            controls.play.addEventListener("click", play);
        }
        if (controls.stop) {
            controls.stop.addEventListener("click", stop);
        }
        if (controls.speed) {
            controls.speed.addEventListener("change", function () {
                if (playing) {
                    play();
                }
            });
        }

        return {
            groupChanged: function (next) {
                if (group && next !== group) {
                    stop();
                }
                group = next;
                status("Stopped. " + capital(label(group)) + " ready.");
            }
        };
    };
})();
