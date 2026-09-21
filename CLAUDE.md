# Talking Scores

A Django site that turns a MusicXML score into a talking score: bars written
out as words, with playback of any range of bars in the browser. The interface
copy lives in `lib/talkingscore.html` (the talking score page),
`talkingscoresapp/templates/*.html` (every other page) and the quoted strings
in `talkingscoresapp/static/js/*.js` (status lines and announcements).

## Copy rules

Every string a reader sees, and every code comment, follows the
`user-facing-copy-guard` skill. Load that skill before writing or editing any
label, hint, error, status line, announcement, README section for readers, or
comment. Name it in the `skills:` field of any subagent that writes copy.

The rules that matter most here, each with the shape to use instead:

- State the mechanism, never a stance. "Checks for bars already written and
  skips them", not "powerful de-duplication".
- Copy describes what the reader sees or does next. A sentence that justifies
  a decision ("because", "we chose", "note that") is rationale: keep it in a
  commit message or a code comment, never in the page.
- Buttons name the outcome in two to four words: "Play this group",
  "Stop playback", "Download as braille". Label the state the control will enter.
- Errors say what to do in the reader's own terms: "Enter a bar number between
  1 and 32", never "Invalid input" or "An error occurred".
- Hints are one sentence, no full stop, no link. Labels are sentence case with
  no colon. No exclamation marks, no metaphors, no "we".
- A confirmation names the object and the consequence; its buttons summarise
  each outcome, never Yes and No.
- One term per concept, from the termbase below. A changed string is followed
  by a repo-wide search for the old one across templates, scripts, tests, the
  design mock-ups and the README; the change log is annotated, not rewritten.
- Comments state the constraint and its consequence, never their source. No
  "as discussed", "per the note", plan phases or feedback numbers. Delete the
  pointer: if nothing still constrains anything, write the constraint.

## Termbase

| Concept | Use | Never |
| --- | --- | --- |
| The output | talking score | description, transcript, reading |
| The music being read | score | piece, tune, song |
| A run of bars on screen | group | chunk, section, segment |
| Bar zero | pickup bar | anacrusis, upbeat, bar 0 |
| An instrument's line | part | track, voice, staff |
| Sounding the bars | playback, play | listen, preview, sound out |
| Every bar at once | the whole score | whole tune, full piece, everything |
| The ticking pulse | metronome click | click track, beat |
| The user | reader | user, listener, you (in prose) |
| The settings page | Options | preferences, config |

## Enforcement

`scripts/check_copy.py` scans the templates, scripts and comments for the
tells above. It runs on every edit through the hook in `.claude/settings.json`
and as `UserFacingCopyTests` in the Django suite, so a leak fails the build.
Run it alone with:

```
python3 scripts/check_copy.py
```

A hit is fixed by rewriting the string, never by widening the scanner's
exceptions, unless the pattern is plainly wrong for a site about music.

## Standing rules

- Prominence budget: one primary task per view; every other control is a line
  or sits behind a disclosure. A third stacked block becomes a disclosure.
- No dead ends: a finished flow names the next action.
- Direct completion: no tray, queue or triage list unless proposed first.
- Tests are run by a verifier subagent, not in the main conversation.
