"""Frame-math invariants. These are the tests that keep cuts landing on frame.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_frame_math
"""
import random
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction

from ..compile import compile_clip
from ..edl import EDL, AudioPlan, BRoll, CameraCut, Clip, Segment, validate
from ..timebase import Timebase
from ..xmeml import from_pathurl
from ..xmeml.writer import XmemlWriter

RATES = [
    Timebase(24, ntsc=True),    # 23.976
    Timebase(24),
    Timebase(25),
    Timebase(30, ntsc=True),    # 29.97
    Timebase(30),
    Timebase(60, ntsc=True),    # 59.94
]

CAMERAS = {
    "A": {"path": r"D:\footage\Cam A.mp4", "offset_sec": 0.0},
    "B": {"path": r"D:\footage\Cam B.mp4", "offset_sec": 0.0},
    "C": {"path": r"D:\footage\Кам C.mp4", "offset_sec": 0.0},  # non-ASCII on purpose
}

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


# ── timebase ─────────────────────────────────────────────────────────────────

def test_ntsc_rates():
    tb = Timebase(30, ntsc=True)
    check(tb.fps == Fraction(30000, 1001), "29.97 must be exactly 30000/1001")
    # One hour of 29.97 is 107892 frames, not 108000. A 30fps assumption would
    # put the last cut of an hour-long episode ~3.6s early.
    check(tb.to_frames(3600.0) == 107892,
          f"1h @29.97 should be 107892 frames, got {tb.to_frames(3600.0)}")
    check(Timebase(30).to_frames(3600.0) == 108000, "1h @30 should be 108000")


def test_timecode_roundtrip():
    for tb in RATES:
        for frame in (0, 1, 999, 12345, 107891):
            tc = tb.to_timecode(frame)
            back = tb.from_timecode(tc)
            check(back == frame,
                  f"{tb} timecode roundtrip {frame} -> {tc} -> {back}")


def test_from_fps():
    check(Timebase.from_fps(Fraction(30000, 1001)) == Timebase(30, ntsc=True),
          "30000/1001 should detect as NTSC 30")
    check(Timebase.from_fps(Fraction(25)) == Timebase(25), "25 should be plain")
    check(Timebase.from_fps(None).timebase == 30, "missing fps falls back to 30")


# ── compile invariants ───────────────────────────────────────────────────────

def _random_clip(rng, tb, n_segments=6):
    """A clip with non-overlapping segments and camera cuts sprinkled inside."""
    segs, cuts = [], []
    t = rng.uniform(0, 30)
    for i in range(n_segments):
        dur = rng.uniform(1.0, 12.0)
        segs.append(Segment(start=round(t, 3), end=round(t + dur, 3), id=f"s{i}"))
        # A couple of camera switches inside the segment.
        for _ in range(rng.randint(0, 3)):
            cuts.append(CameraCut(at=round(rng.uniform(t, t + dur), 3),
                                  camera=rng.choice(list(CAMERAS))))
        t += dur + rng.uniform(0.2, 20.0)
    return Clip(id="c1", title="random", segments=segs, camera_cuts=cuts)


def test_compile_invariants():
    rng = random.Random(1234)
    for trial in range(300):
        tb = rng.choice(RATES)
        clip = _random_clip(rng, tb)
        edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
                  clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
        compiled = compile_clip(edl, clip, CAMERAS)

        for track in compiled.video_tracks + compiled.audio_tracks:
            prev_end = None
            for item in track:
                # The invariant. ClipItem.__post_init__ also asserts it, so
                # reaching here means it held.
                check(item.end - item.start == item.out - item.in_,
                      f"trial {trial}: retime on {item.name}")
                check(item.length > 0, f"trial {trial}: zero-length {item.name}")
                if prev_end is not None:
                    check(item.start >= prev_end,
                          f"trial {trial}: overlap at {item.start}")
                prev_end = item.end

        v1 = compiled.video_tracks[0]
        # V1 must be gapless: a hole would show as black frames in the export.
        for a, b in zip(v1, v1[1:]):
            check(a.end == b.start,
                  f"trial {trial}: gap between {a.end} and {b.start}")
        check(v1[0].start == 0, f"trial {trial}: V1 must start at frame 0")
        check(sum(i.length for i in v1) == compiled.duration,
              f"trial {trial}: durations disagree")

        # Audio must cover exactly the same span as picture.
        for atrack in compiled.audio_tracks:
            check(atrack[-1].end == compiled.duration,
                  f"trial {trial}: audio ends at {atrack[-1].end}, "
                  f"picture at {compiled.duration}")


