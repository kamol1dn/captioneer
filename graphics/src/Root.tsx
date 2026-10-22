import React from "react";
import { Composition } from "remotion";
import manifest from "../templates.json";
import { TEMPLATES } from "./templates";
import { SHOW_COMPOSITIONS } from "./_shows";

// Defaults are only for the studio. A real render overrides size, rate and
// length from the clip's sequence and the b-roll entry it fills.
export const Root: React.FC = () => (
  <>
    {SHOW_COMPOSITIONS.map((c) => <Composition key={c.id} {...c} />)}
    {Object.entries(TEMPLATES).map(([id, component]) => (
      <Composition
        key={id}
        id={id}
        component={component}
        width={1080}
        height={1920}
        fps={30}
        durationInFrames={120}
        defaultProps={(manifest.templates as Record<string, { example: Record<string, unknown> }>)[id]?.example ?? {}}
      />
    ))}
  </>
);

