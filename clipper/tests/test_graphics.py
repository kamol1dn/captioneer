"""Rendered graphics: the Python side of the Remotion seam.

What is worth pinning here is everything decided *before* Node is involved,
because that is where a graphic goes wrong silently: a frame count one off from
the entry it fills (Premiere trims it, or leaves a flash of nothing), a
misspelt prop that renders as a missing unit, an entry moved after its file was
rendered. The render itself is exercised by the end-to-end run, not here — it
needs Node and a headless browser, and is slow.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_graphics
"""
import sys
import tempfile
from pathlib import Path

from ..edl import AudioPlan, BRoll, CameraCut, Clip, EDL, Segment, validate
from ..graphics import (broll_frames, check_props, manifest, plan_jobs,
                        stale_graphics)
from ..timebase import Timebase

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _edl(broll=None, tb=Timebase(30, ntsc=True)):
    # Two segments with a gap, so program time and master time differ by a
    # different offset in each — the case a naive "subtract clip start" breaks.
    clip = Clip(id="c1", title="c1",
                segments=[Segment(10.0, 20.0, id="s1"),
                          Segment(50.0, 60.0, id="s2")],
                camera_cuts=[CameraCut(at=10.0, camera="A")],
                broll=list(broll or []))
    edl = EDL(timebase=tb, frame_size=(1440, 2560), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    return edl, clip


# -- manifest ------------------------------------------------------------------

def test_every_template_has_a_component():
    """templates.json and src/templates/index.ts must list the same names."""
    index = (Path(__file__).resolve().parents[2] / "graphics" / "src"
             / "templates" / "index.ts").read_text(encoding="utf-8")
    for name in manifest():
        check(f"  {name}," in index, f"{name} is in templates.json but not "
                                     f"registered in src/templates/index.ts")


def test_every_example_is_valid():
    # Image props point at files on the author's disk, so an example cannot
    # carry a real one; everything else in it must validate as written.
    for name, spec in manifest().items():
        errors = [e for e in check_props(name, spec["example"])
                  if not any(repr(k) in e or f" {k} " in e
                             for k in spec["image_props"])]
        check(not errors, f"{name} example does not validate: {errors}")


# -- props -----------------------------------------------------------------------

def test_unknown_prop_is_an_error():
    errors = check_props("Stat", {"value": 6, "label": "x", "sufix": "%"})
    check(any("sufix" in e for e in errors), f"misspelt prop not caught: {errors}")


def test_missing_required_prop():
    errors = check_props("LowerThird", {"name": "Oban"})
    check(any("'role'" in e for e in errors), f"missing role not caught: {errors}")


def test_unknown_template():
    check(check_props("Nope", {}), "unknown template must be an error")


def test_bad_position():
    errors = check_props("Stat", {"value": 1, "label": "x", "position": "left"})
    check(any("position" in e for e in errors), "bad position not caught")


def test_missing_image_file():
    errors = check_props("ImageCard", {"image": "Z:/definitely/not/here.png"})
    check(any("does not exist" in e for e in errors), f"missing image: {errors}")


# -- timing ----------------------------------------------------------------------

def test_frames_in_second_segment_use_its_offset():
    tb = Timebase(30, ntsc=True)
    edl, clip = _edl([BRoll(52.0, 55.0, id="b1", kind="overlay")], tb)
    start, frames = broll_frames(clip, tb, clip.broll[0])
    first_len = tb.to_frames(20.0) - tb.to_frames(10.0)
    check(start == first_len + tb.to_frames(52.0) - tb.to_frames(50.0),
          f"program start {start} ignores the first segment's length")
    check(frames == tb.to_frames(55.0) - tb.to_frames(52.0),
          f"frame count {frames} is not the entry's length")


def test_entry_across_a_gap_is_rejected():
    edl, clip = _edl([BRoll(18.0, 52.0, id="b1", kind="overlay")])
    try:
        broll_frames(clip, edl.timebase, clip.broll[0])
        check(False, "an entry spanning the gap between segments must raise")
    except ValueError:
        pass


def test_moved_entry_is_reported_stale():
    edl, clip = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay",
                            source="x.mov", status="attached")])
    _, frames = broll_frames(clip, edl.timebase, clip.broll[0])
    clip.broll[0].graphic = {"template": "Stat", "props": {}, "frames": frames}
    check(not stale_graphics(edl), "an untouched graphic is not stale")
    clip.broll[0].end = 14.0
    check(stale_graphics(edl), "a shortened entry must be reported stale")


def test_graphic_survives_a_round_trip():
    edl, clip = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay",
                            graphic={"template": "Stat", "props": {"value": 6},
                                     "frames": 90})])
    restored = EDL.from_dict(edl.to_dict()).clips[0].broll[0]
    check(restored.graphic == clip.broll[0].graphic,
          f"graphic lost in round trip: {restored.graphic}")


# -- planning --------------------------------------------------------------------

def test_plan_rejects_footage_entries():
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="footage")])
    with tempfile.TemporaryDirectory() as tmp:
        jobs, errors = plan_jobs(edl, [{"clip_id": "c1", "broll_id": "b1",
                                        "template": "Stat",
                                        "props": {"value": 1, "label": "x"}}],
                                 Path(tmp))
    check(not jobs and any("overlay" in e for e in errors),
          f"a graphic on a footage entry must be refused: {errors}")


