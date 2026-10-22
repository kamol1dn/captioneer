# shows/

The client tier. Each show (a client's channel) gets a folder here with
everything that makes its output look like *that* show: caption presets,
graphics, fonts, transitions, long-form layouts, and the written rules for
editing it. The engine repo ignores everything in this folder except this
README. Each show is normally its own private git repo.

```
shows/
  _shared/fonts/          licensed faces several shows use
    graphics/             synced into graphics/public/fonts for Remotion
    <family>/             offered to the caption renderer
  <id>/
    show.json             reel dressing: graphics family, whooshes, outro (clipper/show.py)
    captions.json         {"group": "English", "presets": {name: CaptionStyle dict}}
    templates.json        {"templates": {...}}: the show's graphic templates
    graphics/index.ts     their Remotion components: export TEMPLATES (and COMPOSITIONS)
    fonts/                the show's own faces, laid out like _shared/fonts
    longform.json         long-form pane layouts (longform/, clipper/panels.py)
    RULES.md              how this show is edited; read before working on it
```

Every file is optional. A show with no `graphics/` uses the engine's default
template family (`"graphics": "default"` in show.json).

Per-episode files (clipper projects, Skleyka scenes, long-form plans, renders)
live next to the episode's Premiere project, not here.

Set `CAPTIONEER_SHOWS` to keep this folder somewhere else.
