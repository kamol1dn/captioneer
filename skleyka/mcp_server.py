"""Skleyka as an MCP server: Claude's tools for a live Premiere timeline.

Registered in the repo's .mcp.json, with PYTHONPATH pointing at the repo root.

Times are zero-based sequence seconds, snapped to frames. Angles are 0-based,
as read_timeline numbers them.
"""
import sys

# stdout is the JSON-RPC channel; pin UTF-8 and keep stray prints off it
# (same reasoning as clipper/mcp_server.py).
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")
_real_stdout = sys.stdout
sys.stdout = sys.stderr

from typing import List, Optional  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from pathlib import Path  # noqa: E402

from . import angles, audio, bake, bridge, explain, frames, fx, mgt, occupancy, overlays, preview, render, samples, timeline, transcript  # noqa: E402

mcp = FastMCP("skleyka")


@mcp.tool()
def bridge_status() -> dict:
    """Is the Premiere bridge up, and what is open? Call this first."""
    hb = bridge.heartbeat()
    if hb is None:
        return {"running": False, "hint": "Open Premiere (the bridge starts with it). "
                "If it still isn't running, run scripts/sign-panel.ps1 and restart Premiere."}
    state = bridge.run(
        "var s = app.project.activeSequence;"
        "return {project: app.project.path, active_sequence: s ? s.name : null,"
        " sequences: app.project.sequences.numSequences, version: app.version};"
    )
    return {"running": True, "commands_served": hb.get("commands")} | state


@mcp.tool()
def read_timeline(sequence: Optional[str] = None, save: bool = True) -> dict:
    """Read the edit: every clip on every track, and for multicam cuts the
    active angle, camera file and media time. Saves the project first (the
    angles are read from the saved .prproj) unless save=False.

    The full timeline is written to <project dir>/skleyka/timeline_<seq>.json;
    this returns a summary. ``sequence`` is a name or sequence ID, default the
    active sequence."""
    tl = timeline.read(sequence, save=save)
    return timeline.summary(tl, timeline.save(tl))


@mcp.tool()
def run_jsx(body: str, args: Optional[dict] = None, timeout: float = 60) -> object:
    """Escape hatch: run an ExtendScript function body in Premiere with the
    SK.* helpers loaded. ``ARGS`` holds ``args``; ``return`` a JSON-able value.
    For probing the API and one-off fixes, not for routine work."""
    return bridge.run(body, args, timeout=timeout)


def _style(position, scale, rotation, opacity, blend, gain_db=None) -> dict:
    style = {"position": position, "scale": scale, "rotation": rotation,
             "opacity": opacity, "blend": blend, "gain_db": gain_db}
    return {k: v for k, v in style.items() if v is not None}


@mcp.tool()
def place_overlay(file: str, start: float, end: Optional[float] = None, label: str = "",
                  lane: Optional[str] = None, position: Optional[List[float]] = None,
                  scale: Optional[float] = None, rotation: Optional[float] = None,
                  opacity: Optional[float] = None, blend: Optional[str] = None,
                  media_in: float = 0.0, whoosh: bool = False, sequence: Optional[str] = None) -> dict:
    """Place a render (ProRes 4444 with alpha, no audio stream) above the edit
    on a Skleyka lane ("SKL n" tracks, added on top when needed), from
    ``start`` to ``end`` (default: the render's length).

    ``lane``: a lane number, or a name: renders that contain a camera's
    footage go on "SKL <camera>" (lane="otabek"), one track per angle (for
    order; Premiere has no per-track video effects); alpha-only overlays leave
    it unset. position [x, y] is the render's centre in 0-1 frame units; scale in %;
    blend is normal|screen|add|multiply|overlay|lighten|darken|... (screen for
    light effects). whoosh=True adds the editor's whoosh as it comes in (do
    this for type 2 cards and infographics). Returns the overlay record,
    including its id and source anchor."""
    rec = overlays.place(file, start, end, kind="video", lane=lane, label=label,
                         style=_style(position, scale, rotation, opacity, blend),
                         media_in=media_in, sequence=sequence)
    if whoosh:
        rec = rec | {"whoosh": fx.whoosh(rec["start"], label=label, sequence=sequence)["id"]}
    return rec