def test_plan_names_output_by_clip_and_entry():
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay")])
    with tempfile.TemporaryDirectory() as tmp:
        jobs, errors = plan_jobs(edl, [{"clip_id": "c1", "broll_id": "b1",
                                        "template": "Stat",
                                        "props": {"value": 1, "label": "x"}}],
                                 Path(tmp))
    check(not errors, f"valid item rejected: {errors}")
    check(jobs and jobs[0].out.name == "c1_b1.mov", "unexpected output name")


def test_plan_reports_every_bad_item():
    """One bad item must not hide the next — the whole batch is checked first."""
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay")])
    with tempfile.TemporaryDirectory() as tmp:
        _, errors = plan_jobs(edl, [
            {"clip_id": "c1", "broll_id": "b1", "template": "Nope", "props": {}},
            {"clip_id": "c1", "broll_id": "b9", "template": "Stat", "props": {}},
        ], Path(tmp))
    check(len(errors) >= 2, f"expected an error per bad item, got {errors}")



# -- hook ----------------------------------------------------------------------

def _hooked(seconds=3.0, source="hook.mov", broll=None):
    edl, clip = _edl(broll)
    # First segment is 10s; make a 1s first segment so the hook must span a cut.
    clip.segments = [Segment(10.0, 11.0, id="s0"), Segment(50.0, 60.0, id="s1")]
    clip.hook = {"template": "Hook", "props": {"text": "A *hook*"},
                 "seconds": seconds, "source": source}
    return edl, clip


def _cams():
    return {"A": {"path": "A.mp4", "offset_sec": 0.0, "has_video": True}}


def test_hook_spans_the_first_cut_on_its_own_track():
    from ..compile import compile_clip
    edl, clip = _hooked(broll=[BRoll(55.0, 57.0, id="b1", kind="overlay",
                                     source="card.mov", status="attached")])
    compiled = compile_clip(edl, clip, _cams(), caption_mov="caps.mov")
    tops = [t[0].role for t in compiled.video_tracks if t and t[0].role != "camera"]
    check(tops == ["broll", "title", "caption"],
          f"expected overlay, hook, captions bottom to top, got {tops}")
    hook = compiled.items_by_role("title")[0]
    check(hook.start == 0 and hook.end == edl.timebase.to_frames(3.0),
          f"hook should run frames 0-{edl.timebase.to_frames(3.0)}, got "
          f"{hook.start}-{hook.end}")


def test_unrendered_hook_is_a_marker():
    from ..compile import compile_clip
    edl, clip = _hooked(source=None)
    compiled = compile_clip(edl, clip, _cams())
    check(not compiled.items_by_role("title"), "no file, so no clipitem")
    check(any(m.name == "HOOK" and "A *hook*" in m.comment for m in compiled.markers),
          "an unrendered hook must still reach the editor as a marker")


def test_hook_longer_than_clip_is_an_error():
    edl, _ = _hooked(seconds=30.0)
    res = validate(edl, ["A"], master_duration=600.0)
    check(any("hook runs" in e for e in res["errors"]), f"{res['errors']}")


def test_long_hook_warns():
    edl, _ = _hooked(seconds=6.0, source=None)
    res = validate(edl, ["A"], master_duration=600.0)
    check(res["ok"] and any("banner" in w for w in res["warnings"]),
          f"a 6s hook is legal but should warn: {res}")


def test_card_under_the_hook_warns():
    from ..graphics import hook_conflicts
    edl, _ = _hooked(broll=[BRoll(10.2, 10.9, id="b1", kind="overlay")])
    check(hook_conflicts(edl), "a card at 0.2s starts under a 3s hook")
    edl, _ = _hooked(broll=[BRoll(55.0, 57.0, id="b1", kind="overlay")])
    check(not hook_conflicts(edl), "a card at 6s is clear of the hook")


def test_resized_hook_is_stale():
    edl, clip = _hooked()
    from ..graphics import hook_frames
    clip.hook["frames"] = hook_frames(clip, edl.timebase)
    check(not stale_graphics(edl), "fresh hook is not stale")
    clip.hook["seconds"] = 2.0
    check(stale_graphics(edl), "a shortened hook must be reported stale")


def test_hook_survives_a_round_trip():
    edl, clip = _hooked()
    back = EDL.from_dict(edl.to_dict()).clips[0].hook
    check(back == clip.hook, f"hook lost in round trip: {back}")


def test_hook_template_refused_on_broll():
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay")])
    with tempfile.TemporaryDirectory() as tmp:
        jobs, errors = plan_jobs(edl, [{"clip_id": "c1", "broll_id": "b1",
                                        "template": "Hook", "props": {"text": "x"}}],
                                 Path(tmp))
    check(not jobs and any("set_clip_hook" in e for e in errors), f"{errors}")

def main():
    print("\ntest_graphics")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        before = len(_failures)
        try:
            t()
        except Exception as e:
            _failures.append(f"{t.__name__} raised {type(e).__name__}: {e}")
        print(f"  {'ok' if len(_failures) == before else 'FAIL':4}  {t.__name__}")
    print()
    if _failures:
        print(f"{len(_failures)} failure(s):")
        for f in _failures:
            print("  -", f)
        return 1
    print(f"all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
