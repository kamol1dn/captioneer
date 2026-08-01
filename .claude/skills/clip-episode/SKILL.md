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

## Two ways in: flat exports, or the episode timeline

**Flat exports** (above) are the original route: one vertical video per angle,
each covering the same range. Simple, but a two-hour episode means four ~14 GB
renders before anything can start.

**From the timeline** skips those entirely. The user exports *only* the audio
they want transcribed, plus the episode sequence as FCP7 XML (Premiere: File >
Export > Final Cut Pro XML). Each angle then takes its picture from a V-track of
that timeline. Ask which route this episode is using if it isn't obvious — a
`.xml` beside the media is the tell.

For the timeline route:

1. **`inspect_master_xml(xml_path)`** to list sequences, then
   `inspect_master_xml(xml_path, sequence)` for the tracks. Read off which
   V-track is which angle from the clipitem names, sources and coverage. Ask the
   user to confirm the mapping — the track names can be misleading (on the
   Rahimov episode, V3's clipitems read `otabek 2` while the nest they point at
   is named `rahimovv2`), and a swap here silently gives every clip the wrong
   secondary angle.
2. **`create_project(..., master_xml=..., master_sequence=...)`** with
   `{"id": "H1", "source_track": "V1", "speaker": "host"}` instead of a `path`.
   The transcription source (the mix) is still a normal `path` camera and stays
   the `primary_audio_camera`.
3. **Set the EDL's audio mode to `source_tracks`**, which reproduces the
   timeline's own audio bed under the cut — one reel track per master A-track,
   **including each clip's mute state**. Do not pin a single source: what the
   editor mixed is the *sum* of those tracks, and on a real episode the enhanced
   mix alone covered 17% of the timeline while the camera scratch tracks were
   muted wholesale. The exported mix is still what `verify_clip_audio` and
   `export_preview` listen to, so that check is unchanged.

**Premiere drops multicam items on FCP XML export — it does not flatten them.**
A timeline of multicam clips exports with completely empty video tracks and one
line in the translation-results log saying so. The fix is on the Premiere side:
flatten the multicams, or stack the angles as plain clips. `inspect_master_xml`
and `create_project` both raise with that explanation rather than producing reels
with no picture.

**Crossfades hide clips from a naive reader.** Premiere writes `-1` for whichever
edge of a clipitem a transition defines, and the real value is the other edge
plus the source length. Reading `-1` as "no position" drops *both halves of every
crossfade* — on one real lav track that was 112 of 333 clips, which plays back as
audio cutting in and out at random. The reader recovers those edges and
butt-joins the resulting overlap (the dissolve becomes a hard cut at its own
start); only a clip with `-1` at *both* ends is genuinely unplaceable.

Two things that survive the round trip and are worth knowing: **nested sequences**
(the nest carries its own frame size, and a reframe is often split between an
inner scale and an outer offset — so nests are passed through whole rather than
resolved down to their camera file), and **Basic Motion**, which is where
Premiere bakes the vertical crop. Auto Reframe itself does not translate; what
lands is a single static value, so an angle with *animated* reframing arrives
frozen. Worth one visual check per episode, not per clip.

## Which show is this?

There are two, and they differ in exactly two settings. **Ask once, at the
start, if the user hasn't said** — then pass both to `create_project` and never
think about them again; every later tool reads them off the project.

| Show | `language` | `caption_preset` |
|------|-----------|------------------|
| **Gashtak** (Uzbek) | `"uz"` | `"gashtak_2"` |
| **OTG** (English) | `"en"` | `"otg_cyan"` |

`language="uz"` is not cosmetic. It routes transcription to the Kotib Uzbek
model with MMS forced alignment instead of WhisperX, selects the Uzbek section
of `prompts.txt` (the `o‘`/`g‘` orthography and Russian-code-switch rules), and
makes `verify_clip_audio` listen in Uzbek. Leave it unset on an Uzbek episode
and everything still "works" — badly, and silently: a mediocre auto-detected
transcript, English caption rules applied to Uzbek text, and a verification
report that is pure noise.

**Working on a project created earlier?** Check `get_project` — projects made
before these were tracked have `language: ""` and no preset, so they'd
auto-detect and render with the default preset. Fix with
`set_project_defaults(project_id, language, caption_preset)` rather than
re-creating or hand-editing `project.json`. It doesn't re-transcribe: if the
transcript itself was made under the wrong language, re-run `ingest`.

