"""Cutting reels from an episode timeline instead of flat per-angle exports.

The workflow these cover: the editor exports only audio plus the episode
timeline as FCP7 XML, and picture comes off that timeline's V-tracks. What makes
it more than a path swap is that an edited two-hour timeline has a cut every few
seconds, so master time maps to source time piecewise — one shot can straddle
several master cuts and must come out as several clipitems that still satisfy
``end - start == out - in`` individually.

The fixtures here are synthetic rather than a real 16 MB Premiere export, but
they reproduce the shapes that actually caused trouble: a nested sequence used by
two tracks, an audio clipitem whose in/out disagrees with its program range by a
frame, and material parked under a transition with ``start = -1``.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_master_timeline
"""
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from ..compile import compile_clip
from ..edl import EDL, AudioPlan, CameraCut, Clip, Segment
from ..timebase import Timebase
from ..xmeml.reader import read_master
from ..xmeml.writer import XmemlWriter

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


# ── fixture ──────────────────────────────────────────────────────────────────

def _clipitem(start, end, in_, name, ref_tag, ref_id, define=None,
              filters="", channel=None):
    """One clipitem. ``define`` is inline XML for a first-use definition."""
    src = define if define is not None else f'<{ref_tag} id="{ref_id}"/>'
    st = (f"<sourcetrack><mediatype>audio</mediatype>"
          f"<trackindex>{channel}</trackindex></sourcetrack>"
          if channel else "")
    return (f"<clipitem id='ci-{name}-{start}'><name>{name}</name>"
            f"<enabled>TRUE</enabled><rate><timebase>30</timebase>"
            f"<ntsc>FALSE</ntsc></rate>"
            f"<start>{start}</start><end>{end}</end>"
            f"<in>{in_}</in><out>{in_ + (end - start)}</out>"
            f"{src}{st}{filters}</clipitem>")


def _basic_motion(scale):
    return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid>"
            "<effecttype>motion</effecttype><mediatype>video</mediatype>"
            "<parameter><parameterid>scale</parameterid><name>Scale</name>"
            f"<value>{scale}</value></parameter></effect></filter>")


NEST = (
    '<sequence id="sequence-9"><name>wide reframe</name><duration>2000</duration>'
    '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>'
    '<media><video><format><samplecharacteristics>'
    '<width>2500</width><height>2560</height>'
    '</samplecharacteristics></format><track>'
    + _clipitem(0, 2000, 0, "WIDE.mp4", "file", "file-9",
                define='<file id="file-9"><name>WIDE.mp4</name>'
                       '<pathurl>file://localhost/D%3a/f/WIDE.mp4</pathurl>'
                       '<media><video/></media></file>',
                filters=_basic_motion(130))
    + '</track></video></media></sequence>'
)