@mcp.tool()
def place_sound(file: str, at: float, end: Optional[float] = None, gain_db: float = 0.0,
                label: str = "", lane: Optional[int] = None, media_in: float = 0.0,
                sequence: Optional[str] = None) -> dict:
    """Place a sound (SFX, riser, music sting) on a Skleyka audio lane at
    ``at`` seconds, from its file start. To land a library sound's hit on a
    moment at a matched level, use sfx_hit instead."""
    return overlays.place(file, at, end, kind="audio", lane=lane, label=label,
                          style={"gain_db": gain_db}, media_in=media_in, sequence=sequence)


@mcp.tool()
def list_overlays(sequence: Optional[str] = None) -> dict:
    """Everything Skleyka placed, checked against the live timeline: ok,
    missing, or changed on the timeline (moved/trimmed by hand or a ripple)."""
    return overlays.list_overlays(sequence)


@mcp.tool()
def move_overlay(overlay_id: str, start: Optional[float] = None, frames: Optional[int] = None,
                 sequence: Optional[str] = None) -> dict:
    """Nudge an overlay by ``frames`` or move it to ``start`` seconds. It is
    re-anchored to the moment it now sits on."""
    return overlays.move(overlay_id, start=start, frames=frames, sequence=sequence)


@mcp.tool()
def trim_overlay(overlay_id: str, start: Optional[float] = None, end: Optional[float] = None,
                 sequence: Optional[str] = None) -> dict:
    """Change an overlay's start and/or end in seconds. A later start skips
    into the render (the head is trimmed, not slid)."""
    return overlays.trim(overlay_id, start=start, end=end, sequence=sequence)


@mcp.tool()
def restyle_overlay(overlay_id: str, position: Optional[List[float]] = None,
                    scale: Optional[float] = None, rotation: Optional[float] = None,
                    opacity: Optional[float] = None, blend: Optional[str] = None,
                    gain_db: Optional[float] = None, sequence: Optional[str] = None) -> dict:
    """Change an overlay's position/scale/rotation/opacity/blend, or a
    sound's gain_db."""
    return overlays.restyle(overlay_id, _style(position, scale, rotation, opacity, blend, gain_db),
                            sequence=sequence)


@mcp.tool()
def replace_overlay(overlay_id: str, file: Optional[str] = None, keep_end: bool = False,
                    sequence: Optional[str] = None) -> dict:
    """Swap in a new render: a new ``file``, or the same path re-rendered.
    Keeps id, start, style and anchor; the end follows the new length unless
    keep_end."""
    return overlays.replace(overlay_id, file=file, keep_end=keep_end, sequence=sequence)


@mcp.tool()
def remove_overlay(overlay_id: str, sequence: Optional[str] = None) -> dict:
    """Take an overlay off the timeline (no ripple) and forget it."""
    return overlays.remove(overlay_id, sequence=sequence)


@mcp.tool()
def resync_overlays(apply: bool = True, sequence: Optional[str] = None) -> dict:
    """After the user re-trims: move each overlay back onto the moment (source
    time) it was placed on. Reports orphans (their moment was cut) and
    span changes (material inside them changed); never deletes."""
    return overlays.resync(sequence, apply=apply)


@mcp.tool()
def set_angle(at: float, angle: int, whole_cut: bool = True, force: bool = False,
              sequence: Optional[str] = None) -> dict:
    """Show ``angle`` for the multicam cut at ``at`` seconds (whole cut), or
    from ``at`` to the end of that cut (whole_cut=False). Refuses changes that
    would turn a hidden trim into a jump cut unless force. Saves the project."""
    return angles.set_angle(at, angle, whole_cut=whole_cut, force=force, sequence=sequence)


@mcp.tool()
def move_switch(at: float, frames: int, sequence: Optional[str] = None) -> dict:
    """Roll the angle switch nearest ``at`` seconds by ``frames`` (positive =
    later, so the earlier shot runs longer). Only plain switches roll; a cut
    that hides a trim refuses."""
    return angles.move_switch(at, frames, sequence=sequence)


@mcp.tool()
def grab_frame(at: float, sequence: Optional[str] = None, width: int = 1600) -> dict:
    """Export the composited program frame at ``at`` seconds as a JPEG (to
    look at with Read): the way to check an overlay's placement."""
    return frames.grab(at, sequence=sequence, width=width)


# ── transcript ──────────────────────────────────────────────────────────────

def _timeline(sequence):
    return timeline.read(sequence, save=False)


def _project_path() -> str:
    return bridge.run("return app.project.path;")


