# Test Debt Ledger

Current-state record of reds left standing, one entry per unit. Git carries the
history; a settled entry is **deleted**, not marked resolved.

An entry is written with the change that caused the red, in that same commit. Whoever
made that change never edits the failing test's body — the expectation is re-derived by
someone else, so no change's author can weaken the evidence of the red it caused.

A test that goes red only sometimes, whatever the change, is entered by whoever saw it
red: its commit field says no change caused it, its delta field opens with the mark
`flaky-quarantine.`, exactly so, and its fix is a change of its own — never re-running it
until it passes. A release build accepts a test so marked whether it fails or passes,
while every other test this ledger names must fail; a test named both ways, or a delta
opening with "flaky" spelt any other way, refuses the build.

Fields: **tests · commit · delta · disposition · since**. The **commit** field names the
change that caused the red by its date and a description, never by a commit's
identifier. A **disposition** is `none`; `needs-human`, where the test's new expected
value is the maintainer's to decide; or `origin-flagged`, where the red is a deferred
fix's own regression test, which stands only once the maintainer has accepted it.

---

### The Qt History window's charts

- **tests:** `tests/test_window_qt_history.py`
  `PointerWordsTest.test_a_mark_says_what_it_is_after_windows_hover_time_not_before`
- **commit:** no change caused it. Seen red once, 2026-11-07, in a whole run under the development Python environment
  beside a release build and its suite, while Qt was being carried in a release; that change touches neither the chart
  nor the test.
- **delta:** flaky-quarantine. The words had not come 5 seconds after the pointer rested. The same day the test passed in
  two whole runs, in the release's own among them, in its module alone, and in 18 runs of its class, 12 of them with
  every processor kept busy, so its cause is not known. A pending leave or hide of the chart, which cancels the wait, is
  the suspicion. On 2026-11-14 it passed in 50 runs of its class, in three runs of the four Qt modules about, arrange,
  bills and history in one process beside 24 busy processes, and in 16 runs of those modules on the tree of
  2026-11-07 beside 20. A run of those modules on each tree, counting every view's scrolls and the chart's leave and
  pointer-move events, counted none while it ran, so nothing that cancels or defers the wait came. None of these
  runs held the rest of the suite before it, as the run that saw it red did. The fix is a change of its own.
- **disposition:** none
- **since:** 2026-11-07
