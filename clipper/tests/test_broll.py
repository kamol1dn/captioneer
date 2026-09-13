"""B-roll and graphics: the surface the second pass writes through.

Cutting and dressing are two sessions. The second arrives with no memory of why a
boundary sits where it does, so it edits through narrow tools that cannot reach
``segments`` or ``camera_cuts`` at all. What these cover is that the narrow path
is actually complete (add, remove, replace, attach), that the two kinds of
overlay reach separate tracks in the right order, and that the validator catches
the one shape which silently produces an invalid timeline: two clipitems of the
same kind overlapping on a single track.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_broll
"""
import sys

from ..captions import to_master, to_program
from ..compile import compile_clip
from ..edl import (AudioPlan, BRoll, CameraCut, Clip, EDL, Marker, Segment,
                   add_broll, next_broll_id, parse_broll, parse_markers,
                   remove_broll, validate)
from ..timebase import Timebase

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _edl(broll=None, markers=None):
    clip = Clip(id="c1", title="c1",
                segments=[Segment(10.0, 40.0, id="s1")],
                camera_cuts=[CameraCut(at=10.0, camera="A")],
                broll=list(broll or []), markers=list(markers or []))
    edl = EDL(timebase=Timebase(30), frame_size=(1080, 1920),
              default_camera="A", clips=[clip],
              audio=AudioPlan(mode="pinned", pinned_camera="A"))
    return edl, clip


def _validate(edl):
    return validate(edl, ["A", "B"], master_duration=600.0)


def _cameras():
    return {"A": {"path": "A.mp4", "offset_sec": 0.0, "has_video": True},
            "B": {"path": "B.mp4", "offset_sec": 0.0, "has_video": True}}


def _graphics_tracks(compiled):
    """Names of the tracks above the camera stack, in bottom-to-top order.

    Every camera gets a track whether or not it is cut to, so the stack's height
    is not what these tests are about; b-roll and captions are the tracks with no
    camera of their own.
    """
    return [t[0].name for t in compiled.video_tracks if t and not t[0].camera]


# -- schema ------------------------------------------------------------------

def test_broll_defaults_to_footage():
    """An EDL written before `kind` existed must still load, and mean the same."""
    restored = EDL.from_dict({
        "timebase": Timebase(30).to_dict(),
        "frame_size": {"width": 1080, "height": 1920},
        "default_camera": "A",
        "clips": [{"id": "c1",
                   "segments": [{"start": 10.0, "end": 40.0}],
                   "broll": [{"start": 12.0, "end": 15.0, "id": "b1",
                              "query": "stripe hq"}]}],
    })
    b = restored.clips[0].broll[0]
    check(b.kind == "footage", f"legacy b-roll should be footage, got {b.kind!r}")
    check(b.query == "stripe hq", "the rest of the entry must survive")


def test_kind_survives_a_round_trip():
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay")])
    again = EDL.from_dict(edl.to_dict())
    check(again.clips[0].broll[0].kind == "overlay",
          "kind must survive to_dict/from_dict")


# -- editing helpers ---------------------------------------------------------

def test_ids_are_generated_in_order_and_skip_taken_ones():
    _, clip = _edl()
    a = add_broll(clip, 12.0, 14.0)
    b = add_broll(clip, 16.0, 18.0, broll_id="hero")
    c = add_broll(clip, 20.0, 22.0)
    check([a.id, b.id, c.id] == ["b1", "hero", "b2"],
          f"unexpected ids: {[a.id, b.id, c.id]}")
    check(next_broll_id(clip) == "b3", "next id should skip what is taken")


def test_adding_a_taken_id_raises_rather_than_overwriting():
    _, clip = _edl([BRoll(12.0, 15.0, id="b1", query="keep me")])
    try:
        add_broll(clip, 20.0, 22.0, broll_id="b1")
        _failures.append("adding a duplicate id should raise")
    except ValueError:
        pass
    check(len(clip.broll) == 1 and clip.broll[0].query == "keep me",
          "the existing entry must be untouched after a rejected add")


def test_source_sets_attached_status():
    _, clip = _edl()
    placeholder = add_broll(clip, 12.0, 14.0)
    attached = add_broll(clip, 16.0, 18.0, source="D:/stock/x.mov")
    check(placeholder.status == "placeholder", "no source means placeholder")
    check(attached.status == "attached", "a source means attached")


def test_remove_returns_the_entry_and_rejects_unknown_ids():
    _, clip = _edl([BRoll(12.0, 15.0, id="b1")])
    got = remove_broll(clip, "b1")
    check(got.id == "b1" and not clip.broll, "remove should drop the entry")
    try:
        remove_broll(clip, "nope")
        _failures.append("removing an unknown id should raise")
    except ValueError:
        pass


def test_parse_names_the_bad_field():
    try:
        parse_broll([{"start": 1.0, "end": 2.0, "kidn": "overlay"}])
        _failures.append("a misspelled field should raise")
    except ValueError as e:
        check("kidn" in str(e) and "#0" in str(e),
              f"the error should name the field and the entry, got: {e}")
    check(len(parse_markers([{"at": 1.0, "name": "x"}])) == 1,
          "a valid marker list should parse")


# -- validation --------------------------------------------------------------

