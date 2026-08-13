"""Project state: the set of camera exports and everything derived from them.

A project is a directory, created beside the media it describes:

    D:/episodes/EP12/for claude/
      CamA.mp4  CamB.mp4  CamC.mp4     <- what you drop in
      clipper/                          <- created here
        project.json          cameras, timebase, probe results, ingest state
        cameras/A.words.json  caption_engine.transcriber.save_words() format
        cameras/A.energy.json RMS envelope, one per camera
        edl.json              the artifact — the one file meant for hand-editing
        exports/              generated XML and previews

Everything except the media is regenerable from the media.

Camera paths are stored **relative to the project directory** whenever the media
sits nearby, which is the whole point of colocating: the episode folder can be
moved between drives or machines and the project still resolves. Absolute paths
are only used when the media genuinely lives somewhere else. Note the exported
xmeml still contains absolute ``pathurl`` values — that's Premiere's
requirement, and it's why re-exporting after a move is cheap but necessary.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional

from caption_engine.media import probe

from . import paths
from .timebase import Timebase

SCHEMA_VERSION = 1


@dataclass
class Camera:
    id: str
    path: str
    label: str = ""
    offset_sec: float = 0.0      # master_time + offset = source time
    transcribe: bool = False
    # Who this camera is pointed at. Empty means "its own id", so one camera per
    # person — the original model — needs nothing set. Two cameras sharing a
    # speaker are two angles on one person: a second angle to cut to instead of
    # a jump cut, not a second voice. Everything that answers "who is talking"
    # groups by this, because a person with two mics would otherwise beat
    # themselves in every comparison and have every line transcribed twice.
    speaker: str = ""
    # Picture comes from this track of the project's master timeline ("V1",
    # "V2", …) instead of from a flat export. ``path`` then holds only what this
    # camera is *listened* to on — usually nothing, since a track-backed angle
    # is picture-only and the sound arrives with the master's own audio tracks.
    # Set this and the angle costs no video export at all.
    source_track: str = ""
    probe: dict = field(default_factory=dict)
    transcribed_at: str = ""
    model: str = ""

    @property
    def duration(self) -> float:
        return float(self.probe.get("duration") or 0.0)

    @property
    def from_master(self) -> bool:
        return bool(self.source_track)

    @property
    def speaker_id(self) -> str:
        return self.speaker or self.id

    @property
    def has_audio(self) -> bool:
        return bool((self.probe or {}).get("has_audio", True))

    def to_dict(self, project_dir: Optional[Path] = None) -> dict:
        d = dict(vars(self))
        # Fraction isn't JSON-serializable; store the exact string form.
        p = dict(d.get("probe") or {})
        if isinstance(p.get("fps"), Fraction):
            p["fps"] = str(p["fps"])
        d["probe"] = p
        if project_dir is not None and self.path:
            d["path"] = _relativize(self.path, project_dir)
        return d

    @classmethod
    def from_dict(cls, d: dict, project_dir: Optional[Path] = None) -> "Camera":
        d = dict(d)
        p = dict(d.get("probe") or {})
        if isinstance(p.get("fps"), str):
            p["fps"] = Fraction(p["fps"])
        d["probe"] = p
        if project_dir is not None and d.get("path"):
            d["path"] = _absolutize(d["path"], project_dir)
        return cls(**d)


def _relativize(path: str, project_dir: Path) -> str:
    """Store a media path relative to the project dir when it's nearby.

    ``os.path.relpath`` happily produces things like ``../../../../elsewhere``,
    which is portable in name only. Anything that climbs more than two levels is
    kept absolute — at that point the media isn't really colocated and a
    relative path just obscures where it lives.
    """
    p = Path(path).resolve()
    try:
        rel = os.path.relpath(p, Path(project_dir).resolve())
    except ValueError:
        return str(p)          # different drive on Windows
    if rel.count("..") > 2:
        return str(p)
    return rel.replace(os.sep, "/")


def _absolutize(path: str, project_dir: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((Path(project_dir) / p).resolve())


@dataclass
class Project:
    id: str
    name: str
    cameras: List[Camera] = field(default_factory=list)
    timebase: Timebase = field(default_factory=lambda: Timebase(30))
    frame_size: tuple = (1080, 1920)
    primary_audio_camera: str = ""
    # Spoken language, ISO code ("uz", "en"). Set once at create time and read
    # by everything downstream: it picks the transcription backend (Kotib for
    # Uzbek, WhisperX otherwise), the refinement prompt section, and the
    # verification pass's Whisper language. Carrying it on the project is the
    # point — passing it per call meant one forgotten argument silently gave an
    # Uzbek clip English captions, with nothing raised.
    language: str = ""
    # Caption preset name for this project's clips. Empty = the engine default.
    caption_preset: str = ""
    # The episode timeline exported from Premiere as FCP7 XML. When set, angles
    # can take their picture straight off its V-tracks and its A-tracks become
    # the reel's audio bed, so the only thing that has to be exported as media is
    # the audio used for transcription. Stored relative to the project dir, like
    # camera paths, for the same reason.
    master_xml: str = ""
    master_sequence: str = ""     # which sequence in it; "" when unambiguous
    created_at: str = ""
    ingest_state: dict = field(default_factory=lambda: {"state": "new",
                                                        "progress": 0.0,
                                                        "message": ""})
    version: int = SCHEMA_VERSION
    # Where this project lives. Set at create/load time rather than derived,
    # since projects sit beside their media instead of under one root.
    dir: Path = field(default_factory=Path)

    # ── paths ────────────────────────────────────────────────────────────────

    @property
    def media_dir(self) -> Path:
        """The folder the camera exports were dropped into."""
        return self.dir.parent

    @property
    def edl_path(self) -> Path:
        return self.dir / "edl.json"

    def words_path(self, camera_id: str) -> Path:
        return self.dir / "cameras" / f"{camera_id}.words.json"

    def energy_path(self, camera_id: str) -> Path:
        return self.dir / "cameras" / f"{camera_id}.energy.json"

    @property
    def exports_dir(self) -> Path:
        d = self.dir / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── lookups ──────────────────────────────────────────────────────────────

    def camera(self, camera_id: str) -> Optional[Camera]:
        return next((c for c in self.cameras if c.id == camera_id), None)

    @property
    def camera_ids(self) -> List[str]:
        return [c.id for c in self.cameras]

    @property
    def video_camera_ids(self) -> List[str]:
        """Cameras that can actually appear on screen.

        An audio-only source (a combined/enhanced mix laid in beside the camera
        exports) is a legitimate member of ``cameras`` — it carries the best
        audio and is usually the right thing to transcribe — but it is never an
        angle and never a speaker. Cutting picture to it would emit a video
        clipitem pointing at an mp3, and letting it into speaker scoring would
        swamp every real mic, since the mix contains all of them.
        """
        return [c.id for c in self.cameras
                if (c.probe or {}).get("has_video", True)]

    # ── speakers ─────────────────────────────────────────────────────────────

    def camera_to_speaker(self) -> Dict[str, str]:
        """{camera_id: speaker_id} for every camera, audio-only sources included
        (an isolated lav belongs to whoever it is clipped to)."""
        return {c.id: c.speaker_id for c in self.cameras}

    def speaker_map(self, video_only: bool = True) -> Dict[str, List[str]]:
        """{speaker_id: [camera_id, ...]} — the angles available per person.

        Video-only by default: this is what angle choice reads, and an audio-only
        mix or lav is never an angle. Camera order is preserved, so the first
        entry is that speaker's main angle.
        """
        allowed = set(self.video_camera_ids if video_only else self.camera_ids)
        out: Dict[str, List[str]] = {}
        for c in self.cameras:
            if c.id in allowed:
                out.setdefault(c.speaker_id, []).append(c.id)
        return out

    @property
    def speakers(self) -> List[str]:
        return list(self.speaker_map().keys())

    def angles_for(self, camera_id: str) -> List[str]:
        """Other cameras on the same person as ``camera_id`` — what you cut to
        instead of a jump cut."""
        cam = self.camera(camera_id)
        if cam is None:
            return []
        return [c for c in self.speaker_map().get(cam.speaker_id, [])
                if c != camera_id]

    def transcription_mic(self, speaker_id: str) -> Optional[str]:
        """Which of a speaker's cameras to actually transcribe.

        One pass per *person*, not per camera: a second angle on someone already
        transcribed adds a redundant Whisper pass and, worse, a duplicate of
        every line they said. An explicit ``transcribe`` flag inside the group
        wins (that's how you nominate the better-sounding angle over a camera
        mic); otherwise the first angle with an audio stream.

        Video cameras only. An audio-only source is treated as the mix — it hears
        the whole room, so it is never a single speaker's isolated mic, and
        ``load_envelopes`` holds it out of speaker scoring for the same reason.
        """
        group = [c for c in self.cameras
                 if c.speaker_id == speaker_id and c.id in set(self.video_camera_ids)]
        if not group:
            return None
        flagged = [c for c in group if c.transcribe and c.has_audio]
        if flagged:
            return flagged[0].id
        with_audio = [c for c in group if c.has_audio]
        return with_audio[0].id if with_audio else None

    @property
    def master_duration(self) -> float:
        """Shortest camera wins — past that, some angle has no footage."""
        durs = [c.duration for c in self.cameras if c.duration]
        return min(durs) if durs else 0.0

    @property
    def master_words_path(self) -> Path:
        """The project's canonical word list.

        Written only by a per-mic (diarized) ingest, which merges every mic into
        one speaker-labelled timeline. Absent for a single-source ingest, where
        the primary camera's own word file already is the master.
        """
        return self.dir / "transcript.words.json"

    # ── master timeline ──────────────────────────────────────────────────────

    @property
    def master_xml_path(self) -> Optional[Path]:
        if not self.master_xml:
            return None
        return Path(_absolutize(self.master_xml, self.dir))

    def load_master(self):
        """Parse the episode timeline, once per Project instance.

        Cached because it is a multi-megabyte parse and every clip compiled in a
        run wants the same tracks.
        """
        if not self.master_xml:
            return None
        cached = getattr(self, "_master", None)
        if cached is None:
            from .xmeml.reader import read_master
            cached = read_master(str(self.master_xml_path),
                                 self.master_sequence or None)
            self._master = cached
        return cached

    def master_audio_tracks(self) -> List:
        """The master's A-tracks, in order — the reel's audio bed."""
        master = self.load_master()
        return [t for t in master.audio if t.segments] if master else []

    def camera_map(self) -> Dict[str, dict]:
        """The dict shape compile.py wants.

        ``has_video`` travels with it so the compiler can build the stacked
        angle tracks without having to guess which sources are real cameras.
        ``track`` is set for angles whose picture lives on the master timeline;
        compile switches to a piecewise time mapping whenever it is present.
        """
        master = self.load_master()
        out: Dict[str, dict] = {}
        for c in self.cameras:
            entry = {"path": c.path, "offset_sec": c.offset_sec,
                     "has_video": (c.probe or {}).get("has_video", True)}
            if c.source_track:
                if master is None:
                    raise ValueError(
                        f"camera {c.id} takes its picture from {c.source_track} "
                        f"but the project has no master_xml")
                track = master.track(c.source_track)
                if track is None:
                    have = ", ".join(t.label for t in master.video)
                    raise ValueError(
                        f"camera {c.id}: no track {c.source_track!r} in "
                        f"{master.name!r} (has {have})")
                entry["track"] = track
                entry["has_video"] = True
            out[c.id] = entry
        return out

    def file_meta(self) -> Dict[str, dict]:
        """Per-file metadata for the xmeml <file> elements, keyed by abs path.

        Track-backed angles are absent by design: their ``<file>`` elements are
        copied whole out of the master XML, metadata included, rather than
        rebuilt from a probe.
        """
        out = {}
        for c in self.cameras:
            if not c.path:
                continue
            p = c.probe or {}
            dur = p.get("duration")
            out[str(Path(c.path).resolve())] = {
                "width": p.get("width") or self.frame_size[0],
                "height": p.get("height") or self.frame_size[1],
                "has_video": p.get("has_video", True),
                "has_audio": p.get("has_audio", True),
                "channels": p.get("channels") or 2,
                "sample_rate": p.get("sample_rate") or 48000,
                "duration_frames": self.timebase.to_frames(dur) if dur else None,
            }
        return out

    # ── persistence ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "timebase": self.timebase.to_dict(),
            "frame_size": {"width": self.frame_size[0],
                           "height": self.frame_size[1]},
            "primary_audio_camera": self.primary_audio_camera,
            "language": self.language,
            "caption_preset": self.caption_preset,
            "master_xml": (_relativize(str(self.master_xml_path), self.dir)
                           if self.master_xml else ""),
            "master_sequence": self.master_sequence,
            "master_duration": round(self.master_duration, 3),
            "cameras": [c.to_dict(self.dir) for c in self.cameras],
            "ingest": self.ingest_state,
        }

    @classmethod
    def from_dict(cls, d: dict, project_dir: Path) -> "Project":
        fs = d.get("frame_size") or {}
        return cls(
            version=int(d.get("version", SCHEMA_VERSION)),
            id=d["id"], name=d.get("name", d["id"]),
            created_at=d.get("created_at", ""),
            timebase=Timebase.from_dict(d["timebase"]),
            frame_size=(int(fs.get("width", 1080)), int(fs.get("height", 1920))),
            primary_audio_camera=d.get("primary_audio_camera", ""),
            # Absent in projects written before language was tracked; empty
            # means "auto-detect", which is the old behaviour.
            language=d.get("language", ""),
            caption_preset=d.get("caption_preset", ""),
            master_xml=d.get("master_xml", ""),
            master_sequence=d.get("master_sequence", ""),
            cameras=[Camera.from_dict(c, project_dir)
                     for c in d.get("cameras", [])],
            ingest_state=d.get("ingest") or {"state": "new", "progress": 0.0,
                                             "message": ""},
            dir=Path(project_dir),
        )

    def save(self) -> None:
        paths.write_json_atomic(self.dir / "project.json", self.to_dict())
        # Keep the id -> directory index fresh; it's how a bare project id gets
        # resolved in a later session.
        paths.register(self.id, self.dir)

    @classmethod
    def load(cls, id_or_path: str) -> Optional["Project"]:
        """Load by project id, project directory, or the media folder itself."""
        project_dir = paths.resolve_project_dir(id_or_path)
        if project_dir is None:
            return None
        data = paths.read_json(project_dir / "project.json")
        if not data:
            return None
        project = cls.from_dict(data, project_dir)
        # A project found by path may predate the registry, or the folder may
        # have moved since it was written. Either way, re-point the index.
        if paths.read_registry().get(project.id) != str(project_dir):
            paths.register(project.id, project_dir)
        return project

    def missing_media(self) -> List[str]:
        """Sources that no longer resolve — the failure mode after a move that
        relative paths are meant to prevent, reported rather than raised.

        Track-backed angles have no file of their own; what has to resolve for
        them is the master XML, and the media it names is Premiere's problem on
        import rather than something this tool can relink.
        """
        out = [c.path for c in self.cameras
               if c.path and not Path(c.path).exists()]
        mx = self.master_xml_path
        if mx is not None and not mx.exists():
            out.append(str(mx))
        return out


# ── creation ─────────────────────────────────────────────────────────────────

def create(name: str, cameras: List[dict], primary_audio_camera: str = "",
           frame_size: Optional[tuple] = None,
           drop_frame: bool = False,
           project_dir: Optional[str] = None,
           language: str = "",
           caption_preset: str = "",
           master_xml: str = "",
           master_sequence: str = "") -> tuple:
    """Probe every camera and write a new project. Returns (Project, warnings).

    ``project_dir`` defaults to ``clipper/`` beside the media, so the episode
    folder stays self-contained. Pass it explicitly to put the project
    elsewhere (or set CLIPPER_PROJECTS_DIR to force a central root globally).

    ``language`` ("uz", "en", …) is recorded once here and then used by ingest,
    captions and verification without being re-passed. ``caption_preset`` is
    the preset those clips render with.

    Warnings are the point of this function: mismatched frame rates, mismatched
    durations, and non-zero start timecodes all silently break the shared-t=0
    assumption, and each is far cheaper to catch here than after a bad export.
    """
    warnings: List[str] = []
    if not cameras:
        raise ValueError("at least one camera is required")

    master = None
    if master_xml:
        from .xmeml.reader import read_master
        master_xml = str(Path(master_xml).resolve())
        master = read_master(master_xml, master_sequence or None)
        warnings.extend(master.warnings)

    cams: List[Camera] = []
    for spec in cameras:
        track_label = str(spec.get("source_track", "") or "").strip().upper()
        if track_label:
            # A track-backed angle costs no export: its picture is whatever the
            # master timeline's V-track already points at. Its shape comes from
            # the timeline rather than from a probe, and the per-clip source
            # metadata is copied out of the XML at write time.
            if master is None:
                raise ValueError(
                    f"camera {spec['id']} names source_track {track_label!r} but "
                    f"no master_xml was given")
            track = master.track(track_label)
            if track is None:
                have = ", ".join(t.label for t in master.video)
                raise ValueError(
                    f"camera {spec['id']}: no track {track_label!r} in "
                    f"{master.name!r} (has {have})")
            if track.kind != "video":
                raise ValueError(
                    f"camera {spec['id']}: {track_label} is an audio track; an "
                    f"angle needs picture")
            covered = track.coverage / master.duration if master.duration else 0
            if covered < 0.99:
                warnings.append(
                    f"camera {spec['id']} ({track_label}) covers "
                    f"{covered:.1%} of the timeline — clips landing in the "
                    f"remainder will have no picture on this angle")
            # A track-backed angle may still name a ``path``: the isolated mic
            # that person is *listened* to on. Picture comes off the timeline
            # either way — but the file is what supplies this camera's loudness
            # envelope, and on a diarized ingest its transcript. Without one the
            # angle has no audio at all, so it can never be a speaker's mic and
            # ``diarize`` rejects the whole run.
            mic = str(spec.get("path", "") or "").strip()
            mic_probe: dict = {}
            if mic:
                mic = str(Path(mic).resolve())
                if not Path(mic).exists():
                    raise FileNotFoundError(f"camera source not found: {mic}")
                mic_probe = probe(mic)
                if not mic_probe.get("has_audio"):
                    warnings.append(
                        f"camera {spec['id']}: {Path(mic).name} carries no "
                        f"audio stream, so this angle has no mic")
                mic_dur = float(mic_probe.get("duration") or 0.0)
                if mic_dur and abs(mic_dur - master.duration_seconds) > 0.5:
                    warnings.append(
                        f"camera {spec['id']}: mic {Path(mic).name} runs "
                        f"{mic_dur:.2f}s but {track_label} covers "
                        f"{master.duration_seconds:.2f}s — the mic and the "
                        f"timeline may not share t=0")
            cams.append(Camera(
                id=spec["id"], path=mic,
                label=spec.get("label", "") or track.name,
                speaker=str(spec.get("speaker", "") or ""),
                transcribe=bool(spec.get("transcribe", False)),
                source_track=track_label,
                # Shape from the timeline, sound from the mic (if any).
                probe={"has_video": True,
                       "has_audio": bool(mic_probe.get("has_audio", False)),
                       "width": master.frame_size[0],
                       "height": master.frame_size[1],
                       "fps": master.timebase.fps,
                       "duration": master.duration_seconds,
                       "channels": mic_probe.get("channels") or 0,
                       "sample_rate": mic_probe.get("sample_rate") or 0,
                       "start_timecode": None},
            ))
            continue

        path = str(Path(spec["path"]).resolve())
        if not Path(path).exists():
            raise FileNotFoundError(f"camera source not found: {path}")
        info = probe(path)
        if not info.get("has_audio"):
            warnings.append(f"camera {spec['id']}: no audio stream")
        cams.append(Camera(
            id=spec["id"], path=path,
            label=spec.get("label", ""),
            offset_sec=float(spec.get("offset_sec", 0.0) or 0.0),
            transcribe=bool(spec.get("transcribe", False)),
            speaker=str(spec.get("speaker", "") or ""),
            probe=info,
        ))

    # Frame rate: every camera should agree. If not, the first one wins and the
    # rest are flagged — mixed rates need a conform pass in Premiere first.
    rates = {c.id: c.probe.get("fps") for c in cams if c.probe.get("fps")}
    distinct = set(rates.values())
    if len(distinct) > 1:
        warnings.append(
            "cameras have different frame rates (" +
            ", ".join(f"{k}={float(v):.3f}" for k, v in rates.items()) +
            "); using the first and expecting Premiere to conform the rest")
    tb = Timebase.from_fps(next(iter(rates.values()), None), drop_frame=drop_frame)

    # Duration: the exports are supposed to span the same range.
    durs = {c.id: c.duration for c in cams if c.duration}
    if durs and (max(durs.values()) - min(durs.values())) > 0.5:
        warnings.append(
            "camera durations differ by more than 0.5s (" +
            ", ".join(f"{k}={v:.2f}s" for k, v in durs.items()) +
            "); they may not share a common t=0")

    # Speaker grouping: a name that is also another camera's id reads as a
    # grouping but isn't one, and the mistake only shows up as doubled captions
    # after a diarized ingest.
    ids = {c.id for c in cams}
    for c in cams:
        if c.speaker and c.speaker != c.id and c.speaker in ids:
            warnings.append(
                f"camera {c.id} has speaker {c.speaker!r}, which is also a "
                f"camera id — name the person (e.g. 'host'), not the other "
                f"camera, or set the same speaker on both")

    # Start timecode: harmless for in/out (which are media-relative) but a
    # strong hint that the exports were not cut from one common range.
    for c in cams:
        tc = c.probe.get("start_timecode")
        if tc and tc not in ("00:00:00:00", "00:00:00;00"):
            warnings.append(
                f"camera {c.id} has start timecode {tc}; if the cameras were "
                f"synced by timecode rather than a common export range, set "
                f"offset_sec on this camera")

    if not frame_size:
        v = next((c for c in cams if c.probe.get("width")), None)
        frame_size = ((v.probe["width"], v.probe["height"]) if v else (1080, 1920))
    if frame_size[1] < frame_size[0]:
        warnings.append(
            f"source is {frame_size[0]}x{frame_size[1]} (landscape) — the "
            f"workflow expects vertical exports")

    primary = primary_audio_camera or cams[0].id
    if not any(c.id == primary for c in cams):
        raise ValueError(f"primary_audio_camera {primary!r} is not a camera id")
    # Only the primary is transcribed by default: every camera records the same
    # room, so extra Whisper passes cost GPU minutes for near-identical text.
    if not any(c.transcribe for c in cams):
        next(c for c in cams if c.id == primary).transcribe = True

    # Report multi-angle speakers *after* the transcribe defaulting above, so
    # the warning names the mic that will actually be used rather than telling
    # the caller to choose one that has already been chosen for them.
    groups: Dict[str, List[Camera]] = {}
    for c in cams:
        if (c.probe or {}).get("has_video", True):
            groups.setdefault(c.speaker_id, []).append(c)
    for spk, group in groups.items():
        if len(group) < 2:
            continue
        if all(c.from_master for c in group):
            # Track-backed angles are picture-only by construction; their sound
            # arrives with the master's own audio tracks, so the usual "which of
            # these do we transcribe" advice does not apply to them.
            warnings.append(
                f"speaker {spk!r} has {len(group)} angles "
                f"({', '.join(c.id for c in group)}), all taken off the master "
                f"timeline — picture only, with the sound coming from its audio "
                f"tracks")
            continue
        flagged = [c.id for c in group if c.transcribe and c.has_audio]
        with_audio = [c.id for c in group if c.has_audio]
        mic = flagged[0] if flagged else (with_audio[0] if with_audio else None)
        warnings.append(
            f"speaker {spk!r} has {len(group)} angles "
            f"({', '.join(c.id for c in group)}) — a second angle to cut to "
            f"instead of a jump cut. One transcription pass covers the group" +
            (f", from {mic}" if mic else
             " — but none of these has audio, so a diarized ingest will fail") +
            ("; flag another with transcribe: true if it sounds better"
             if mic and not flagged else ""))

    # Track-backed angles contribute no path, so a project made entirely of them
    # would have nothing to sit beside; the master XML stands in as the anchor.
    media_paths = [c.path for c in cams if c.path] or ([master_xml]
                                                       if master_xml else [])
    if not media_paths:
        raise ValueError("no media to locate the project beside")
    pid = _unique_id(name, media_paths)
    target = (Path(project_dir) if project_dir
              else paths.default_project_dir(media_paths, pid))
    if (target / "project.json").exists():
        raise FileExistsError(
            f"a clipper project already exists at {target} — load it instead, "
            f"or pass a different project_dir")

    project = Project(
        id=pid, name=name, cameras=cams, timebase=tb,
        frame_size=tuple(frame_size), primary_audio_camera=primary,
        language=(language or "").strip().lower(),
        caption_preset=(caption_preset or "").strip(),
        master_xml=master_xml, master_sequence=master_sequence,
        created_at=datetime.now().isoformat(timespec="seconds"),
        dir=target.resolve(),
    )
    (project.dir / "cameras").mkdir(parents=True, exist_ok=True)
    project.save()
    return project, warnings


def list_projects() -> List[dict]:
    """Every known project, newest first. Reads the registry, and drops entries
    whose directory has been deleted rather than reporting phantoms."""
    out, stale = [], []
    for pid, path in paths.read_registry().items():
        d = Path(path)
        data = paths.read_json(d / "project.json")
        if not data:
            stale.append(pid)
            continue
        out.append({
            "id": data["id"], "name": data.get("name", ""),
            "created_at": data.get("created_at", ""),
            "language": data.get("language", ""),
            "dir": str(d),
            "media_dir": str(d.parent),
            "n_cameras": len(data.get("cameras", [])),
            "duration": data.get("master_duration", 0),
            "state": (data.get("ingest") or {}).get("state", "new"),
            "has_edl": (d / "edl.json").exists(),
        })
    for pid in stale:
        paths.unregister(pid)
    return sorted(out, key=lambda p: p["created_at"], reverse=True)


def _unique_id(name: str, media_paths: List[str]) -> str:
    """A stable id, disambiguated only if that exact id is already registered."""
    base = f"{datetime.now():%Y-%m-%d}_{paths.slugify(name)}"
    reg = paths.read_registry()
    candidate, n = base, 2
    while candidate in reg:
        candidate = f"{base}-{n}"
        n += 1
    return candidate
