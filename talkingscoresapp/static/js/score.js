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

        function rangeLabel(start, end, capital) {
            if (start === data.pickupBar && end === data.pickupBar) {
                return capital ? "Pickup bar" : "pickup bar";
            }
            if (start === end) {
                return (capital ? "Bar " : "bar ") + start;
            }
            return (capital ? "Bars " : "bars ") + start + " to " + end;
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
                text.textContent = positionText(group) + (next ? " Next: " + rangeLabel(next.start, next.end, false) + "." : " This is the end of the score.");
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
            var text = first.textContent.replace(/\s+/g, " ").trim();
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
                preview.textContent = group.preview.textContent;
                item.appendChild(preview);
                contents.appendChild(item);
            });
        }

        function show(index, focus) {
            current = Math.max(0, Math.min(groups.length - 1, index));
            groups.forEach(function (group, i) {
                var open = i === current;
                group.section.classList.toggle("current", open);
                group.toggle.setAttribute("aria-expanded", open ? "true" : "false");
            });
            var group = groups[current];
            if (position) {
                position.textContent = positionText(group).replace(/\.$/, "");
            }
            if (gotoInput) {
                gotoInput.value = String(group.start);
            }
            if (focus) {
                group.section.scrollIntoView({block: "start", behavior: reducedMotion() ? "auto" : "smooth"});
                group.toggle.focus({preventScroll: true});
            }
            if (window.history && window.history.replaceState && window.location.hash !== "#" + group.section.id) {
                window.history.replaceState(null, "", "#" + group.section.id);
            }
            rememberPosition(group.start);
            if (midiLink) {
                midiLink.href = data.midi.base + "?start=" + group.start + "&end=" + group.end;
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
            var number = parseInt(gotoInput.value, 10);
            var index = isNaN(number) ? -1 : groupIndexForBar(number);
            if (index < 0) {
                var message = "Enter a bar number from " + data.firstNumberedBar + " to " + data.lastBar + ".";
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
            show(index, true);
        }

        function regroup(size) {
            var currentStart = groups.length ? groups[current].start : data.firstBar;
            barsPerGroup = size;
            buildGroups(size);
            show(Math.max(0, groupIndexForBar(currentStart)), false);
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
                announce(rangeLabel(group.start, group.end, true) + ". " + readableText(group.body).replace(/\s+/g, " ").trim());
            });
        }

        function announce(text) {
            if (!live) {
                return;
            }
            live.textContent = "";
            window.setTimeout(function () { live.textContent = text; }, 50);
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
                }
            }

            Array.prototype.forEach.call(sizeInputs, function (input) {
                input.checked = input.value === (prefs.size || "standard");
                input.addEventListener("change", function () {
                    prefs.size = input.value === "standard" ? undefined : input.value;
                    applyAppearance(prefs);
                    reflect();
                    savePrefs();
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
        // repeat mean the same in any score. The instruments and the balance name
        // positions in one score's part list, so they are kept against that score.
        var SHARED_PLAYBACK = ["speed", "click", "repeat"];
        var SCORE_PLAYBACK = ["voice", "forward"];

        function rememberPlayback(name, value) {
            if (SCORE_PLAYBACK.indexOf(name) === -1) {
                prefs.playback = prefs.playback || {};
                prefs.playback[name] = value;
            } else if (scoreKey) {
                prefs.playbackByScore = prefs.playbackByScore || {};
                prefs.playbackByScore[scoreKey] = prefs.playbackByScore[scoreKey] || {};
                prefs.playbackByScore[scoreKey][name] = value;
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
        var stopButton = document.getElementById("stop-playback");
        if (data.midi && window.TalkingScoresPlayer) {
            var playbackControls = {
                status: document.getElementById("playback-status-text"),
                announce: announce,
                play: playButton,
                stop: stopButton,
                speed: document.getElementById("speed"),
                voice: document.getElementById("setting-voice"),
                click: document.getElementById("setting-click"),
                forward: document.getElementById("setting-forward"),
                repeat: document.getElementById("setting-repeat"),
                rangeLabel: rangeLabel,
                remember: rememberPlayback
            };
            restorePlayback(playbackControls);
            player = window.TalkingScoresPlayer(data, playbackControls);
        } else if (playButton) {
            playButton.disabled = true;
            if (stopButton) {
                stopButton.disabled = true;
            }
            var statusText = document.getElementById("playback-status-text");
            if (statusText) {
                statusText.textContent = "A downloaded page cannot play the score. Open it on the Talking Scores website to hear these bars.";
            }
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
