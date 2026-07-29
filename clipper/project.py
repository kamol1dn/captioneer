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
    probe: dict = field(default_factory=dict)
    transcribed_at: str = ""
    model: str = ""

    @property
    def duration(self) -> float:
        return float(self.probe.get("duration") or 0.0)

    def to_dict(self, project_dir: Optional[Path] = None) -> dict:
        d = dict(vars(self))
        # Fraction isn't JSON-serializable; store the exact string form.
        p = dict(d.get("probe") or {})
        if isinstance(p.get("fps"), Fraction):
            p["fps"] = str(p["fps"])
        d["probe"] = p
        if project_dir is not None:
            d["path"] = _relativize(self.path, project_dir)
        return d

    @classmethod
    def from_dict(cls, d: dict, project_dir: Optional[Path] = None) -> "Camera":
        d = dict(d)
        p = dict(d.get("probe") or {})
        if isinstance(p.get("fps"), str):
            p["fps"] = Fraction(p["fps"])
        d["probe"] = p
        if project_dir is not None:
            d["path"] = _absolutize(d.get("path", ""), project_dir)
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

    def camera_map(self) -> Dict[str, dict]:
        """The dict shape compile.py wants.

        ``has_video`` travels with it so the compiler can build the stacked
        angle tracks without having to guess which sources are real cameras.
        """
        return {c.id: {"path": c.path, "offset_sec": c.offset_sec,
                       "has_video": (c.probe or {}).get("has_video", True)}
                for c in self.cameras}

    def file_meta(self) -> Dict[str, dict]:
        """Per-file metadata for the xmeml <file> elements, keyed by abs path."""
        out = {}
        for c in self.cameras:
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
        """Camera files that no longer resolve — the failure mode after a move
        that relative paths are meant to prevent, reported rather than raised."""
        return [c.path for c in self.cameras if not Path(c.path).exists()]


# ── creation ─────────────────────────────────────────────────────────────────

def create(name: str, cameras: List[dict], primary_audio_camera: str = "",
           frame_size: Optional[tuple] = None,
           drop_frame: bool = False,
           project_dir: Optional[str] = None) -> tuple:
    """Probe every camera and write a new project. Returns (Project, warnings).

    ``project_dir`` defaults to ``clipper/`` beside the media, so the episode
    folder stays self-contained. Pass it explicitly to put the project
    elsewhere (or set CLIPPER_PROJECTS_DIR to force a central root globally).

    Warnings are the point of this function: mismatched frame rates, mismatched
    durations, and non-zero start timecodes all silently break the shared-t=0
    assumption, and each is far cheaper to catch here than after a bad export.
    """
    warnings: List[str] = []
    if not cameras:
        raise ValueError("at least one camera is required")

    cams: List[Camera] = []
    for spec in cameras:
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

    media_paths = [c.path for c in cams]
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
