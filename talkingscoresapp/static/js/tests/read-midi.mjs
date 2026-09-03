/* Read a MIDI file the way the reading page does and print what it found.

   The Python tests use this to check the browser's reading of a file music21 has
   actually written, which no fixture built by hand can stand in for. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "..", "player.js"), "utf8");
const scope = { window: {} };
new Function("window", source)(scope.window);
const { parseMidi, collect } = scope.window.TalkingScoresPlayer.reading;

const [file, parts] = process.argv.slice(2);
const bytes = fs.readFileSync(file);
const music = collect(parseMidi(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)),
    parseInt(parts, 10));
process.stdout.write(JSON.stringify({
    parts: music.parts.map(notes => notes.map(note => note.note)),
    clicks: music.clicks.length,
    duration: music.duration
}));
