/* Reading a standard MIDI file: run with `node --test talkingscoresapp/static/js/tests`. */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "..", "player.js"), "utf8");
const scope = { window: {} };
new Function("window", source)(scope.window);
const { parseMidi, collect } = scope.window.TalkingScoresPlayer.reading;

const DIVISION = 96;

function variable(value) {
    const bytes = [value & 0x7f];
    let rest = value >> 7;
    while (rest) {
        bytes.unshift((rest & 0x7f) | 0x80);
        rest >>= 7;
    }
    return bytes;
}

function chunk(name, body) {
    const length = body.length;
    return [...name].map(c => c.charCodeAt(0)).concat(
        [(length >> 24) & 0xff, (length >> 16) & 0xff, (length >> 8) & 0xff, length & 0xff], body);
}

function header({ format = 1, tracks = 1, division = DIVISION } = {}) {
    return chunk("MThd", [(format >> 8) & 0xff, format & 0xff,
        (tracks >> 8) & 0xff, tracks & 0xff, (division >> 8) & 0xff, division & 0xff]);
}

function track(events) {
    return chunk("MTrk", events.concat(variable(0), [0xff, 0x2f, 0x00]));
}

function file(tracks, options) {
    return Uint8Array.from(header({ ...options, tracks: tracks.length })
        .concat(...tracks.map(track))).buffer;
}

const tempo = (microseconds) => variable(0).concat([0xff, 0x51, 0x03,
    (microseconds >> 16) & 0xff, (microseconds >> 8) & 0xff, microseconds & 0xff]);
// The second byte is the power of two the beat is written in: 1 is a minim, 3 a quaver.
// music21 repeats the closing speed on the final barline, so the file carries the
// end of the range even when it finishes in rests.
const tempoAfter = (delta, microseconds) => variable(delta).concat([0xff, 0x51, 0x03,
    (microseconds >> 16) & 0xff, (microseconds >> 8) & 0xff, microseconds & 0xff]);
const timeSignature = (beats, beatPower) => variable(0).concat([0xff, 0x58, 0x04, beats, beatPower, 24, 8]);
const noteOn = (delta, note, velocity = 90, channel = 0) => variable(delta).concat([0x90 | channel, note, velocity]);
const noteOff = (delta, note, channel = 0) => variable(delta).concat([0x80 | channel, note, 64]);

test("a part that rests through the range keeps its place", () => {
    const conductor = tempo(500000);
    const resting = [];
    const sounding = noteOn(0, 60).concat(noteOff(DIVISION, 60));
    const music = collect(parseMidi(file([conductor, resting, sounding])), 2);
    assert.equal(music.parts.length, 2);
    assert.equal(music.parts[0].length, 0);
    assert.equal(music.parts[1][0].note, 60);
});

test("a file with no conductor track lines up part for part", () => {
    const first = noteOn(0, 60).concat(noteOff(DIVISION, 60));
    const second = noteOn(0, 48).concat(noteOff(DIVISION, 48));
    const music = collect(parseMidi(file([first, second])), 2);
    assert.deepEqual(music.parts.map(notes => notes[0].note), [60, 48]);
});

test("two voices holding one pitch at once are both heard", () => {
    const events = noteOn(0, 60).concat(noteOn(DIVISION / 2, 60), noteOff(DIVISION / 2, 60), noteOff(DIVISION, 60));
    const music = collect(parseMidi(file([events])), 1);
    assert.equal(music.parts[0].length, 2);
    assert.deepEqual(music.parts[0].map(n => Math.round(n.start * 1000)), [0, 250]);
    assert.deepEqual(music.parts[0].map(n => Math.round(n.end * 1000)), [500, 1000]);
});

test("a note off written as a note on with no force ends the note", () => {
    const events = noteOn(0, 62).concat(noteOn(DIVISION, 62, 0));
    const music = collect(parseMidi(file([events])), 1);
    assert.equal(music.parts[0].length, 1);
    assert.equal(Math.round(music.parts[0][0].end * 1000), 500);
});

test("running status carries the note on across events", () => {
    const events = variable(0).concat([0x90, 60, 90], variable(DIVISION), [62, 90],
        variable(0), [0x80, 60, 64], variable(0), [62, 64]);
    const music = collect(parseMidi(file([events])), 1);
    assert.deepEqual(music.parts[0].map(n => n.note), [60, 62]);
});

test("a metronome mark part way through changes what follows it", () => {
    const events = tempo(500000).concat(noteOn(0, 60), noteOff(DIVISION, 60),
        tempo(250000), noteOn(0, 62), noteOff(DIVISION, 62));
    const music = collect(parseMidi(file([events])), 1);
    assert.equal(Math.round(music.parts[0][1].start * 1000), 500);
    assert.equal(Math.round(music.parts[0][1].end * 1000), 750);
});

test("a compound meter is counted in dotted beats", () => {
    const events = timeSignature(6, 3).concat(tempo(500000),
        noteOn(0, 60), noteOff(DIVISION * 3, 60));   // one bar of 6/8
    const music = collect(parseMidi(file([events])), 1);
    assert.equal(music.clicks.length, 2);
    assert.deepEqual(music.clicks.map(c => c.strong), [true, false]);
});

