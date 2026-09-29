"""Per-show dressing: the assets and rules that make a reel look like *that* show.

A show is everything about the finished look that isn't the cut: which whoosh
covers a cutaway, how loud it sits under the voice, whether reels end on a
subscribe card, which graphics family the cards are drawn from. Two shows share
the clipper and share nothing else.

Config lives in ``shows/<id>.json`` at the repo root, and a project names one in
``project.json``. A project that names no show gets ``DEFAULT``, which dresses
nothing — so every project written before this module existed exports exactly
the bytes it did before. That is the whole reason the empty show exists rather
than defaulting to a real one.

Asset paths are resolved relative to the config file, so a show can keep its
whooshes and logos next to its JSON or point at a drive elsewhere.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SHOWS_DIR = Path(__file__).resolve().parent.parent / "shows"


@dataclass
class TransitionAsset:
    """A whoosh: a short clip laid over a cut, not a Premiere transition.

    Premiere's own transitions don't survive an FCP7 round trip (the episode's
    own export says so: "Transition <Custom Fade> not translated"). An overlay
    clip does, which is why this is a file on a track with a composite mode
    rather than a ``<transitionitem>``.

    ``hit_sec`` is the moment *within the asset* where the flash peaks. The clip
    is placed so that instant lands on the cut, which is the only placement that
    reads as covering the cut rather than following it.

    Both times are seconds, not frames, because the asset rarely shares the
    sequence's rate — this one is 25fps material conformed into 29.97 — and a
    frame count measured against the wrong rate slides the flash off the cut.
    """
    id: str
    path: str
    hit_sec: float = 0.0         # head of the asset to the flash
    seconds: float = 0.0         # 0 -> use the whole asset
    rotation: float = 0.0        # for a landscape asset in a vertical frame
    scale: float = 0.0           # percent; 0 -> cover the frame exactly
    composite: str = "screen"    # xmeml <compositemode>
    gain_db: Optional[float] = None   # None -> keep the asset's own level
    width: int = 0
    height: int = 0
    audio: bool = True

    def lead(self, tb) -> int:
        """Frames of the asset that sit *before* the cut, at a given timebase."""
        return tb.to_frames(self.hit_sec)

    def length(self, tb) -> int:
        return tb.to_frames(self.seconds)

    def footprint(self) -> tuple:
        """The asset's on-screen size after ``rotation``, as (w, h).

        A quarter turn swaps the axes, so the scale that covers the frame has to
        be worked out against the rotated shape — computing it from the file's
        own 1920x1080 would leave a landscape strip across a vertical frame.
        """
        if self.width and self.height and round(abs(self.rotation) % 180) == 90:
            return self.height, self.width
        return self.width, self.height


@dataclass
class Outro:
    """The tail card every reel of a show ends on.

    The picture keeps running underneath: ``hold`` frames of the last camera
    shot are added past the end of the cut, and the card sits over them. It is a
    rendered alpha file, not a Premiere text layer plus dissolves, because a
    dissolve applied in Premiere does not survive a re-export — the same reason
    the graphics templates fade themselves.
    """
    template: str = ""
    props: Dict = field(default_factory=dict)
    hold: int = 0                # frames of picture added after the cut
    scrim: float = 0.0           # 0-1, darkening baked into the card


@dataclass
class Show:
    id: str = ""
    name: str = ""
    graphics: str = "otg"        # which template family cards come from
    transitions: Dict[str, TransitionAsset] = field(default_factory=dict)
    default_transition: str = ""
    outro: Optional[Outro] = None

    def transition(self, key: str = "") -> Optional[TransitionAsset]:
        """The named asset, or the show's default when ``key`` is empty."""
        if not self.transitions:
            return None
        return self.transitions.get(key or self.default_transition
                                    or next(iter(self.transitions)))

    @property
    def dresses(self) -> bool:
        return bool(self.transitions or self.outro)


DEFAULT = Show(id="", name="none")


def load(show_id: str) -> Show:
    """Read ``shows/<id>.json``. An empty or unknown id is the empty show.

    Unknown rather than error on purpose: a project moved between machines
    should still export its cut, just undressed, instead of refusing.
    """
    if not show_id:
        return DEFAULT
    path = SHOWS_DIR / f"{show_id}.json"
    if not path.is_file():
        return DEFAULT
    return parse(json.loads(path.read_text(encoding="utf-8")), base=path.parent,
                 show_id=show_id)


def parse(d: dict, base: Optional[Path] = None, show_id: str = "") -> Show:
    def resolve(p: str) -> str:
        if not p:
            return ""
        q = Path(p)
        return str(q if q.is_absolute() or base is None else (base / q).resolve())

    transitions: Dict[str, TransitionAsset] = {}
    for key, t in (d.get("transitions") or {}).items():
        transitions[key] = TransitionAsset(
            id=key, path=resolve(t.get("path", "")),
            hit_sec=float(t.get("hit_sec", 0.0)),
            seconds=float(t.get("seconds", 0.0)),
            rotation=float(t.get("rotation", 0.0)),
            scale=float(t.get("scale", 0.0)),
            composite=str(t.get("composite", "screen")),
            gain_db=(None if t.get("gain_db") is None else float(t["gain_db"])),
            width=int(t.get("width", 0)), height=int(t.get("height", 0)),
            audio=bool(t.get("audio", True)),
        )

    outro = None
    o = d.get("outro")
    if o:
        outro = Outro(template=o.get("template", ""), props=o.get("props") or {},
                      hold=int(o.get("hold", 0)), scrim=float(o.get("scrim", 0.0)))

    return Show(
        id=show_id or d.get("id", ""), name=d.get("name", ""),
        graphics=d.get("graphics", "otg"),
        transitions=transitions,
        default_transition=d.get("default_transition", ""),
        outro=outro,
    )


def file_meta(show: Show, frame_size, tb, outro_mov: Optional[str] = None,
              outro_frames: int = 0) -> Dict[str, dict]:
    """xmeml ``<file>`` metadata for a show's own assets, keyed by absolute path.

    The whoosh is landscape material dropped into a vertical sequence, and its
    scale is computed against those real dimensions — so declaring the writer's
    default 1080x1920 instead would make Premiere conform the file to a shape it
    does not have and put the flash somewhere other than where it was placed.

    ``has_audio`` is stated rather than defaulted for the same reason the
    captions state it: a video-only ProRes claiming a stream it hasn't got shows
    up in Premiere as an audio channel that can never be filled.
    """
    out: Dict[str, dict] = {}
    for asset in show.transitions.values():
        if not asset.path:
            continue
        out[str(Path(asset.path).resolve())] = {
            "width": asset.width or frame_size[0],
            "height": asset.height or frame_size[1],
            "has_video": True, "has_audio": asset.audio,
            "channels": 2, "sample_rate": 48000,
            "duration_frames": asset.length(tb) or None,
        }
    if outro_mov:
        out[str(Path(outro_mov).resolve())] = {
            "width": frame_size[0], "height": frame_size[1],
            "has_video": True, "has_audio": False,
            "duration_frames": outro_frames or None,
        }
    return out


def known() -> List[str]:
    if not SHOWS_DIR.is_dir():
        return []
    return sorted(p.stem for p in SHOWS_DIR.glob("*.json"))
