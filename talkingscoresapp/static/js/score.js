/* Score reader behaviour: one open group of bars, a toolbar to move between groups,
   reading settings kept on this device, and playback of the open group.
   Without this file every group renders open and the toolbar stays hidden. */
(function () {
    "use strict";

    var STORAGE_KEY = "talkingscores.reader";
    var REMEMBERED_SCORES = 40;
    var root = document.documentElement;
    var pageTheme = root.getAttribute("data-theme");
    var prefs = loadPrefs();

    // Applied before the body is parsed so the page paints in the saved size and colours.
    root.classList.add("js");
    applyAppearance(prefs);

    function loadPrefs() {
        try {
            var stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
            return stored && typeof stored === "object" ? stored : {};
        } catch (error) {
            return {};
        }
    }

    function savePrefs() {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
        } catch (error) {
            // Private windows and blocked storage fall back to this visit only.
        }
    }

    function stacked(settings) {
        return Boolean(settings.stack) || settings.size === "xlarge";
    }

    // A saved choice wins; a downloaded page's own colours come next; otherwise the system setting.
    function effectiveTheme(settings) {
        var theme = settings.theme;
        if (theme === "light" || theme === "dark" || theme === "contrast" || theme === "system") {
            return theme;
        }
        return pageTheme || "system";
    }

    function applyAppearance(settings) {
        var size = settings.size;
        if (size === "large" || size === "xlarge" || size === "browser") {
            root.setAttribute("data-size", size);
        } else {
            root.removeAttribute("data-size");
        }
        root.classList.toggle("stack", stacked(settings));
        var theme = effectiveTheme(settings);
        if (theme === "system") {
            root.removeAttribute("data-theme");
        } else {
            root.setAttribute("data-theme", theme);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        var dataNode = document.getElementById("score-data");
        if (!dataNode) {
            return;
        }
        var data = JSON.parse(dataNode.textContent);
        var scoreKey = data.key;
        var main = document.getElementById("score");
        var bars = main ? Array.prototype.slice.call(main.querySelectorAll(".bar")) : [];
        var toolbar = document.getElementById("toolbar");
        var gotoInput = document.getElementById("goto-bar");
        var gotoError = document.getElementById("goto-error");
        var position = document.getElementById("position");
        var perGroup = document.getElementById("bars-per-group");
        var contents = document.getElementById("contents-list");
        var live = document.getElementById("reader-live");
        var clearLive = 0;
        var groups = [];
        var current = 0;
        var barsPerGroup = data.barsPerGroup;
        var player = null;

        wireSettings();
        var printButton = document.getElementById("print-score");
        if (printButton) {
            printButton.addEventListener("click", function () { window.print(); });
        }
        // Chrome prints a closed details as its summary alone, so every one opens for the printer.
        window.addEventListener("beforeprint", function () {
            Array.prototype.forEach.call(document.querySelectorAll(".part details:not([open])"), function (details) {
                details.setAttribute("open", "");
                details.setAttribute("data-opened-for-print", "");
            });
        });
        window.addEventListener("afterprint", function () {
            Array.prototype.forEach.call(document.querySelectorAll("[data-opened-for-print]"), function (details) {
                details.removeAttribute("open");
                details.removeAttribute("data-opened-for-print");
            });
        });

        if (!bars.length) {
            return;
        }

        if (prefs.barsPerGroup && perGroup && hasOption(perGroup, String(prefs.barsPerGroup))) {
            barsPerGroup = prefs.barsPerGroup;
        }
        if (perGroup) {
            perGroup.value = String(barsPerGroup);
        }

        function hasOption(select, value) {
            return Array.prototype.some.call(select.options, function (option) { return option.value === value; });
        }

        function barNumber(bar) {
            return parseInt(bar.getAttribute("data-bar"), 10);
        }

        // Bars are counted in the order they are written, so a number always reaches
        // one bar; what the page prints is what the reader sees and types, and both
        // halves of a repeat ending print the same number.
        var printedNumbers = {};
        var countedForPrinted = {};
        bars.forEach(function (bar) {
            var counted = barNumber(bar);
            var printed = bar.getAttribute("data-printed") || String(counted);
            printedNumbers[counted] = printed;
            var typed = parseInt(printed, 10);
            if (!isNaN(typed) && !(typed in countedForPrinted)) {
                countedForPrinted[typed] = counted;
            }
        });

        function printedNumber(counted) {
            return printedNumbers[counted] || String(counted);
        }

        function rangeLabel(start, end, capital) {
            if (start === data.pickupBar && end === data.pickupBar) {
                return capital ? "Pickup bar" : "pickup bar";
            }
            if (start === end) {
                return (capital ? "Bar " : "bar ") + printedNumber(start);
            }
            return (capital ? "Bars " : "bars ") + printedNumber(start) + " to " + printedNumber(end);
        }

        function buildGroups(size) {
            var plan = [];
            var chunk = [];
            bars.forEach(function (bar) {
                var number = barNumber(bar);
                if (number === data.pickupBar) {
                    plan.push([bar]);
                    return;
                }
                chunk.push(bar);
                if (chunk.length === size) {
                    plan.push(chunk);
                    chunk = [];
                }
            });
            if (chunk.length) {
                plan.push(chunk);
            }
            main.textContent = "";
            groups = plan.map(function (members, index) {
                var start = barNumber(members[0]);
                var end = barNumber(members[members.length - 1]);
                var section = document.createElement("section");
                section.className = "group";
                section.id = "group-" + start;
                var heading = document.createElement("h2");
                var toggle = document.createElement("button");
                toggle.type = "button";
                toggle.className = "group-toggle";
                toggle.setAttribute("aria-expanded", "false");
                toggle.setAttribute("aria-controls", section.id + "-body");
                toggle.innerHTML = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>';
                toggle.appendChild(document.createTextNode(rangeLabel(start, end, true)));
                toggle.addEventListener("click", function () {
                    if (index === current) {
                        return;
                    }
                    show(index, true);
                });
                heading.appendChild(toggle);
                var preview = document.createElement("span");
                preview.className = "prev";
                preview.setAttribute("aria-hidden", "true");
                preview.textContent = previewText(members[0]);
                heading.appendChild(preview);
                section.appendChild(heading);
                var body = document.createElement("div");
                body.className = "body";
                body.id = section.id + "-body";
                members.forEach(function (bar) { body.appendChild(bar); });
                section.appendChild(body);
                return {section: section, body: body, toggle: toggle, preview: preview, start: start, end: end, members: members};
            });
            groups.forEach(function (group, index) {
                var endline = document.createElement("div");
                endline.className = "endline";
                var text = document.createElement("p");
                var next = groups[index + 1];
                text.textContent = positionText(group) + (next ? " Next: " + rangeLabel(next.start, next.end, false) + "." : " This is the last group.");
                endline.appendChild(text);
                if (next) {
                    var button = document.createElement("button");
                    button.type = "button";
                    button.className = "btn";
                    button.innerHTML = 'Next group<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>';
                    button.addEventListener("click", function () { show(index + 1, true); });
                    endline.appendChild(button);
                }
                group.body.appendChild(endline);
                main.appendChild(group.section);
            });
            buildContents();
        }

        function previewText(bar) {
            var first = bar.querySelector(".same, .beats li");
            if (!first) {
                return "";
            }
            var text = readableText(first).replace(/\s+/g, " ").trim();
            var label = bar.querySelector(".part .label");
            if (label) {
                text = label.textContent.trim() + ": " + text;
            }
            return text.length > 70 ? text.slice(0, 69).replace(/\s\S*$/, "") + "…" : text;
        }

        function positionText(group) {
            if (group.start === data.pickupBar && group.end === data.pickupBar) {
                return "Pickup bar.";
            }
            return rangeLabel(group.start, group.end, true) + " of " + data.totalBars + ".";
        }

        function buildContents() {
            if (!contents) {
                return;
            }
            contents.textContent = "";
            groups.forEach(function (group, index) {
                var item = document.createElement("li");
                var link = document.createElement("a");
                link.href = "#" + group.section.id;
                link.textContent = rangeLabel(group.start, group.end, true);
                link.addEventListener("click", function (event) {
                    event.preventDefault();
                    show(index, true);
                });
                item.appendChild(link);
                var preview = document.createElement("span");
                preview.className = "prev";
                preview.setAttribute("aria-hidden", "true");
                preview.textContent = group.preview.textContent;
                item.appendChild(preview);
                contents.appendChild(item);
            });
        }

        function show(index, focus, keepTyped) {
            current = Math.max(0, Math.min(groups.length - 1, index));
            groups.forEach(function (group, i) {
                var open = i === current;
                group.section.classList.toggle("current", open);
                // A long score has one toggle per group, and tabbing back through
                // all of them to reach the toolbar costs more than it saves: the
                // contents list, Previous, Next and the bar box all reach a group.
                group.toggle.tabIndex = open ? 0 : -1;
                // Only one group is open at a time, so the open one's own toggle has
                // nothing to do: it says where the reader is rather than offering a
                // state they can change.
                if (open) {
                    group.toggle.removeAttribute("aria-expanded");
                    group.toggle.removeAttribute("aria-controls");
                    group.toggle.setAttribute("aria-current", "true");
                    group.toggle.setAttribute("aria-disabled", "true");
                } else {
                    group.toggle.setAttribute("aria-expanded", "false");
                    group.toggle.setAttribute("aria-controls", group.section.id + "-body");
                    group.toggle.removeAttribute("aria-current");
                    group.toggle.removeAttribute("aria-disabled");
                }
            });
            var group = groups[current];
            if (reading && reading.group !== group) {
                stopReading(true);
            }
            if (position) {
                position.textContent = positionText(group).replace(/\.$/, "");
            }
            if (gotoInput && !keepTyped) {
                gotoInput.value = String(group.start);
            }
            if (focus) {
                group.section.scrollIntoView({block: "start", behavior: reducedMotion() ? "auto" : "smooth"});
                group.toggle.focus({preventScroll: true});
            }
            if (focus && window.history && window.history.replaceState && window.location.hash !== "#" + group.section.id) {
                window.history.replaceState(null, "", "#" + group.section.id);
            }
            rememberPosition(group.start);
            if (midiLink) {
                midiLink.href = data.midi.base + "?start=" + group.start + "&end=" + group.end;
                midiLink.textContent = "Download " + rangeLabel(group.start, group.end, false) + " as MIDI";
            }
            if (player) {
                player.groupChanged(group);
            }
        }

        function rememberPosition(start) {
            if (!scoreKey) {
                return;
            }
            var positions = prefs.positions && typeof prefs.positions === "object" ? prefs.positions : {};
            delete positions[scoreKey];
            var keys = Object.keys(positions);
            while (keys.length >= REMEMBERED_SCORES) {
                delete positions[keys.shift()];
            }
            positions[scoreKey] = start;
            prefs.positions = positions;
            savePrefs();
        }

        function reducedMotion() {
            return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        }

        function groupIndexForBar(number) {
            for (var i = 0; i < groups.length; i += 1) {
                if (number >= groups[i].start && number <= groups[i].end) {
                    return i;
                }
            }
            return -1;
        }

        function goToTypedBar() {
            var typed = parseInt(gotoInput.value, 10);
            // A number typed here is the one printed on the page. Where two bars print
            // it, as the two halves of a repeat ending do, the first one is opened.
            var number = isNaN(typed) ? NaN : countedForPrinted[typed];
            var index = number === undefined || isNaN(number) ? -1 : groupIndexForBar(number);
            if (index < 0) {
                var message = "Enter a bar number from " + data.firstPrintedBar
                    + " to " + data.lastPrintedBar + ".";
                gotoError.textContent = message;
                gotoInput.setAttribute("aria-invalid", "true");
                if (document.activeElement === gotoInput) {
                    announce(message);
                } else {
                    gotoInput.focus();
                }
                return;
            }
            gotoError.textContent = "";
            gotoInput.removeAttribute("aria-invalid");
            show(index, true, true);
        }

        function regroup(size) {
            var currentStart = groups.length ? groups[current].start : data.firstBar;
            barsPerGroup = size;
            buildGroups(size);
            show(Math.max(0, groupIndexForBar(currentStart)), false);
            announce(positionText(groups[current]));
            prefs.barsPerGroup = size;
            savePrefs();
        }

        // Text as a reader would meet it: closed details contribute their summary only.
        function readableText(node) {
            if (node.nodeType === 3) {
                return node.textContent;
            }
            if (node.nodeType !== 1 || node.classList.contains("endline") || node.getAttribute("aria-hidden") === "true") {
                return "";
            }
            if (node.tagName === "DETAILS" && !node.open) {
                var summary = node.querySelector("summary");
                return summary ? readableText(summary) + " " : "";
            }
            var text = "";
            Array.prototype.forEach.call(node.childNodes, function (child) {
                text += readableText(child);
            });
            return text + " ";
        }

        function wire(id, event, handler) {
            var element = document.getElementById(id);
            if (element) {
                element.addEventListener(event, handler);
            }
            return element;
        }

        // Toolbar
        if (toolbar) {
            toolbar.hidden = false;
            wire("goto-go", "click", goToTypedBar);
            if (gotoInput) {
                gotoInput.addEventListener("keydown", function (event) {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        goToTypedBar();
                    }
                });
            }
            wire("previous-group", "click", function () {
                if (current === 0) {
                    announce("This is the first group.");
                    return;
                }
                show(current - 1, true);
            });
            wire("next-group", "click", function () {
                if (current === groups.length - 1) {
                    announce("This is the last group.");
                    return;
                }
                show(current + 1, true);
            });
            if (perGroup) {
                perGroup.addEventListener("change", function () {
                    regroup(parseInt(perGroup.value, 10));
                });
            }
            wire("read-again", "click", function () {
                var group = groups[current];
                // A group runs to hundreds of characters, and a live region reads
                // them out in one piece that cannot be paused or skipped. The
                // button puts the reader at the top of the group's text instead,
                // so the reading stays under their own commands.
                group.body.setAttribute("tabindex", "-1");
                group.body.focus();
                group.section.scrollIntoView({block: "start", behavior: reducedMotion() ? "auto" : "smooth"});
                announce(rangeLabel(group.start, group.end, true) + ".");
            });
        }

        function announce(text) {
            // A screen reader would speak over the voice reading the bars, so the
            // live region waits until the reading ends; the status lines still change.
            if (!live || reading) {
                return;
            }
            live.textContent = "";
            window.setTimeout(function () { live.textContent = text; }, 50);
            window.clearTimeout(clearLive);
            clearLive = window.setTimeout(function () { live.textContent = ""; }, 10000);
        }

        function wireSettings() {
            var settingsForm = document.getElementById("reading-settings-form");
            if (!settingsForm) {
                return;
            }
            var sizeInputs = settingsForm.querySelectorAll('input[name="size"]');
            var stack = document.getElementById("setting-stack");
            var theme = document.getElementById("setting-theme");

            function reflect() {
                Array.prototype.forEach.call(sizeInputs, function (input) {
                    var card = input.closest(".size");
                    if (card) {
                        card.classList.toggle("checked", input.checked);
                    }
                });
                if (stack) {
                    // Extra large always stacks, so the box shows that and cannot be cleared.
                    stack.checked = stacked(prefs);
                    stack.disabled = prefs.size === "xlarge";
                    // A greyed box is the whole explanation to anyone reading the
                    // screen, so the reason is written out beside it as well.
                    var locked = document.getElementById("stack-locked");
                    if (locked) {
                        locked.hidden = !stack.disabled;
                    }
                }
            }

            Array.prototype.forEach.call(sizeInputs, function (input) {
                input.checked = input.value === (prefs.size || "standard");
                input.addEventListener("change", function () {
                    prefs.size = input.value === "standard" ? undefined : input.value;
                    applyAppearance(prefs);
                    reflect();
                    savePrefs();
                    // Extra large turns one note per line on and locks the box, so
                    // the side effect is said rather than left to be discovered.
                    if (stack && stack.disabled) {
                        announce("Extra large text. One note per line is on and cannot be turned off at this size.");
                    }
                });
            });
            if (stack) {
                stack.addEventListener("change", function () {
                    prefs.stack = stack.checked || undefined;
                    applyAppearance(prefs);
                    savePrefs();
                });
            }
            if (theme) {
                theme.value = effectiveTheme(prefs);
                theme.addEventListener("change", function () {
                    prefs.theme = theme.value;
                    applyAppearance(prefs);
                    savePrefs();
                });
            }
            reflect();
        }

        // Playback choices are kept alongside the reading settings, so a reader who
        // needs half speed or the click sets them once. The speed, the click and the
        // repeat and the choice of sounds mean the same in any score. The instruments
        // and the balance name positions in one score's part list, so they are kept
        // against that score.
        var SHARED_PLAYBACK = ["speed", "click", "repeat", "sampled"];
        var SCORE_PLAYBACK = ["voice", "forward"];

        function rememberPlayback(name, value) {
            if (SCORE_PLAYBACK.indexOf(name) === -1) {
                prefs.playback = prefs.playback || {};
                prefs.playback[name] = value;
            } else if (scoreKey) {
                var byScore = prefs.playbackByScore && typeof prefs.playbackByScore === "object"
                    ? prefs.playbackByScore : {};
                var kept = byScore[scoreKey] || {};
                delete byScore[scoreKey];
                var keys = Object.keys(byScore);
                while (keys.length >= REMEMBERED_SCORES) {
                    delete byScore[keys.shift()];
                }
                kept[name] = value;
                byScore[scoreKey] = kept;
                prefs.playbackByScore = byScore;
            }
            savePrefs();
        }

        function restorePlayback(playbackControls) {
            var shared = prefs.playback || {};
            var perScore = (scoreKey && prefs.playbackByScore && prefs.playbackByScore[scoreKey]) || {};
            SHARED_PLAYBACK.concat(SCORE_PLAYBACK).forEach(function (name) {
                var control = playbackControls[name];
                if (!control) {
                    return;
                }
                var saved = SCORE_PLAYBACK.indexOf(name) === -1 ? shared[name] : perScore[name];
                if (saved !== undefined) {
                    if (control.type === "checkbox") {
                        control.checked = Boolean(saved);
                    } else {
                        // A saved choice from a score with different parts, or from an
                        // earlier list of speeds, leaves the control on what the page
                        // was written with rather than on its first option.
                        var written = control.value;
                        control.value = saved;
                        if (control.selectedIndex === -1) {
                            control.value = written;
                        }
                    }
                }
                control.addEventListener("change", function () {
                    rememberPlayback(name, control.type === "checkbox" ? control.checked : control.value);
                });
            });
        }

        // The saved file follows the open group, so it holds the bars on screen.
        var midiLink = data.midi ? document.getElementById("download-midi") : null;

        // Playback of the open group. The player is a separate script when audio is available.
        var playButton = document.getElementById("play-group");
        var playAllButton = document.getElementById("play-whole-score");
        var stopButton = document.getElementById("stop-playback");
        if (data.midi && window.TalkingScoresPlayer) {
            var playbackControls = {
                status: document.getElementById("playback-status-text"),
                announce: announce,
                play: playButton,
                playAll: playAllButton,
                stop: stopButton,
                speed: document.getElementById("speed"),
                voice: document.getElementById("setting-voice"),
                click: document.getElementById("setting-click"),
                forward: document.getElementById("setting-forward"),
                repeat: document.getElementById("setting-repeat"),
                sampled: document.getElementById("setting-sampled"),
                rangeLabel: rangeLabel,
                remember: rememberPlayback
            };
            restorePlayback(playbackControls);
            player = window.TalkingScoresPlayer(data, playbackControls);
        } else if (playButton) {
            playButton.disabled = true;
            [playAllButton, stopButton].forEach(function (button) {
                if (button) {
                    button.disabled = true;
                }
            });
            var statusText = document.getElementById("playback-status-text");
            if (statusText) {
                statusText.textContent = "A downloaded page cannot play the music. Open it on the Talking Scores website to hear these bars.";
            }
        }


        // Reading aloud: the open group's words in the device's own voice, bar by
        // bar, with each bar played after its words when the reader asks for it.
        var readAloudButton = document.getElementById("read-aloud");
        var readAloudStatus = document.getElementById("read-aloud-status");
        var readAloudText = document.getElementById("read-aloud-status-text");
        var readAloudSettings = document.getElementById("read-aloud-settings");
        var readingSpeed = document.getElementById("setting-reading-speed");
        var readAndPlay = document.getElementById("setting-read-and-play");
        var sayBars = document.getElementById("setting-say-bars");
        var speech = null;
        var reading = null;

        if (readAloudButton && window.TalkingScoresSpeech && window.TalkingScoresSpeech.available()) {
            speech = window.TalkingScoresSpeech.create({
                rate: function () {
                    var chosen = readingSpeed ? parseInt(readingSpeed.value, 10) : 100;
                    return (chosen > 0 ? chosen : 100) / 100;
                }
            });
            [readAloudButton, readAloudStatus, readAloudSettings].forEach(function (element) {
                if (element) {
                    element.hidden = false;
                }
            });
            restoreReading();
            readAloudButton.addEventListener("click", function () {
                if (reading) {
                    stopReading(true);
                } else {
                    readAloud();
                }
            });
            // Playback and reading aloud share the one speaker, so starting either
            // ends the other.
            // The player has already acted on these presses, so the reading stops
            // without stopping the playback the reader has just asked for.
            [playButton, playAllButton].forEach(function (button) {
                if (button) {
                    button.addEventListener("click", function () {
                        if (reading) {
                            stopReading(false, true);
                        }
                    });
                }
            });
            // The player's own answer to Stop was held back while the voice was
            // speaking, so the reading gives it instead.
            if (stopButton) {
                stopButton.addEventListener("click", function () {
                    if (reading) {
                        stopReading(true, true);
                    }
                });
            }
            if (player && playbackControls) {
                playbackControls.sayBars = sayBars;
                playbackControls.sayBar = function (number) {
                    // Each bar read aloud already starts with its number.
                    if (!reading) {
                        speech.say(number === data.pickupBar ? "Pickup" : printedNumber(number));
                    }
                };
            }
        }

        // The reading settings mean the same in any score, so they are kept once.
        function restoreReading() {
            var saved = prefs.readAloud && typeof prefs.readAloud === "object" ? prefs.readAloud : {};
            [["speed", readingSpeed], ["andPlay", readAndPlay], ["sayBars", sayBars]].forEach(function (pair) {
                var name = pair[0];
                var control = pair[1];
                if (!control) {
                    return;
                }
                if (saved[name] !== undefined) {
                    if (control.type === "checkbox") {
                        control.checked = Boolean(saved[name]);
                    } else {
                        var written = control.value;
                        control.value = saved[name];
                        if (control.selectedIndex === -1) {
                            control.value = written;
                        }
                    }
                }
                control.addEventListener("change", function () {
                    prefs.readAloud = prefs.readAloud && typeof prefs.readAloud === "object" ? prefs.readAloud : {};
                    prefs.readAloud[name] = control.type === "checkbox" ? control.checked : control.value;
                    savePrefs();
                });
            });
        }

        function readingState(text) {
            if (readAloudText) {
                readAloudText.textContent = text;
            }
        }

        function readingButton(active) {
            var label = readAloudButton.querySelector(".label") || readAloudButton;
            label.textContent = active ? "Stop reading aloud" : "Read this group aloud";
        }

        // The words of one bar as the page writes them, every note included: a
        // closed "Show the notes" still holds the beats, and its summary is only
        // the control that opens them.
        function spokenBar(bar) {
            var lines = [];
            Array.prototype.forEach.call(bar.querySelectorAll("h3, p, li"), function (element) {
                if (element.closest("summary") || element.closest("[aria-hidden='true']")) {
                    return;
                }
                var text;
                var beat = element.tagName === "LI" ? element.querySelector("b") : null;
                if (beat) {
                    var notes = element.querySelector(".notes");
                    text = beat.textContent + ", " + (notes ? notes.textContent : "");
                } else {
                    text = element.textContent;
                }
                text = text.replace(/\s+/g, " ").trim();
                if (text) {
                    lines.push(/[.,;:?]$/.test(text) ? text : text + ".");
                }
            });
            return lines.join(" ");
        }

        function barName(number) {
            return number === data.pickupBar ? "the pickup bar" : "bar " + printedNumber(number);
        }

        function readAloud() {
            if (player) {
                player.stop();
            }
            var group = groups[current];
            var withPlayback = Boolean(player && readAndPlay && readAndPlay.checked);
            var run = { group: group, bar: null };
            var index = 0;
            reading = run;
            readingButton(true);

            function next() {
                if (reading !== run) {
                    return;
                }
                if (index >= group.members.length) {
                    finishReading(run);
                    return;
                }
                var bar = group.members[index++];
                var number = barNumber(bar);
                run.bar = number;
                readingState("Reading " + barName(number) + ".");
                speech.say(spokenBar(bar), function (heard) {
                    if (!heard || reading !== run) {
                        return;
                    }
                    if (!withPlayback) {
                        next();
                        return;
                    }
                    readingState("Playing " + barName(number) + ".");
                    player.playOnce({ start: number, end: number }).then(function (finished) {
                        if (reading !== run) {
                            return;
                        }
                        if (finished) {
                            next();
                        } else {
                            // The player has said why the bar did not play.
                            reading = null;
                            readingButton(false);
                            readingState("Stopped at " + barName(number) + ". Press Read this group aloud to start again.");
                        }
                    });
                });
            }
            next();
        }

        function stopReading(spoken, playerDone) {
            var run = reading;
            reading = null;
            speech.cancel();
            readingButton(false);
            if (!playerDone && run && run.bar !== null && player && readAndPlay && readAndPlay.checked) {
                player.stop();
            }
            var said = run && run.bar !== null
                ? "Stopped reading at " + barName(run.bar) + ". Press Read this group aloud to start the group again."
                : "Nothing is being read.";
            readingState(said);
            if (spoken) {
                announce(said);
            }
        }

        // The end of a group names where the reading goes next, and puts the reader
        // on the control that takes them there.
        function finishReading(run) {
            reading = null;
            readingButton(false);
            var index = groups.indexOf(run.group);
            var done = "Finished reading " + rangeLabel(run.group.start, run.group.end, false) + ".";
            var said;
            if (index >= 0 && index < groups.length - 1) {
                var following = groups[index + 1];
                said = done + " Next group is " + rangeLabel(following.start, following.end, false) + ".";
                var nextButton = document.getElementById("next-group");
                if (nextButton) {
                    nextButton.focus();
                }
            } else {
                said = done + " This is the last group.";
            }
            readingState(said);
            announce(said);
        }
        buildGroups(barsPerGroup);

        function barFromHash() {
            var match = /^#(?:group|bar)-(\d+)$/.exec(window.location.hash);
            return match ? parseInt(match[1], 10) : null;
        }

        var hashBar = barFromHash();
        var startBar = data.firstBar;
        if (hashBar !== null) {
            startBar = hashBar;
        } else if (scoreKey && prefs.positions && typeof prefs.positions[scoreKey] === "number") {
            startBar = prefs.positions[scoreKey];
        }
        var startIndex = groupIndexForBar(startBar);
        show(startIndex < 0 ? 0 : startIndex, false);
        if (hashBar !== null) {
            // The browser's own jump to the fragment lands after this and clears focus, so wait for it.
            var focusGroup = function () { show(current, true); };
            if (document.readyState === "complete") {
                window.setTimeout(focusGroup, 0);
            } else {
                window.addEventListener("load", function () { window.setTimeout(focusGroup, 0); });
            }
        }

        window.addEventListener("hashchange", function () {
            var number = barFromHash();
            if (number === null) {
                return;
            }
            var index = groupIndexForBar(number);
            if (index >= 0 && index !== current) {
                show(index, true);
            }
        });
    });
})();
