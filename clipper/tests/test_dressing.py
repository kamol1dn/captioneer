"""Show dressing: whooshes over cuts, and the tail card every reel ends on.

The reference this was built from is a hand-dressed Gashtak reel exported back
out of Premiere. Three things in it are easy to get subtly wrong and invisible
until an editor scrubs the timeline, so they are pinned here:

* the whoosh straddles the cut rather than starting on it — its flash frame is
  what lands on the join, and the asset's head runs *before* it;
* it composites with ``screen`` and carries a gain, not a volume keyframe, since
  Premiere re-reads a keyframed level as a fader move on top of the mix;
* the tail card lengthens the reel, and picture and sound run on underneath it
  while the captions stop at the cut.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_dressing
"""
import sys
import xml.etree.ElementTree as ET

from ..compile import compile_clip
from ..edl import (AudioPlan, CameraCut, Clip, EDL, Segment, Transition,
                   parse_transitions, validate)
from ..show import Outro, Show, TransitionAsset
from ..timebase import Timebase
from ..xmeml.writer import XmemlWriter

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


# The reference asset, to its real numbers: 25fps material conformed into a
# 29.97 sequence, so 0.88s is 26 frames and the flash at 0.3337s is frame 10.
def _show(**kw):
    asset = TransitionAsset(
        id="burn", path="X:/assets/burn.mov", seconds=0.88, hit_sec=0.3337,
        rotation=90, composite="screen", gain_db=-19.0,
        width=1920, height=1080, scale=154.0)
    return Show(id="gashtak", graphics="gashtak", transitions={"burn": asset},
                default_transition="burn", **kw)


def _edl(transitions=None):
    clip = Clip(id="c1", title="c1",
                segments=[Segment(10.0, 40.0, id="s1")],
                camera_cuts=[CameraCut(at=10.0, camera="A")],
                transitions=list(transitions or []))
    edl = EDL(timebase=Timebase(30, ntsc=True), frame_size=(1440, 2560),
              default_camera="A", clips=[clip],
              audio=AudioPlan(mode="pinned", pinned_camera="A"))
    return edl, clip


def _cameras():
    return {"A": {"path": "A.mp4", "offset_sec": 0.0, "has_video": True},
            "B": {"path": "B.mp4", "offset_sec": 0.0, "has_video": True}}


def _compile(transitions=None, show=None, outro_mov=None):
    edl, clip = _edl(transitions)
    return compile_clip(edl, clip, _cameras(), show=show or _show(),
                        outro_mov=outro_mov)


def _role(compiled, role):
    return [it for tr in compiled.video_tracks + compiled.audio_tracks
            for it in tr if it.role == role]


# ── placement ────────────────────────────────────────────────────────────────

def test_flash_lands_on_the_cut_not_after_it():
    """The asset starts 10 frames early so its flash sits on the join."""
    c = _compile([Transition(at=20.0, id="t1")])
    vids = [it for it in _role(c, "transition") if it.media_type == "video"]
    if not check(len(vids) == 1, f"expected one whoosh, got {len(vids)}"):
        return
    v = vids[0]
    # The cut is program frame 299: master 20.0s is source frame 599 and the
    # segment opens at 300, and the compiler subtracts rounded frames rather
    # than rounding the 10s difference — which is the whole point of that rule.
    check(v.start == 289, f"whoosh starts at {v.start}, expected 299-10=289")
    check(v.end - v.start == 26, f"whoosh runs {v.end - v.start}f, expected 26")
    check(v.in_ == 0, f"whoosh in is {v.in_}, expected 0")


def test_head_is_trimmed_never_slid():
    """A whoosh on the first frames loses its head rather than its alignment."""
    c = _compile([Transition(at=10.1, id="t1")])
    v = [it for it in _role(c, "transition") if it.media_type == "video"][0]
    check(v.start == 0, f"whoosh starts at {v.start}, expected 0")
    # program frame 3 is the cut; 10 frames of lead do not fit, so 7 are cut off
    # the asset's head and the flash still lands on 3.
    check(v.in_ == 7, f"whoosh in is {v.in_}, expected 7 (trimmed head)")
    check(v.start + (asset_lead := 10) - v.in_ == 3,
          f"flash lands at {v.start + asset_lead - v.in_}, expected program 3")
    check(v.end - v.start == v.out - v.in_,
          "trimming the head retimed the clip")


def test_tail_is_trimmed_at_the_end_of_the_reel():
    c = _compile([Transition(at=39.95, id="t1")])
    v = [it for it in _role(c, "transition") if it.media_type == "video"][0]
    check(v.end == c.duration, f"whoosh ends at {v.end}, past duration {c.duration}")
    check(v.end - v.start == v.out - v.in_, "trimming the tail retimed the clip")


def test_whoosh_sits_above_the_captions():
    c = _compile([Transition(at=20.0, id="t1")], outro_mov=None)
    top = [tr for tr in c.video_tracks if tr and tr[0].role == "transition"]
    idx = c.video_tracks.index(top[0])
    cams = [i for i, tr in enumerate(c.video_tracks)
            if tr and tr[0].role == "camera"]
    check(idx > max(cams), "whoosh track is not above the camera stack")


# ── framing and mix ──────────────────────────────────────────────────────────

def test_rotation_and_composite_reach_the_xml():
    c = _compile([Transition(at=20.0, id="t1")])
    xml = ET.fromstring(XmemlWriter().build([c], "t"))
    item = next(el for el in xml.iter("clipitem")
                if (el.findtext("name") or "").startswith("burn"))
    check(item.findtext("compositemode") == "screen",
          f"compositemode is {item.findtext('compositemode')!r}, expected 'screen'")
    rot = next((p.findtext("value") for p in item.iter("parameter")
                if p.findtext("parameterid") == "rotation"), None)
    check(rot == "90", f"rotation is {rot!r}, expected '90'")
    scale = next((p.findtext("value") for p in item.iter("parameter")
                  if p.findtext("parameterid") == "scale"), None)
    check(scale == "154", f"scale is {scale!r}, expected '154'")


