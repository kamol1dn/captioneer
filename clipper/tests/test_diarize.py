"""Per-mic merge: bleed rejection and speaker attribution.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_diarize

The envelopes here are synthetic: a camera is "hot" (-12 dB) while its owner
speaks and "bleeding" (-45 dB) while the other one does. That is the same shape
``energy.compute_envelope`` produces from real isolated mics, so the merge sees
exactly the signal it will see in production.
"""
import sys

from caption_engine.transcriber.word import Word

from ..diarize import merge_per_mic, own_word_fraction
from ..energy import RESOLUTION_HZ, group_by_speaker, mean_db, speaker_scores

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)


def envelope(loud_windows, duration=20.0, hot=-12.0, quiet=-45.0):
    """An envelope that is `hot` inside loud_windows and `quiet` elsewhere."""
    n = int(duration * RESOLUTION_HZ)
    db = []
    for i in range(n):
        t = i / RESOLUTION_HZ
        live = any(a <= t < b for a, b in loud_windows)
        db.append(hot if live else quiet)
    return {"resolution_hz": RESOLUTION_HZ, "duration": duration, "db": db}


def words(spec):
    """[(text, start, end), ...] -> [Word]"""
    return [Word(text=t, start=s, end=e, probability=1.0) for t, s, e in spec]


# ── tests ────────────────────────────────────────────────────────────────────

def test_bleed_is_rejected_and_speech_is_kept():
    """Both mics transcribe both voices; only the owner's lines survive."""
    # A speaks 0-3, B speaks 5-8.
    envs = {"A": envelope([(0, 3)]), "B": envelope([(5, 8)])}

    a_own = words([("hello", 0.2, 0.8), ("there", 1.0, 1.6), ("friend", 2.0, 2.6)])
    b_own = words([("good", 5.2, 5.8), ("to", 6.0, 6.4), ("see", 6.8, 7.4)])

    # Each mic also picks the other up — same words, same times.
    per_cam = {"A": a_own + b_own, "B": a_own + b_own}
    utts, report = merge_per_mic(per_cam, envs)

    check(len(utts) == 2, f"expected 2 merged utterances, got {len(utts)}")
    got = [(u.speaker, u.text) for u in utts]
    check(got[0][0] == "A" and "hello" in got[0][1],
          f"first utterance should be A's, got {got[0]}")
    check(got[1][0] == "B" and "good" in got[1][1],
          f"second utterance should be B's, got {got[1]}")
    check(report["A"]["dropped_as_bleed"] == 1,
          f"A should drop B's bleed, got {report['A']}")
    check(report["B"]["dropped_as_bleed"] == 1,
          f"B should drop A's bleed, got {report['B']}")


def test_simultaneous_speech_survives_on_both_mics():
    """The payoff of per-mic: a single mix cannot represent this at all."""
    # Both are hot over the same window — each loud on their own mic.
    envs = {"A": envelope([(0, 4)]), "B": envelope([(0, 4)])}
    per_cam = {
        "A": words([("wait", 1.0, 1.5), ("no", 1.6, 2.0)]),
        "B": words([("but", 1.1, 1.6), ("listen", 1.7, 2.3)]),
    }
    utts, report = merge_per_mic(per_cam, envs)

    speakers = {u.speaker for u in utts}
    check(speakers == {"A", "B"},
          f"both speakers should survive an overlap, got {speakers}")
    check(report["_totals"]["overlaps"] >= 1,
          "an overlapping pair should be reported as an overlap")


def test_output_is_ordered_and_reindexed():
    envs = {"A": envelope([(0, 2), (6, 8)]), "B": envelope([(3, 5)])}
    per_cam = {
        "A": words([("first", 0.2, 0.8)]) + words([("third", 6.2, 6.8)]),
        "B": words([("second", 3.2, 3.8)]),
    }
    utts, _ = merge_per_mic(per_cam, envs)
    check([u.text for u in utts] == ["first", "second", "third"],
          f"merged timeline should be in time order, got {[u.text for u in utts]}")
    check([u.index for u in utts] == [0, 1, 2],
          f"indices should be renumbered, got {[u.index for u in utts]}")
    check(all(u.speaker_confidence > 0 for u in utts),
          "kept utterances should carry a confidence")


def test_missing_envelope_keeps_the_transcript():
    """No evidence of bleed is not evidence of bleed — don't silently delete."""
    frac = own_word_fraction("A", words([("x", 0.0, 0.5)]), {})
    check(frac == 1.0, f"absent envelope should keep words, got {frac}")


# ── two cameras on one speaker ───────────────────────────────────────────────

def test_two_angles_on_one_speaker_merge_to_one_loudness_line():
    """A person's cameras collapse to their best mic, not their average.

    A2 is the same voice 25 dB down (a camera mic behind a lav). Averaging would
    put the group halfway to silence and let the other speaker win windows where
    the first person is plainly talking.
    """
    envs = {"A1": envelope([(0, 3)]), "A2": envelope([(0, 3)], hot=-37.0),
            "B": envelope([(5, 8)])}
    grouped = group_by_speaker(envs, {"A1": "host", "A2": "host", "B": "guest"})

    check(set(grouped) == {"host", "guest"},
          f"cameras should collapse to people, got {sorted(grouped)}")
    scores = speaker_scores(grouped, 0.5, 2.5)
    check(scores["host"] > scores["guest"],
          f"the host should own their own window, got {scores}")
    check(mean_db(grouped["host"], 0.5, 2.5) > -13.0,
          "the group should stay as loud as its best mic, not average down to "
          f"the weak one (got {mean_db(grouped['host'], 0.5, 2.5):.1f} dB)")


def test_one_transcript_per_speaker_not_per_camera():
    """The regression the speaker grouping exists to prevent.

    Two mics on one person hear that person within a decibel of each other, so
    both clear the bleed margin on every word. Passed in as separate rivals — a
    per-*camera* merge — every line the host says survives twice and lands in the
    master timeline twice, which is a doubled caption on every clip.
    """
    envs = {"A1": envelope([(0, 3)]), "A2": envelope([(0, 3)], hot=-13.0),
            "B": envelope([(5, 8)])}
    spoken = words([("hello", 0.2, 0.8), ("there", 1.0, 1.6)])

    # What the old per-camera path did: one entry per mic, both the same voice.
    per_camera, _ = merge_per_mic({"A1": spoken, "A2": spoken}, envs)
    check(len(per_camera) == 2,
          "per-camera keying should double the host's line — if it no longer "
          "does, this test has stopped guarding anything")

    # What ingest does now: one entry per person, envelopes merged per person.
    grouped = group_by_speaker(envs, {"A1": "host", "A2": "host", "B": "guest"})
    per_speaker, report = merge_per_mic({"host": spoken}, grouped)
    check(len(per_speaker) == 1,
          f"the host's line should appear once, got {len(per_speaker)}: "
          f"{[u.text for u in per_speaker]}")
    check(per_speaker[0].speaker == "host",
          f"attributed to the person, not a camera: {per_speaker[0].speaker}")
    check(report["_totals"]["overlaps"] == 0,
          "one person's two mics must not be reported as simultaneous speech")


def test_grouping_is_identity_for_one_camera_per_speaker():
    """The default path must be untouched, so callers can group unconditionally."""
    envs = {"A": envelope([(0, 3)]), "B": envelope([(5, 8)])}
    grouped = group_by_speaker(envs, {"A": "A", "B": "B"})
    check(grouped == envs, "one camera per speaker should pass through unchanged")


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
