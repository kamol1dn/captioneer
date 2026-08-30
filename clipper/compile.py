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
import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .edl import EDL, AudioPlan, Clip, iter_shots
from .sources import SourceRef, SourceTrack
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
    # Set when this item came off a master timeline rather than a flat export.
    # It carries the source definition (a file, or a nested sequence with its own
    # framing) for the writer to re-emit verbatim, so a crop expressed as
    # nest-plus-offset survives into the reel without being understood here.
    source: Optional[SourceRef] = None
    # The source clipitem's own <filter> elements, passed through unchanged.
    # ``scale`` composes into an existing Basic Motion rather than adding a
    # second one — two Basic Motions on one clipitem is undefined in Premiere.
    filters: List[ET.Element] = field(default_factory=list)

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
    # Program ranges where a track-backed angle has no footage, as
    # {camera_id: [(program_start, program_end), ...]}. A hole on the *selected*
    # angle is black frames in the finished reel, so this is reported rather
    # than silently filled.
    coverage_gaps: Dict[str, List[tuple]] = field(default_factory=dict)

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
                 caption_mov: Optional[str] = None,
                 audio_tracks: Optional[List[SourceTrack]] = None) -> CompiledClip:
    """Compile one clip. ``cameras`` maps camera id -> {"path", "offset_sec", ...}.

    A camera entry may instead carry ``"track"``: a ``SourceTrack`` read off the
    episode timeline. That camera's picture then comes from whatever the master's
    V-track points at, and master time maps to source time piecewise rather than
    by a constant offset — so one shot on such a camera can become several
    clipitems, one per master cut it spans.

    ``caption_mov`` is an alpha overlay rendered by ``clipper.captions``; when
    present it becomes the topmost video track, spanning the whole clip.

    ``audio_tracks`` are the master's own A-tracks, used by the ``source_tracks``
    audio mode to reproduce the episode's whole audio bed under the cut.
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

    def track_of(cam_id: str) -> Optional[SourceTrack]:
        return (cameras.get(cam_id) or {}).get("track")

    shots = list(iter_shots(clip, edl.default_camera))
    if not shots:
        return CompiledClip(id=clip.id, name=_clip_name(edl, clip),
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

    gaps: Dict[str, List[tuple]] = {}

    for shot_idx, (master_start, master_end, cam) in enumerate(shots):
        if track_of(cam) is not None:
            # A track-backed angle is addressed in timeline frames, which are
            # master frames — the export and the timeline share t=0 — so the
            # shot length comes straight off the master boundaries instead of a
            # per-camera offset that does not apply here.
            length = tb.to_frames(master_end) - tb.to_frames(master_start)
        else:
            length = src_frame(master_end, cam) - src_frame(master_start, cam)
        if length <= 0:
            continue
        for cid in stack_cams:
            track = track_of(cid)
            if track is None:
                c_in = src_frame(master_start, cid)
                items = [ClipItem(
                    name=f"{cid} {_tc(tb, c_in)}",
                    camera=cid, path=cameras.get(cid, {}).get("path", ""),
                    start=prog, end=prog + length,
                    # Length comes from the selected angle, never from this
                    # camera's own rounding — a per-camera offset must not be
                    # able to retime the twin.
                    in_=c_in, out=c_in + length,
                    media_type="video",
                    enabled=(cid == cam), role="camera", scale=scales[shot_idx],
                )]
            else:
                items = _track_items(
                    track, cid, tb.to_frames(master_start), length, prog, tb,
                    media_type="video", enabled=(cid == cam), role="camera",
                    scale=scales[shot_idx])
                for a, b in track.gaps(tb.to_frames(master_start), length):
                    gaps.setdefault(cid, []).append(
                        (prog + a - tb.to_frames(master_start),
                         prog + b - tb.to_frames(master_start)))
            cam_tracks[cid].extend(items)
            if cid == cam:
                selected.extend(items)
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
    compiled_audio = _compile_audio(edl, clip, cameras, selected, prog_of_master,
                                    tb, stack_cams, audio_tracks or [])

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
        id=clip.id, name=_clip_name(edl, clip),
        timebase=tb, frame_size=edl.frame_size,
        video_tracks=video_tracks, audio_tracks=compiled_audio,
        markers=sorted(markers, key=lambda m: m.frame),
        duration=total,
        coverage_gaps={k: _merge_ranges(v) for k, v in gaps.items()},
    )


def _clip_name(edl: EDL, clip: Clip) -> str:
    """Sequence name, prefixed with the clip's position in the EDL.

    Premiere sorts a bin's sequences by name, so 13 reels arrive in *title*
    order — which is neither the order they were chosen in nor anything an editor
    can navigate against the episode. A two-digit prefix restores the EDL's own
    ordering, and it lines up with the number already carried in the clip ids, so
    the sequence, the caption file and the EDL entry all read the same.

    Position in the whole EDL, not in the compiled subset: exporting one clip on
    its own must still call it 07, not 01.
    """
    title = clip.title or clip.id
    for i, c in enumerate(edl.clips, start=1):
        if c.id == clip.id:
            return f"{i:02d} {title}"
    return title          # compiled ad hoc, outside any EDL


def _track_items(track: SourceTrack, cam_id: str, m_start: int, length: int,
                 prog: int, tb: Timebase, media_type: str,
                 enabled: bool = True, role: str = "camera",
                 scale: float = 100.0) -> List[ClipItem]:
    """Slice a master track into clipitems on the program timeline.

    ``m_start`` is where this shot begins on the master timeline and ``prog``
    where it begins in the finished clip; a piece keeps its offset between the
    two, so the pieces of one shot stay butt-joined. Each piece satisfies
    ``end - start == out - in`` on its own, which is what keeps the invariant
    true no matter how many master cuts a shot spans.
    """
    out: List[ClipItem] = []
    for p in track.slice(m_start, length):
        out.append(ClipItem(
            name=f"{cam_id} {_tc(tb, p.in_)}" if cam_id else p.name,
            camera=cam_id, path=p.source.path,
            start=prog + (p.start - m_start),
            end=prog + (p.end - m_start),
            in_=p.in_, out=p.in_ + p.length,
            media_type=media_type, source_channel=p.source_channel,
            # Both flags have to agree: the caller's says whether this is the
            # angle the cut selects, the source's says whether the editor had
            # muted or disabled that clip on the master. Ignoring the second one
            # un-mutes every camera scratch track the mix was supposed to replace.
            enabled=enabled and p.enabled,
            role=role, scale=scale,
            source=p.source, filters=p.filters,
        ))
    return out


def _merge_ranges(ranges: List[tuple]) -> List[tuple]:
    """Coalesce touching/overlapping (start, end) pairs."""
    out: List[tuple] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


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

    A track-backed angle qualifies on its track alone. It has no file of its own
    — its picture is whatever the master timeline's V-track points at — so
    requiring a path would drop exactly the angles this workflow exists for.
    """
    ids = [cid for cid in sorted(cameras)
           if cameras[cid].get("has_video", True)
           and (cameras[cid].get("path") or cameras[cid].get("track") is not None)]
    used = {cam for _, _, cam in shots}
    # A camera the EDL actually cuts to must be present even if the caller's
    # metadata claims it has no picture — the cut is the stronger signal.
    return ids or sorted(used)


