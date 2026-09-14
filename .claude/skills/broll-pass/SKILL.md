---
name: broll-pass
description: Dress finished clips with b-roll, graphics, screenshots, stat overlays and idea markers — the second pass over an EDL the clipper engine has already cut. Use when the user wants to add b-roll or footage to clips, put graphics/images/screenshots/animations on a cut, mark up a timeline with ideas, or asks for the "b-roll pass" or "graphics pass". Not for choosing or cutting clips — that is clip-episode.
---

# The b-roll and graphics pass

A second session over a cut that is already finished. The clips were chosen, the
boundaries were snapped to silence, the audio was verified and the captions were
polished — all of that happened in a `clip-episode` session that this one did not
see. What is left is what goes *on top*: footage, graphics, and notes to the
editor.

Running it separately is deliberate. Choosing moments and dressing them are
different jobs, and a fresh context reads the clips the way a viewer will rather
than the way the person who cut them remembers them.

## The one rule

**Do not change the cut.** Not the segments, not the camera cuts, not the
captions. They were decided against the audio with checks this session has not
run, and a reconstruction that looks right still costs the caption polish and
invalidates the verification.

The tools here enforce it — `add_broll`, `remove_broll`, `set_clip_broll`,
`set_clip_markers` and `attach_broll` reach `broll` and `markers` and nothing
else. **Never reach for `set_edl` in this session.** It replaces the whole
document, which is how a b-roll pass silently rewrites an edit it never watched.

If the cut genuinely looks wrong — a clip opens mid-sentence, a handover has no
camera change — **say so and stop on that clip**. Fixing it is a `clip-episode`
job, and it has to happen before the graphics go on, since moving a boundary
moves everything laid over it.

## Where this sits in the workflow

Run it **after `export_xml` is possible but before the user imports into
Premiere.** Adding b-roll changes the timeline's structure, so it needs a fresh
`export_xml` and a fresh import — unlike a caption re-render, which Premiere
picks up off disk with no re-import at all.

That matters because the user continues editing by hand after importing. Once
they have, a re-import lands a second copy of every sequence beside the work in
progress, and there is no clean way to merge. **Ask whether the XML has been
imported yet.** If it has, place markers rather than clips and say plainly that
attached b-roll will need a re-import — it is their call whether that is worth it.

## Two time bases, and this is the easy mistake

The pass reads in one and writes in the other:

- **Program time** — seconds from the start of the short, what you hear. This is
  what `get_clip_captions` returns.
- **Master time** — seconds on the original episode timeline. This is what the
  EDL stores and what `add_broll` expects.

A clip made of three segments has **three different offsets** between them, so
there is no single number to add. Guessing puts a graphic 30 seconds from where
you meant it, and nothing in the export complains.

Use `convert_clip_times(project_id, clip_id, times, to="master")`. Convert the
caption times you decided from, then pass the results to `add_broll`. A `null`
back means that moment is not in the clip — trimmed out, or past the end. That is
an answer; do not substitute a nearby value.

## Reading a clip

1. `get_edl(project_id)` — the clips, their titles, and anything already placed.
   Read each clip's `note`: the cutting pass leaves a line there when it knew a
   clip would need visual context.
2. `get_clip_captions(project_id, clip_id)` — **the best read of a clip.** The
   words are already polished, so proper nouns are spelled right, and they are
   exactly what is in the short with nothing from the episode around it.
3. `preview_edl_text(project_id)` for the rundown across all clips.
4. `export_preview(clip_id)` when you need to actually watch one. It renders
   without b-roll, so it shows what you are dressing, not the result.

Read the clip the way a viewer meets it: no prior context, sound possibly off,
three seconds to decide whether to stay.

## What you are placing

Three different things, and choosing the wrong one is the most common error.

**`kind="footage"`** — anything that *replaces* the picture. Two sources:
stock video (Envato — see "Stock footage" below) when the words describe
something worth seeing instead of a person saying it, and a **full-screen
graphic** when the information is too big or too structured for a card — a list
of conditions, a sequence of events, a side-by-side. Either costs the speaker's
face, so it has to earn that.

**`kind="overlay"`** — an alpha graphic *on top* of the picture: a screenshot
card, a stat animation, a lower third. Use it when the point is a number, a
name, a headline or a chart — something read rather than watched. Overlays and
footage compile to separate tracks and may run at the same time. **Most
overlays you can make yourself** — see "Rendering graphics" below.

