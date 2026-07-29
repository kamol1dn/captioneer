"""End-to-end test with synthetic multicam footage — no real media required.

Builds 3 vertical "cameras" with lavfi: each has a distinct color and a sine
tone at a distinct frequency, plus a burned-in clock. Creates a real project
(exercising probe()), hand-writes an EDL that switches between them, compiles,
exports both xmeml and an ffmpeg preview, and checks the preview's rendered
duration against what the compiler claims. This is the closest thing to the
Premiere round trip that's checkable without Premiere installed.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_preview
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from caption_engine.media import ffmpeg_bin, probe

from ..compile import compile_edl
from ..edl import EDL, AudioPlan, CameraCut, Clip, Segment, validate
from ..preview import render_preview
from ..project import Project, create
from ..xmeml import write_xmeml

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
    return cond


def _make_camera(path: Path, color: str, tone_hz: int, duration: int = 40):
    """A vertical test clip: solid color background, camera label, sine tone."""
    cmd = [
        ffmpeg_bin("ffmpeg"), "-y", "-nostdin",
        "-f", "lavfi", "-i",
        f"color=c={color}:s=1080x1920:r=30:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency={tone_hz}:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"synthetic camera generation failed:\n{proc.stderr[-2000:]}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="clipper_test_"))
    project = None
    try:
        cam_paths = {
            "A": tmp / "CamA.mp4",
            "B": tmp / "CamB.mp4",
            "C": tmp / "CamC.mp4",
        }
        _make_camera(cam_paths["A"], "red", 440)
        _make_camera(cam_paths["B"], "blue", 550)
        _make_camera(cam_paths["C"], "green", 660)

        project, warnings_ = create(
            "Clipper Self Test",
            [{"id": k, "path": str(v)} for k, v in cam_paths.items()],
            primary_audio_camera="A",
        )
        check(project.master_duration > 39, "probed duration looks wrong")
        check(project.frame_size == (1080, 1920), "frame size should be vertical")

        # Colocation: the project lands beside the media, not under the repo.
        check(project.dir == tmp / "clipper",
              f"project should be colocated at {tmp / 'clipper'}, "
              f"got {project.dir}")
        check(project.media_dir == tmp, "media_dir should be the drop folder")

        # Camera paths must round-trip as relative, so the folder stays movable.
        raw = json.loads((project.dir / "project.json").read_text(encoding="utf-8"))
        stored = [c["path"] for c in raw["cameras"]]
        check(all(not Path(p).is_absolute() for p in stored),
              f"camera paths should be stored relative, got {stored}")
        reloaded = Project.load(str(project.dir))
        check(reloaded is not None, "project should load back from its directory")
        check([c.path for c in reloaded.cameras] == [c.path for c in project.cameras],
              "relative paths must resolve back to the same absolute paths")
        check(Project.load(str(tmp)) is not None,
              "loading by the media folder should find the nested project")
        check(not reloaded.missing_media(), "all camera media should resolve")
        print(f"  project created: {project.id} at {project.dir}, "
             f"warnings={warnings_}")

        # One 12s clip: A for 5s, switch to B for 4s, switch to C for 3s.
        clip = Clip(
            id="short01", title="test short",
            segments=[Segment(start=2.0, end=14.0, id="s1")],
            camera_cuts=[
                CameraCut(at=2.0, camera="A"),
                CameraCut(at=7.0, camera="B"),
                CameraCut(at=11.0, camera="C"),
            ],
        )
        edl = EDL(timebase=project.timebase, frame_size=project.frame_size,
                  default_camera="A", clips=[clip],
                  audio=AudioPlan(mode="pinned", pinned_camera="A"))
        result = validate(edl, project.camera_ids, project.master_duration)
        check(result["ok"], f"EDL should validate cleanly: {result['errors']}")
        edl.save(project.edl_path)

        compiled = compile_edl(edl, project.camera_map())
        check(len(compiled) == 1, "should compile exactly 1 clip")
        c = compiled[0]
        check(c.duration == project.timebase.to_frames(12.0),
              f"expected 12s of program, got {c.duration} frames")
        check(len(c.video_tracks[0]) == 3, "expected 3 shots (A, B, C)")

        xml_path = write_xmeml(compiled, project.exports_dir / "test.xml",
                               project_name=project.name,
                               file_meta=project.file_meta())
        check(xml_path.exists() and xml_path.stat().st_size > 500,
              "xmeml file should be written and non-trivial")
        print(f"  xmeml written: {xml_path} ({xml_path.stat().st_size} bytes)")

        preview_path = render_preview(c, project.exports_dir / "test_preview.mp4",
                                      quality="fast")
        info = probe(str(preview_path))
        rendered_dur = info["duration"]
        expected_dur = project.timebase.to_seconds(c.duration)
        check(abs(rendered_dur - expected_dur) < 0.15,
              f"preview duration {rendered_dur:.2f}s vs expected "
              f"{expected_dur:.2f}s")
        check(info["width"] == 1080 and info["height"] == 1920,
              f"preview should stay vertical, got {info['width']}x{info['height']}")
        print(f"  preview rendered: {preview_path} "
             f"({rendered_dur:.2f}s vs expected {expected_dur:.2f}s)")

    finally:
        # The project registered itself in the real registry; drop it so a test
        # run doesn't leave a phantom entry pointing into a deleted temp dir.
        if project is not None:
            from .. import paths as _paths
            _paths.unregister(project.id)
        shutil.rmtree(tmp, ignore_errors=True)

    if _failures:
        print(f"\n{len(_failures)} failure(s):")
        for f in _failures:
            print("  -", f)
        return 1
    print("\nend-to-end preview test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