def _master_xml() -> str:
    """A two-angle timeline: V1 flat files cut at 300, V2 a reused nest.

    V1's cut at frame 300 is the point of the whole fixture — a shot spanning it
    has to come out as two clipitems.
    """
    v1 = (_clipitem(0, 300, 1000, "CAM A", "file", "file-1",
                    define='<file id="file-1"><name>A.mp4</name>'
                           '<pathurl>file://localhost/D%3a/f/A.mp4</pathurl>'
                           '<media><video/></media></file>',
                    filters=_basic_motion(116))
          + _clipitem(300, 900, 5000, "CAM A", "file", "file-2",
                      define='<file id="file-2"><name>A2.mp4</name>'
                             '<pathurl>file://localhost/D%3a/f/A2.mp4</pathurl>'
                             '<media><video/></media></file>',
                      filters=_basic_motion(116))
          # Parked under a transition: no position on the timeline.
          + '<clipitem id="ci-hidden"><name>CAM A</name><start>-1</start>'
            '<end>-1</end><in>0</in><out>10</out>'
            '<file id="file-1"/></clipitem>')
    # Same nest on both halves, defined once and referenced after — and with a
    # gap from 600 to 700 where this angle simply has no footage.
    v2 = (_clipitem(0, 600, 100, "WIDE", "sequence", "sequence-9", define=NEST)
          + _clipitem(700, 900, 800, "WIDE", "sequence", "sequence-9"))
    a1 = (_clipitem(0, 400, 200, "MIX", "file", "file-5",
                    define='<file id="file-5"><name>mix.wav</name>'
                           '<pathurl>file://localhost/D%3a/f/mix.wav</pathurl>'
                           '<media><audio/></media></file>', channel=1)
          # A frame of sample-vs-frame rounding, exactly as Premiere writes it.
          + '<clipitem id="ci-drift"><name>MIX</name><start>400</start>'
            '<end>900</end><in>600</in><out>1099</out>'
            '<file id="file-5"/><sourcetrack><mediatype>audio</mediatype>'
            '<trackindex>1</trackindex></sourcetrack></clipitem>')
    # A muted camera scratch track: every clip disabled, and the pair either side
    # of a crossfade written with the transition-anchored -1 edges.
    a2 = ('<clipitem id="ci-s1"><name>SCRATCH</name><enabled>FALSE</enabled>'
          '<start>0</start><end>-1</end><in>50</in><out>350</out>'
          '<file id="file-7"><name>scratch.wav</name>'
          '<pathurl>file://localhost/D%3a/f/scratch.wav</pathurl>'
          '<media><audio/></media></file>'
          '<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex>'
          '</sourcetrack></clipitem>'
          '<transitionitem><start>298</start><end>302</end>'
          '<effect><name>Cross Fade</name></effect></transitionitem>'
          '<clipitem id="ci-s2"><name>SCRATCH</name><enabled>FALSE</enabled>'
          '<start>-1</start><end>900</end><in>400</in><out>1002</out>'
          '<file id="file-7"/><sourcetrack><mediatype>audio</mediatype>'
          '<trackindex>1</trackindex></sourcetrack></clipitem>'
          # Wholly inside a transition: genuinely unplaceable.
          '<clipitem id="ci-s3"><name>SCRATCH</name><start>-1</start>'
          '<end>-1</end><in>0</in><out>4</out><file id="file-7"/></clipitem>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE xmeml><xmeml version="4">'
        '<sequence id="sequence-1"><name>episode</name><duration>900</duration>'
        '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>'
        '<timecode><frame>0</frame></timecode>'
        '<media><video><format><samplecharacteristics>'
        '<width>1440</width><height>2560</height></samplecharacteristics></format>'
        f'<track>{v1}<enabled>TRUE</enabled></track>'
        f'<track>{v2}<enabled>TRUE</enabled></track>'
        '</video>'
        f'<audio><track>{a1}<enabled>TRUE</enabled></track>'
        f'<track>{a2}<enabled>TRUE</enabled></track></audio>'
        '</media></sequence></xmeml>')


def _write(tmp: Path, text: str) -> str:
    p = tmp / "master.xml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _load(tmp):
    return read_master(_write(tmp, _master_xml()))


# ── reader ───────────────────────────────────────────────────────────────────

def test_reads_tracks_and_resolves_references():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    check(m.duration == 900 and m.frame_size == (1440, 2560),
          f"sequence shape misread: {m.duration} {m.frame_size}")
    v1, v2 = m.track("V1"), m.track("V2")
    check(len(v1.segments) == 2,
          f"V1 should drop the transition-hidden item, got {len(v1.segments)}")
    check(v1.segments[0].source.path.endswith("A.mp4"),
          f"pathurl not decoded: {v1.segments[0].source.path!r}")
    # The second use is a bare <sequence id=…/>; it must resolve to the same
    # definition the first use carried, not to an empty stub.
    check(all(s.source.is_nest and s.source.name == "wide reframe"
              for s in v2.segments),
          "a bare nest reference should resolve to its first-use definition")


def test_slice_splits_at_master_cuts_and_reports_gaps():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    v1 = m.track("V1")
    pieces = v1.slice(200, 200)          # straddles the cut at 300
    check(len(pieces) == 2, f"expected 2 pieces across the cut, got {len(pieces)}")
    check(sum(p.length for p in pieces) == 200,
          "pieces must tile the requested range exactly")
    check(pieces[0].in_ == 1200 and pieces[1].in_ == 5000,
          f"source frames wrong: {[p.in_ for p in pieces]}")
    # Slicing wholly inside one segment is still one piece.
    check(len(v1.slice(310, 50)) == 1, "no spurious split inside a segment")
    check(m.track("V2").gaps(550, 200) == [(600, 700)],
          f"uncovered range misreported: {m.track('V2').gaps(550, 200)}")


def test_audio_frame_drift_is_snapped_not_rejected():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    a1 = m.track("A1")
    drifted = a1.segments[1]
    check(drifted.length == 500, "program range is the edit and must be kept")
    check(any("snapped" in w for w in m.warnings),
          "a snapped audio frame should be reported, not silent")