**A marker** — an idea, with no file. Use it when the right move needs a human:
a title card, a decision about tone, anything you cannot specify precisely.
Markers cost nothing and are read in Premiere's timeline, so an uncertain
suggestion belongs here rather than as a placeholder nobody asked for.

A b-roll entry with no `source` is a **placeholder**: it exports as a marker
carrying its `query`, so the intent reaches the editor without Premiere nagging
about offline media. That is the right output when you know what is wanted but
the file does not exist yet — write the `query` as something searchable, not as a
description of the idea.

## What the editor does with what you leave (from a finished ep11 timeline)

Read off a finished episode, so this is what the house style actually looks like
rather than what it ought to:

- **Graphics sit above the captions** — a title card over the hook, images
  through the body, and an Essential Graphics "Watch the full video on YouTube!"
  end card.
- **Cross Dissolve with `start-black` / `end-black` alignment** on every graphic
  and image track, roughly 7-42 frames. That is how graphics enter and leave —
  nothing cuts on hard.
- **A blurred Adjustment Layer** (~138% scale) behind scaled-down imagery: the
  standard vertical background treatment for anything not full-frame.
- **Opacity at 60-95%** on overlay imagery.

Two consequences for this pass:

1. **Essential Graphics text cannot be authored from XML.** Title cards and the
   end card are `GraphicAndType` effects carrying an opaque blob — Premiere
   writes them, nothing else can. So a title card is always a **marker**, never
   a placeholder. A *rendered* overlay file is different: an alpha .mov or a PNG
   is a real clip and attaches normally.
2. **You are placing content, not transitions.** The dissolves, the blur layer
   and the opacity are applied by hand afterwards and do not survive an XML
   round trip either. Place the clip on the right frames; do not try to express
   how it should arrive. The exception is a **rendered graphic**: its entrance
   and exit are baked into the file, so it needs no dissolve — say so when you
   hand over, or the editor will add one on top of the animation.

## When a clip needs something

The standing direction from the cutting pass applies here, and this pass is
where most of it gets satisfied:

> Assume the viewer has never seen the podcast. Within the clip they must get
> what is being discussed, why it matters, and the key point.

A clip that leans on context the audio never supplies is exactly what this pass
fixes, and fixing it visually is **the user's preferred solution** — it keeps the
cut tight and the hook early instead of spending four seconds of runtime on
setup. So:

- **Establish what the audio assumes.** A company named without saying what it
  does, a story referred to as already known, a number with no scale — these are
  the highest-value placements in the pass.
- **Earliest is best.** Context that arrives after the viewer has decided to
  leave did not work. If a clip needs establishing, it needs it in the first few
  seconds.
- **A proper noun with nothing on screen is a candidate.** Most are worth taking
  — a lower third for a person, an explainer for a company, a stat for a number.
- **Leave the reaction alone.** When the value of a moment is a face — a laugh, a
  pause, someone being caught out — covering it with footage is a downgrade.

## Rhythm — hook, then keep the screen moving

The user wants these used **often**. A short that is a talking head for 50
seconds loses the scroll; the graphics are what keep it. Every clip follows the
same shape:

1. **Hook** — 0 to ~3s, always (see "Hooks" below).
2. **Then a visual beat every 5-8 seconds** until the end: a card, a
   sticker, a full-screen frame, or footage. For a 45-60s clip that is **hook +
   6-8 placements**, with **two or three full-screen frames** (a Website to
   establish the story, then wherever the audio lists, compares, quotes or
   sequences anything). EP19's first import at hook + 1-3 cards read as empty
   to the user; this density is the corrected bar.
3. **The first beat lands soon after the hook** — often the lower third for
   whoever is speaking, or the context the hook raised.

What still holds: one new thing on screen at a time (don't open a card while
another is up unless one is footage underneath), don't cover a reaction, and
every placement says something the viewer benefits from reading. Density comes
from finding more of those, not from decoration — an empty stretch usually has
a number, a name, a claim or a list in it that deserves a card.

## Where things go on the frame

The frame has three reserved zones, and everything drawn stays out of them:

- **The top 20%: logo and sponsor overlay.** The user adds these in Premiere —
  transparent and small, but a graphic under them reads as clutter. The
  templates already hang every card, hook and full-screen block from just below
  it (21.5%), so this is automatic; just never add something that reaches up.
- **The caption band, ~64-80%.** Positioned by hand per clip. Cards and hooks
  stand above it; full-screen frames leave it as plain background.
