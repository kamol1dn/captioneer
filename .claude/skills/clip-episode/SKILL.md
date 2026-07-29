---
name: clip-episode
description: Cut short vertical clips from a long multicam episode using the clipper engine MCP — pick moments from the transcript, choose camera angles, snap cuts to silence, add word-level captions, and export FCP7 XML for Premiere. Use when the user wants to make shorts/reels from an episode, asks to "cut clips" or "find moments" from footage, or mentions the clipper engine, an EDL, or exporting a timeline to Premiere.
---

# Cutting shorts from a multicam episode

Turn a long multicam recording into a set of short vertical clips, decided from
the transcript and exported as a Premiere-importable timeline. You make the edit
decisions; Premiere does the rendering.

## Before you start

The user exports each camera's timeline from Premiere — vertical, own audio, all
covering the **same time range** so they share a common t=0 — and drops them in a
folder (typically `for claude/`). The clipper project is created as `clipper/`
right beside that media, so the whole episode folder stays self-contained.

The MCP server is `clipper-engine`. If its tools aren't available, the server
isn't connected — say so rather than falling back to shell commands.

## House defaults (OTG)

Don't ask about these; just do them.

- **Caption preset is `otg_cyan`** — `render_all_captions(project_id,
  preset="otg_cyan")`. `list_caption_presets` shows the rest; the `gashtak_*`
  ones belong to the other channel.
- **An enhanced/combined mix** (`enhanced audio.mp3`) usually sits beside the
  camera exports. Register it as an extra source and make it
  `primary_audio_camera` — it is the audio the viewer hears. It is audio-only,
  so it is never an angle and never a diarization target.
- **Ingest with `diarize=True`.** Each camera carries its own subject's mic, so
  per-mic transcription gives attributed lines and survives crosstalk. The mix
  stays pinned as the audio; the camera mics supply the words.
- **Run the two checks before captioning**: `check_segments` (does it read?) then
  `verify_clip_audio` (does it sound right?). Both catch defects that are
  invisible in the EDL, and fixing a boundary after captioning costs the polish.
- **A `.vtt` from a previous captioneer run** may exist one folder up. It is the
  same audio on the same timeline, so it's an excellent cross-reference for
  exact word times and for ASR name errors — but never hand-write it into files
  the engine owns; let ingest produce its own transcript.

## Pipeline

**1. Create.** `create_project(name, cameras=[{id, path, label}], primary_audio_camera)`

Camera ids are short (`A`, `B`, `C`); labels say who they're on (`host`,
`guest`). **Read the warnings it returns.** Mismatched frame rates, durations
differing by >0.5s, or a non-zero start timecode all mean the exports may not
share a common t=0 — surface these to the user before going further, because
every downstream cut inherits the error.

**2. Ingest.** `ingest(project_id, model_size="large-v3", diarize=True)` then
poll `ingest_status`. Computes a loudness envelope for every camera and
transcribes at word level. Minutes on an hour of audio — tell the user it's
running rather than sitting silent.

**Prefer `diarize=True` when each camera carries its own subject's mic** (the
normal two-track setup here). It transcribes each mic separately and merges them
into one speaker-labelled timeline, so `get_transcript` returns `A:` / `B:` per
line instead of an energy guess, and two people talking at once survive as two
lines. It costs one Whisper pass per camera and needs at least two mics.

Every mic hears the whole room, so each raw transcript also contains the other
speaker 20-40 dB down. That bleed is rejected per word against the energy
envelopes; `ingest_status` reports what survived under `diarization`. **Read
that report** — a mic showing almost everything `dropped_as_bleed` means the
mics aren't as isolated as assumed, and the labels can't be trusted.

Leave `diarize` off for a single room mic, or when only a combined mix exists.
Then the transcript has no labels and the energy line is the speaker signal.

The combined mix is never a diarization target — it contains every voice at once
and would win every bleed comparison. It stays registered as an audio-only
source so it can still be pinned as the audio you hear.

