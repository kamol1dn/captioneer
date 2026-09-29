import React from "react";
import { useVideoConfig } from "remotion";
import { Band, Card, Position, Rule, fitSize, reveal, useCue, useUnit } from "../theme";

export type ExplainerProps = { title: string; lines: string[]; position?: Position };

const Line: React.FC<{ text: string; start: number; size: number }> = ({ text, start, size }) => {
  const u = useUnit();
  const p = useCue(start, 10);
  return (
    <div style={reveal(p, u)}>
      <Rule />
      <div style={{ fontWeight: 400, fontSize: size * u, lineHeight: 1.25, padding: `${16 * u}px 0` }}>{text}</div>
    </div>
  );
};

// "What is X": a title and up to three facts, each under a hairline, revealed
// one by one across the first third of the graphic.
export const Explainer: React.FC<ExplainerProps> = ({ title, lines, position = "bottom" }) => {
  const u = useUnit();
  const { fps, durationInFrames } = useVideoConfig();
  const shown = lines.slice(0, 3);
  const window = Math.max(fps * 0.4, durationInFrames / 3);
  const step = shown.length > 1 ? window / shown.length : 0;
  const longest = shown.reduce((m, l) => Math.max(m, l.length), 0);
  const lineSize = fitSize("x".repeat(longest), 42, 30, 32);
  return (
    <Band position={position}>
      <Card width={920} padding={40} style={{ paddingBottom: 24 * u }}>
        <div style={{ fontWeight: 700, fontSize: fitSize(title, 58, 22, 42) * u, lineHeight: 1.12, marginBottom: 18 * u }}>
          {title}
        </div>
        {shown.map((line, i) => (
          <Line key={i} text={line} start={8 + i * step} size={lineSize} />
        ))}
      </Card>
    </Band>
  );
};