test("a change of time signature moves the strong beat", () => {
    const events = timeSignature(2, 1).concat(tempo(500000), noteOn(0, 60),
        noteOff(DIVISION * 4, 60), timeSignature(3, 1), noteOn(0, 62), noteOff(DIVISION * 6, 62));
    const music = collect(parseMidi(file([events])), 1);
    assert.deepEqual(music.clicks.map(c => c.strong), [true, false, true, false, false]);
});

test("percussion keeps its rhythm and its place among the parts", () => {
    const kit = noteOn(0, 38, 90, 9).concat(noteOff(DIVISION, 38, 9));
    const music = collect(parseMidi(file([kit])), 1);
    assert.equal(music.parts[0].length, 1);
    assert.equal(music.parts[0][0].percussion, true);
    assert.ok(music.duration > 0);
});

test("a note still sounding at the end of the track is held to the end", () => {
    // A note tied out of the last bar has no note off, so it runs to the closing
    // speed on the final barline rather than being dropped.
    const events = tempo(500000).concat(noteOn(0, 60), tempoAfter(DIVISION, 500000),
        variable(DIVISION), [0xff, 0x2f, 0x00]);
    const music = collect(parseMidi(Uint8Array.from(
        header({ tracks: 1 }).concat(chunk("MTrk", events))).buffer), 1);
    assert.equal(music.parts[0].length, 1);
    assert.equal(Math.round(music.parts[0][0].end * 1000), 500);
});

test("a range finishing in rests keeps its full length", () => {
    // Two bars of four four sounding one note: the writing stops at that note, the
    // closing speed marks the end of the range, and the end of track sits a beat
    // further on again, which is why it says nothing about how long the range is.
    const events = timeSignature(4, 2).concat(tempo(500000), noteOn(0, 60), noteOff(DIVISION, 60),
        tempoAfter(DIVISION * 7, 500000), variable(DIVISION), [0xff, 0x2f, 0x00]);
    const music = collect(parseMidi(Uint8Array.from(
        header({ tracks: 1 }).concat(chunk("MTrk", events))).buffer), 1);
    assert.equal(Math.round(music.duration * 1000), 4000);
    assert.equal(music.clicks.length, 8);
});

test("the end of track written past the range does not lengthen it", () => {
    const events = timeSignature(4, 2).concat(tempo(500000), noteOn(0, 60),
        noteOff(DIVISION * 4, 60), tempoAfter(0, 500000), variable(DIVISION), [0xff, 0x2f, 0x00]);
    const music = collect(parseMidi(Uint8Array.from(
        header({ tracks: 1 }).concat(chunk("MTrk", events))).buffer), 1);
    assert.equal(Math.round(music.duration * 1000), 2000);
    assert.equal(music.clicks.length, 4);
});

test("a file with more tracks than parts keeps them in the order written and says so", () => {
    const conductor = tempo(500000);
    const first = noteOn(0, 60).concat(noteOff(DIVISION, 60));
    const second = noteOn(0, 48).concat(noteOff(DIVISION, 48));
    const music = collect(parseMidi(file([conductor, first, second])), 1);
    assert.deepEqual(music.parts.map(notes => notes[0].note), [60, 48]);
    // The parts cannot be named from a file that does not line up with the score.
    assert.equal(music.matches, false);
});

test("a system message does not lose the rest of the track", () => {
    const events = noteOn(0, 60).concat(variable(0), [0xf2, 0x00, 0x01],
        variable(0), [0xf8], noteOff(DIVISION, 60));
    const music = collect(parseMidi(file([events])), 1);
    assert.equal(music.parts[0].length, 1);
    assert.equal(Math.round(music.parts[0][0].end * 1000), 500);
});

test("a chunk longer than the file stops at the end of the file", () => {
    const bytes = new Uint8Array(file([noteOn(0, 60).concat(noteOff(DIVISION, 60))]));
    bytes[headerSize() + 5] = 0x7f;    // a length far past the last byte
    const music = collect(parseMidi(bytes.buffer), 1);
    assert.equal(music.parts[0].length, 1);
});

function headerSize() {
    return 14;
}

test("frame timing is refused rather than read at the wrong speed", () => {
    assert.throws(() => parseMidi(file([[]], { division: 0xe728 })), /frames/);
});

test("independent sequences are refused", () => {
    assert.throws(() => parseMidi(file([[]], { format: 2 })), /independent/);
});

test("a file that is not MIDI is refused", () => {
    assert.throws(() => parseMidi(Uint8Array.from([1, 2, 3]).buffer), /MIDI header/);
});

test("a delta time that never ends is refused", () => {
    const events = [0xff, 0xff, 0xff, 0xff, 0xff];
    assert.throws(() => parseMidi(Uint8Array.from(header({ tracks: 1 }).concat(chunk("MTrk", events))).buffer),
        /too long|no status/);
});