@mcp.tool()
def transcribe_program(voice_track: Optional[int] = None, language: str = "uz",
                       sequence: Optional[str] = None) -> dict:
    """Start transcribing the program voice (Kotib, in the background; a
    2-hour mix takes ~40 min on this GPU). The voice is the audio track
    carrying the recorder's mix: auto-picked (a file named *mix* on an
    unmuted track with full coverage) unless ``voice_track`` (0-based, A1=0)
    is given. Returns the choice, the other candidates, and the job state;
    poll transcript_status. A file transcribed before is reused."""
    tl = _timeline(sequence)
    cands = transcript.voice_candidates(tl)
    if voice_track is not None:
        pick = next((c for c in cands if c["track"] == voice_track), None)
        if pick is None:
            raise transcript.TranscriptError(
                f"A{voice_track + 1} is not a usable voice track; candidates: "
                + ", ".join(c["label"] for c in cands))
    elif cands:
        pick = cands[0]
    else:
        raise transcript.TranscriptError("No unmuted audio track with a single file found")
    ep = transcript.load_episode(tl["project_path"])
    ep["voice"] = {"track": pick["track"], "file": pick["file"]}
    transcript.save_episode(tl["project_path"], ep)
    job = transcript.start_job(tl["project_path"], pick["file"], language=language)
    return {"voice": {"label": pick["label"], "file": pick["file"]},
            "candidates": [{k: c[k] for k in ("label", "file", "covered_s")} for c in cands[1:]],
            "job": job}


@mcp.tool()
def transcript_status() -> dict:
    """Progress of the voice transcription: not_started | running (percent) |
    done | failed (with the log tail)."""
    project = _project_path()
    ep = transcript.load_episode(project)
    if not ep.get("voice"):
        return {"state": "not_started", "hint": "run transcribe_program"}
    return transcript.job_status(project, ep["voice"]["file"]) | {"voice_file": ep["voice"]["file"]}


@mcp.tool()
def identify_speakers(mic_files: Optional[List[str]] = None, apply: bool = False,
                      sequence: Optional[str] = None) -> dict:
    """Match the recorder's isolated mic files to people. By default every
    audio file in the voice file's folder is tried; silent ones and ones that
    share no material with the voice are dropped. Each mic's clock offset to
    the voice file is measured, and each mic is assigned the camera angle the
    user cuts to while that mic is loudest. Returns the dB matrix and a
    proposal (mic -> camera name); apply=True saves it as the speaker map,
    naming speakers after the camera angles. Needs transcribe_program run
    first (for the voice choice), not the transcript itself."""
    tl = _timeline(sequence)
    ep = transcript.load_episode(tl["project_path"])
    if not ep.get("voice"):
        raise transcript.TranscriptError("Run transcribe_program first so the voice file is known")
    voice_file = Path(ep["voice"]["file"])
    cache = transcript.transcripts_dir(tl["project_path"])
    ref = audio.envelope(voice_file, cache)
    if mic_files is None:
        mic_files = [str(f) for f in sorted(voice_file.parent.iterdir())
                     if f.suffix.lower() in transcript.AUDIO_EXT and f != voice_file]
    envs, offsets, skipped = {}, {}, []
    for f in mic_files:
        env = audio.envelope(f, cache)
        name = Path(f).name
        if not audio.is_live(env):
            skipped.append({"file": name, "why": "silent"})
            continue
        x = audio.offset_by_xcorr(ref, env)
        if x["peak"] < 0.3:
            skipped.append({"file": name, "why": f"no shared material (correlation {x['peak']})"})
            continue
        envs[name] = env
        offsets[name] = x["offset_s"]
    if not envs:
        raise transcript.TranscriptError("No live mic file shares material with the voice file; pass mic_files")
    clips = transcript.voice_clips(tl, ep["voice"]["track"])
    res = transcript.angle_mic_matrix(tl, clips, envs, offsets)
    files = {Path(f).name: str(f) for f in mic_files}
    result = {"offsets_s": offsets, "skipped": skipped} | res
    if apply:
        mics, mic_offsets = {}, {}
        for mic, p in res["proposal"].items():
            who = p["camera"]
            if who in mics:
                raise transcript.TranscriptError(f"Two mics map to '{who}'; use set_speakers by hand")
            mics[who] = files[mic]
            mic_offsets[who] = offsets[mic]
        ep["mics"], ep["mic_offsets"] = mics, mic_offsets
        transcript.save_episode(tl["project_path"], ep)
        result["saved"] = mics
    return result