Nothing else in the pipeline is language-specific — the same defaults below
apply to both shows. One caveat: `check_segments`' dangling-word and filler
heuristics are English word lists, so on Gashtak only its punctuation and gap
checks fire. It says so in its own output; read the joins yourself there.

## House defaults

Don't ask about these; just do them.

- **An enhanced/combined mix** (`enhanced audio.mp3`) usually sits beside the
  camera exports. Register it as an extra source and make it
  `primary_audio_camera` — it is the audio the viewer hears. It is audio-only,
  so it is never an angle and never a diarization target.
- **Ingest with `diarize=True`.** Each subject has their own mic, so per-speaker
  transcription gives attributed lines and survives crosstalk. The mix stays
  pinned as the audio; the camera mics supply the words.
- **Run the two checks before captioning**: `check_segments` (does it read?) then
  `verify_clip_audio` (does it sound right?). Both catch defects that are
  invisible in the EDL, and fixing a boundary after captioning costs the polish.
- **A `.vtt` from a previous captioneer run** may exist one folder up. It is the
  same audio on the same timeline, so it's an excellent cross-reference for
  exact word times and for ASR name errors — but never hand-write it into files
  the engine owns; let ingest produce its own transcript.

## Pipeline

**1. Create.** `create_project(name, cameras=[{id, path, label, speaker}],
primary_audio_camera, language, caption_preset)`

On the timeline route this is
`create_project(..., master_xml=..., master_sequence=...)` with
`{id, source_track, label, speaker}` for each angle — see the section above.

`language` and `caption_preset` come from the show table above and are stored on
the project — ingest, captions, rendering and verification all default to them,
so they're passed here and nowhere else. The call warns if `language` is empty.

**If any subject has more than one camera, set `speaker` on each of that
subject's cameras** (`{"id": "A2", "speaker": "host", ...}`) — otherwise the
engine treats the second angle as a second person. Ask if the camera labels are
ambiguous; two cameras named `host wide` and `host tight` are one speaker. Omit
`speaker` entirely for the normal one-camera-per-subject setup; it defaults to
the camera's own id.

Camera ids are short (`A`, `B`, `C`, or `A1`/`A2` for two angles on one person).
Labels describe the *shot* (`host tight`, `host wide`, `guest`); `speaker` is
what says they're the same person. **Read the warnings it returns.** Mismatched
frame rates, durations differing by >0.5s, or a non-zero start timecode all mean
the exports may not share a common t=0 — surface these to the user before going
further, because every downstream cut inherits the error. A multi-angle speaker
also warns, naming the mic that will be transcribed for that person; check it's
the good one and pass `transcribe: true` on a different angle if not.

**2. Ingest.** `ingest(project_id, model_size="large-v3", diarize=True)` then
poll `ingest_status`. Computes a loudness envelope for every camera and
transcribes at word level. Minutes on an hour of audio — tell the user it's
running rather than sitting silent. It uses the project's language; pass
`language=` only to correct a project created without one (it's saved back).

**Prefer `diarize=True` when each camera carries its own subject's mic** (the
normal two-track setup here). It transcribes one mic per speaker and merges them
into one speaker-labelled timeline, so `get_transcript` returns `A:` / `B:` per
line instead of an energy guess, and two people talking at once survive as two
lines. It costs one Whisper pass per **speaker** and needs at least two of them —
two angles on one person are one speaker, and the extra angle is transcribed by
nobody. `ingest_status` reports the choice under `diarization.mics`.

Every mic hears the whole room, so each raw transcript also contains the other
speaker 20-40 dB down. That bleed is rejected per word against the energy
envelopes; `ingest_status` reports what survived under `diarization`, keyed by
speaker. **Read that report** — a speaker whose transcript is almost entirely
`dropped_as_bleed` means the mics aren't as isolated as assumed, and the labels
can't be trusted.

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

**Those labels are speaker ids, and `camera_cuts` wants camera ids.** They're the
same string in the usual setup, where a camera is its own speaker — `A:` means cut
to `A`. When cameras are grouped they differ: the transcript says `host:` and the
energy line reads `host88 guest09`, but a cut must name one of that person's
cameras. `get_project`'s `speakers` map is the translation, and the first camera
listed for a person is their main angle. Writing `"camera": "host"` is rejected by
`set_edl` as an unknown camera — that's the validator catching it, not a bug.

Either way, **check every handover**. Missing a switch is the easiest mistake to
make on a long episode: scan each clip's lines for a speaker change and confirm
a `camera_cut` sits at it. A clip that never switches is fine when one person
narrates throughout — but verify that, don't assume it.