def test_cover_scale_is_worked_out_after_rotation():
    """A quarter-turned 1920x1080 is 1080 wide, so cover is 133%, not 178%."""
    show = _show()
    show.transitions["burn"].scale = 0.0        # auto
    c = _compile([Transition(at=20.0, id="t1")], show=show)
    v = [it for it in _role(c, "transition") if it.media_type == "video"][0]
    check(abs(v.scale - 133.333) < 0.01,
          f"cover scale is {v.scale}, expected ~133.333 for the rotated shape")


def test_audio_is_two_mono_tracks_carrying_gain():
    c = _compile([Transition(at=20.0, id="t1")])
    auds = [it for it in _role(c, "transition") if it.media_type == "audio"]
    check(len(auds) == 2, f"expected a stereo pair, got {len(auds)} clipitems")
    check(sorted(a.source_channel for a in auds) == [1, 2],
          "whoosh audio does not ask for source channels 1 and 2")
    check(all(a.gain_db == -19.0 for a in auds), "whoosh audio lost its gain")

    xml = ET.fromstring(XmemlWriter().build([c], "t"))
    gains = [p.findtext("value") for p in xml.iter("parameter")
             if p.findtext("name") == "Gain(dB)"]
    check(gains == ["-19", "-19"], f"Gain(dB) in xml is {gains}")
    check(not [k for k in xml.iter("effectid") if k.text == "audiolevels"],
          "level was written as audiolevels keyframes, which Premiere re-reads "
          "as a fader move stacked on the mix")


def test_picture_and_audio_are_linked():
    c = _compile([Transition(at=20.0, id="t1")])
    xml = ET.fromstring(XmemlWriter().build([c], "t"))
    item = next(el for el in xml.iter("clipitem")
                if (el.findtext("name") or "").startswith("burn"))
    kinds = sorted(lk.findtext("mediatype") for lk in item.findall("link"))
    check(kinds == ["audio", "audio", "video"],
          f"whoosh links are {kinds}, expected one video and two audio")


# ── the tail card ────────────────────────────────────────────────────────────

def test_outro_holds_picture_and_sound_but_not_captions():
    show = _show(outro=Outro(template="GashtakOutro", hold=285))
    edl, clip = _edl()
    bare = compile_clip(edl, clip, _cameras(), caption_mov="cap.mov", show=show)
    dressed = compile_clip(edl, clip, _cameras(), caption_mov="cap.mov",
                           show=show, outro_mov="outro.mov")
    check(dressed.duration == bare.duration + 285,
          f"outro added {dressed.duration - bare.duration}f, expected 285")

    cams = [it for tr in dressed.video_tracks for it in tr
            if it.role == "camera"]
    check(all(it.end - it.start == it.out - it.in_ for it in cams),
          "holding the tail retimed a camera clipitem")
    check(max(it.end for it in cams) == dressed.duration,
          "picture stops before the tail card ends")
    aud = [it for tr in dressed.audio_tracks for it in tr]
    check(max(it.end for it in aud) == dressed.duration,
          "sound stops before the tail card ends")
    cap = [it for tr in dressed.video_tracks for it in tr
           if it.role == "caption"][0]
    check(cap.end == bare.duration,
          f"captions run to {cap.end}, should stop at the cut ({bare.duration})")


def test_outro_is_skipped_until_the_card_is_rendered():
    show = _show(outro=Outro(template="GashtakOutro", hold=285))
    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(), show=show, outro_mov=None)
    bare = compile_clip(edl, clip, _cameras(), show=_show())
    check(c.duration == bare.duration,
          "picture was held under a tail card that does not exist yet")


# ── the undressed path is unchanged ──────────────────────────────────────────

def test_no_show_means_no_dressing():
    edl, clip = _edl([Transition(at=20.0, id="t1")])
    c = compile_clip(edl, clip, _cameras())      # no show at all
    check(not _role(c, "transition"),
          "a project naming no show got a whoosh anyway")
    check(len(c.markers) == 1 and "TRANSITION" in c.markers[0].name,
          "an unresolvable transition should leave a marker for the editor")


# ── the edit surface ─────────────────────────────────────────────────────────

def test_ids_are_minted_in_time_order():
    ts = parse_transitions([{"at": 30.0}, {"at": 12.0}, {"at": 20.0, "id": "t1"}])
    check([t.at for t in ts] == [12.0, 20.0, 30.0], "transitions were not sorted")
    check([t.id for t in ts] == ["t2", "t1", "t3"],
          f"ids are {[t.id for t in ts]}; an explicit id must not be reused")


def test_transition_outside_a_segment_is_an_error():
    edl, _clip = _edl([Transition(at=55.0, id="t1")])
    report = validate(edl, ["A", "B"], master_duration=600.0)
    errors = report["errors"]
    check(any("not inside a kept segment" in e for e in errors),
          f"a transition off the keep list was accepted: {errors}")


def test_round_trips_through_the_edl_file():
    edl, _clip = _edl([Transition(at=20.0, id="t1", asset="burn", note="n")])
    back = EDL.from_dict(edl.to_dict())
    check(back.clips[0].transitions == edl.clips[0].transitions,
          "transitions did not survive save/load")
    plain = EDL.from_dict(_edl()[0].to_dict())
    check("transitions" not in _edl()[0].to_dict()["clips"][0],
          "an undressed clip gained an empty transitions key")
    check(plain.clips[0].transitions == [], "empty transitions did not load")


def main():
    print("\ntest_dressing")
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
