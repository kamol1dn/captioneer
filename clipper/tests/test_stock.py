"""Stock footage: from a download to an attached, correctly scaled entry.

The failure modes worth pinning are the silent ones. A 16:9 shot at 100% on a
9:16 sequence is a letterboxed band nobody asked for; a file declared at the
wrong size makes Premiere rescale it; a download paired with the wrong
placeholder attaches without complaint. None of these error — they just look
wrong in Premiere, after the import.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_stock
"""
import sys
import tempfile
import zipfile
from pathlib import Path

from ..compile import compile_clip, fill_scale
from ..edl import AudioPlan, BRoll, CameraCut, Clip, EDL, Segment
from ..graphics import check_props, plan_jobs, template_kind
from ..stock import _unzip_videos, broll_file_meta, pending_slots, suggest
from ..timebase import Timebase

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _edl(broll=None):
    clip = Clip(id="c1", title="c1", segments=[Segment(10.0, 40.0, id="s1")],
                camera_cuts=[CameraCut(at=10.0, camera="A")],
                broll=list(broll or []))
    edl = EDL(timebase=Timebase(30, ntsc=True), frame_size=(1440, 2560),
              default_camera="A", clips=[clip],
              audio=AudioPlan(mode="pinned", pinned_camera="A"))
    return edl, clip


def _cameras():
    return {"A": {"path": "A.mp4", "offset_sec": 0.0, "has_video": True}}


# -- scale ---------------------------------------------------------------------

def test_horizontal_4k_covers_vertical_frame():
    s = fill_scale({"width": 3840, "height": 2160}, (1440, 2560))
    check(abs(s - 2560 / 2160 * 100) < 0.01, f"4K 16:9 should fill height, got {s}")


def test_vertical_4k_scales_down():
    s = fill_scale({"width": 2160, "height": 3840}, (1440, 2560))
    check(abs(s - 66.667) < 0.01, f"vertical 4K should scale to 66.7%, got {s}")


def test_unknown_size_stays_at_100():
    check(fill_scale(None, (1440, 2560)) == 100.0, "no media -> 100%")


def test_compiled_footage_carries_fill_scale():
    edl, clip = _edl([BRoll(12.0, 15.0, id="b1", kind="footage",
                            source="stock.mp4", status="attached",
                            media={"width": 3840, "height": 2160})])
    compiled = compile_clip(edl, clip, _cameras())
    items = compiled.items_by_role("broll")
    check(items and abs(items[0].scale - 118.519) < 0.01,
          f"footage should compile at fill scale, got {items and items[0].scale}")


def test_candidates_reach_the_placeholder_marker():
    edl, clip = _edl([BRoll(12.0, 15.0, id="b1", kind="footage",
                            query="bank exterior",
                            candidates=[{"url": "https://e.com/bank-ABC1234",
                                         "title": "Bank Facade"}])])
    compiled = compile_clip(edl, clip, _cameras())
    comments = " ".join(m.comment for m in compiled.markers)
    check("https://e.com/bank-ABC1234" in comments,
          f"candidate url missing from marker: {comments!r}")


# -- file metadata -------------------------------------------------------------

def test_rendered_graphic_declares_no_audio_and_real_size():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "g.mov"
        f.write_bytes(b"x")
        edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay", source=str(f),
                             status="attached",
                             media={"width": 1440, "height": 2560, "fps": 29.97,
                                    "duration": 3.0, "has_audio": False})])
        meta, warnings = broll_file_meta(edl)
    m = meta.get(str(f.resolve()), {})
    check(m.get("has_audio") is False, f"graphic must declare no audio: {m}")
    check((m.get("width"), m.get("height")) == (1440, 2560), f"size wrong: {m}")
    check(m.get("duration_frames") == 90, f"duration frames wrong: {m}")


# -- matching ------------------------------------------------------------------

def test_name_match_beats_order():
    edl, clip = _edl([
        BRoll(12.0, 14.0, id="b1", kind="footage",
              candidates=[{"url": "https://elements.envato.com/city-skyline-at-night-QWE1234"}]),
        BRoll(20.0, 22.0, id="b2", kind="footage",
              candidates=[{"url": "https://elements.envato.com/hand-holding-phone-ZXC9876",
                           "title": "Hand Holding Phone"}]),
    ])
    files = [Path("hand-holding-phone-2024-01-01-10-00-00-utc.mp4"),
             Path("city-skyline-night-2024-01-01-10-05-00-utc.mp4")]
    got = {s["file"]: s["broll_id"] for s in suggest(files, pending_slots(edl))}
    check(got.get(str(files[0])) == "b2", f"phone file should go to b2: {got}")
    check(got.get(str(files[1])) == "b1", f"skyline file should go to b1: {got}")


def test_unmatched_fall_back_to_order_and_say_so():
    edl, _ = _edl([BRoll(12.0, 14.0, id="b1", kind="footage"),
                   BRoll(20.0, 22.0, id="b2", kind="footage")])
    files = [Path("aaa.mp4"), Path("bbb.mp4")]
    out = suggest(files, pending_slots(edl))
    check([s["broll_id"] for s in out] == ["b1", "b2"], f"order fallback: {out}")
    check(all("order" in s["how"] for s in out), "order guesses must be flagged")


def test_attached_and_overlay_entries_are_not_waiting():
    edl, _ = _edl([BRoll(12.0, 14.0, id="b1", kind="footage", source="x.mp4"),
                   BRoll(15.0, 17.0, id="b2", kind="overlay"),
                   BRoll(20.0, 22.0, id="b3", kind="footage")])
    check([b.id for _, b in pending_slots(edl)] == ["b3"],
          "only unfilled footage placeholders wait for stock")


def test_zip_videos_are_extracted():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "item-ABC1234.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("item/shot.mov", b"video")
            zf.writestr("item/license.txt", b"text")
            zf.writestr("__MACOSX/item/._shot.mov", b"fork")
        out = _unzip_videos(z, tmp / "out")
        check([p.name for p in out] == ["item-ABC1234__shot.mov"],
              f"expected only the video, got {[p.name for p in out]}")


# -- full-screen routing -------------------------------------------------------

def test_full_screen_templates_route_to_footage():
    check(template_kind("Breakdown") == "footage", "Breakdown is full screen")
    check(template_kind("Stat") == "overlay", "Stat is a card")


def test_full_screen_on_overlay_is_refused():
    edl, _ = _edl([BRoll(12.0, 15.0, id="b1", kind="overlay")])
    with tempfile.TemporaryDirectory() as tmp:
        jobs, errors = plan_jobs(edl, [{"clip_id": "c1", "broll_id": "b1",
                                        "template": "Breakdown",
                                        "props": {"points": ["a", "b"]}}],
                                 Path(tmp))
    check(not jobs and errors, "a full-screen frame on an overlay entry must be refused")


def test_full_screen_examples_validate():
    for name in ("Breakdown", "Timeline", "Compare", "Chart", "Quote"):
        from ..graphics import manifest
        errors = check_props(name, manifest()[name]["example"])
        check(not errors, f"{name} example: {errors}")


def test_media_and_candidates_survive_a_round_trip():
    edl, clip = _edl([BRoll(12.0, 15.0, id="b1", kind="footage",
                            media={"width": 3840, "height": 2160},
                            candidates=[{"url": "u", "title": "t"}])])
    b = EDL.from_dict(edl.to_dict()).clips[0].broll[0]
    check(b.media == {"width": 3840, "height": 2160}, f"media lost: {b.media}")
    check(b.candidates == [{"url": "u", "title": "t"}], f"candidates lost: {b.candidates}")


def main():
    print("\ntest_stock")
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