def test_transition_anchored_edges_are_recovered_not_dropped():
    """A -1 edge means "the transition sets this", not "no position".

    Reading it as unplaceable silently drops both halves of every crossfade — a
    third of a real lav track — which plays back as audio cutting in and out.
    """
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    a2 = m.track("A2")
    check(len(a2.segments) == 2,
          f"both halves of the crossfade should survive, got {len(a2.segments)}")
    # end=-1 recovers to start + (out - in); start=-1 to end - (out - in).
    check(a2.segments[0].start == 0 and a2.segments[1].end == 900,
          f"recovered edges are wrong: {[(s.start, s.end) for s in a2.segments]}")
    check(a2.coverage == 900, f"the track should tile 0..900, got {a2.coverage}")
    # The crossfade made them overlap; one track can't hold two clips at once.
    check(a2.segments[0].end == a2.segments[1].start,
          "overlapping halves must be butt-joined")
    for s in a2.segments:
        check(s.length > 0, "a trimmed segment must not survive with zero length")
    # An item with *both* edges at -1 really is unplaceable.
    check(all(s.name != "SCRATCH" or s.length > 4 for s in a2.segments),
          "the wholly-hidden item should not have been placed")


def test_source_mute_state_is_preserved():
    """The editor muted that scratch track on purpose."""
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    check(all(not s.enabled for s in m.track("A2").segments),
          "a disabled source clip must stay disabled")
    check(all(s.enabled for s in m.track("A1").segments),
          "an enabled source clip must stay enabled")

    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    beds = {tuple(sorted({i.enabled for i in tr})) for tr in c.audio_tracks}
    check((False,) in beds,
          f"the muted track must reach the reel muted, got {beds}")
    check((True,) in beds, f"the live track must stay live, got {beds}")


def test_retimed_picture_is_rejected():
    bad = _master_xml().replace("<in>5000</in><out>5600</out>",
                                "<in>5000</in><out>5300</out>")
    with tempfile.TemporaryDirectory() as td:
        try:
            read_master(_write(Path(td), bad))
            check(False, "a retimed video clipitem must raise")
        except ValueError as e:
            check("retimed" in str(e), f"unhelpful message: {e}")


def test_empty_video_tracks_name_the_multicam_cause():
    """Premiere drops multicam items silently — the error has to say so."""
    empty = ('<?xml version="1.0"?><!DOCTYPE xmeml><xmeml version="4">'
             '<sequence id="s"><name>episode</name><duration>900</duration>'
             '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>'
             '<media><video><track><enabled>TRUE</enabled></track></video>'
             '</media></sequence></xmeml>')
    with tempfile.TemporaryDirectory() as td:
        try:
            read_master(_write(Path(td), empty))
            check(False, "an all-empty video timeline must raise")
        except ValueError as e:
            check("multicam" in str(e).lower(),
                  f"error should point at multicam export, got: {e}")


# ── compile ──────────────────────────────────────────────────────────────────

def _cameras(m):
    return {"A": {"path": "", "offset_sec": 0.0, "has_video": True,
                  "track": m.track("V1")},
            "W": {"path": "", "offset_sec": 0.0, "has_video": True,
                  "track": m.track("V2")}}


def _edl(mode="source_tracks"):
    tb = Timebase(30)
    clip = Clip(id="c1", title="c1",
                segments=[Segment(5.0, 15.0, id="s1")],   # frames 150..450
                camera_cuts=[CameraCut(at=5.0, camera="A")])
    return EDL(timebase=tb, frame_size=(1440, 2560), default_camera="A",
               clips=[clip], audio=AudioPlan(mode=mode)), clip


def test_a_shot_spanning_a_master_cut_becomes_several_clipitems():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)

    a_track = next(t for t in c.video_tracks if t and t[0].camera == "A")
    check(len(a_track) == 2,
          f"the shot crosses one master cut, expected 2 items, got {len(a_track)}")
    check(a_track[0].start == 0 and a_track[-1].end == c.duration,
          "pieces must tile the program range")
    for a, b in zip(a_track, a_track[1:]):
        check(a.end == b.start, "pieces must butt-join, not overlap or gap")
    # __post_init__ already enforces this per item; assert the sum too.
    check(sum(i.length for i in a_track) == c.duration,
          "split pieces must sum to the shot length")


def test_stacked_angles_stay_aligned_with_only_one_enabled():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    for t in c.video_tracks:
        if not t or t[0].role != "camera":
            continue
        check(t[0].start == 0, f"angle {t[0].camera} must start at 0")
        enabled = {i.enabled for i in t}
        check(len(enabled) == 1, "an angle is enabled for the whole shot or not")
    seen = {t[0].camera for t in c.video_tracks if t and t[0].role == "camera"}
    check(seen == {"A", "W"},
          f"every track-backed angle should be stacked, got {seen}")
    check({i.camera for i in c.program_video()} == {"A"},
          "only the cut angle is enabled")