/* The shape of a struck note. A piano falls away from the moment the hammer lands,
   dulling as it goes, and a low string rings far longer than a high one. */

const { pianoVoice } = scope.window.TalkingScoresPlayer.voice;

test("a low string rings longer than a high one", () => {
    const bass = pianoVoice(28, 90);
    const middle = pianoVoice(60, 90);
    const treble = pianoVoice(96, 90);
    assert.ok(bass.bodyRing > middle.bodyRing);
    assert.ok(middle.bodyRing > treble.bodyRing);
    assert.ok(treble.bodyRing >= 0.6);
});

test("the upper partials fall away before the fundamental", () => {
    for (const number of [28, 60, 96]) {
        const voice = pianoVoice(number, 90);
        assert.ok(voice.strikeRing < voice.bodyRing,
            `note ${number} rings ${voice.bodyRing} but strikes for ${voice.strikeRing}`);
    }
});

test("a note struck harder is louder and brighter", () => {
    const soft = pianoVoice(60, 30);
    const hard = pianoVoice(60, 120);
    assert.ok(hard.level > soft.level);
    assert.ok(hard.strikeLevel > soft.strikeLevel);
});

test("a velocity outside the scale is held to the ends of it", () => {
    assert.deepEqual(pianoVoice(60, -20), pianoVoice(60, 0));
    assert.deepEqual(pianoVoice(60, 500), pianoVoice(60, 127));
});

test("every note has an attack short enough to be heard as a strike", () => {
    for (const number of [21, 60, 108]) {
        assert.ok(pianoVoice(number, 90).attack <= 0.01);
    }
});

test("the top of the keyboard is still quieter above than the bottom", () => {
    assert.ok(pianoVoice(96, 90).strikeLevel < pianoVoice(36, 90).strikeLevel);
});

const { sampleName, nearestSample } = scope.window.TalkingScoresPlayer.samples;

test("a recording is named as the note it holds", () => {
    assert.equal(sampleName(21), "A0");
    assert.equal(sampleName(60), "C4");
    assert.equal(sampleName(108), "C8");
    // The files are named with flats, so a black key has one spelling only.
    assert.equal(sampleName(61), "Db4");
    assert.equal(sampleName(66), "Gb4");
});

test("a note is played from a recording no more than a semitone away", () => {
    for (let number = 21; number <= 108; number++) {
        const sampled = nearestSample(number);
        assert.ok(Math.abs(number - sampled) <= 1,
            `note ${number} would be played from ${sampled}`);
        assert.equal((sampled - 21) % 3, 0);
    }
});

test("a note off the ends of the keyboard is played from the nearest recording", () => {
    assert.equal(nearestSample(0), 21);
    assert.equal(nearestSample(20), 21);
    assert.equal(nearestSample(127), 108);
});

/* A page saved to a device carries the whole score and cuts the group out of it. */

scope.window.atob = atob;
const { bytesFromBase64, readEmbedded, embeddedRange } =
    scope.window.TalkingScoresPlayer.carried;

// Four bars of three crotchets each at one beat a second, one note a bar.
const FOUR_BARS = (() => {
    const conductor = tempo(1000000).concat(timeSignature(3, 2));
    let events = [];
    for (let bar = 0; bar < 4; bar++) {
        events = events.concat(noteOn(bar ? DIVISION * 2 : 0, 60 + bar), noteOff(DIVISION, 60 + bar));
    }
    return file([conductor, events]);
})();
const BAR_OFFSETS = { 1: 0, 2: 3, 3: 6, 4: 9, 5: 12 };

function base64(buffer) {
    return Buffer.from(new Uint8Array(buffer)).toString("base64");
}

test("a score written into the page is read back byte for byte", () => {
    const bytes = new Uint8Array(bytesFromBase64(base64(FOUR_BARS)));
    assert.deepEqual([...bytes], [...new Uint8Array(FOUR_BARS)]);
});

test("a group is cut out of the carried score at its own bar lines", () => {
    const carried = readEmbedded(base64(FOUR_BARS), 1, BAR_OFFSETS);
    const second = embeddedRange(carried, 2, 3);
    assert.equal(Math.round(second.duration), 6);
    assert.deepEqual(second.parts[0].map(note => note.note), [61, 62]);
    // The group is played from its own start, not from the start of the score.
    assert.deepEqual(second.parts[0].map(note => Math.round(note.start)), [0, 3]);
});

test("the click of the carried score counts from the group's first beat", () => {
    const carried = readEmbedded(base64(FOUR_BARS), 1, BAR_OFFSETS);
    const second = embeddedRange(carried, 2, 2);
    assert.deepEqual(second.clicks.map(click => Math.round(click.start)), [0, 1, 2]);
    assert.deepEqual(second.clicks.map(click => click.strong), [true, false, false]);
});

test("a group reaching past the last bar stops at the end of the score", () => {
    const carried = readEmbedded(base64(FOUR_BARS), 1, BAR_OFFSETS);
    const past = embeddedRange(carried, 4, 40);
    assert.deepEqual(past.parts[0].map(note => note.note), [63]);
    assert.ok(past.duration > 0);
});