def test_pinned_audio_ignores_camera_cuts():
    """Pinned audio should cut at segments only — that continuity is the point."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")],
                camera_cuts=[CameraCut(at=0, camera="A"),
                             CameraCut(at=3, camera="B"),
                             CameraCut(at=6, camera="A")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)
    check(len(c.video_tracks[0]) == 3, "3 camera cuts should give 3 video shots")
    check(all(len(t) == 1 for t in c.audio_tracks),
          "pinned audio should be one unbroken run per track")
    heard = c.program_audio()
    check(heard and heard[0].camera == "A",
          "the audible audio must come from the pinned camera only")
    # Every other camera's mic is laid in underneath, muted.
    for track in c.audio_tracks[1:]:
        check(all(not it.enabled for it in track),
              f"scratch audio from {track[0].camera!r} must import disabled")


def test_pinned_audio_is_not_duplicated():
    """One source, one track.

    A stereo file has a single source audio *track* carrying two channels;
    asking for source tracks 1 and 2 lands the same stereo pair on two timeline
    tracks, which is what this guards against.
    """
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip],
              audio=AudioPlan(mode="pinned", pinned_camera="A", channels=2))
    c = compile_clip(edl, clip, CAMERAS)
    from_pinned = [t for t in c.audio_tracks if t[0].camera == "A"]
    check(len(from_pinned) == 1,
          f"pinned source must occupy exactly 1 track, got {len(from_pinned)}")
    enabled = [t for t in c.audio_tracks if any(i.enabled for i in t)]
    check(len(enabled) == 1,
          f"exactly 1 audio track should be enabled, got {len(enabled)}")


def test_camera_stack_toggles_the_angle():
    """Every shot exists on every camera track; exactly one is enabled."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")],
                camera_cuts=[CameraCut(at=0, camera="A"),
                             CameraCut(at=5, camera="B")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)
    cam_tracks = [t for t in c.video_tracks if t and t[0].role == "camera"]
    check(len(cam_tracks) == len(CAMERAS),
          f"expected one track per camera, got {len(cam_tracks)}")
    check(all(len(t) == 2 for t in cam_tracks),
          "every camera track must carry every shot")

    # At each shot, exactly one angle is live — and it's the one the EDL picked.
    for shot_idx, expected in enumerate(["A", "B"]):
        live = [t[shot_idx] for t in cam_tracks if t[shot_idx].enabled]
        check(len(live) == 1,
              f"shot {shot_idx}: expected 1 enabled angle, got {len(live)}")
        check(live[0].camera == expected,
              f"shot {shot_idx}: expected {expected}, got {live[0].camera}")

    # Toggling must not move the edit: twins are frame-identical in program time.
    for shot_idx in range(2):
        twins = [t[shot_idx] for t in cam_tracks]
        check(len({(i.start, i.end) for i in twins}) == 1,
              f"shot {shot_idx}: stacked angles must share program timing")
        check(all(i.end - i.start == i.out - i.in_ for i in twins),
              f"shot {shot_idx}: a stacked twin would retime")

    check([i.camera for i in c.program_video()] == ["A", "B"],
          "program_video should read the cut across the stack")


def test_jump_cut_punch_breaks_matching_framing():
    """Same camera + a gap in the source = a jump cut, and must not match."""
    from ..compile import jump_cut_scales

    # 0-5 and 8-12 are one take with the middle dropped: a jump cut.
    shots = [(0.0, 5.0, "A"), (8.0, 12.0, "A")]
    s = jump_cut_scales(shots, punch=4.0)
    check(s[0] != s[1], f"a jump cut must change framing, got {s}")

    # Contiguous source is not a cut at all — leave it alone.
    s = jump_cut_scales([(0.0, 5.0, "A"), (5.0, 9.0, "A")], punch=4.0)
    check(s == [100.0, 100.0], f"contiguous source needs no punch, got {s}")

    # An angle change already hides the join, and resets the alternation.
    s = jump_cut_scales([(0.0, 5.0, "A"), (8.0, 12.0, "B")], punch=4.0)
    check(s == [100.0, 100.0], f"an angle change needs no punch, got {s}")

    # Consecutive jump cuts must keep alternating, never repeat a framing.
    shots = [(0.0, 2.0, "A"), (4.0, 6.0, "A"), (8.0, 10.0, "A"), (12.0, 14.0, "A")]
    s = jump_cut_scales(shots, punch=4.0)
    for a, b in zip(s, s[1:]):
        check(a != b, f"adjacent jump cuts must differ, got {s}")

    check(jump_cut_scales(shots, punch=0.0) == [100.0] * 4,
          "punch=0 must disable the effect entirely")