@mcp.tool()
def set_speakers(mics: dict, offsets: Optional[dict] = None) -> dict:
    """Set the speaker map by hand: {name: mic file path}. ``offsets`` (name ->
    seconds to add to a voice-file time to get that mic's file time) are
    measured by cross-correlation when omitted."""
    project = _project_path()
    ep = transcript.load_episode(project)
    if not ep.get("voice"):
        raise transcript.TranscriptError("Run transcribe_program first so the voice file is known")
    cache = transcript.transcripts_dir(project)
    ref = audio.envelope(ep["voice"]["file"], cache)
    measured = {}
    for who, f in mics.items():
        if offsets and who in offsets:
            measured[who] = offsets[who]
        else:
            measured[who] = audio.offset_by_xcorr(ref, audio.envelope(f, cache))["offset_s"]
    ep["mics"], ep["mic_offsets"] = dict(mics), measured
    transcript.save_episode(project, ep)
    return {"mics": ep["mics"], "offsets_s": measured}


@mcp.tool()
def build_transcript(sequence: Optional[str] = None) -> dict:
    """Map the cached voice transcript onto the current edit (sequence time)
    and label speakers. Re-run after any re-trim; it takes seconds. Writes
    <episode>/skleyka/transcript_<seq>.json and returns a summary."""
    tl = _timeline(sequence)
    ep = transcript.load_episode(tl["project_path"])
    data = transcript.build(tl, ep)
    by_spk: dict = {}
    for u in data["utterances"]:
        who = u["spk"] or "?"
        by_spk[who] = round(by_spk.get(who, 0) + u["end"] - u["start"], 1)
    unsure = sum(1 for w in data["words"] if w.get("margin_db") is not None and w["margin_db"] < 3)
    return {"words": len(data["words"]), "utterances": len(data["utterances"]),
            "talk_time_s": by_spk, "words_with_unsure_speaker": unsure,
            "first_lines": transcript.window(data, 0, 40)}


def _data(sequence: Optional[str]) -> dict:
    name = sequence or bridge.run("return app.project.activeSequence.name;")
    return transcript.load(_project_path(), name)


@mcp.tool()
def transcript_outline(bucket_s: float = 30.0, start: float = 0.0, end: Optional[float] = None,
                       sequence: Optional[str] = None) -> str:
    """The whole episode at a glance: one line per bucket with who holds the
    floor and the first words. Read this before get_transcript."""
    return transcript.outline(_data(sequence), bucket_s=bucket_s, start=start, end=end)


@mcp.tool()
def get_transcript(start: float, end: float, sequence: Optional[str] = None) -> str:
    """What is said between ``start`` and ``end`` seconds of the edit, as
    timed, speaker-labelled lines."""
    return transcript.window(_data(sequence), start, end)


@mcp.tool()
def get_words(start: float, end: float, sequence: Optional[str] = None) -> List[dict]:
    """Word-level timing in a window (for placing a graphic on a word)."""
    return [{k: w[k] for k in ("text", "start", "end", "spk") if k in w}
            for w in transcript.words_in(_data(sequence), start, end)]


@mcp.tool()
def retranscribe_snippet(start: float, end: float, source: str = "voice", pad: float = 1.5,
                         sequence: Optional[str] = None) -> dict:
    """Re-run Kotib on just [start, end) seconds of the edit (padded by
    ``pad``), from the voice mix or from one speaker's own mic (``source`` =
    speaker name). Use it before putting a doubtful word in a graphic. Takes
    ~30 s; don't run it while transcribe_program is still running."""
    tl = _timeline(sequence)
    ep = transcript.load_episode(tl["project_path"])
    return transcript.retranscribe(tl, ep, start, end, source=source, pad=pad)


@mcp.tool()
def search_transcript(query: str, limit: int = 40, sequence: Optional[str] = None) -> List[dict]:
    """Lines containing ``query`` (case-insensitive; apostrophe variants
    treated alike), with their times and speakers."""
    return transcript.search(_data(sequence), query, limit=limit)


# ── rendering ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_graphic_templates() -> dict:
    """The long-form Gashtak templates (word, quote, number, list, still,
    full-screen card) with what each prop means and an example."""
    return render.templates()