def test_source_tracks_audio_reproduces_the_master_bed():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    check(len(c.audio_tracks) == len([t for t in m.audio if t.segments]),
          f"one reel track per master track, got {len(c.audio_tracks)}")
    for items in c.audio_tracks:
        check(sum(i.length for i in items) == c.duration,
              "each bed track must cover the whole program")
        check(all(i.source is not None for i in items),
              "bed items should carry their master source, not a camera path")


def _muted_bed_master() -> str:
    """The shape Premiere actually writes for a muted track.

    Pressing M mutes the *track*; the clipitems on it are untouched and still
    read TRUE. The fixture's own scratch track is disabled the other way (per
    clipitem), so it can't catch this.
    """
    head, tail = _master_xml().split("<audio>", 1)
    return head + "<audio>" + tail.replace(
        "<enabled>TRUE</enabled></track>", "<enabled>FALSE</enabled></track>", 1)


def test_track_level_mute_reaches_the_reel():
    with tempfile.TemporaryDirectory() as td:
        m = read_master(_write(Path(td), _muted_bed_master()))
    check(not m.audio[0].enabled, "fixture: the first bed track should be muted")
    check(all(s.enabled for s in m.audio[0].segments),
          "fixture: its clipitems must still read enabled, as Premiere writes them")

    edl, clip = _edl()
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    muted = c.audio_tracks[0]
    check(muted and not any(i.enabled for i in muted),
          "a track the editor muted must arrive muted — otherwise the reel "
          "plays the camera scratch the enhanced mix was there to replace")
    with tempfile.TemporaryDirectory() as td:
        plain = _load(Path(td))
    base = compile_clip(edl, clip, _cameras(plain), audio_tracks=plain.audio)
    check([i.enabled for i in c.audio_tracks[1]]
          == [i.enabled for i in base.audio_tracks[1]],
          "muting one track must not disturb the others")


# ── writer ───────────────────────────────────────────────────────────────────

def test_nest_is_defined_once_and_referenced_after():
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    # Two segments either side of V2's gap, so the nest is used twice.
    tb = Timebase(30)
    clip = Clip(id="c1", title="c1",
                segments=[Segment(17.0, 19.0, id="s1"),    # frames 510..570
                          Segment(24.0, 26.0, id="s2")],   # frames 720..780
                camera_cuts=[CameraCut(at=17.0, camera="A")])
    edl = EDL(timebase=tb, frame_size=(1440, 2560), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="source_tracks"))
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    root = ET.fromstring(XmemlWriter().build([c], "t").split("<!DOCTYPE xmeml>\n")[1])

    nests = [s for s in root.iter("sequence")
             if s.get("id") == "sequence-9" and len(s)]
    check(len(nests) == 1,
          f"the nest must be defined exactly once, got {len(nests)}")
    sc = nests[0].find("media/video/format/samplecharacteristics")
    check(sc is not None and sc.findtext("width") == "2500",
          "the nest's own frame size carries its framing and must survive")
    refs = [s for s in root.iter("sequence")
            if s.get("id") == "sequence-9" and not len(s)]
    check(refs, "later uses should be bare id references")


def test_punch_composes_into_the_sources_own_motion():
    """Two Basic Motion blocks on one clipitem is undefined; multiply instead."""
    with tempfile.TemporaryDirectory() as td:
        m = _load(Path(td))
    tb = Timebase(30)
    # Two segments off the same angle: a jump cut, which earns a punch.
    clip = Clip(id="c1", title="c1",
                segments=[Segment(1.0, 3.0, id="s1"), Segment(8.0, 10.0, id="s2")],
                camera_cuts=[CameraCut(at=1.0, camera="A")])
    edl = EDL(timebase=tb, frame_size=(1440, 2560), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="source_tracks"))
    c = compile_clip(edl, clip, _cameras(m), audio_tracks=m.audio)
    root = ET.fromstring(XmemlWriter().build([c], "t").split("<!DOCTYPE xmeml>\n")[1])

    for ci in root.iter("clipitem"):
        motions = [f for f in ci.findall("filter")
                   if f.findtext("effect/effectid") == "basic"]
        check(len(motions) <= 1,
              f"{len(motions)} Basic Motion blocks on one clipitem")
    scales = sorted(float(p.findtext("value")) for p in root.iter("parameter")
                    if p.findtext("parameterid") == "scale")
    check(116.0 in scales,
          f"the source's own framing must survive unpunched shots: {scales}")
    check(any(116.0 < s <= 116.0 * 1.10 for s in scales),
          f"the punch should multiply the source scale, got {scales}")


def main():
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
