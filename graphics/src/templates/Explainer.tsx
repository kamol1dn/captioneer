import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Band, COLORS, Card, Position, fitSize, useUnit } from "../theme";

export type ExplainerProps = { title: string; lines: string[]; position?: Position };

export const Explainer: React.FC<ExplainerProps> = ({ title, lines, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const shown = lines.slice(0, 3);
  // Stagger the lines across the first third of the graphic, so the last one is
  // on screen for most of it however long the entry is.
  const window = Math.max(fps * 0.4, durationInFrames / 3);
  const step = shown.length > 1 ? window / shown.length : 0;
  const longest = shown.reduce((m, l) => Math.max(m, l.length), 0);
  const lineSize = fitSize("x".repeat(longest), 44, 30, 32);
  return (
    <Band position={position}>
      <Card width={920}>
        <div style={{ fontWeight: 800, fontSize: fitSize(title, 62, 22, 44) * u, lineHeight: 1.15 }}>{title}</div>
        <div style={{ marginTop: 26 * u, display: "flex", flexDirection: "column", gap: 18 * u }}>
          {shown.map((line, i) => {
            const start = 8 + i * step;
            const p = interpolate(frame, [start, start + 8], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 20 * u,
                  opacity: p,
                  transform: `translateX(${(1 - p) * 24 * u}px)`,
                }}
              >
                <div
                  style={{
                    flex: "none",
                    width: 16 * u,
                    height: 16 * u,
                    borderRadius: 4 * u,
                    background: COLORS.accent,
                    transform: `translateY(${-4 * u}px)`,
                  }}
                />
                <div style={{ fontWeight: 600, fontSize: lineSize * u, lineHeight: 1.25 }}>{line}</div>
              </div>
            );
          })}
        </div>
      </Card>
    </Band>
  );
};