def test_punch_is_shared_by_stacked_angles_and_reaches_xml():
    """Toggling an angle must not also change the zoom."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 5), Segment(8, 12)])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)

    cam_tracks = [t for t in c.video_tracks if t and t[0].role == "camera"]
    for shot_idx in range(2):
        scales = {t[shot_idx].scale for t in cam_tracks}
        check(len(scales) == 1,
              f"shot {shot_idx}: stacked angles must share a scale, got {scales}")
    check(cam_tracks[0][0].scale != cam_tracks[0][1].scale,
          "the jump cut between the two segments should be punched")

    xml = XmemlWriter().build([c], "test")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])
    scale_vals = [p.findtext("value") for p in root.findall(".//parameter")
                  if p.findtext("parameterid") == "scale"]
    check(scale_vals, "a punched shot should emit a Basic Motion scale")
    check(all(float(v) > 100.0 for v in scale_vals),
          f"emitted scales should be punch-ins, got {scale_vals}")
    # Identity framing must not carry a filter at all — a 100% Basic Motion
    # block on every clip is noise the editor has to look past.
    check(len(scale_vals) < sum(len(t) for t in cam_tracks),
          "unpunched shots must not emit a motion filter")


def test_audio_only_source_is_never_stacked_as_picture():
    """The enhanced mix carries the sound, but it is not an angle."""
    tb = Timebase(30)
    cams = dict(CAMERAS)
    cams["MIX"] = {"path": r"D:\footage\mix.mp3", "offset_sec": 0.0,
                   "has_video": False}
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="MIX"))
    c = compile_clip(edl, clip, cams)
    picture_cams = {i.camera for t in c.video_tracks for i in t
                    if i.role == "camera"}
    check("MIX" not in picture_cams,
          "an audio-only source must never get a picture track")
    check(c.program_audio()[0].camera == "MIX",
          "the mix should still be the audible track")


def test_follow_video_links():
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")],
                camera_cuts=[CameraCut(at=0, camera="A"),
                             CameraCut(at=5, camera="B")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="follow_video", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)
    xml = XmemlWriter().build([c], "test")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])
    links = root.findall(".//link")
    check(links, "follow_video should emit <link> elements")
    # Every audio clipitem is frame-identical to its video partner, and one
    # source is one track, so each group is 1 video + 1 audio = 2 links.
    for item in root.findall(".//clipitem"):
        n = len(item.findall("link"))
        check(n in (0, 2), f"expected 2 links per linked item, got {n}")


def test_pinned_emits_no_links():
    """Pinned audio spans camera switches, so nothing is frame-identical."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10, id="s1")],
                camera_cuts=[CameraCut(at=0, camera="A"),
                             CameraCut(at=5, camera="B")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    xml = XmemlWriter().build([compile_clip(edl, clip, CAMERAS)], "test")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])
    check(not root.findall(".//link"),
          "pinned audio must not be linked to picture (it would flag out-of-sync)")


# ── xmeml structure ──────────────────────────────────────────────────────────

def test_sequence_names_carry_their_edl_position():
    """Premiere sorts a bin by name, so the order has to be in the name."""
    tb = Timebase(30)
    clips = [Clip(id=f"c{i:02d}", title=f"clip {i}",
                  segments=[Segment(i * 60.0, i * 60.0 + 20, id="s1")],
                  camera_cuts=[CameraCut(at=i * 60.0, camera="A")])
             for i in range(1, 4)]
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=clips, audio=AudioPlan(mode="pinned", pinned_camera="A"))

    names = [compile_clip(edl, c, CAMERAS).name for c in clips]
    check(names == ["01 clip 1", "02 clip 2", "03 clip 3"],
          f"sequences should be numbered in EDL order, got {names}")
    # Exporting one clip alone must keep its own number, not restart at 01.
    check(compile_clip(edl, clips[2], CAMERAS).name == "03 clip 3",
          "a clip's number comes from the EDL, not from the compiled subset")

    xml = XmemlWriter().build([compile_clip(edl, c, CAMERAS) for c in clips], "t")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])
    seq_names = [s.findtext("name") for s in root.findall("bin/children/sequence")]
    check(seq_names == ["01 clip 1", "02 clip 2", "03 clip 3"],
          f"the number has to reach the XML, got {seq_names}")


