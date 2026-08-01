"""Caption remapping: master-timeline words -> a clip's program timeline.

The property that matters is that caption time and picture time are derived the
same way, so a word can never drift from the frame it was spoken on.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_captions
"""
import sys

from caption_engine.transcriber.word import Word

from ..captions import (build_style, program_ranges, validate_words,
                        words_for_clip, words_from_payload)
from ..compile import compile_clip
from ..edl import EDL, AudioPlan, CameraCut, Clip, Segment
from ..timebase import Timebase

CAMERAS = {"A": {"path": r"D:\f\A.mp4", "offset_sec": 0.0},
           "B": {"path": r"D:\f\B.mp4", "offset_sec": 0.0}}

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _words(spec):
    """[(text, start, end), ...] -> Word list."""
    return [Word(text=t, start=s, end=e) for t, s, e in spec]


def test_discarded_words_are_dropped():
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(10, 20), Segment(40, 50)])
    master = _words([("keep1", 11, 12), ("gone", 30, 31), ("keep2", 41, 42)])
    out = words_for_clip(master, clip, tb)
    check([w.text for w in out] == ["keep1", "keep2"],
          f"words outside kept segments must vanish, got {[w.text for w in out]}")


def test_program_time_is_contiguous():
    """A word 1s into the second segment lands 1s after the first segment ends."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(10, 20), Segment(40, 50)])
    master = _words([("a", 10.5, 11.0), ("b", 41.0, 41.5)])
    out = words_for_clip(master, clip, tb)
    check(abs(out[0].start - 0.5) < 1e-6,
          f"first word should start at 0.5s program, got {out[0].start}")
    # Segment 1 is 10s long, so 41.0 master = 1.0 into segment 2 = 11.0 program.
    check(abs(out[1].start - 11.0) < 1e-6,
          f"second word should start at 11.0s program, got {out[1].start}")


def test_straddling_word_is_clamped_not_dropped():
    """A word crossing a segment edge keeps the part that survived — dropping it
    would silently lose the first or last word, usually the hook."""
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(10, 20)])
    master = _words([("edge", 9.5, 10.4), ("tail", 19.7, 20.6)])
    out = words_for_clip(master, clip, tb)
    check(len(out) == 2, f"both straddling words should survive, got {len(out)}")
    check(abs(out[0].start - 0.0) < 1e-6,
          f"leading straddle should clamp to 0, got {out[0].start}")
    check(abs(out[1].end - 10.0) < 1e-6,
          f"trailing straddle should clamp to clip end, got {out[1].end}")


def test_caption_time_matches_picture_time():
    """The real invariant: caption program length must equal the compiled
    clip's program length, at every rate, including NTSC."""
    for tb in (Timebase(30), Timebase(30, ntsc=True), Timebase(25),
               Timebase(24, ntsc=True)):
        clip = Clip(id="c1",
                    segments=[Segment(3.3, 11.7), Segment(20.15, 33.9),
                              Segment(50.0, 58.42)],
                    camera_cuts=[CameraCut(at=3.3, camera="A"),
                                 CameraCut(at=25.0, camera="B")])
        edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
                  clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))
        compiled = compile_clip(edl, clip, CAMERAS)

        ranges = program_ranges(clip, tb)
        total_from_ranges = ranges[-1][2] + (tb.to_frames(ranges[-1][1])
                                             - tb.to_frames(ranges[-1][0]))
        check(total_from_ranges == compiled.duration,
              f"{tb}: caption ranges total {total_from_ranges}f but picture is "
              f"{compiled.duration}f — captions would drift")

        # A word at the very end of the last segment must land inside the clip.
        master = _words([("last", 58.3, 58.42)])
        out = words_for_clip(master, clip, tb)
        check(out and out[0].end <= compiled.duration_seconds + 1e-6,
              f"{tb}: final word ends at {out[0].end if out else None}, "
              f"clip is {compiled.duration_seconds}")


