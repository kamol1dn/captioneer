"""Track-backed angles with no mic file: picture only, never decoded.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_ingest_picture_only

The EP23 shape: Otabek on two angles off the master timeline, one of them (O)
naming his lav, the other (O2) naming nothing. A diarized ingest used to hand
O2's empty path to ffmpeg after finishing O. Here O2 is skipped for energy and
transcription alike, and Otabek is heard through O.

Nothing is decoded: the envelope, transcription and merge steps are stubbed,
the job runs inline, and ``save`` is a no-op so no registry is touched.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .. import ingest as ingest_mod
from .. import project as project_mod
from ..project import Camera, Project

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)


def cam(id_, path, speaker="", source_track="", has_audio=True, transcribe=False):
    return Camera(id=id_, path=path, speaker=speaker, source_track=source_track,
                  transcribe=transcribe,
                  probe={"has_video": True, "has_audio": has_audio,
                         "duration": 60.0})


def ep23(tmp):
    p = Project(id="p", name="p", dir=Path(tmp), cameras=[
        cam("O", "D:/a/otabek.wav", speaker="otabek", source_track="V2"),
        # create_project records has_audio False for a path-less angle; True
        # here proves the path, not the stored probe, is what decides.
        cam("O2", "", speaker="otabek", source_track="V1"),
        cam("S", "D:/a/sam.wav", speaker="sam", source_track="V3"),
        cam("MIX", "D:/a/mix.wav", transcribe=True),
    ])
    p.cameras[-1].probe["has_video"] = False
    p.primary_audio_camera = "MIX"
    p.save = lambda: None
    return p


class _Stubs:
    """Swap out every step that would touch media or the registry."""

    def __enter__(self):
        self.decoded, self.transcribed = [], []
        self._saved = (ingest_mod.energy_mod.compute_envelope,
                       ingest_mod._transcribe_out_of_process,
                       ingest_mod._merge_speakers, ingest_mod.jobs.submit)

        def envelope(path):
            if not path:
                raise RuntimeError("ffmpeg failed to decode ''")
            self.decoded.append(path)
            return {"resolution_hz": 20, "db": [-30.0] * 10, "duration": 0.5}

        def transcribe(path, out, **kw):
            self.transcribed.append(path)
            return []

        def submit(target):
            job = SimpleNamespace(progress=lambda *a, **k: None)
            return SimpleNamespace(result=target(job))

        ingest_mod.energy_mod.compute_envelope = envelope
        ingest_mod._transcribe_out_of_process = transcribe
        ingest_mod._merge_speakers = lambda project, spoken: {}
        ingest_mod.jobs.submit = submit
        return self

    def __exit__(self, *exc):
        (ingest_mod.energy_mod.compute_envelope,
         ingest_mod._transcribe_out_of_process,
         ingest_mod._merge_speakers, ingest_mod.jobs.submit) = self._saved


# ── tests ────────────────────────────────────────────────────────────────────

def test_pathless_angle_has_no_audio():
    with tempfile.TemporaryDirectory() as tmp:
        p = ep23(tmp)
        check(not p.camera("O2").has_audio,
              "a track-backed angle with no path cannot have audio")
        check(p.transcription_mic("otabek") == "O",
              f"otabek's mic should be O, got {p.transcription_mic('otabek')}")


def test_diarized_ingest_skips_pathless_angle():
    with tempfile.TemporaryDirectory() as tmp, _Stubs() as s:
        p = ep23(tmp)
        job = ingest_mod.start_ingest(p, diarize=True)
        per = job.result["per_camera"]
        check(per.get("O2") == "picture_only",
              f"O2 should be reported picture_only, got {per.get('O2')!r}")
        check(per.get("O") == "done" and per.get("S") == "done",
              f"O and S should be transcribed, got {per}")
        check("" not in s.decoded and len(s.decoded) == 3,
              f"energy should decode O, S and MIX only, got {s.decoded}")
        check(sorted(s.transcribed) == ["D:/a/otabek.wav", "D:/a/sam.wav"],
              f"one pass per speaker, got {s.transcribed}")
        check(not p.energy_path("O2").exists(),
              "no envelope should be written for O2")
        check("O2" in job.result["diarization"]["picture_only"],
              f"O2 belongs in picture_only, got {job.result['diarization']}")
        check(p.ingest_state["state"] == "done",
              f"ingest should finish, got {p.ingest_state}")


def test_pathless_angle_flagged_to_transcribe_fails_up_front():
    with tempfile.TemporaryDirectory() as tmp, _Stubs() as s:
        p = ep23(tmp)
        p.camera("O2").transcribe = True
        try:
            ingest_mod.start_ingest(p)
        except ValueError as e:
            check("O2" in str(e), f"the error should name O2, got {e}")
        else:
            _failures.append("transcribing a path-less angle should raise")
        check(not s.decoded, "nothing should run once the check fails")


def test_create_project_warns_about_pathless_angle():
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "otabek.wav"
        wav.write_bytes(b"")
        track = SimpleNamespace(kind="video", coverage=60.0, name="cam")
        master = SimpleNamespace(
            warnings=[], name="main", duration=60.0, duration_seconds=60.0,
            frame_size=(1440, 2560), timebase=SimpleNamespace(fps=25),
            video=[], track=lambda label: track)
        from ..xmeml import reader
        saved = (reader.read_master, project_mod.probe,
                 project_mod.paths.register)
        reader.read_master = lambda path, seq=None: master
        project_mod.probe = lambda path: {"has_audio": True, "duration": 60.0}
        project_mod.paths.register = lambda *a: None
        try:
            _, warnings = project_mod.create(
                "ep", [{"id": "O", "source_track": "V2", "path": str(wav),
                        "speaker": "otabek"},
                       {"id": "O2", "source_track": "V1", "speaker": "otabek"}],
                master_xml=str(Path(tmp) / "main.xml"),
                project_dir=str(Path(tmp) / "clipper"))
        finally:
            (reader.read_master, project_mod.probe,
             project_mod.paths.register) = saved
        text = "\n".join(warnings)
        check("O2" in text and "picture only" in text and "through O" in text,
              f"should warn that O2 is heard through O, got:\n{text}")
        check("sound coming from its audio tracks" not in text,
              f"O has a mic, so the group is not all picture-only:\n{text}")


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