- Cut to whoever is speaking. A wide gap (`A88 B09`) means confident; a narrow
  one (`A51 B47`) means crosstalk — hold the current angle rather than flipping.
- Don't switch faster than ~2s. Sub-0.5s shots get flagged as glitches.
- A cut on the *incoming* speaker's first word reads better than one a beat late.
- Use `get_energy(start, end)` for a finer look when the utterance average is
  ambiguous. It reports per camera; `by_speaker=True` asks who is talking
  instead of which angle is hottest.

### When a speaker has two cameras

`get_project` returns `speakers` as `{person: [camera ids]}`. A person with two
entries has a second angle on the same voice — a tight and a wide, say — and it
exists to hide jump cuts.

A jump cut is what a *same-camera* join with a gap in the source leaves behind:
filler removed from one continuous take, so the head teleports between identical
framings. Two ways to hide it, and they are not interchangeable:

- **The punch** (automatic, nothing to do): the compiler alternates a ~4% zoom
  across those joins so consecutive framings differ. Right for rapid filler
  trims — a half-second of "um" removed, several times in a row.
- **The second angle** (a `camera_cut` you write): switch to that person's other
  camera at the join. Right for a bigger removal or a topic beat, where the
  reframe reads as intentional. An angle change resets the punch to 100%, since a
  different camera already hides the join — so don't try to stack them.

Keep it occasional. **At most one same-speaker angle change every ~8–10s**; more
often and it reads as a camera hunting for focus rather than an edit. If you
find yourself wanting one at every join, the punch is already handling those —
leave them alone.

Say which in `why`: `"hide jump cut — 6s tangent removed"` reads very differently
from `"handover to guest"`, and the user audits that field.

Grouping matters upstream too: two angles on one person must share a `speaker` at
`create_project`, or a diarized ingest transcribes both mics and every line that
person says lands in the master timeline **twice**.

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
but do run it. On Gashtak it re-transcribes through Kotib (the project's
language again), which ignores `model_size` and so costs a full Uzbek pass per
clip — slower, but the alternative is a diff against a transcript in the wrong
language, which is worthless. Both defects it was built for shipped in ep12 and both read
perfectly in the EDL.

**7. Save the EDL.** `set_edl(project_id, edl)` — one EDL holds all the clips.

- `segments` — kept ranges in master seconds; the clip is their concatenation.
- `camera_cuts` — `{at, camera, why}` over the master timeline; the camera at
  time t is the last cut at or before t. Independent of segments, so you can
  retime one without redoing the other. `camera` is a **camera id** (`A2`), never
  a speaker name (`host`). Fill in `why` — it's how the user audits your
  reasoning.
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
viewer notices. Recurring offenders on OTG: **Otabek** (not "Otome"),
**Andreessen Horowitz** (not "Anderson"), **Satya Nadella** *backing* (not
"baking"), **Anthropic** (not "Tropic"/"Antropic"), **Wise** (the ASR writes
"VISA" and "Y" all through the Wise story), **Nik Storonski**, **Genius Act**,
and "earnings per **share**". If a figure looks mis-transcribed, leave it out of
the caption rather than burning in a wrong number.

Polish every clip first, then render them all at once with
`render_all_captions(project_id)` — the project's preset is used automatically
(gashtak_2 if it somehow has none), so pass `preset=` only to override for a
one-off; `list_caption_presets` shows what else exists. One call instead of
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
  toggle can never shift the edit or desync captions. This is also the cheap way
  to try a second angle on one speaker: toggle it, watch it, keep it or don't.
- **One video track per camera, then b-roll, then captions on top.** The layout
  above is a two-camera example, not fixed: the camera stack grows with the
  number of cameras and captions stay topmost, so three cameras push the caption
  track up accordingly. Only cameras that carry picture are stacked; an
  audio-only mix never gets a video track.
- **One source is one audio track.** A stereo file has a single source audio
  track carrying two channels — emitting one clipitem per channel puts the same
  stereo pair on two tracks, which reads as duplicated audio.
- **Jump cuts are punched automatically.** Dropping filler out of one continuous
  take leaves two shots with identical framing, so the speaker's head teleports.
  The compiler alternates a small zoom (`style.jump_cut_punch`, default 4%)
  across same-camera cuts that have a real gap in the source, which makes the
  cut read as a deliberate reframe. Contiguous joins and angle changes are left
  at 100% — a different camera already hides the join. Set it to 0 to disable,
  or raise it if the user wants the effect more visible. Where a speaker has a
  second camera you can hide the bigger joins with an angle change instead — see
  "When a speaker has two cameras" above.
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
