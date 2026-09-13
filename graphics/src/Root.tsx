import React from "react";
import { Composition } from "remotion";
import manifest from "../templates.json";
import { TEMPLATES } from "./templates";

// Defaults are only for the studio. A real render overrides size, rate and
// length from the clip's sequence and the b-roll entry it fills.
export const Root: React.FC = () => (
  <>
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