@mcp.tool()
def render_graphic(template: str, props: dict, w: float, h: float, seconds: float,
                   name: Optional[str] = None, sequence: Optional[str] = None) -> dict:
    """Render a graphic to a .mov with alpha (and a .png still to look at),
    sized to a box of w x h fractions of the frame (from free_space) so
    place_overlay can lay it in at 100% with position=[x + w/2, y + h/2].
    GashtakFull ignores w/h and fills the frame (place at [0.5, 0.5])."""
    tl = _timeline(sequence)
    fw, fh, fps = tl["sequence"]["width"], tl["sequence"]["height"], tl["sequence"]["fps"]
    if template == "GashtakFull":
        w, h = 1.0, 1.0
    return render.render(tl["project_path"], template, props, round(fw * w), round(fh * h), seconds,
                         fps=fps, name=name)


@mcp.tool()
def graphic_still(template: str, props: dict, w: float, h: float, at: float = 0.85, seconds: float = 4.0,
                  sequence: Optional[str] = None) -> dict:
    """One frame of a template (``at`` = fraction of its length) as a PNG, in
    ~5 s, to judge a design or text fit before render_graphic renders video."""
    tl = _timeline(sequence)
    fw, fh, fps = tl["sequence"]["width"], tl["sequence"]["height"], tl["sequence"]["fps"]
    return {"still": render.still(tl["project_path"], template, props, round(fw * w), round(fh * h),
                                  at=at, seconds=seconds, fps=fps)}


@mcp.tool()
def render_scene(scene: str, seconds: float, still_at: Optional[float] = None, props: Optional[dict] = None,
                 background: bool = False, sequence: Optional[str] = None) -> dict:
    """Type 3: render the episode's own scene, <episode>/skleyka/scenes/<scene>.tsx
    (default export, built from the show's scene kit, e.g. shows/gashtak/graphics/scene.tsx; see the show's LONGFORM-GRAPHICS.md
    "Type 3"), full frame at the sequence size as ProRes 422 for place_full.
    With ``still_at`` (0-1 of its length) it renders one frame as a PNG
    instead, in seconds; iterate on stills, render video once. Video takes
    about a minute per second of 4K; background=True starts it and returns at
    once (this server answers one call at a time, so a blocking render holds
    up everyone else's calls): follow it with render_status."""
    tl = _timeline(sequence)
    s = tl["sequence"]
    kw = dict(props=props, width=s["width"], height=s["height"], fps=s["fps"])
    if background and still_at is None:
        return render.render_scene_background(tl["project_path"], scene, seconds, **kw)
    return render.render_scene(tl["project_path"], scene, seconds, still_at=still_at, **kw)


@mcp.tool()
def render_status(job: Optional[str] = None) -> List[dict]:
    """Background scene renders started this session (render_scene with
    background=True): running, done (with the .mov path for place_full) or
    failed. ``job`` is a job id or a scene name; none lists all."""
    return render.jobs(job)


@mcp.tool()
def preview_placement(at: float, still: str, x: float, y: float, w: float, h: float,
                      sequence: Optional[str] = None) -> dict:
    """The rendered still (from render_graphic) composited over the sampled
    frame of the cut at ``at``, with its top-left at (x, y) and size w x h
    (fractions), faces outlined faintly. A JPEG to look at before placing;
    no Premiere involved."""
    tl = _timeline(sequence)
    s = samples.sample_at(tl["project_path"], tl, at)
    if s is None:
        return {"ok": False, "hint": "no sample for this cut; run analyze_frames or people_at(grab=True)"}
    path = preview.preview(tl["project_path"], s, still, {"x": x, "y": y, "w": w, "h": h}, at)
    return {"ok": True, "image": path, "camera": s["camera"], "exact": s.get("exact")}



@mcp.tool()
def bake_card(template: str, props: dict, start: float, seconds: float, label: str = "",
              whoosh: bool = True, sequence: Optional[str] = None) -> dict:
    """Type 2 on glass: export the program span under it from Premiere,
    render ``template`` (GashtakGlassQuote | GashtakGlassFact |
    GashtakGlassStill | GashtakGlassChart | GashtakGlassBlitz; props include
    the card's ``box`` from free_space) with that footage blurred inside the
    card as its frost, and place only the card (alpha, ProRes 4444) on the
    camera's lane ("SKL <camera>"), so the picture around it stays the live
    cut, with the editor's whoosh (whoosh=False to skip). The card stays inside
    the shot it starts in (a same-angle through edit doesn't end it), except
    GashtakGlassBlitz, which runs across cuts on "SKL glass"; start and length
    snap to frames. Records the cuts underneath; see baked_stale."""
    return bake.bake(template, props, start, seconds, label=label, sequence=sequence, whoosh=whoosh)


