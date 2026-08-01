"""Speaker grouping: several cameras on one person.

Run: venv\\Scripts\\python.exe -m clipper.tests.test_speakers

A camera's speaker defaults to its own id, so the one-camera-per-subject model
is a special case of this one. What these tests pin down is the part that has no
safe default: which of a person's mics gets transcribed. Pick two and every line
that person says enters the master timeline twice.

Cameras are built by hand — ``project.create`` probes real media, and none of
this logic needs a file to exist.
"""
import sys

from ..project import Camera, Project

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)


def cam(id_, speaker="", transcribe=False, has_video=True, has_audio=True):
    return Camera(id=id_, path=f"D:/f/{id_}.mp4", speaker=speaker,
                  transcribe=transcribe,
                  probe={"has_video": has_video, "has_audio": has_audio,
                         "duration": 60.0})


def project(*cameras):
    return Project(id="p", name="p", cameras=list(cameras))


# ── tests ────────────────────────────────────────────────────────────────────

def test_speaker_defaults_to_camera_id():
    """The original model, unchanged: one camera is one speaker."""
    p = project(cam("A"), cam("B"))
    check(p.speaker_map() == {"A": ["A"], "B": ["B"]},
          f"ungrouped cameras should each be their own speaker, got "
          f"{p.speaker_map()}")
    check(p.camera_to_speaker() == {"A": "A", "B": "B"},
          f"got {p.camera_to_speaker()}")
    check(p.angles_for("A") == [], "a lone camera has no alternate angle")


def test_two_angles_group_under_one_person():
    p = project(cam("A1", speaker="host"), cam("A2", speaker="host"),
                cam("B", speaker="guest"))
    check(p.speaker_map() == {"host": ["A1", "A2"], "guest": ["B"]},
          f"got {p.speaker_map()}")
    check(p.speakers == ["host", "guest"],
          f"speakers should keep camera order, got {p.speakers}")
    check(p.angles_for("A1") == ["A2"],
          f"A1's alternate angle is A2, got {p.angles_for('A1')}")
    check(p.angles_for("A2") == ["A1"], f"got {p.angles_for('A2')}")
    check(p.angles_for("B") == [],
          "the guest has one camera, so nothing to cut to")


def test_transcription_mic_is_one_per_speaker():
    """Two angles, one Whisper pass — the duplicate-lines guard."""
    p = project(cam("A1", speaker="host"), cam("A2", speaker="host"),
                cam("B", speaker="guest"))
    mics = {s: p.transcription_mic(s) for s in p.speakers}
    check(mics == {"host": "A1", "guest": "B"},
          f"one mic per person, first angle by default, got {mics}")
    check(len(set(mics.values())) == len(mics),
          "no camera may speak for two people")


def test_explicit_transcribe_flag_chooses_the_mic():
    """How you nominate the better-sounding angle inside a group."""
    p = project(cam("A1", speaker="host"),
                cam("A2", speaker="host", transcribe=True))
    check(p.transcription_mic("host") == "A2",
          f"the flagged angle should win, got {p.transcription_mic('host')}")


def test_silent_angle_is_never_the_mic():
    """A picture-only second angle (dead camera mic) must not be transcribed."""
    p = project(cam("A1", speaker="host", has_audio=False),
                cam("A2", speaker="host"))
    check(p.transcription_mic("host") == "A2",
          f"should skip the silent angle, got {p.transcription_mic('host')}")

    silent = project(cam("A1", speaker="host", has_audio=False))
    check(silent.transcription_mic("host") is None,
          "a speaker with no audio at all has no mic — ingest should say so "
          "rather than transcribe silence")


def test_audio_only_source_is_not_an_angle_or_a_mic():
    """The enhanced mix hears everyone, so it is nobody's isolated mic."""
    p = project(cam("A", speaker="host"), cam("B", speaker="guest"),
                cam("MIX", speaker="host", has_video=False))
    check(p.speaker_map() == {"host": ["A"], "guest": ["B"]},
          f"an audio-only source must not appear as an angle, got "
          f"{p.speaker_map()}")
    check(p.transcription_mic("host") == "A",
          f"got {p.transcription_mic('host')}")
    check("MIX" in p.camera_to_speaker(),
          "it is still mapped, so grouped envelopes can find it if asked")


def test_speaker_survives_a_save_load_roundtrip():
    p = project(cam("A1", speaker="host"), cam("A2", speaker="host"))
    d = p.to_dict()
    back = Project.from_dict(d, ".")
    check(back.speaker_map() == {"host": ["A1", "A2"]},
          f"grouping should persist, got {back.speaker_map()}")

    # A project written before speakers existed has no key at all.
    for c in d["cameras"]:
        c.pop("speaker")
    legacy = Project.from_dict(d, ".")
    check(legacy.speaker_map() == {"A1": ["A1"], "A2": ["A2"]},
          f"an older project should read as one speaker per camera, got "
          f"{legacy.speaker_map()}")


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
