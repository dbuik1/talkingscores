import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "..", "speech.js"), "utf8");

function load(window) {
    new Function("window", "document", source)(window, {
        documentElement: { getAttribute: () => "en-GB" }
    });
    return window.TalkingScoresSpeech;
}

const { speakable, pieces } = load({});

test("accidental symbols are spoken as words", () => {
    assert.equal(speakable("B♭ major (2 flats: B♭, E♭)"), "B flat major (2 flats: B flat, E flat)");
    assert.equal(speakable("crotchet F♯, G♮"), "crotchet F sharp, G natural");
    assert.equal(speakable("C𝄪"), "C double sharp");
});

test("the abbreviated style is spoken in full", () => {
    assert.equal(speakable("qv C sh, dsq E fl"), "quaver C sharp, demisemiquaver E flat");
});

test("a part name that looks like an abbreviation keeps its own reading", () => {
    assert.equal(speakable("Fl. 1"), "Fl. 1");
    assert.equal(speakable("Brass"), "Brass");
});

test("separators engines misread become pauses", () => {
    assert.equal(speakable("C major · 3 4 · Flute"), "C major, 3 4, Flute");
});

test("long text is spoken in pieces that end at a sentence or a list item", () => {
    const text = Array.from({ length: 30 }, (_, i) => "Beat " + (i + 1) + ", crotchet C").join(". ") + ".";
    const parts = pieces(text);
    assert.ok(parts.length > 1);
    parts.forEach(part => assert.ok(part.length <= 181, part));
    assert.equal(parts.join(" "), text);
    parts.slice(0, -1).forEach(part => assert.match(part, /[.,]$/));
});

test("reading is unavailable where the browser has no speech", () => {
    assert.equal(load({}).available(), false);
});

test("a reading cut short tells its caller it was not heard", () => {
    const spoken = [];
    const engine = {
        speaking: false, pending: false,
        speak(utterance) { spoken.push(utterance); this.speaking = true; },
        cancel() { this.speaking = false; }
    };
    function Utterance(text) { this.text = text; }
    const speech = load({ speechSynthesis: engine, SpeechSynthesisUtterance: Utterance });
    assert.equal(speech.available(), true);
    const reader = speech.create({ rate: () => 1.5 });
    const outcomes = [];
    reader.say("Bar 1. Beat 1, minim high G.", heard => outcomes.push(["first", heard]));
    assert.equal(spoken.length, 1);
    assert.equal(spoken[0].rate, 1.5);
    assert.equal(spoken[0].lang, "en-GB");
    reader.say("Bar 2.", heard => outcomes.push(["second", heard]));
    assert.deepEqual(outcomes, [["first", false]]);
    spoken[1].onend();
    assert.deepEqual(outcomes, [["first", false], ["second", true]]);
    // An end event from the cut-short reading changes nothing.
    spoken[0].onend();
    assert.deepEqual(outcomes, [["first", false], ["second", true]]);
});