- **The outer ~9% of each side.** On a tall phone (19.5:9, 20:9) Reels, TikTok
  and Shorts scale a 9:16 video to fill the height and crop the left and right
  edges — ~130 px each side at 1440 wide. `SAFE.side`/`SAFE_W` in
  `graphics/src/theme.tsx` keep every card, hook and full-screen block inside
  the middle 880 of 1080 design units; a new template must size to them too.

Cards default to `position: "bottom"` — standing just above the caption band,
over the chest. **The user repositions cards in Premiere themselves**, per shot,
so don't spend re-renders or passes chasing position: leave the default unless a
card would sit squarely on a face in the check image. The hook stays at the top
(the title slot), and full-screen content centres itself between the two zones.

## Placement craft

- **Never cover the hook.** The first seconds establish who is speaking.
- **Land it on the word, not after it.** Start slightly before the phrase it
  illustrates; arriving late reads as a mistake.
- **Fit inside a segment.** B-roll must sit inside a kept range — the validator
  rejects anything else, since the space between segments does not exist in the
  finished clip.
- **The captions are already on top.** They render as a strip the user positions
  by hand in Premiere, so do not place an overlay where it will fight them
  without saying so in the entry's `query` or a marker.

## Placing it

```
add_broll(project_id, clip_id, start, end, kind="footage"|"overlay",
          query="what is wanted", source=None)
```

`start`/`end` in **master seconds** (convert first). Leave `source` empty for a
placeholder. Ids are generated (`b1`, `b2`, …) unless you pass `broll_id`.

- `set_clip_broll(project_id, clip_id, broll)` lays out a whole clip at once —
  better than a run of `add_broll` calls when planning a clip end to end.
- `set_clip_markers(project_id, clip_id, markers)` — `{at, name, comment}`, `at`
  in master seconds. Replaces the clip's markers, so read them first.
- `attach_broll(project_id, clip_id, broll_id, source_path, source_in)` fills a
  placeholder once a file exists — the seam the footage and animation passes
  deliver through.
- `remove_broll(project_id, clip_id, broll_id)` to undo one.

Every one of these validates before saving and **a rejected edit is not
written**. Two entries of the same kind may not overlap — one track cannot carry
both — while an overlay over footage is fine and is the point of the split.

## Rendering graphics

Overlays don't have to stay placeholders. `graphics/` at the repo root is a
Remotion project with a small set of house templates, and `render_graphics`
turns an overlay entry into a finished alpha ProRes file and attaches it in one
call. `list_graphic_templates()` gives the current set and their props. There
are two families, and each renders onto its own kind of entry:

**Cards** — `kind="overlay"`, sit over the speaker, who stays on screen:

| Template | For |
|---|---|
| `LowerThird` | who someone is — name + role |
| `Headline` | a news story the audio treats as known — source, headline, date |
| `Stat` | one number that needs scale — counts up to it |
| `Explainer` | "what is X" — a title and up to three facts |
| `ImageCard` | a screenshot or image in a card, slow push-in |
| `Bars` | 2-5 values being compared |
| `Punch` | the line a clip turns on, as white/yellow stickers popping in — heard and read |
| `Ring` | a percentage as a filling ring — 72% of people, under 5% of spend |
| `Checklist` | 2-4 items ticking ✓ or crossing ✗ — what something has and lacks |

**Full screen** — `kind="footage"`, replace the picture for their duration:

| Template | For |
|---|---|
| `Breakdown` | 2-6 numbered points — conditions, reasons, steps |
| `Timeline` | 2-6 dated events — how something unfolded |
| `Compare` | A vs B in two columns, with a one-line verdict |
| `Chart` | 2-8 values as big bars |
| `Quote` | what someone else said or wrote, attributed |
| `Scroll` | a tall screenshot — article, filing, thread — scrolling past |
| `Website` | the real article in a browser window: the phrase highlighted, a push-in on it, a takeaway sticker |
| `BigNumber` | the number the clip is about, at full size — $177M, 12 lenders |
| `Flow` | 2-5 boxes joined by drawing arrows — how money or data moves |
| `NewsStack` | 2-4 headline cards piling up — a pattern across stories |
| `Chat` | an AI chat thread, typing then answering — what asking the agent looks like |

**Website cards.** The strongest establishing beat: the viewer sees the story is
real. Capture the page in phone layout, then build the props:

```
python -m longform.shoot "<ep>/longform/shots/mobile/<name>.png" <url> --mobile --height 3400 --mark "exact phrase"
python -m clipper.webcard <that png> --seconds 6 --mark 0:marker@0.12 --caption "*$100M* into Kraken"
```

