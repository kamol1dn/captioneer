"""EDL.save merges concurrent writers clip by clip instead of overwriting.

Run: venv\Scripts\python.exe -m clipper.tests.test_edl_merge
"""
import sys
import tempfile
from pathlib import Path

from ..edl import AudioPlan, BRoll, Clip, EDL, Segment
from ..timebase import Timebase

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _file():
    d = Path(tempfile.mkdtemp()) / "edl.json"
    EDL(timebase=Timebase(30, ntsc=True), frame_size=(1440, 2560), default_camera="A",
        clips=[Clip(id="01", segments=[Segment(0, 10)]), Clip(id="02", segments=[Segment(20, 30)])],
        audio=AudioPlan(mode="pinned", pinned_camera="A")).save(d)
    return d


def test_two_writers_on_different_clips_both_survive():
    p = _file()
    a, b = EDL.load(p), EDL.load(p)          # both load the same version
    a.clip("01").hook = {"template": "Hook", "props": {"text": "hi"}, "seconds": 3.0}
    b.clip("02").broll.append(BRoll(21, 24, id="g1", kind="overlay"))
    a.save(p)                                 # a renders first and saves
    b.save(p)                                 # b, holding a stale copy, saves later
    e = EDL.load(p)
    check(e.clip("01").hook is not None, "writer a's hook on clip 01 was erased by writer b")
    check(len(e.clip("02").broll) == 1, "writer b's b-roll on clip 02 is missing")


def test_hook_updated_in_place_is_saved():
    # render_hooks does clip.hook.update(source=...); the base snapshot taken at load
    # must not share that dict, or the save merge sees no change and keeps the disk copy.
    p = _file()
    a = EDL.load(p)
    a.clip("01").hook = {"template": "Hook", "props": {"text": "hi"}, "seconds": 3.0}
    a.save(p)
    b, other = EDL.load(p), EDL.load(p)
    other.clip("02").segments = [Segment(20, 31)]
    other.save(p)                             # disk now differs from b's base
    b.clip("01").hook.update(source="x.mov", frames=90)
    b.save(p)
    e = EDL.load(p)
    check((e.clip("01").hook or {}).get("source") == "x.mov", "in-place hook update was dropped by the merge")
    check(e.clip("02").segments[0].end == 31, "the other writer's clip 02 change was lost")


def test_new_clip_from_another_writer_is_kept():
    p = _file()
    a, b = EDL.load(p), EDL.load(p)
    a.clips.append(Clip(id="03", segments=[Segment(40, 50)]))
    b.clip("01").title = "new title"
    a.save(p)
    b.save(p)
    e = EDL.load(p)
    check(e.clip("03") is not None, "clip 03 added by writer a was dropped")
    check(e.clip("01").title == "new title", "writer b's title change is missing")


def test_same_clip_last_writer_wins():
    p = _file()
    a, b = EDL.load(p), EDL.load(p)
    a.clip("01").title = "from a"
    b.clip("01").title = "from b"
    a.save(p)
    b.save(p)
    check(EDL.load(p).clip("01").title == "from b", "same clip: the later save should win")


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
