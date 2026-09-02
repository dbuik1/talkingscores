/* Score reader behaviour: one open group of bars, a toolbar to move between groups,
   reading settings kept on this device, and playback of the open group.
   Without this file every group renders open and the toolbar stays hidden. */
(function () {
    "use strict";

    var STORAGE_KEY = "talkingscores.reader";
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

    function applyAppearance(settings) {
        var size = settings.size;
        if (size === "large" || size === "xlarge" || size === "browser") {
            root.setAttribute("data-size", size);
        } else {
            root.removeAttribute("data-size");
        }
        root.classList.toggle("stack", Boolean(settings.stack) || size === "xlarge");
        var theme = settings.theme;
        if (theme === "light" || theme === "dark" || theme === "contrast") {
            root.setAttribute("data-theme", theme);
        } else if (pageTheme) {
            root.setAttribute("data-theme", pageTheme);
        } else {
            root.removeAttribute("data-theme");
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
        var bars = Array.prototype.slice.call(main.querySelectorAll(".bar"));
        if (!bars.length) {
            return;
        }
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
                return {section: section, body: body, toggle: toggle, start: start, end: end, members: members};
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
                    button.innerHTML = 'Next<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>';
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
                preview.textContent = group.toggle.nextSibling ? group.section.querySelector(".prev").textContent : "";
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
            if (scoreKey) {
                prefs.positions = prefs.positions || {};
                prefs.positions[scoreKey] = group.start;
                savePrefs();
            }
            if (player) {
                player.groupChanged(group);
            }
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
                gotoError.textContent = "Enter a bar number from " + data.firstNumberedBar + " to " + data.lastBar + ".";
                gotoInput.focus();
                return;
            }
            gotoError.textContent = "";
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

        // Toolbar
        if (toolbar) {
            toolbar.hidden = false;
            document.getElementById("goto-go").addEventListener("click", goToTypedBar);
            gotoInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    goToTypedBar();
                }
            });
            document.getElementById("previous-group").addEventListener("click", function () {
                if (current === 0) {
                    announce("This is the first group.");
                    return;
                }
                show(current - 1, true);
            });
            document.getElementById("next-group").addEventListener("click", function () {
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
            var readAgain = document.getElementById("read-again");
            if (readAgain) {
                readAgain.addEventListener("click", function () {
                    var group = groups[current];
                    announce(rangeLabel(group.start, group.end, true) + ". " + group.body.textContent.replace(/\s+/g, " ").trim());
                });
            }
        }

        function announce(text) {
            if (!live) {
                return;
            }
            live.textContent = "";
            window.setTimeout(function () { live.textContent = text; }, 50);
        }

        // Reading settings
        var settingsForm = document.getElementById("reading-settings-form");
        if (settingsForm) {
            var sizeInputs = settingsForm.querySelectorAll('input[name="size"]');
            Array.prototype.forEach.call(sizeInputs, function (input) {
                input.checked = input.value === (prefs.size || "standard");
                input.addEventListener("change", function () {
                    prefs.size = input.value === "standard" ? undefined : input.value;
                    applyAppearance(prefs);
                    savePrefs();
                });
            });
            var stack = document.getElementById("setting-stack");
            stack.checked = Boolean(prefs.stack);
            stack.addEventListener("change", function () {
                prefs.stack = stack.checked || undefined;
                applyAppearance(prefs);
                savePrefs();
            });
            var theme = document.getElementById("setting-theme");
            theme.value = prefs.theme || "system";
            theme.addEventListener("change", function () {
                prefs.theme = theme.value === "system" ? undefined : theme.value;
                applyAppearance(prefs);
                savePrefs();
            });
        }

        var printButton = document.getElementById("print-score");
        if (printButton) {
            printButton.addEventListener("click", function () { window.print(); });
        }

        // Playback of the open group. The player is a separate script when audio is available.
        var player = null;
        if (data.midi && window.TalkingScoresPlayer) {
            player = window.TalkingScoresPlayer(data, {
                status: document.getElementById("playback-status-text"),
                play: document.getElementById("play-group"),
                stop: document.getElementById("stop-playback"),
                speed: document.getElementById("speed"),
                rangeLabel: rangeLabel
            });
        }

        buildGroups(barsPerGroup);
        var startBar = data.firstBar;
        if (window.location.hash) {
            var match = /^#(?:group|bar)-(\d+)$/.exec(window.location.hash);
            if (match) {
                startBar = parseInt(match[1], 10);
            }
        } else if (scoreKey && prefs.positions && typeof prefs.positions[scoreKey] === "number") {
            startBar = prefs.positions[scoreKey];
        }
        var startIndex = groupIndexForBar(startBar);
        show(startIndex < 0 ? 0 : startIndex, false);
    });
})();
