# Gashtak lower thirds — design proposal

Three small lower-third variants, built in React/SVG and rendered by the existing Remotion renderer. No generated imagery or external artwork. The book symbol is generic, not an edition cover.

- Book: abstract book, warm label, white title and author.
- Term: just the word and definition; no icon or category label.
- Question: pale blue paper-plane mark and source label above white question text.

All variants use the licensed Helvetica regular/bold files already in `assets-fonts/helvetica`. The preview job script stages them under ignored `_assets`; Remotion waits for font loading. There are no card backgrounds, borders or accent bars. Subtle dark text shadows support readability over footage.

`graphics/src/gashtak/LowerThird.tsx` contains the templates and motion. `GashtakLowerThird` renders a transparent frame; `GashtakPreview` adds the supplied podcast still solely for review. Both are registered separately from the shorts template catalogue. Geometry targets 16:9 and scales from 1920 x 1080. Entrance: 0.4 seconds; exit: 0.3 seconds. The bottom-left watermark area is left clear.

## Reproduce the proposal

Stage the supplied reference frame as `graphics/public/_assets/gashtak-reference.jpg`, then from the repository root:

```powershell
venv/Scripts/python.exe longform/gashtak/preview_jobs.py
node graphics/render.mjs data/outputs/gashtak-preview/jobs.json
venv/Scripts/python.exe longform/gashtak/composite_previews.py
```

The jobs render three 1080p alpha PNGs and a 15-second 720p motion preview. The same `GashtakLowerThird` composition accepts the existing renderer's ProRes 4444 output: remove `stillOnly`, use a `.mov` output, and omit `codec` (the renderer defaults to alpha ProRes 4444).

## Proposed episode workflow after design review

1. Turn the cue sheet into a simple JSON list with `id`, `start`, `duration`, `kind`, `title`, optional `detail` and `label`.
2. Match size, frame rate and timeline origin to the editing sequence, then review reading durations and overlapping cues.
3. Render one full-frame transparent ProRes 4444 MOV per cue, with entrance and exit baked in.
4. Export an overlay-only Premiere-compatible XML, with gaps preserving cue positions, and bins by type. Import and place the graphics above the podcast at the matching sequence origin.

Existing `clipper/panels.py` demonstrates the binned XMEML structure and `clipper/xmeml/pathurl.py` handles media URLs. Its OTG layout, footage, tracks and fixed rate should not be carried into the simpler Gashtak exporter. XML export is not implemented in this design proposal.

## Source status

Example text is taken from the supplied `lower-third-cues.md`. Its timing anchors and text are draft ASR-derived material, not audio-verified edits. The Telegram label is shown as a design example; original message attribution remains unverified. No sender name or real book cover is invented. This proposal does not fetch the source links, verify the transcript or commit the entire episode to these timings.