**3. Read the episode.** `get_outline` first — one line per ~20s bucket, the
whole hour in ~2k tokens. Then `get_transcript(start, end)` on the promising
stretches, and `search_transcript` when the user names a topic.

Never pull the full transcript in one call. It's capped server-side; if
`truncated` comes back, continue from `next_start`.

**4. Pick the clips.** What makes a good short:

- A complete thought — a question and its answer, a claim and its payoff. If a
  viewer needs the previous two minutes to follow it, it isn't a clip.
- A strong first line. The first 2 seconds decide whether anyone watches. Prefer
  starting on a question, a claim, or a number — not on "so", "yeah", "I mean".
- Ends on the point, not on trailing filler.
- 30–60s typically. Say so if a moment genuinely needs 90s.

Cut filler and dead air by using **multiple segments** for one clip rather than
one long take: keep 124.3–141.8 and 208.0–240.5, drop the tangent between.

**5. Choose angles.** With `diarize=True` the transcript states the speaker
(`A:` / `B:`) — cut to whoever the line belongs to and skip the guesswork. Fall
back to the energy line (`A88 B09 C04`) for an unlabelled transcript: the
highest number is whoever's mic is hottest, so almost certainly who's talking.

Either way, **check every handover**. Missing a switch is the easiest mistake to
make on a long episode: scan each clip's lines for a speaker change and confirm
a `camera_cut` sits at it. A clip that never switches is fine when one person
narrates throughout — but verify that, don't assume it.

- Cut to whoever is speaking. A wide gap (`A88 B09`) means confident; a narrow
  one (`A51 B47`) means crosstalk — hold the current angle rather than flipping.
- Don't switch faster than ~2s. Sub-0.5s shots get flagged as glitches.
- A cut on the *incoming* speaker's first word reads better than one a beat late.
- Use `get_energy(start, end)` for a finer look when the utterance average is
  ambiguous.

**6. Snap the cuts.** Run every segment boundary through
`snap_to_silence(times)` before saving. Cuts landing mid-word are the single
most audible flaw in an automated edit, and this is cheap insurance.
`find_silences(start, end)` shows legal cut points directly.

Snapping only guarantees you didn't cut *through* a word — it can't tell you the
words you kept form a sentence. **`check_segments(project_id)` does that**, so
run it after `set_edl` and before captioning. It reports the text either side of
every join and flags:

- `orphan_open` — a segment opening on a fragment ("...policy letter. ⟩JOIN⟨ of
  25 US tech companies") because the words that started the clause fell in the
  trimmed gap.
- `orphan_close` — stopping on a dangling "And"/"as"/"The", so the audio trails
  off mid-thought even when the caption reads fine.
- `hook` / `empty_segment`.

It defaults to high-confidence findings; every deliberate trim technically
starts mid-clause, so showing everything buries the real breakages. Pass
`min_confidence="medium"` to see the rest. These are **warnings** — read the
context and decide. Fix by nudging the boundary and re-snapping; `get_transcript`
gives the exact word time to move to.

Do this *before* captioning: changing a boundary afterwards makes the clip stale
and costs the caption polish.

**Then hear it.** `verify_clip_audio(project_id)` renders each clip's audio,
transcribes it, and diffs it against the words the cut is supposed to contain.
`check_segments` reasons about the plan; this checks the result, and it catches
the class of defect that only exists once segments are concatenated:

- `clipped_word` — a planned word the render doesn't say, sitting on a boundary:
  the cut sliced it into a fragment, so the audio has a truncated syllable.
- `stutter` — a word heard twice because a boundary landed inside it.
- `extra_speech` — audio the plan didn't expect.

Read `mismatch` sceptically; ASR disagrees with itself on names and numbers, so
a lone substitution is usually the recogniser wavering, not the cut. It costs an
ffmpeg pass plus a Whisper pass per clip, so run it once the EDL is settled —
but do run it. Both defects it was built for shipped in ep12 and both read
perfectly in the EDL.

**7. Save the EDL.** `set_edl(project_id, edl)` — one EDL holds all the clips.

- `segments` — kept ranges in master seconds; the clip is their concatenation.
- `camera_cuts` — `{at, camera, why}` over the master timeline; the camera at
  time t is the last cut at or before t. Independent of segments, so you can
  retime one without redoing the other. Fill in `why` — it's how the user
  audits your reasoning.
- `audio.mode` — leave `pinned`. Every camera records the same room, so cutting
  audio at each visual switch produces an audible tonal jump.
- `broll` — placeholders with a `query` describing wanted footage. They export
  as timeline markers, not offline clips.

Rejected on errors (overlaps, out-of-range, unknown camera); warnings don't
block. If it rejects, fix and resubmit — don't work around the validator.

**8. Review with the user.** `preview_edl_text` gives a readable rundown — show
it and get agreement before rendering anything. `export_preview(clip_id)`
renders one clip with ffmpeg to actually watch (approximate: no b-roll, single
audio track).

**9. Captions.** Per clip:

- `get_clip_captions(project_id, clip_id)` returns the words **and** the
  project's own refinement prompt from `prompts.txt`.
- **Follow that prompt exactly.** It carries hand-tuned rules — capitalization,
  numbers as digits, Uzbek orthography (`o‘`/`g‘` vs `ma’no`), Russian
  code-switching in Cyrillic quotes, emoji appended to a word with no space and
  never as a standalone entry, `line_break` on the last word of each line. Don't
  substitute your own judgment for it.
- Do **not** change `start`/`end` except where the prompt allows (merging a
  spoken number, merging a split word).
- `set_clip_captions(project_id, clip_id, words)` — validated against clip
  duration.

Beyond the prompt's rules, fix what the ASR misheard — proper nouns are what a
viewer notices. Recurring offenders on this show: **Otabek** (not "Otome"),
**Andreessen Horowitz** (not "Anderson"), **Satya Nadella** *backing* (not
"baking"), **Anthropic** (not "Tropic"/"Antropic"), **Wise** (the ASR writes
"VISA" and "Y" all through the Wise story), **Nik Storonski**, **Genius Act**,
and "earnings per **share**". If a figure looks mis-transcribed, leave it out of
the caption rather than burning in a wrong number.

Polish every clip first, then render them all at once with
`render_all_captions(project_id, preset="otg_cyan")` — one call instead of
fourteen, ~11s per 60s clip. Strip-sized by default, positioned by hand in
Premiere; don't pass `full_frame=True` unless asked.

`caption_status(project_id)` is the "what's left" view: which clips are
polished, rendered, or **stale** (the cut changed after captioning, so their
timings no longer match picture — re-polish and re-render those).

No audio export and no re-transcription: words come from the master transcript
remapped onto the clip's program time, frame-exact against picture.

**10. Export.** `export_xml(project_id)` writes one XML with every clip as its
own sequence. Tell the user: File > Import in Premiere.

### What lands on the timeline

Each sequence is built so the editor can change decisions without a re-export:

```
V3   captions (rendered overlay, spans the clip)
V2   camera B — every shot, only B's shots enabled
V1   camera A — every shot, only A's shots enabled
A1   enhanced mix   — enabled   (what you hear)
A2   camera A mic   — disabled  (scratch)
A3   camera B mic   — disabled  (scratch)
```

- **Angle changes are a toggle.** Every shot exists on every camera track;
  exactly one is enabled. To flip an angle in Premiere, disable the live clip
  and enable its twin — no re-export. Stacked twins share program timing, so a
  toggle can never shift the edit or desync captions.
- Only cameras that carry picture are stacked; an audio-only mix never gets a
  video track.
- **One source is one audio track.** A stereo file has a single source audio
  track carrying two channels — emitting one clipitem per channel puts the same
  stereo pair on two tracks, which reads as duplicated audio.
- **Jump cuts are punched automatically.** Dropping filler out of one continuous
  take leaves two shots with identical framing, so the speaker's head teleports.
  The compiler alternates a small zoom (`style.jump_cut_punch`, default 4%)
  across same-camera cuts that have a real gap in the source, which makes the
  cut read as a deliberate reframe. Contiguous joins and angle changes are left
  at 100% — a different camera already hides the join. Set it to 0 to disable,
  or raise it if the user wants the effect more visible.
- Changing an angle via toggle does **not** update the EDL. If the user wants
  the change recorded, edit `camera_cuts` and re-export.

### What the user adds on top (from a finished ep11 timeline)

The engine delivers V1/V2 + audio; everything below is hand-finishing done in
Premiere afterwards. Don't try to reproduce it, but leave room for it and don't
fight it:

- **Graphics tracks above the captions** — a title card over the hook, images
  and an Essential Graphics "Watch the full video on YouTube!" end card. These
  are `GraphicAndType` effects carrying an opaque blob; they cannot be authored
  from XML.
- **Cross Dissolve with `start-black` / `end-black` alignment** on every graphic
  and image track, roughly 7-42 frames. That is how graphics enter and leave.
- **A blurred Adjustment Layer** (~138% scale) behind scaled-down imagery — the
  standard vertical-video background treatment.
- **Opacity** at 60-95% on overlay imagery.

Two things this tells us, both load-bearing:

1. **The picture edit and the audio are hard cuts — no transitions anywhere on
   V1 or the audio tracks.** Don't add dissolves between camera shots or fades
   at audio splices; that is not the house style.
2. Premiere-native effects (Lumetri, Gaussian Blur, Warp Stabilizer, synthetic
   Black Video) do **not** survive an FCP7 XML round trip. A re-exported
   reference will list them as "not translated" — that is expected and harmless,
   not a bug to chase.

## Gotchas

- **Recut after captioning means re-caption.** Polished words are stored in
  program time. If segments change afterward, `caption_status` flags the clip
  `stale` — re-polish and re-render, or captions will drift against picture.
- **Caption overlays are large** — ProRes 4444 with alpha, ~115 MB per 60s
  clip, so a 14-clip episode is ~1.6 GB. They live in `clipper/captions/` and
  Premiere links to them, so they must stay put while the project is live. They
  are regenerable, so old episodes' overlays can be deleted once exported.
- **Moving the episode folder** is fine — camera paths are relative. But the
  exported XML holds absolute paths, so re-run `export_xml` after a move.
- **Master seconds, always.** Everything in the EDL is on the original timeline,
  never program time. Program time is derived at compile.
- **Don't hand-edit files** the tools own. Use `set_edl` / `set_clip_captions`
  so validation runs.
- **Transcription can OOM on an 8 GB GPU.** `ingest` fails with `CUDA failed
  with error out of memory` when something else (Premiere, Media Encoder) holds
  VRAM. Energy envelopes are cached, so a re-run resumes at the transcription
  step. The batch size lives in `clipper/_transcribe_worker.py` (`--batch-size`,
  default 4); lower it further before suggesting the user close Premiere.
- **The MCP server holds the engine code in memory.** If you change anything
  under `clipper/`, the running `clipper-engine` tools keep the old behaviour
  until the server restarts. Verify with the CLI instead — `python -m clipper
  export-xml <project_id>` loads fresh code and takes the same path — and tell
  the user a restart is needed before the MCP tools match.

## Judgment

Propose a full set of clips and explain the picks briefly — don't ask which
moment to look at next for every clip. But do check in before the expensive or
hard-to-undo steps: starting ingest on a long episode, and exporting after the
user has reviewed the rundown.

If the transcript doesn't support the number of clips asked for, say so instead
of padding with weak moments.