def test_two_of_one_kind_may_not_overlap():
    edl, _ = _edl([BRoll(12.0, 18.0, id="b1"), BRoll(16.0, 20.0, id="b2")])
    r = _validate(edl)
    check(not r["ok"], "overlapping footage must be an error")
    check(any("overlap" in e for e in r["errors"]),
          f"the error should say overlap, got {r['errors']}")


def test_an_overlay_may_sit_over_footage():
    edl, _ = _edl([BRoll(12.0, 18.0, id="b1", kind="footage"),
                   BRoll(13.0, 16.0, id="b2", kind="overlay")])
    r = _validate(edl)
    check(r["ok"], f"kinds should be free to overlap, got {r['errors']}")


def test_touching_at_a_boundary_is_not_an_overlap():
    edl, _ = _edl([BRoll(12.0, 16.0, id="b1"), BRoll(16.0, 20.0, id="b2")])
    check(_validate(edl)["ok"], "back-to-back b-roll is legal")


def test_unknown_kind_and_duplicate_ids_are_errors():
    edl, _ = _edl([BRoll(12.0, 14.0, id="b1", kind="sticker"),
                   BRoll(16.0, 18.0, id="b1")])
    r = _validate(edl)
    check(any("kind" in e for e in r["errors"]), "unknown kind must be caught")
    check(any("duplicate" in e for e in r["errors"]),
          f"duplicate id must be caught, got {r['errors']}")


def test_broll_outside_a_kept_segment_is_still_rejected():
    edl, _ = _edl([BRoll(50.0, 52.0, id="b1")])
    check(not _validate(edl)["ok"], "b-roll outside the cut must be an error")


# -- compile -----------------------------------------------------------------

def test_footage_and_overlays_get_their_own_tracks_in_order():
    edl, clip = _edl([BRoll(12.0, 18.0, id="b1", source="f.mov"),
                      BRoll(13.0, 16.0, id="b2", kind="overlay",
                            source="o.mov")])
    c = compile_clip(edl, clip, _cameras(), caption_mov="cap.mov")
    names = _graphics_tracks(c)
    check(names == ["broll b1", "overlay b2", "captions c1"],
          f"order above the cameras should be footage, overlay, captions: {names}")


def test_an_overlay_alone_still_sits_above_the_camera():
    edl, clip = _edl([BRoll(13.0, 16.0, id="b2", kind="overlay",
                            source="o.mov")])
    names = _graphics_tracks(compile_clip(edl, clip, _cameras()))
    check(names == ["overlay b2"],
          f"an overlay with no footage should be the only track above the "
          f"cameras: {names}")


def test_placeholders_become_markers_naming_their_kind():
    edl, clip = _edl([BRoll(12.0, 14.0, id="b1", query="stripe hq"),
                      BRoll(20.0, 22.0, id="b2", kind="overlay",
                            query="revenue chart")])
    c = compile_clip(edl, clip, _cameras())
    check(_graphics_tracks(c) == [],
          f"placeholders must not produce clipitems: {_graphics_tracks(c)}")
    names = sorted(m.name for m in c.markers)
    check(names == ["BROLL b1", "OVERLAY b2"],
          f"markers should name the kind, got {names}")
    check(any("revenue chart" in (m.comment or "") for m in c.markers),
          "the query must reach the marker comment")


def test_markers_are_placed_in_program_time():
    """A marker's `at` is master seconds; what lands is a program frame."""
    edl, clip = _edl(markers=[Marker(at=25.0, name="title card")])
    c = compile_clip(edl, clip, _cameras())
    # The segment starts at 10.0, so master 25.0 is program 15.0 -> frame 450.
    frames = [m.frame for m in c.markers]
    check(frames == [450], f"marker should land at frame 450, got {frames}")


# -- program <-> master ------------------------------------------------------

def _multi():
    """Two kept segments: master 10-20 and 30-45, so program 0-10 then 10-25."""
    clip = Clip(id="c1", segments=[Segment(10.0, 20.0), Segment(30.0, 45.0)])
    return clip, Timebase(30)


def test_conversion_accounts_for_the_gap_between_segments():
    clip, tb = _multi()
    # Program 12s is 2s into the second segment, which starts at master 30.
    check(to_master(clip, tb, 12.0) == 32.0,
          f"program 12 should be master 32, got {to_master(clip, tb, 12.0)}")
    check(to_program(clip, tb, 32.0) == 12.0,
          f"master 32 should be program 12, got {to_program(clip, tb, 32.0)}")
    # Inside the first segment the offset is a different number entirely.
    check(to_master(clip, tb, 5.0) == 15.0,
          f"program 5 should be master 15, got {to_master(clip, tb, 5.0)}")


def test_a_trimmed_moment_converts_to_none():
    clip, tb = _multi()
    check(to_program(clip, tb, 25.0) is None,
          "a master time in the dropped gap is not in the clip")
    check(to_master(clip, tb, 99.0) is None,
          "a program time past the end is not in the clip")


def test_conversion_round_trips_across_the_whole_clip():
    clip, tb = _multi()
    for frame in range(tb.to_frames(clip.duration)):
        prog = tb.to_seconds(frame)
        master = to_master(clip, tb, prog)
        if not check(master is not None, f"no master time for program {prog}"):
            return
        back = to_program(clip, tb, master)
        if not check(back is not None and abs(back - prog) < 1e-9,
                     f"round trip failed at program {prog}: got {back}"):
            return


def main():
    print("\ntest_broll")
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