def _compile_audio(edl: EDL, clip: Clip, cameras: Dict[str, dict],
                   selected: List[ClipItem], prog_of_master: List[tuple],
                   tb: Timebase, stack_cams: List[str],
                   master_audio: List[SourceTrack]) -> List[List[ClipItem]]:
    """Build audio tracks according to the EDL's audio mode.

    ``pinned`` cuts audio at *segment* boundaries only, never at camera switches
    — that continuity is the whole reason it's the default.

    One source becomes exactly one track. A stereo file has a single source
    audio *track* carrying two channels, so emitting one clipitem per channel
    asks for source track 1 and source track 2 of a file that only has one, and
    Premiere answers with the same stereo pair twice.
    """
    mode = edl.audio.mode

    if mode == "source_tracks":
        return _source_track_audio(master_audio, clip, prog_of_master, tb)

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


def _source_track_audio(tracks: List[SourceTrack], clip: Clip,
                        prog_of_master: List[tuple],
                        tb: Timebase) -> List[List[ClipItem]]:
    """Reproduce the master timeline's own audio bed under the cut.

    One reel track per master A-track, sliced to the kept segments and otherwise
    untouched: the same lavs, camera scratch, music and mix layers, at the same
    relative positions. That matters because the audio an editor hears is the
    *sum* of those tracks — on this episode the enhanced mix covers barely a
    fifth of the timeline and the rest of the sound lives elsewhere, so pinning
    any single source would drop most of the audio.

    Cuts land only at segment boundaries and wherever the master itself already
    cut, never at a camera switch, so toggling an angle can't disturb the sound.

    A track the editor muted comes through muted. Premiere writes that mute on
    the *track*, leaving every clipitem on it reading TRUE, so honouring only
    the per-clip flag un-mutes exactly the camera scratch tracks the enhanced
    mix was laid in to replace — and the reel plays both lavs summed on top of
    the mix.
    """
    out: List[List[ClipItem]] = []
    seen: set = set()
    for tr in tracks:
        if not tr.segments:
            continue
        # A stereo source arrives from Premiere as *two* master tracks holding
        # the same clips at the same times, differing only in which source
        # channel each takes. Reproducing both asks for source track 2 of a file
        # whose <file> declares a single stereo track, and Premiere answers with
        # the whole pair twice — which plays as that source doubled. One source
        # is one track, so a clip already placed by an earlier track is dropped.
        #
        # Matched per *segment*, not per whole track: one Premiere track can hold
        # a mix of stereo and mono clips, and then only the stereo ones get a twin
        # track. On ep15 the host track was 56 stereo DJI clips plus 163 mono lav
        # clips, so the twin held 56 of the parent's 219 — no layout in common,
        # and comparing whole tracks let the DJI double for the entire 22 minutes
        # the guest was in the room.
        fresh = [s for s in tr.segments
                 if (getattr(s.source, "key", None), s.start, s.end, s.in_)
                 not in seen]
        if not fresh:
            continue
        seen.update((getattr(s.source, "key", None), s.start, s.end, s.in_)
                    for s in fresh)
        tr = copy.copy(tr)          # shallow: only the segment list is narrowed
        tr.segments = fresh
        items: List[ClipItem] = []
        for seg in sorted(clip.segments, key=lambda s: s.start):
            covering = [(ms, me, ps) for ms, me, ps in prog_of_master
                        if ms >= seg.start - 1e-9 and me <= seg.end + 1e-9]
            if not covering:
                continue
            p_start = covering[0][2]
            p_end = covering[-1][2] + (tb.to_frames(covering[-1][1])
                                       - tb.to_frames(covering[-1][0]))
            items.extend(_track_items(
                tr, "", tb.to_frames(covering[0][0]), p_end - p_start, p_start,
                tb, media_type="audio", role="audio", enabled=tr.enabled))
        if items:
            # The surviving track carries the source's whole stereo pair, so it
            # must reference source track 1 regardless of which channel the
            # master track it came from was taking.
            for it in items:
                it.source_channel = 1
            out.append(items)
    return out


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
                caption_movs: Optional[Dict[str, str]] = None,
                audio_tracks: Optional[List[SourceTrack]] = None) -> List[CompiledClip]:
    """Compile every clip (or a named subset) in the EDL.

    ``caption_movs`` maps clip id -> rendered overlay path; clips without an
    entry just get no caption track.
    """
    wanted = [c for c in edl.clips if clip_ids is None or c.id in clip_ids]
    movs = caption_movs or {}
    return [compile_clip(edl, c, cameras, movs.get(c.id), audio_tracks)
            for c in wanted]