@mcp.tool()
def baked_stale(sequence: Optional[str] = None) -> List[dict]:
    """Baked overlays whose footage no longer matches the cut under them
    (the user re-trimmed or switched an angle there). Fix with rebake."""
    return bake.stale(sequence)


@mcp.tool()
def rebake(overlay_id: str, sequence: Optional[str] = None) -> dict:
    """Export, render and place a baked overlay again over the current cut,
    keeping its id, text and timing."""
    return bake.rebake(overlay_id, sequence=sequence)

@mcp.tool()
def place_explain(title: str, detail: Optional[str] = None, at: float = 0.0, seconds: float = 7.0,
                  whoosh: bool = True, sequence: Optional[str] = None) -> dict:
    """Type 1, the explaining lower third, as the editor builds it: a scrim
    PNG, the title and the line as PNG stills (white Helvetica, rendered
    once and reused), staggered by 4 frames on lanes SKL scrim/title/detail
    with keyframed entrances, and the editor's whoosh 0.1 s before. Nothing
    rendered as video; every layer stays editable in Premiere."""
    return explain.place_explain(title, detail, at, seconds=seconds, whoosh=whoosh, sequence=sequence)


@mcp.tool()
def template_controls(mogrt: str, sequence: Optional[str] = None) -> dict:
    """What a .mogrt offers: whether scripting can fill it (After
    Effects-authored only) and its controls with their current text."""
    return mgt.controls(mogrt, sequence=sequence)


@mcp.tool()
def place_graphic_template(mogrt: str, start: float, seconds: float, texts: Optional[dict] = None,
                           lane: Optional[str] = None, label: str = "",
                           sequence: Optional[str] = None) -> dict:
    """Place a native Premiere graphic from an After Effects-authored .mogrt
    on a Skleyka lane and fill its text controls ({control name: text}). The
    user can then edit it in the Essential Graphics panel and the project
    stays small. Recorded like an overlay (resync/move/remove work)."""
    return mgt.place(mogrt, start, seconds, texts, lane=lane, label=label, sequence=sequence)



# ── transitions and sound design ────────────────────────────────────────────

@mcp.tool()
def place_burn(cut: float, variant: int = 4, sound: bool = True, sequence: Optional[str] = None) -> dict:
    """The editor's transition: a Burning Light Transition (no. 4 by default,
    1-10 exist) over the cut at ``cut`` seconds, screen blend, 90% opacity,
    scaled to fill, its brightest frame on the cut, with its own sound at
    -12 dB. Use at cuts to and from a full-screen or a cutaway segment."""
    return fx.place_burn(cut, variant=variant, sound=sound, sequence=sequence)


@mcp.tool()
def sfx_library(kind: Optional[str] = None, query: Optional[str] = None) -> List[dict]:
    """The editor's SOUNDS library, measured: each sound's kind (hit, swell,
    riser, texture), length, hit time (its loudest moment, from the start),
    loudness and the gain that matches the editor's whoosh level."""
    return fx.sounds(kind=kind, query=query)


@mcp.tool()
def sfx_hit(sound: str, at: float, trim_db: float = 0.0, gain_db: Optional[float] = None,
            sequence: Optional[str] = None) -> dict:
    """Place a library sound so its loudest moment lands on ``at`` seconds,
    at the level of the editor's whoosh (trim_db to sit it above or under;
    gain_db to override). Lane "SKL sfx"."""
    return fx.hit(sound, at, gain_db=gain_db, trim_db=trim_db, sequence=sequence)


@mcp.tool()
def place_full(file: str, start: float, end: Optional[float] = None, burn_in: bool = True,
               burn_out: bool = True, variant: int = 4, cues: Optional[List[dict]] = None,
               label: str = "full", sequence: Optional[str] = None) -> dict:
    """Type 3: a full-screen render on "SKL full" above the camera lanes, a
    burn over the cut in and the cut out, and its sound design: cues =
    [{"sound", "at" (seconds from start, where the hit lands), "trim_db"?}],
    one per thing that appears or moves (see README, type 3)."""
    return fx.place_full(file, start, end, burn_in=burn_in, burn_out=burn_out, variant=variant,
                         sound_cues=cues, label=label, sequence=sequence)

