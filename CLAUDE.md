# Talking Scores

Django app that converts music scores into text descriptions. Run the test suite
with `python manage.py test` and Django's system checks with `python manage.py check`.

# Standing rules

- **Prominence budget.** Every view has one primary task and that task's surface gets
  the space. Each control is classified as primary (at most one per view), secondary
  (one line), or reference (behind a disclosure). Information the user must read
  before acting renders as a callout above the controls it governs. A third block on
  a view means a disclosure, not more stacking.

- **No dead ends.** A flow is finished when the interface names the next action. Every
  committing step's confirmation points at what comes next: a status line, a jump
  affordance, or an explicit focus move. A committing action with a side effect not
  implied by its label says so in the label or an adjacent hint.

- **Direct completion over deferred triage.** Capture and review flows produce the
  final artefact in one sitting. An intermediate holding state - tray, queue, triage
  list - is never an assumed default; propose it explicitly for review before
  building one.

- **Comments state constraints, not provenance.** No comment references a note, a
  numbered feedback item, a plan phase or wave. A why-comment is self-contained and
  meaningful without the conversation that produced it. Phase and wave numbering
  belongs only in build logs and commit messages.

- **Rename sweep.** Any change to a user-facing string is followed by a repo-wide
  search for the old string across docs, other UI surfaces, code and test assertions,
  updating every real hit. Changelogs and build logs are annotated rather than
  rewritten. A rename is not done while the old string still appears anywhere it
  could mislead.