def compile_for(project, edl: EDL, clip_ids: Optional[List[str]] = None,
                caption_movs: Optional[Dict[str, str]] = None) -> List[CompiledClip]:
    """Compile an EDL against a project, wiring in its master timeline if it has
    one.

    Every caller had been assembling compile's inputs by hand, which was fine
    while a project was just a camera map — but a master-timeline project has a
    second input, and one call site forgetting it produces reels with no audio
    rather than an error. ``project`` is duck-typed to keep the dependency
    pointing this way: ``xmeml`` already imports this module.
    """
    return compile_edl(edl, project.camera_map(), clip_ids, caption_movs,
                       project.master_audio_tracks())


def compile_for_monitor(project, edl: EDL, clip_ids: Optional[List[str]] = None,
                        caption_movs: Optional[Dict[str, str]] = None
                        ) -> List[CompiledClip]:
    """Compile for local monitoring — preview renders and audio verification.

    ffmpeg has to be handed one audible track, but ``source_tracks`` audio is a
    bed whose sound is the *sum* of a dozen layers; no single one of them is what
    a viewer hears, and picking the first would verify the cut against one lav.
    The project's primary audio camera is precisely the exported mix that stands
    in for that sum, so monitoring pins it and leaves the export path — which
    should carry the real tracks into Premiere — untouched.
    """
    if edl.audio.mode != "source_tracks":
        return compile_for(project, edl, clip_ids, caption_movs)
    pinned = project.primary_audio_camera
    if not pinned:
        raise ValueError(
            "monitoring a source_tracks EDL needs a primary_audio_camera to "
            "stand in for the mix; the project has none")
    monitor = copy.copy(edl)          # shallow: only the audio plan differs
    monitor.audio = AudioPlan(mode="pinned", pinned_camera=pinned,
                              channels=edl.audio.channels)
    return compile_edl(monitor, project.camera_map(), clip_ids, caption_movs)


def _tc(tb: Timebase, frame: int) -> str:
    return tb.to_timecode(frame)
