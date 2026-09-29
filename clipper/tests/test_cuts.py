"""Verbatim words and where to cut them.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_cuts

Pinned here are the failures found while building this against OTG EP21's
guest mic, each of which read fine on paper:

* **Touching words.** "that would be great": no pause between "would" and
  "be". Snapping to the nearest *pause* moved an out point 0.4 s back and
  silently dropped "that would". A word boundary with no pause is still where
  the cut belongs.
* **CTC overrun.** The aligner held the "o" of "two" straight over the "M" of
  "Most" (nasals murmur ~170 ms before their letter fires), so searching for
  the word's end *after* its CTC end found nothing and the cut kept an "M".
  The search starts at the word's last letter and takes the dip.
* **The blank.** "-" is the MMS aligner's CTC blank; letting it through made
  every window holding "non-dilutive" fail to align.

No model is loaded: extents are refined on synthetic envelopes.
"""
import sys

import numpy as np

from caption_engine.transcriber.word import Word, is_filler

from ..captions import words_for_clip
from ..cuts import gaps, place
from ..edl import Clip, Segment
from ..sanity import check_clip
from ..timebase import Timebase
from ..transcript import build_utterances, format_words, search

_failures = []
TB = Timebase(30, ntsc=True)


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def W(text, start, end):
    return Word(text=text, start=start, end=end, probability=1.0)


# ── fillers ──────────────────────────────────────────────────────────────────

def test_filler_recognition():
    for t in ("[uh]", "[um]", "um,", "Uh.", "hmm"):
        check(is_filler(t), f"{t!r} is a filler")
    for t in ("ah", "Oh,", "umbrella", "[laughs", "the"):
        check(not is_filler(t), f"{t!r} is not a filler")


def test_glued_fillers_are_split():
    from caption_engine.transcriber.verbatim_backend import split_token
    parts = [p for p, _, _ in split_token("[UM][UH]", 1.0, 2.0)]
    check(parts == ["[um]", "[uh]"], f"two glued fillers split: {parts}")
    parts = split_token(".[UH]there", 1.0, 1.6)
    check([p for p, _, _ in parts] == ["[uh]", "there"],
          f"filler glued to a word splits off it: {parts}")
    check(abs(parts[0][2] - 1.3) < 1e-9, "the glued span is shared out")
    check(split_token(" growth.", 1.0, 1.2) == [("growth.", 1.0, 1.2)],
          "an ordinary word passes through")


def test_hyphen_is_not_sent_to_the_aligner():
    from caption_engine.transcriber import mms_align
    mms_align._ensure_loaded("cpu")
    check(mms_align._normalize("non-dilutive") == "nondilutive",
          "the CTC blank '-' must never reach the aligner's targets")


# ── cut placement ────────────────────────────────────────────────────────────

SENT = [W("growth.", 1.00, 1.40), W("[uh]", 1.62, 2.05), W("that", 2.30, 2.45),
        W("would", 2.45, 2.62), W("be", 2.62, 2.75), W("great.", 2.75, 3.10),
        W("So", 3.30, 3.50)]


def test_gaps_keep_touching_boundaries():
    gl = gaps(SENT, 4.0)
    points = [(round(g.start, 2), round(g.end, 2)) for g in gl]
    check((2.62, 2.62) in points, f"would|be touch — still a boundary: {points}")
    check((1.40, 1.62) in points and (2.05, 2.30) in points,
          f"a filler has a boundary on both sides: {points}")


def test_crosstalk_has_no_boundary():
    host = [W("yeah", 2.40, 2.70)]          # talks over would|be
    gl = gaps(SENT + host, 4.0)
    check(not any(2.4 < g.start < 2.7 for g in gl),
          "no cut point inside someone else's word")


def test_out_point_stays_on_its_boundary_when_words_touch():
    """The EP21 regression: never jump to a pause and drop words."""
    r = place(2.62, gaps(SENT, 4.0), "out", TB)
    check(abs(r["t"] - 2.62) <= 0.5 / 29.97 + 1e-6,
          f"out after 'would' stays at 2.62 (±half a frame), got {r['t']}")
    check("note" in r, "a join with no pause is flagged to listen to")


def test_roles_place_inside_a_real_pause():
    gl = gaps(SENT, 4.0)
    out = place(1.40, gl, "out", TB)          # after "growth.", drop the [uh]
    inn = place(2.30, gl, "in", TB)           # resume at "that"
    check(1.40 < out["t"] <= 1.40 + 0.075, f"out keeps a short tail: {out}")
    check(2.30 - 0.075 <= inn["t"] < 2.30, f"in keeps a short lead: {inn}")
    for r in (out, inn):
        on_frame = TB.to_seconds(TB.to_frames(r["t"]))
        check(abs(on_frame - r["t"]) < 1e-3, f"lands on a frame: {r['t']}")
    check("[uh]" in out["context"], f"context names the filler: {out['context']}")


def test_inside_a_long_word_is_refused():
    long_word = [W("a", 0.0, 0.1), W("extraordinarily", 0.2, 1.6), W("b", 1.7, 1.8)]
    r = place(0.9, gaps(long_word, 2.0), "out", TB, max_shift=0.3)
    check(r["ok"] is False and abs(r["t"] - 0.9) < 1e-9,
          f"no boundary within max_shift: left alone and reported: {r}")


# ── extents from audio ───────────────────────────────────────────────────────