`--mobile` matters: a desktop page shrunk into the 880-unit window is
unreadable; the phone layout's column reads at full width. `webcard` crops the
capture, plans the scroll so each phrase is in view before it draws, sets the
push-in, and prints props for `render_graphics` with template `Website`. A
phrase the shoot reports as not found, or whose `y` in the json is past 1.0
(below the capture), can't be marked — pick another sentence. Many establishing
beats in EP19 were a Website right after the hook (3.1s on).

**Card or full screen?** A card when the point fits in about a dozen words and
the speaker's delivery still matters. Full screen when the viewer has to *read*
something the audio is enumerating — three conditions said aloud in eight
seconds are lost by ear and kept on screen. Full-screen frames centre their
content between the logo zone and the caption band and leave both as plain
background, so the overlay and the captions stay readable over them; the
speaker keeps talking underneath, which is the point. Give them time: about a
second per point plus two, so a three-point `Breakdown` wants 5-6s. One per
clip is the norm; two works in a longer clip if they are well apart and the
face gets real time in between.

The flow:

1. `add_broll(..., kind="overlay" | "footage", query="...")` — the entry decides
   *when* and for *how long*. The file is rendered to its exact frame count.
2. `render_graphics(project_id, items=[{clip_id, broll_id, template, props}, ...])`
   — **batch every graphic for the episode into one call**; the renderer bundles
   once per call, and that is most of the cost (a batch of two took ~30s).
   Everything is checked before anything renders.
3. **Read every `check` PNG it returns.** Each is the graphic composited over the
   camera frame it will actually sit on. This is the only place you will see a
   card covering a face, a headline wrapping to four lines, or a lower third on
   top of the speaker's own name tag. Fix with `position` ("top" | "center" |
   "bottom") or shorter text, and re-render.

What the checks from the first real run taught:

- **Position is the editor's call** — cards land low by default and the user
  moves them per shot. What the checks are for is content: an overflowing line,
  a wrong number, a card that says too much.
- **Length is reading time.** About one second per four words on the card plus a
  second for the entrance; under 2.5s nothing gets read, over 5s it is wallpaper.
- **Words on a card should be fewer than the words being spoken over it.** It
  reinforces the audio; it is not a second script.
- Write props in the language of the clip. Montserrat covers Uzbek Latin
  (oʻ, gʻ) and Cyrillic.

**Re-rendering.** Moving or resizing a rendered entry keeps the old file, which
Premiere would then trim or leave short — every graphics edit reports this as a
warning. `render_graphics` with just `{clip_id, broll_id}` re-renders from the
template and props recorded on the entry.

**Images** (`ImageCard.image`, `Headline.logo`) take an absolute path on disk.
When the image doesn't exist yet — a screenshot of an article, a tweet — leave
the overlay as a placeholder whose `query` says exactly what to capture, and
render once the user drops the file in.

**A new kind of graphic** means a new template: a component in
`graphics/src/templates/`, registered in `templates/index.ts` and described in
`graphics/templates.json` (the engine lists and validates from that file).
Build it on `Card`/`Band`/`useEnterExit` (cards) or `FullFrame`/`useStagger`
(full screen) from `src/theme.tsx` so it matches the rest, and set `"frame"` in
the manifest to `"card"` or `"full"`. Worth it when a graphic will recur across
episodes; a one-off is better as a marker for the editor.

## Hooks — every clip opens with one

The first 2-3 seconds of each short carry a hook title: the line a scrolling
viewer reads before deciding to stay. The user edits these shorts themselves and
used to build this card by hand in Essential Graphics on every clip — so it is
now part of this pass, **one per clip, done first**, before anything else is
placed.

```
set_clip_hook(project_id, clip_id, text, seconds=3.0)
render_hooks(project_id)          # all clips in one batch
```

It is not a b-roll entry: it is anchored to the start of the short and runs
across the first cuts, which a master-time range cannot express. It renders onto
its own track above the cards and below the captions.

Writing it:

- **7 words or fewer, the number or the tension first.** "$177M raised. Still
  shut down." — not the clip's title, which is written for the upload and runs
  15 words.
- **One phrase in `*asterisks*`** goes on the yellow highlighter and lands last.
  Pick the words that make it a hook — the number, the twist, the verdict.
- It must be **true to the clip** and land in the clip's own audio. A hook the
  short doesn't pay off is clickbait, and the user's audience is people who care
  about fintech news.
- The wrap balances itself; a newline in `text` forces a break when it still
  splits a thought badly.