def test_payload_parsing_and_validation():
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10)])
    parsed = words_from_payload([
        {"text": "Hello", "start": 0.1, "end": 0.5},
        {"text": "world🔥", "start": 0.5, "end": 1.0, "line_break": True},
    ])
    check(len(parsed) == 2, "payload should parse two words")
    check(parsed[1].line_break, "line_break should survive parsing")
    check(validate_words(parsed, clip.duration)["ok"], "valid words should pass")

    try:
        words_from_payload([{"text": "x", "start": 0.0}])
        check(False, "missing 'end' should raise")
    except ValueError:
        pass

    past = words_from_payload([{"text": "x", "start": 0.0, "end": 99.0}])
    r = validate_words(past, clip.duration)
    check(not r["ok"], "a word past the clip end must be rejected")

    backwards = words_from_payload([
        {"text": "b", "start": 5.0, "end": 5.5},
        {"text": "a", "start": 1.0, "end": 1.5},
    ])
    # words_from_payload sorts, so ordering is repaired rather than rejected.
    check([w.text for w in backwards] == ["a", "b"],
          "out-of-order payload should be sorted, not rejected")

    no_breaks = words_from_payload([{"text": "x", "start": 0.0, "end": 1.0}])
    check(any("line_break" in w for w in validate_words(no_breaks, 10)["warnings"]),
          "missing line_break should warn (it drives on-screen line layout)")


def test_strip_is_default_and_preserves_preset():
    """Strip is the default: positioning by hand is the preferred workflow, and
    presets are hand-tuned at their own canvas width."""
    from caption_engine import presets as _presets
    from ..captions import DEFAULT_PRESET
    base = _presets.get(DEFAULT_PRESET)

    style = build_style(None, (1080, 1920), 30)
    check(style.height < 1920,
          f"default should be a strip, got height {style.height}")
    check(style.width == base.width,
          f"strip mode must not rewrite the preset's width "
          f"({base.width} -> {style.width})")
    check(style.vertical_anchor == base.vertical_anchor,
          "strip mode must keep the preset's own anchor")
    check(style.font_size == base.font_size,
          "strip mode must not touch typography")
    check(style.fps == 30, "fps must follow the sequence timebase regardless")


def test_full_frame_opt_in():
    style = build_style(None, (1080, 1920), 30, full_frame=True)
    check((style.width, style.height) == (1080, 1920),
          f"full-frame canvas should match the clip, got "
          f"{style.width}x{style.height}")
    check(0.5 < style.vertical_anchor < 1.0,
          f"full-frame captions should sit in the lower half, got "
          f"{style.vertical_anchor}")

    custom = build_style(None, (1080, 1920), 30, full_frame=True,
                         vertical_anchor=0.9)
    check(custom.vertical_anchor == 0.9, "explicit anchor should win")


def test_scale_to_width_scales_typography():
    """Resizing the canvas without scaling type would change the design."""
    from caption_engine import presets as _presets
    from ..captions import DEFAULT_PRESET
    base = _presets.get(DEFAULT_PRESET)
    target_w = int(base.width * 0.75)

    style = build_style(None, (target_w, 1920), 30, scale_to_width=True)
    check(style.width == target_w, f"width should become {target_w}")
    check(abs(style.font_size - base.font_size * 0.75) <= 1,
          f"font should scale with the canvas: {base.font_size} -> "
          f"{style.font_size}, expected ~{base.font_size * 0.75:.0f}")
    check(style.height < base.height,
          "strip height should shrink with the canvas")


def test_caption_track_lands_on_top():
    tb = Timebase(30)
    clip = Clip(id="c1", segments=[Segment(0, 10)],
                camera_cuts=[CameraCut(at=0, camera="A")])
    edl = EDL(timebase=tb, frame_size=(1080, 1920), default_camera="A",
              clips=[clip], audio=AudioPlan(mode="pinned", pinned_camera="A"))

    plain = compile_clip(edl, clip, CAMERAS)
    check(not plain.items_by_role("caption"),
          "no caption mov => no caption track")

    withcap = compile_clip(edl, clip, CAMERAS, caption_mov=r"D:\f\c1.mov")
    check(len(withcap.video_tracks) == len(plain.video_tracks) + 1,
          "caption mov should add exactly one track")
    check(withcap.video_tracks[-1][0].role == "caption",
          "captions must be the topmost video track, above the camera stack")
    cap = withcap.video_tracks[-1][0]
    check(cap.start == 0 and cap.end == withcap.duration,
          f"caption should span the whole clip, got {cap.start}-{cap.end} "
          f"of {withcap.duration}")
    check(cap.end - cap.start == cap.out - cap.in_,
          "caption clipitem must not retime")


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
