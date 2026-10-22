# gashtak-skleyka

Claude edits Gashtak long-form podcasts inside a live Premiere timeline. The
user syncs, switches angles by hand in a multicam sequence, trims, then says
"start". Claude reads that edit, transcribes it, and puts graphics rendered by
our own system (Remotion, from reel-studio's kit) on tracks above the cut, in
the free space of whichever angle is on screen.

OTG is not affected: its long-form workflow (`longform/`) stays as it is.

To dress an episode, follow `HANDOFF.md`: transcribe, identify the speakers,
plan, get the user's yes, then craft with subagents one at a time.

## How it talks to Premiere

```
Claude ──MCP──▶ skleyka.mcp_server ──cmd_*.jsx / res_*.json──▶ CEP panel ──evalScript──▶ Premiere
                (Python, this repo's venv)   %LOCALAPPDATA%\gashtak-skleyka\bridge
```

- `panel/`: the CEP connector, forked from
  [premiere-pro-mcp](https://github.com/leancoderkavy/premiere-pro-mcp) (MIT)
  and cut down to the file bridge. A headless extension starts with Premiere,
  and **Window > Extensions > Gashtak Skleyka** shows its status. It is signed
  with a local certificate because CEP 12 on this machine rejects unsigned
  panels: `scripts/sign-panel.ps1`. Re-sign after any edit to `panel/`.
- `skleyka/jsx/`: the ExtendScript helpers. They are sent with every command,
  so changing them never needs re-signing or a Premiere restart.
- `skleyka/prproj.py`: the angle of each multicam cut. Scripting can't see
  it, but the saved project file stores it as `SelectedTrackIndex`. Your
  multicam sequence is never flattened or modified.
- Editing `panel/` without restarting Premiere: re-sign, then reload the two
  pages over their debug ports (8093 headless, 8094 panel) with the DevTools
  `Page.reload` command. The signature is checked when Premiere starts, not on reload.
- The MCP server is registered in the repo's `.mcp.json` with `PYTHONPATH`
  pointing here; Claude Code ignores a `cwd` key there.

## What Skleyka may touch

- Its own lanes: tracks named `SKL <n>`, added on top of the video stack and
  at the bottom of the audio stack, never in between the user's tracks.
- Its own clips: named `SKL <id> <label>` (`g001` renders, `a001` sounds),
  recorded in `<episode>/skleyka/overlays.json` with their source anchors.
- The multicam edit track, only through `set_angle` / `move_switch`.
- Everything else is read-only.

## Rules learned by probing Premiere 25.6

- **Angles:** `qe.sequence.multicam.changeCamera(n)` (1-based) is the
  scripted "press camera n". With the playhead on a cut's first frame it
  switches the whole cut; mid-cut it splits there and switches the rest.
  `trackItem.setMulticam(bool)` only toggles multicam on or off.
- **Switch points:** `qeItem.roll("<frames>", true, ...)` rolls a clip's head
  edit, `false` its tail. Only `switch` joins roll; at a `trim` join a roll
  would change what is said.
- **Exact placement:** `track.overwriteClip` lays down the project item's
  in/out range. The marks take seconds and round down a frame, so video marks
  are aimed half a frame in, then read back before overwriting.
- **Head trims:** setting `trackItem.start` slides the content. Skleyka
  re-places the render from the right point inside it instead.
- **Re-renders:** Premiere locks media it uses, so a render cannot be
  overwritten in place. Write `name_v2.mov` and `replace_overlay(file=...)`.
- **Blend modes** (Opacity > first "Blend Mode", measured per pixel): normal
  18, screen 22, add 14, multiply 17, overlay 19, lighten 11, darken 3, color
  dodge 2, color burn 1, linear burn 13, difference 5, exclusion 7, subtract 25.
- **Clip volume** is stored as 10^((dB − 15) / 20).
- **Stills** land with an in-point an hour into their virtual media and show
  nothing; set `trackItem.inPoint = 0` after placing, then extend `end`
  freely (a still has no length limit).
- **Keyframes** (`setTimeVarying`, `addKey`, `setValueAtKey`) take times in
  the clip's media clock: in-point = the clip's first frame. Keys set at
  sequence time fall past the clip and the first key's value is held
  throughout.
- **Audio marks** must be set/read with media type 2; type 4 rounds them to
  video frames (0–1.5 s became 0–1.467 s).
- **Dissolves:** `qeClip.addTransition(qe.project.getVideoTransitionByName
  ('Cross Dissolve'), head, "<timecode of the length>", '0', 0.5, false,
  true)` puts a real Cross Dissolve on a clip's head (true) or tail (false);
  on a lone clip it fades from/to nothing. The editor's lower third uses
  4-frame dissolves, so Skleyka's does too (`animate="dissolve"`).
- **Frames:** `qeSeq.exportFramePNG(timecode, path)` wants a timecode in the
  sequence's display format (a ticks string reads as frame 0) and a backslash
  path without extension or dots (forward slashes throw).
- **ES3:** `in`, `final` and other reserved words can't be bare object keys;
  the panel reports a bare "EvalScript error" for any syntax error.
- **Sync lock:** lanes are sync-locked like the user's tracks, so ripple
  re-trims carry overlays along; `resync_overlays` fixes anything that drifted.

## Phases

1. **Bridge + timeline reading** (done): read the cut live. Each multicam cut
   gives its angle, its camera layers (a split-screen angle is two layers,
   each with position/scale/crop), media file and time, the Motion on `main`
   (punch-ins), and how it joins the previous cut: `switch`, `trim` (cut-out
   material hidden by an angle change) or `jump`. Moving an angle switch must
   never turn a trim into a jump. Tools: `bridge_status`, `read_timeline`,
   `run_jsx`.
2. **Placing renders + angles** (done): `place_overlay` (ProRes 4444 alpha,
   no audio; position, scale, rotation, opacity, blend), `place_sound`,
   `move_overlay`, `trim_overlay`, `restyle_overlay`, `replace_overlay`,
   `remove_overlay`, `list_overlays`, `resync_overlays` (put overlays back on
   their moment after a re-trim), `set_angle` (with the jump-cut guard),
   `move_switch`, and `grab_frame` (the composited program frame, to check
   placement by eye). Tested end to end on a copy of Teacher Azam's `main`.
3. **Audio + transcript** (done): the recorder's mix is transcribed once per
   file, in file time, with the clipper's Kotib worker in the background
   (`transcribe_program`, `transcript_status`; ~40 min for 2 h). Words are
   then mapped onto the edit through the voice track's clips
   (`build_transcript`, seconds; re-run after a re-trim). Speakers come from
   the recorder's isolated mics: `identify_speakers` finds the live mic files
   next to the mix, measures each one's clock offset by cross-correlation,
   and matches each mic to the camera angle the user cuts to while it is
   loudest (behzod tahlil: three mics matched three people with 3–11 dB
   margins; ~92% word agreement with the camera on the two lav mics). Each
   word keeps the loudest mic's margin so unsure labels are visible. Readers:
   `transcript_outline`, `get_transcript`, `get_words`, `search_transcript`,
   and `retranscribe_snippet` (Kotib again on a few padded seconds, from the
   mix or one speaker's mic, before trusting a doubtful word).
4. **Free space per cut** (done): `analyze_frames` grabs one composited
   program frame per multicam cut (plus one every 20 s inside long cuts)
   through Premiere's own frame export, so nests, crops and punch-ins are
   already applied, and finds the faces with YuNet (reel-studio's model).
   Samples are keyed by the cut's source time and kept under
   `<episode>/skleyka/samples/`, so a re-trim only grabs new cuts.
   `free_space(at, w, h, near=...)` grows each face into a seated body,
   rasterises a 48×27 occupancy grid with edge and lower-third margins, and
   returns positions where a w×h graphic covers nobody: beside a named
   person at head height (`set_seats` maps names to left/centre/right), or
   the roomiest spot. `people_at` returns the faces and the sample JPEG to
   look at. In a three-shot the honest answer is "the band above the heads";
   in close-ups there is room beside the speaker.
5. **Graphics** (renderer done, placing next): six long-form templates in
   the clipper's Remotion project (`graphics/src/gashtak/longform.tsx`,
   registered in `templates.json` with `show: gashtak`): `GashtakWord`,
   `GashtakQuote`, `GashtakNumber`, `GashtakList`, `GashtakStill` as
   overlays, `GashtakFull` as a crimson full-frame card with the reels'
   pictogram kit (copied in as `gashtak/pictos.tsx`). `render_graphic`
   renders an overlay at the pixel size of its free-space box (ProRes 4444,
   no audio, plus a PNG still), so `place_overlay` lays it in at 100% with
   position = the box centre. `preview_placement` composites the still over
   the cut's sample frame at a proposed spot, so a placement is judged from a
   file and Premiere is only asked for the final frame. The burn transition is
   placed as-is with blend "screen"; SFX via `place_sound`. Not yet done: baked effects (glass, blur)
   that need the footage under them, and the stale-check for those.

Gashtak's graphic types and full-screen scene rules live with the show: `shows/gashtak/LONGFORM-GRAPHICS.md`.

## Engine vs. episode

As with reel-studio, this repo is the engine; nothing episode-specific is
kept here. Everything an episode makes lives in `<episode>/skleyka/`:

```
overlays.json, timeline_*.json, episode.json   what Skleyka placed and read
assets/        type 1 PNGs (scrim, text lines), burn copies (video + .wav)
public/        the episode's Remotion public dir: fonts/ (synced from
               graphics/public/fonts), _assets/ (staged images), spans/
               (exported footage under glass cards), scenes/ (a scene's art)
scenes/        the episode's own full-screen scenes (.tsx)
renders/       every render, stills/ for previews, spans/ (Premiere exports)
frames/, samples/, transcripts/
```

The renderer (`graphics/render.mjs`) takes the episode's public dir and,
for scenes, a generated entry: the scenes are copied into
`graphics/src/_episode/` (git-ignored, rewritten on every scene render) so
they can import the engine's kit. Engine changes (a new template, a better
kit piece) go in the repo; anything for one episode stays with it.

## Keep Premiere alive

Premiere wedged twice during batch frame exports while a Kotib transcription
held the GPU (frame export is GPU-accelerated; the 8 GB card was shared with
several worker processes). Rules: never run `transcribe_program` and
`analyze_frames` at the same time; keep exports to a few dozen per session
with a pause between them; and if Premiere stops answering, the sampler
stops on its own and resumes later. The transcription worker is several
processes (the venv launcher re-executes the interpreter): stop it with a
command-line match, not one pid.