# ── free space ──────────────────────────────────────────────────────────────

@mcp.tool()
def set_seats(seats: dict) -> dict:
    """Who sits where, left to right as the wide shot shows them:
    {"left": name, "centre": name, "right": name}. Lets free_space(near=name)
    find a person in any shot. Decide it by looking at one wide sample and
    the single-person angles."""
    bad = [k for k in seats if k not in ("left", "centre", "right")]
    if bad:
        raise transcript.TranscriptError(f"seats are left/centre/right, not {bad}")
    project = _project_path()
    ep = transcript.load_episode(project)
    ep["seats"] = dict(seats)
    transcript.save_episode(project, ep)
    return {"seats": ep["seats"]}


@mcp.tool()
def analyze_frames(sequence: Optional[str] = None) -> dict:
    """Grab about ten program frames per camera angle, spread over the
    episode, and find the faces in each, in the background (~3 s a frame,
    paced so Premiere stays responsive). Samples are keyed by the cut's
    source time, so a re-trim reuses them. Poll frames_status."""
    ctx = bridge.run("var s = SK.sequence(ARGS.s); return {project: app.project.path, id: s.sequenceID};",
                     {"s": sequence})
    return samples.start(ctx["project"], ctx["id"])


@mcp.tool()
def frames_status() -> dict:
    """Progress of analyze_frames and the samples on disk per angle."""
    return samples.status(_project_path())


@mcp.tool()
def people_at(at: float, grab: bool = False, sequence: Optional[str] = None) -> dict:
    """Who is in the frame at ``at`` seconds and where: faces as normalised
    boxes left to right, the camera name, and a 960-wide JPEG to look at.
    Without a sample of this exact cut it merges the angle's samples
    (exact=False); grab=True exports this cut's own frame now (one export,
    ~3 s) for a placement that has to be precise."""
    tl = _timeline(sequence)
    if grab:
        s = samples.grab_at(tl["project_path"], tl["sequence"]["sequence_id"], tl, at)
        if s is not None:
            s = s | {"exact": True, "angle_samples": 1}
    else:
        s = samples.sample_at(tl["project_path"], tl, at)
    if s is None:
        return {"sampled": False, "hint": "no multicam cut here, or run analyze_frames first"}
    return {"sampled": True} | {k: s.get(k) for k in ("key", "exact", "angle_samples", "at", "angle", "camera",
                                                       "faces", "image", "timecode")}


@mcp.tool()
def free_space(at: float, w: float, h: float, near: Optional[str] = None, grab: bool = False,
               sequence: Optional[str] = None) -> dict:
    """Where a graphic of size w x h (fractions of the frame) can sit at ``at``
    seconds without covering anyone. ``near`` = "left" | "centre" | "right" |
    a speaker name picks a person to sit beside (at head height); otherwise
    the roomiest spots come first. Uses this cut's own frame if sampled, else
    the angle's samples merged (conservative); grab=True exports this cut's
    frame first. Returns top-left positions (normalised), the largest free
    rectangles, and the bodies they avoid. Premiere Motion position =
    [x + w/2, y + h/2]."""
    tl = _timeline(sequence)
    if grab:
        s = samples.grab_at(tl["project_path"], tl["sequence"]["sequence_id"], tl, at)
    else:
        s = samples.sample_at(tl["project_path"], tl, at)
    if s is None:
        return {"sampled": False, "hint": "no multicam cut here, or run analyze_frames first"}
    faces = s["faces"]
    grid = occupancy.occupancy(faces)
    target = None
    if near and faces:
        seats = transcript.load_episode(tl["project_path"]).get("seats") or {}
        seat = near if near in ("left", "centre", "center", "right") else \
            next((st for st, who in seats.items() if who == near), None)
        if seat is None:
            raise transcript.TranscriptError(f"'{near}' is not a seat or a seated speaker; set_seats first "
                                             f"(seats now: {seats})")
        target = occupancy.face_for(faces, seat)
    return {
        "sampled": True, "camera": s["camera"], "image": s["image"],
        "spots": occupancy.place(grid, w, h, near=target),
        "free_rects": occupancy.free_rects(grid),
        "people": [occupancy.body_of(f) for f in faces],
        "faces": faces,
        "near": target,
    }


if __name__ == "__main__":
    sys.stdout = _real_stdout
    mcp.run()
