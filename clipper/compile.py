"""EDL (master seconds) -> clipitems (integer frames).

The invariant that must hold for every clipitem is::

    end - start == out - in

Any inequality is a speed change, which Premiere will either reject or silently
retime. The way to guarantee it is to never compute a program position from
seconds. Instead, round each *master* boundary to frames exactly once, take the
shot length as a difference of those integers, and accumulate program position
as a running sum of those lengths. Gaps and overlaps then become impossible by
construction rather than by rounding luck.

A subtlety worth stating: the frame integer at a shot boundary is reused as both
the outgoing clip's ``out`` and the incoming clip's ``in``. Rounding the same
master time twice in two places is how off-by-one-frame flashes appear.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .edl import EDL, Clip, iter_shots
from .timebase import Timebase


@dataclass
class ClipItem:
    """One rectangle on one track."""
    name: str
    camera: str              # camera id, or "" for b-roll
    path: str                # absolute source path
    start: int               # program frame, inclusive
    end: int                 # program frame, exclusive
    in_: int                 # source frame, inclusive
    out: int                 # source frame, exclusive
    media_type: str          # "video" | "audio"
    source_channel: int = 1  # audio only: 1-based source track index
    link_group: Optional[int] = None   # members of a group get <link> elements
    enabled: bool = True     # FALSE -> imported muted/hidden, toggleable in Premiere
    role: str = "camera"     # "camera" | "broll" | "caption" | "audio"
    scale: float = 100.0     # percent; != 100 emits a Basic Motion filter

    @property
    def length(self) -> int:
        return self.end - self.start

    def __post_init__(self):
        if self.end - self.start != self.out - self.in_:
            raise AssertionError(
                f"clipitem {self.name!r} would retime: "
                f"program {self.end - self.start}f vs source {self.out - self.in_}f")


@dataclass
class CompiledMarker:
    frame: int
    name: str
    comment: str = ""
    duration: int = 0


@dataclass
class CompiledClip:
    """A clip ready to become one xmeml <sequence>."""
    id: str
    name: str
    timebase: Timebase
    frame_size: tuple
    video_tracks: List[List[ClipItem]] = field(default_factory=list)
    audio_tracks: List[List[ClipItem]] = field(default_factory=list)
    markers: List[CompiledMarker] = field(default_factory=list)
    duration: int = 0

    @property
    def duration_seconds(self) -> float:
        return self.timebase.to_seconds(self.duration)

    def all_items(self) -> List[ClipItem]:
        return [it for tr in self.video_tracks + self.audio_tracks for it in tr]

    def program_video(self) -> List[ClipItem]:
        """The picture actually seen, in program order.

        Every camera carries a clipitem for every shot; only the chosen angle is
        enabled. Anything reading "the edit" (preview, QC) wants this rather than
        a track, because no single track holds the whole cut any more.
        """
        return sorted((it for tr in self.video_tracks for it in tr
                       if it.role == "camera" and it.enabled),
                      key=lambda i: i.start)

    def items_by_role(self, role: str) -> List[ClipItem]:
        return sorted((it for tr in self.video_tracks + self.audio_tracks
                       for it in tr if it.role == role),
                      key=lambda i: i.start)

    def program_audio(self) -> List[ClipItem]:
        """The audio actually heard: the first enabled audio track."""
        for tr in self.audio_tracks:
            if tr and all(it.enabled for it in tr):
                return tr
        return []


def compile_clip(edl: EDL, clip: Clip, cameras: Dict[str, dict],
                 caption_mov: Optional[str] = None) -> CompiledClip:
    """Compile one clip. ``cameras`` maps camera id -> {"path", "offset_sec", ...}.

    ``caption_mov`` is an alpha overlay rendered by ``clipper.captions``; when
    present it becomes the topmost video track, spanning the whole clip.
    """
    tb = edl.timebase

    def src_frame(master_t: float, cam_id: str) -> int:
        """Master seconds -> source frame for a given camera.

        in/out in xmeml are offsets from the start of the *media file*, so a
        non-zero reel timecode on the source does not enter here — it is
        declared on the <file> element instead. Deliberate desync between
        cameras is expressed as offset_sec.
        """
        offset = float(cameras.get(cam_id, {}).get("offset_sec", 0.0) or 0.0)
        return tb.to_frames(master_t + offset)

    shots = list(iter_shots(clip, edl.default_camera))
    if not shots:
        return CompiledClip(id=clip.id, name=clip.title or clip.id,
                            timebase=tb, frame_size=edl.frame_size)

    stack_cams = _stack_cameras(cameras, shots)
    # Both angles of a shot get the same framing, so toggling an angle in
    # Premiere doesn't also change the zoom.
    scales = jump_cut_scales(shots, edl.style.jump_cut_punch)

    # ── Camera stack: every shot exists on every camera track, exactly one of
    #    them enabled ─────────────────────────────────────────────────────────
    # Laying the alternate angles under the cut (disabled) instead of dropping
    # them is what makes an angle change a toggle in Premiere rather than a
    # re-export. Program time is defined by the *selected* camera and every
    # stacked twin is cut to that same length, so toggling can't shift the edit.
    cam_tracks: Dict[str, List[ClipItem]] = {cid: [] for cid in stack_cams}
    selected: List[ClipItem] = []
    prog = 0
    # Program frame at each master boundary, so audio and b-roll can map master
    # time onto the program timeline without recomputing the concatenation.
    prog_of_master: List[tuple] = []   # (master_start, master_end, prog_start)

    for shot_idx, (master_start, master_end, cam) in enumerate(shots):
        in_f = src_frame(master_start, cam)
        out_f = src_frame(master_end, cam)
        length = out_f - in_f
        if length <= 0:
            continue
        for cid in stack_cams:
            c_in = src_frame(master_start, cid)
            item = ClipItem(
                name=f"{cid} {_tc(tb, c_in)}",
                camera=cid, path=cameras.get(cid, {}).get("path", ""),
                start=prog, end=prog + length,
                # Length comes from the selected angle, never from this
                # camera's own rounding — a per-camera offset must not be able
                # to retime the twin.
                in_=c_in, out=c_in + length,
                media_type="video",
                enabled=(cid == cam),
                role="camera",
                scale=scales[shot_idx],
            )
            cam_tracks[cid].append(item)
            if cid == cam:
                selected.append(item)
        prog_of_master.append((master_start, master_end, prog))
        prog += length

    total = prog

    def master_to_prog(t: float) -> int:
        """Map a master time onto the program timeline (clamped into a segment)."""
        for m_start, m_end, p_start in prog_of_master:
            if m_start - 1e-9 <= t <= m_end + 1e-9:
                return p_start + (tb.to_frames(t) - tb.to_frames(m_start))
        # Outside every kept shot — clamp to the nearest edge.
        if t < prog_of_master[0][0]:
            return 0
        return total

    # ── V2: b-roll overlays, only where real footage is attached ─────────────
    v2: List[ClipItem] = []
    markers: List[CompiledMarker] = [
        CompiledMarker(frame=master_to_prog(m.at), name=m.name or "marker",
                       comment=m.comment)
        for m in clip.markers
    ]

    for b in clip.broll:
        p_start = master_to_prog(b.start)
        p_end = master_to_prog(b.end)
        if p_end <= p_start:
            continue
        if b.source:
            length = p_end - p_start
            in_f = tb.to_frames(b.source_in)
            v2.append(ClipItem(
                name=f"broll {b.id}" if b.id else "broll",
                camera="", path=b.source,
                start=p_start, end=p_end,
                in_=in_f, out=in_f + length,
                media_type="video", role="broll",
            ))
        else:
            # Placeholder: a marker carries the intent without making Premiere
            # nag about offline media on every import.
            markers.append(CompiledMarker(
                frame=p_start, duration=p_end - p_start,
                name=f"BROLL {b.id}".strip(),
                comment=f"BROLL: {b.query}" if b.query else "BROLL",
            ))

    # ── Audio ────────────────────────────────────────────────────────────────
    audio_tracks = _compile_audio(edl, clip, cameras, selected, prog_of_master,
                                  tb, stack_cams)

    # ── Captions: topmost video track, spanning the whole clip ───────────────
    caption_track: List[ClipItem] = []
    if caption_mov and total > 0:
        caption_track.append(ClipItem(
            name=f"captions {clip.id}",
            camera="", path=caption_mov,
            start=0, end=total,
            in_=0, out=total,
            media_type="video", role="caption",
        ))

    # Bottom -> top: camera stack, then b-roll, then captions on top.
    video_tracks = ([cam_tracks[cid] for cid in stack_cams]
                    + ([v2] if v2 else [])
                    + ([caption_track] if caption_track else []))
    return CompiledClip(
        id=clip.id, name=clip.title or clip.id,
        timebase=tb, frame_size=edl.frame_size,
        video_tracks=video_tracks, audio_tracks=audio_tracks,
        markers=sorted(markers, key=lambda m: m.frame),
        duration=total,
    )


def jump_cut_scales(shots: List[tuple], punch: float) -> List[float]:
    """A scale per shot that keeps adjacent same-camera framings different.

    ``shots`` is the ``(master_start, master_end, camera)`` list. A join is a
    jump cut when the camera is unchanged *and* the source is discontinuous —
    the two halves of one take with the middle removed, which is exactly the
    edit a viewer sees as a glitch. Alternating between two zoom levels across
    those joins guarantees consecutive shots never share framing.

    A contiguous join is invisible and is left alone; an angle change resets to
    100%, since the new camera already hides the cut and stacking a punch on top
    would make the angle change itself look like a zoom.
    """
    scales: List[float] = []
    punched = False
    for i, (m_start, _m_end, cam) in enumerate(shots):
        if i == 0:
            punched = False
        else:
            prev_start, prev_end, prev_cam = shots[i - 1]
            same_camera = cam == prev_cam
            source_gap = abs(m_start - prev_end) > 1e-6
            if same_camera and source_gap and punch > 0:
                punched = not punched      # alternate, so neighbours differ
            elif not same_camera:
                punched = False
        scales.append(100.0 + punch if punched else 100.0)
    return scales


def _stack_cameras(cameras: Dict[str, dict], shots) -> List[str]:
    """Camera ids that get a stacked picture track, bottom to top.

    Audio-only sources (an enhanced mix) are excluded — they carry no picture,
    and a video clipitem pointing at an mp3 makes Premiere report offline media.
    Every *video* camera is stacked even if this clip never cuts to it: having
    the unused angle sitting there, disabled, is the point.
    """
    ids = [cid for cid in sorted(cameras)
           if cameras[cid].get("has_video", True) and cameras[cid].get("path")]
    used = {cam for _, _, cam in shots}
    # A camera the EDL actually cuts to must be present even if the caller's
    # metadata claims it has no picture — the cut is the stronger signal.
    return ids or sorted(used)


def _compile_audio(edl: EDL, clip: Clip, cameras: Dict[str, dict],
                   selected: List[ClipItem], prog_of_master: List[tuple],
                   tb: Timebase, stack_cams: List[str]) -> List[List[ClipItem]]:
    """Build audio tracks according to the EDL's audio mode.

    ``pinned`` cuts audio at *segment* boundaries only, never at camera switches
    — that continuity is the whole reason it's the default.

    One source becomes exactly one track. A stereo file has a single source
    audio *track* carrying two channels, so emitting one clipitem per channel
    asks for source track 1 and source track 2 of a file that only has one, and
    Premiere answers with the same stereo pair twice.
    """
    mode = edl.audio.mode

    if mode == "follow_video":
        # Audio mirrors the picture edit exactly, so every pair can be linked.
        track: List[ClipItem] = []
        for group, vi in enumerate(selected, start=1):
            vi.link_group = group
            track.append(ClipItem(
                name=vi.name, camera=vi.camera, path=vi.path,
                start=vi.start, end=vi.end, in_=vi.in_, out=vi.out,
                media_type="audio", link_group=group, role="audio",
            ))
        return [track] if track else []

    if mode == "multitrack":
        return [t for t in
                (_audio_run(cid, cameras, clip, prog_of_master, tb)
                 for cid in sorted(cameras))
                if t]

    # pinned (default): the pinned source is the one you hear; every camera's
    # own mic is laid in underneath it, disabled, so a scratch track is one
    # toggle away when the mix doesn't cover something.
    pinned = edl.audio.pinned_camera or edl.default_camera
    tracks: List[List[ClipItem]] = []
    main = _audio_run(pinned, cameras, clip, prog_of_master, tb)
    if main:
        tracks.append(main)
    for cid in stack_cams:
        if cid == pinned:
            continue
        scratch = _audio_run(cid, cameras, clip, prog_of_master, tb,
                             enabled=not main)
        if scratch:
            tracks.append(scratch)
    return tracks


def _audio_run(cam_id: str, cameras: Dict[str, dict], clip: Clip,
               prog_of_master: List[tuple], tb: Timebase,
               enabled: bool = True) -> List[ClipItem]:
    """One continuous audio track from a single camera, cut only at segments."""
    offset = float(cameras.get(cam_id, {}).get("offset_sec", 0.0) or 0.0)
    path = cameras.get(cam_id, {}).get("path", "")
    items: List[ClipItem] = []

    # Merge adjacent shots that came from the same segment back into one run.
    for seg in sorted(clip.segments, key=lambda s: s.start):
        covering = [(ms, me, ps) for ms, me, ps in prog_of_master
                    if ms >= seg.start - 1e-9 and me <= seg.end + 1e-9]
        if not covering:
            continue
        p_start = covering[0][2]
        p_end = covering[-1][2] + (tb.to_frames(covering[-1][1])
                                   - tb.to_frames(covering[-1][0]))
        in_f = tb.to_frames(seg.start + offset)
        length = p_end - p_start
        items.append(ClipItem(
            name=f"{cam_id} audio {_tc(tb, in_f)}",
            camera=cam_id, path=path,
            start=p_start, end=p_end,
            in_=in_f, out=in_f + length,
            media_type="audio", enabled=enabled, role="audio",
        ))
    return items


def compile_edl(edl: EDL, cameras: Dict[str, dict],
                clip_ids: Optional[List[str]] = None,
                caption_movs: Optional[Dict[str, str]] = None) -> List[CompiledClip]:
    """Compile every clip (or a named subset) in the EDL.

    ``caption_movs`` maps clip id -> rendered overlay path; clips without an
    entry just get no caption track.
    """
    wanted = [c for c in edl.clips if clip_ids is None or c.id in clip_ids]
    movs = caption_movs or {}
    return [compile_clip(edl, c, cameras, movs.get(c.id)) for c in wanted]


def _tc(tb: Timebase, frame: int) -> str:
    return tb.to_timecode(frame)