def test_file_definitions_are_deduped():
    """14 clips off 3 cameras must yield 3 <file> definitions, not 42."""
    tb = Timebase(30)
    clips = []
    for i in range(14):
        base = i * 60.0
        clips.append(Clip(
            id=f"c{i:02d}", title=f"clip {i}",
            segments=[Segment(base, base + 20, id="s1")],
            camera_cuts=[CameraCut(at=base, camera="A"),
                         CameraCut(at=base + 7, camera="B"),
                         CameraCut(at=base + 13, camera="C")]))
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=clips, audio=AudioPlan(mode="pinned", pinned_camera="A"))
    compiled = [compile_clip(edl, c, CAMERAS) for c in clips]
    xml = XmemlWriter().build(compiled, "episode")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])

    full = [f for f in root.findall(".//file") if f.find("pathurl") is not None]
    check(len(full) == 3,
          f"expected 3 full <file> definitions for 3 cameras, got {len(full)}")
    refs = [f for f in root.findall(".//file") if f.find("pathurl") is None]
    check(refs, "later references should be bare <file id=.../>")
    check(len(root.findall(".//sequence")) == 14,
          "expected one sequence per clip")
    # Every bare reference must point at a defined id.
    defined = {f.get("id") for f in full}
    check(all(r.get("id") in defined for r in refs),
          "a bare <file> reference points at an undefined id")


def test_pathurl_forms():
    from ..xmeml.pathurl import to_pathurl
    u = to_pathurl(r"D:\footage\Cam A.mp4")
    check(u.startswith("file://localhost/"),
          f"Premiere wants file://localhost/, got {u}")
    check("%20" in u, f"spaces must be percent-encoded: {u}")
    check(from_pathurl(u).name == "Cam A.mp4", f"roundtrip failed: {u}")
    cyr = to_pathurl(r"D:\footage\Кам C.mp4")
    check("%D0%9A" in cyr, f"Cyrillic must be percent-encoded from UTF-8: {cyr}")
    check(from_pathurl(cyr).name == "Кам C.mp4", "Cyrillic roundtrip failed")


def test_xml_roundtrip_positions():
    """Re-read the XML and confirm positions survive serialization."""
    tb = Timebase(30, ntsc=True)
    clip = Clip(id="c1", title="hook",
                segments=[Segment(10.0, 25.0, id="s1"), Segment(60.0, 72.5, id="s2")],
                camera_cuts=[CameraCut(at=10.0, camera="A"),
                             CameraCut(at=18.0, camera="B")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    compiled = compile_clip(edl, clip, CAMERAS)
    xml = XmemlWriter().build([compiled], "test")
    root = ET.fromstring(xml.split("<!DOCTYPE xmeml>\n")[1])

    seq = root.find(".//sequence")
    check(int(seq.find("duration").text) == compiled.duration,
          "sequence duration mismatch")
    vtrack = seq.find("./media/video/track")
    parsed = [(int(ci.find("start").text), int(ci.find("end").text),
               int(ci.find("in").text), int(ci.find("out").text))
              for ci in vtrack.findall("clipitem")]
    original = [(i.start, i.end, i.in_, i.out) for i in compiled.video_tracks[0]]
    check(parsed == original, f"positions changed through XML:\n{parsed}\n{original}")


def test_broll_placeholder_becomes_marker():
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 30, id="s1")],
                broll=[BRoll(start=10, end=14, id="b1", query="drone, Tashkent")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)
    check(not c.items_by_role("broll"),
          "placeholder b-roll must not create a b-roll track")
    check(any("BROLL" in m.comment for m in c.markers),
          "placeholder b-roll should become a marker carrying the query")
    marker = next(m for m in c.markers if "BROLL" in m.comment)
    check(marker.frame == 300, f"marker should sit at frame 300, got {marker.frame}")