def _env(spans, total=4.0, floor=1e-4):
    """10 ms RMS envelope: ``floor`` everywhere, ``level`` over each span."""
    env = np.full(int(total / 0.01), floor)
    for a, b, level in spans:
        env[int(a / 0.01):int(b / 0.01)] = level
    return env


def test_word_end_found_after_ctc_spike():
    from caption_engine.transcriber.verbatim_backend import refine_extents
    # A word sounding 1.00-1.50, silence, the next 1.80-2.20; CTC saw less.
    env = _env([(1.00, 1.50, 0.1), (1.80, 2.20, 0.1)])
    words = [W("first", 1.05, 1.30), W("second", 1.90, 2.10)]
    refine_extents(words, env, [(0.0, 4.0)], last_char=[1.25, 2.05])
    check(abs(words[0].end - 1.50) <= 0.011, f"end walks to 1.50: {words[0].end}")
    check(abs(words[1].start - 1.80) <= 0.011, f"onset walks back to 1.80: {words[1].start}")


def test_touching_words_meet_at_the_dip():
    """The EP21 "two. Most" case: CTC ran "two" over the M."""
    from caption_engine.transcriber.verbatim_backend import refine_extents
    env = _env([(2.20, 2.50, 0.1), (2.52, 2.90, 0.1), (2.50, 2.52, 0.004)])
    words = [W("two.", 2.25, 2.70), W("Most", 2.70, 2.85)]
    refine_extents(words, env, [(0.0, 4.0)], last_char=[2.40, 2.84])
    check(abs(words[0].end - 2.50) <= 0.011, f"'two.' ends at the dip: {words[0].end}")
    check(abs(words[1].start - words[0].end) < 1e-6,
          f"'Most' starts where 'two.' ends: {words[1].start}")


def test_chunks_cover_everything_and_cut_at_quiet():
    from caption_engine.transcriber.verbatim_backend import chunk_bounds
    env = _env([(0.0, 100.0, 0.1)], total=100.0)
    for q in (25.0, 50.0, 75.0):              # quiet spots to cut on
        env[int(q / 0.01):int((q + 0.3) / 0.01)] = 1e-4
    ch = chunk_bounds(env)
    check(ch[0][0] == 0.0 and abs(ch[-1][1] - 100.0) < 1e-6, f"covers the file: {ch}")
    check(all(b - a <= 29.0 + 1e-6 for a, b in ch), f"no chunk over 29 s: {ch}")
    check(all(abs(b - a2) < 1e-9 for (_, b), (a2, _) in zip(ch, ch[1:])),
          "chunks abut")
    check(all(any(q <= b <= q + 0.3 for q in (25, 50, 75)) for _, b in ch[:-1]),
          f"every cut is in a quiet spot: {ch}")


# ── downstream ───────────────────────────────────────────────────────────────

def test_captions_skip_fillers():
    clip = Clip(id="c", segments=[Segment(0.9, 3.2)])
    texts = [w.text for w in words_for_clip(SENT, clip, TB)]
    check("[uh]" not in texts and "growth." in texts, f"no filler captioned: {texts}")


def test_sanity_flags_a_cut_inside_a_word():
    clip = Clip(id="c", segments=[Segment(0.95, 2.70)])     # ends inside "be"
    kinds = [i["kind"] for i in check_clip(SENT, clip, precise=True, tb=TB)["issues"]]
    check("cuts_word" in kinds, f"a boundary inside 'be' is flagged: {kinds}")
    kinds = [i["kind"] for i in check_clip(SENT, clip, precise=False)["issues"]]
    check("cuts_word" not in kinds, "not on imprecise (WhisperX) timings")


def test_sanity_flags_a_segment_opening_on_a_filler():
    clip = Clip(id="c", segments=[Segment(1.55, 3.15)])     # opens on [uh]
    issues = check_clip(SENT, clip, precise=True, tb=TB)["issues"]
    check(any(i["kind"] == "filler_edge" for i in issues),
          f"opening on [uh] is flagged: {[i['kind'] for i in issues]}")


def test_sentence_checks_look_past_fillers():
    """'growth. [uh] ⟩CUT⟨ that…' closed a sentence; the filler isn't a clause."""
    clip = Clip(id="c", segments=[Segment(2.20, 3.20)])
    kinds = [i["kind"] for i in check_clip(SENT, clip, precise=True, tb=TB)["issues"]
             if i["confidence"] == "high"]
    check("orphan_open" not in kinds, f"no orphan_open after 'growth. [uh]': {kinds}")


def test_search_and_word_view_see_fillers():
    utts = build_utterances(SENT)
    check(search(utts, "growth. that would"), "search reads through [uh]")
    view = format_words(SENT, utts, 0.0, 4.0)["text"]
    check("[uh]" in view and "(0.25s)" in view,
          f"word view shows the filler and the pause after it: {view}")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        before = len(_failures)
        try:
            t()
        except Exception as e:               # noqa: BLE001
            _failures.append(f"{t.__name__} raised {e!r}")
        print(f"  {'ok  ' if len(_failures) == before else 'FAIL'}  {t.__name__}")
    print()
    if _failures:
        print(f"{len(_failures)} failure(s):")
        for f in _failures:
            print("  -", f)
        sys.exit(1)
    print(f"all {len(tests)} tests passed")


if __name__ == "__main__":
    main()
