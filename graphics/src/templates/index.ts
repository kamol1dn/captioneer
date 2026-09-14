import React from "react";
import { Bars } from "./Bars";
import { Explainer } from "./Explainer";
import { Breakdown, Chart, Compare, Quote, Scroll, Timeline } from "./full";
import { Headline } from "./Headline";
import { Hook } from "./Hook";
import { ImageCard } from "./ImageCard";
import { LowerThird } from "./LowerThird";
import { Stat } from "./Stat";
import { PANEL_TEMPLATES } from "../panel/templates";

// Names must match the keys of templates.json — that file is what the clipper
// engine lists and validates against; this is only where the components live.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const TEMPLATES: Record<string, React.FC<any>> = {
  LowerThird,
  Headline,
  Stat,
  Explainer,
  ImageCard,
  Bars,
  // Full-screen: these replace the picture, and go on footage entries.
  Breakdown,
  Timeline,
  Compare,
  Chart,
  Quote,
  Scroll,
  // Title: the clip's opening hook, on its own track at the very start.
  Hook,
  // Long-form panels: opaque, sized to a pane of the long-form layouts. Not in
  // templates.json: the clipper doesn't place them, render.mjs jobs do.
  ...PANEL_TEMPLATES,
};