def test_broll_overlay_maps_to_program_time():
    """B-roll at master 65s must land at program time, not master time."""
    tb = Timebase(30)
    clip = Clip(id="c1",
                segments=[Segment(0, 10, id="s1"), Segment(60, 70, id="s2")],
                broll=[BRoll(start=62, end=65, id="b1",
                             source=r"D:\broll\drone.mp4", status="attached")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    c = compile_clip(edl, clip, CAMERAS)
    broll = c.items_by_role("broll")
    check(len(broll) == 1, "attached b-roll should create a b-roll track")
    b = broll[0]
    check(c.video_tracks[-1] is not broll,
          "b-roll must sit above the camera stack, not replace it")
    # Segment 1 is 10s (300f); b-roll starts 2s into segment 2 => frame 360.
    check(b.start == 360, f"b-roll should map to program frame 360, got {b.start}")
    check(b.length == 90, f"b-roll should be 90 frames, got {b.length}")


# ── validation ───────────────────────────────────────────────────────────────

def test_validation_catches_real_mistakes():
    tb = Timebase(30)
    bad = Clip(id="c1", segments=[Segment(10, 20, id="s1"), Segment(15, 25, id="s2")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[bad], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    r = validate(edl, list(CAMERAS), master_duration=3600)
    check(any("overlap" in e for e in r["errors"]), "overlap must be an error")

    unknown = Clip(id="c2", segments=[Segment(0, 5)],
                   camera_cuts=[CameraCut(at=0, camera="Z")])
    edl.clips = [unknown]
    r = validate(edl, list(CAMERAS), master_duration=3600)
    check(any("unknown camera" in e for e in r["errors"]),
          "unknown camera must be an error")

    past = Clip(id="c3", segments=[Segment(0, 99999)])
    edl.clips = [past]
    r = validate(edl, list(CAMERAS), master_duration=3600)
    check(any("past the" in e for e in r["errors"]),
          "segment beyond source must be an error")

    outside = Clip(id="c4", segments=[Segment(0, 10)],
                   broll=[BRoll(start=50, end=55, id="b1")])
    edl.clips = [outside]
    r = validate(edl, list(CAMERAS), master_duration=3600)
    check(any("not inside a kept segment" in e for e in r["errors"]),
          "b-roll outside a segment must be an error")

    glitch = Clip(id="c5", segments=[Segment(0, 10)],
                  camera_cuts=[CameraCut(at=0, camera="A"),
                               CameraCut(at=5.0, camera="B"),
                               CameraCut(at=5.2, camera="A")])
    edl.clips = [glitch]
    r = validate(edl, list(CAMERAS), master_duration=3600)
    check(any("glitch" in w for w in r["warnings"]),
          "a 0.2s shot should warn but not block")
    check(r["ok"], "warnings alone must not block export")


def test_audio_only_source_cannot_carry_picture():
    """A combined mix registered beside the cameras is pinnable but not cuttable.

    Isolated per-subject mics mean no single camera hears the conversation, so
    the mix gets registered as a source and transcribed. It has no video stream:
    cutting picture to it would emit a video clipitem pointing at an mp3, which
    Premiere shows as offline media rather than failing loudly.
    """
    tb = Timebase(30)
    ids = list(CAMERAS) + ["M"]
    with_video = list(CAMERAS)

    cut_to_mix = Clip(id="c1", segments=[Segment(0, 10)],
                      camera_cuts=[CameraCut(at=0, camera="M")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[cut_to_mix], audio=AudioPlan(mode="pinned", pinned_camera="M"))
    r = validate(edl, ids, master_duration=3600, video_camera_ids=with_video)
    check(any("no video stream" in e for e in r["errors"]),
          "cutting picture to an audio-only source must be an error")

    # ...but pinning audio to that same source is exactly the intended use.
    edl.clips = [Clip(id="c2", segments=[Segment(0, 10)],
                      camera_cuts=[CameraCut(at=0, camera="A")])]
    r = validate(edl, ids, master_duration=3600, video_camera_ids=with_video)
    check(r["ok"], f"pinning audio to the mix must be allowed: {r['errors']}")

    edl.default_camera = "M"
    r = validate(edl, ids, master_duration=3600, video_camera_ids=with_video)
    check(any("no video stream" in e for e in r["errors"]),
          "an audio-only default_camera must be an error")

    # Omitting video_camera_ids keeps the pre-audio-only behaviour intact.
    edl.default_camera = "A"
    edl.clips = [cut_to_mix]
    r = validate(edl, ids, master_duration=3600)
    check(not any("no video stream" in e for e in r["errors"]),
          "without video_camera_ids, every known camera may carry picture")


def test_edl_json_roundtrip():
    tb = Timebase(30, ntsc=True)
    clip = Clip(id="c1", title="hook", segments=[Segment(1.5, 9.25, id="s1")],
                camera_cuts=[CameraCut(at=1.5, camera="A", why="host")],
                broll=[BRoll(start=3, end=5, id="b1", query="drone")],
                markers=[])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
    back = EDL.from_dict(edl.to_dict())
    check(back.to_dict() == edl.to_dict(), "EDL JSON roundtrip lost data")
    check(back.timebase == tb, "timebase lost through roundtrip")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        before = len(_failures)
        try:
            t()
        except Exception as e:
            _failures.append(f"{t.__name__} raised {type(e).__name__}: {e}")
        status = "ok" if len(_failures) == before else "FAIL"
        print(f"  {status:4}  {t.__name__}")
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
