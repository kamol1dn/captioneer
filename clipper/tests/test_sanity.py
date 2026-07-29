"""Segment sanity: do the kept words still read as sentences?

Run: venv\\Scripts\\python.exe -m clipper.tests.test_sanity

The fixtures are modelled on real failures from cutting OTG ep12, because the
interesting question is not "does it flag something" but "does it flag the two
defects that actually shipped, without flagging the twelve deliberate trims that
sat right next to them".
"""
import sys

from caption_engine.transcriber.word import Word

from ..edl import Clip, Segment
from ..sanity import check_clip

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)


def W(text, start, end):
    return Word(text=text, start=start, end=end, probability=1.0)


def kinds(clip, words, confidence="high"):
    issues = check_clip(words, clip)["issues"]
    return [i["kind"] for i in issues if i["confidence"] == confidence]


# ── the real failures ────────────────────────────────────────────────────────

def test_catches_the_orphaned_preposition():
    """The ep12 defect: "A coalition" fell in the gap, leaving "of 25 US..."."""
    words = [
        W("It", 0.0, 0.2), W("was", 0.3, 0.5), W("about", 0.6, 0.9),
        W("policy", 1.0, 1.4), W("letter.", 1.5, 1.9),
        W("A", 2.0, 2.1), W("coalition", 2.2, 2.7),
        W("of", 2.8, 2.9), W("25", 3.0, 3.4), W("US", 3.5, 3.8),
        W("companies", 3.9, 4.4),
    ]
    # Keep the first sentence, then resume *after* "A coalition".
    clip = Clip(id="c", segments=[Segment(0.0, 1.95), Segment(2.75, 4.5)])
    check("orphan_open" in kinds(clip, words),
          "a segment opening on a stranded preposition must be flagged")

    # Keeping "A coalition" makes it read; it must go quiet.
    ok = Clip(id="c", segments=[Segment(0.0, 1.95), Segment(1.99, 4.5)])
    check("orphan_open" not in kinds(ok, words),
          "a clean join must not be flagged")


def test_catches_the_dangling_tail():
    """The ep12 defect: a clip ending on "...to win the AI race. And"."""
    words = [
        W("win", 0.0, 0.3), W("the", 0.4, 0.5), W("AI", 0.6, 0.8),
        W("race.", 0.9, 1.3), W("And", 1.4, 1.6),
        W("it", 1.7, 1.9), W("seems", 2.0, 2.4),
    ]
    clip = Clip(id="c", segments=[Segment(0.0, 1.65)])
    check("orphan_close" in kinds(clip, words),
          "ending on a dangling 'And' must be flagged")

    tight = Clip(id="c", segments=[Segment(0.0, 1.35)])
    check("orphan_close" not in kinds(tight, words),
          "ending on the full stop must not be flagged")


def test_deliberate_trims_are_not_high_confidence():
    """Dropping a lead-in is the whole point of trimming — don't cry wolf.

    "the funny thing is | two months ago, they moved..." is a good cut, and the
    checker sees the same mid-clause open as a real break. It may note it, but
    it must not rank it alongside genuine breakage.
    """
    words = [
        W("the", 0.0, 0.1), W("funny", 0.2, 0.5), W("thing", 0.6, 0.9),
        W("is", 1.0, 1.1),
        W("two", 1.2, 1.4), W("months", 1.5, 1.9), W("ago,", 2.0, 2.3),
        W("they", 2.4, 2.6), W("moved.", 2.7, 3.1),
    ]
    clip = Clip(id="c", segments=[Segment(1.15, 3.2)])
    check("orphan_open" not in kinds(clip, words),
          "a deliberate lead-in trim must not be high-confidence")


def test_mid_clip_join_is_judged_in_program_order():
    """A segment continuing the previous one's sentence is fine.

    Judged against the master word it was cut away from, this looks broken;
    judged against what the viewer actually hears, it reads.
    """
    words = [
        W("promote", 0.0, 0.4), W("it,", 0.5, 0.7),
        W("posting", 0.8, 1.2), W("for", 1.3, 1.5), W("the", 1.6, 1.7),
        W("first", 1.8, 2.1), W("time", 2.2, 2.5), W("ever", 2.6, 2.9),
        W("with", 3.0, 3.2), W("Microsoft", 3.3, 3.9), W("CEO.", 4.0, 4.4),
    ]
    # Drop "posting ... ever"; "promote it," + "with Microsoft CEO." reads.
    clip = Clip(id="c", segments=[Segment(0.0, 0.75), Segment(2.95, 4.5)])
    check("orphan_open" not in kinds(clip, words),
          "a segment continuing the previous clause must not be flagged")


def test_empty_segment_is_reported():
    words = [W("hello", 0.0, 0.5)]
    clip = Clip(id="c", segments=[Segment(10.0, 12.0)])
    check("empty_segment" in kinds(clip, words),
          "a segment containing no words must be reported")


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