- **Propose all the hook lines to the user as a list before rendering.** They
  are the headline of each clip, and cheap to change as text, not as files.

Then **no card starts under it** — begin the clip's first overlay after the hook
has finished (`hook_conflicts` warns otherwise). An early `Headline` or
`LowerThird` that the clip needs right away moves to start at the hook's end.

## Stock footage (Envato)

The user has an Envato Elements subscription. The split is fixed: **you find
and shortlist, the user clicks Download, you attach.** Envato's terms forbid
downloading through automated tools, and each download licenses the item to a
project on the user's account — so the click is theirs. **Never click Download,
never answer the licence dialog, never sign in.** Everything either side of the
click is yours.

1. **Place the placeholders first.** `add_broll(..., kind="footage",
   query="...")` for each slot, so the entries — and their lengths — exist.
2. **Search in the user's Chrome** (the claude-in-chrome tools; it has their
   Envato session). Search URLs take the query as a hyphenated path, with a
   vertical filter:
   `https://elements.envato.com/stock-video/phone-payment-terminal/orientation-vertical`
   Vertical first — it fills the frame with nothing cropped. Fall back to
   horizontal only when nothing vertical fits; it will be scaled to fill, which
   crops the sides away.
3. **Choose on the item page, not the thumbnail.** It must be longer than the
   entry by a second or two (the file is used from 1s in), and 29.97 or 30 fps
   is best — anything else is conformed on the way in, which works but costs a
   re-encode. Look at the preview: stock that is obviously stock (handshakes,
   people pointing at glass screens) is worse than the speaker's face.
4. **Record the shortlist**: `set_broll_candidates(project_id, clip_id,
   broll_id, [{url, title, note}])`, best first. It feeds the Premiere marker
   and lets `collect_broll` match downloads back.
5. **Leave one tab open per slot — the pick — in slot order**, and hand over a
   numbered list: tab, clip and entry, what it covers, and the project name to
   license it to (the episode, e.g. "OTG EP18"). Suggest the MP4 download at
   4K when offered — ProRes 4K stock is gigabytes a shot.
6. **When the user says they're done**: `collect_broll(project_id)` lists what
   arrived in Downloads with a three-frame `sheet` per file and a suggested
   pairing. **Read every sheet** — download names rarely match the item, and
   pairings marked "download order" are guesses. Then `collect_broll(project_id,
   assign=[{file, clip_id, broll_id, source_in?}])`.

`collect_broll` moves each file into the episode's `broll/` folder (tell the
user — it leaves their Downloads), conforms the frame rate if needed, records
the size so the export scales it to fill 9:16, and attaches it. Anything shorter
than its entry comes back as a note; shorten the entry or pick another shot.

## Finishing

`export_xml(project_id)` — one XML, every clip a sequence, and the tracks arrive
bottom to top as: camera stack, b-roll footage, overlays, captions.

Then show the user what was placed and why, per clip. Placeholders and markers
are instructions to a human, so they have to read as instructions — `"stripe
office exterior, 3s"` is useful and `"visual for this bit"` is not.

## Gotchas

- **Master seconds, always**, in everything written to the EDL. Convert first.
- **B-roll placeholders do not render in `export_preview`** — there is no
  footage yet. Rendered graphics and attached footage do.
- **Footage is scaled to cover the vertical frame** (the sides of a 16:9 shot
  crop). The whole frame is still in the file, so the editor can slide it
  across in Premiere; say so when a horizontal shot's subject is off-centre.
- **Rendered graphics are ~40 MB per 3 seconds** at 1440x2560 (ProRes 4444, like
  the captions). They live in the project's `graphics/` folder next to `captions/`.
- **First render on a new machine downloads a headless Chrome** (~110 MB, once)
  and needs `npm install` in `graphics/`. `render_graphics` says so if missing.
- **Re-exporting after the user has imported** duplicates sequences in their
  project. Ask first.
- **`set_edl` is not for this session.** If something seems to need it, that is
  the signal to hand back to `clip-episode`, not to reach for it.
- **The MCP server holds the engine code in memory.** If `clipper/` changed since
  the server started, the tools still run the old code — the CLI (`python -m
  clipper ...`) loads fresh.

## Judgment

Propose a full plan per clip and explain the picks briefly rather than asking
about each placement. Aim for the rhythm above — **hook, then a beat every 6-10
seconds** — because the user has asked for more graphics, not fewer. Every beat
still has to earn its place by saying something; when a stretch genuinely has
nothing worth putting on screen, leave it on the face and say why.
