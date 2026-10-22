# Long-form episode tooling

Graphics for the panes of a show's long-form layouts, and text layers retitled
across the timeline, for Premiere, all from JSON plans.

```
longform/
  shoot.py, reshoot.py   page screenshots with phrase marks (Playwright + installed Chrome)
  find.py                phrase -> timestamp from word timings
  transcribe.py          WhisperX word timings, or the YouTube upload's captions
  templates/             starting points for a plan and a text-layer spec
```

A show's layout panes, tracks, bins and text-layer limits are its
`shows/<id>/longform.json` (the client tier, see `shows/README.md`). Plans,
text specs and any per-episode build scripts live with the episode, next to
its Premiere project (`<episode>/longform/`), along with `shots/`, `panels/`
and word timings. Nothing episode-specific goes in this folder.

## An episode

1. **Timings**: `python -m longform.transcribe main.mp4 OUT` (and `--youtube URL OUT`),
   then `python -m longform.find OUT/whisperx.words.json "phrase" ...`.
2. **Screenshots**: `python -m longform.shoot shots/name.png URL --width 1440 --height 2400 --mark "exact sentence"`.
   Overlays are hidden, never clicked. Marks are located on the page and saved to `name.json`.
3. **Plan**: copy `templates/plan.example.json` into `<episode>/longform/`, one item per graphic; its `show` names the layouts.
4. **Preview**: `python -m clipper.panels stills plan.json` renders one frame each and
   composites it into the 4K layout (`panels/checks/`). Read them.
5. **Render and XML**: `python -m clipper.panels render plan.json`, then
   `python -m clipper.panels xml plan_a.json plan_b.json`, which gives one binned XML with
   the render on V1 and panels on their tracks.
6. **Text layers**: export the sequence to XML from Premiere, copy
   `templates/text_layer.example.json`, then `python -m clipper.headlines spec.json`.
   Each text must fit in the template clip's text (same byte count; `longform.json` has the limits).

## A new show

Add `shows/<show>/longform.json`: for each layout, the PNG, the transparent `pane` as
`[x, y, w, h]` (measure it: the alpha==0 rectangle), a render `size` a few px larger and even,
the `track`, and a `bin`. Then set `"show": "<show>"` in its plans.
