// The hook title: the line a scrolling viewer reads in the first two seconds.
//
// Big condensed type on flat near-black blocks — a broadcast super, one block
// per line — so it reads as the clip's headline over any wall without a
// shadow. Words land one by one with a small rise; the phrase that carries the
// tension is marked with *asterisks* and lands last, in red.
import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Band, COLORS, DISPLAY, Kicker, Position, SAFE_W, fitSize, superLines, useUnit } from "../theme";

export type HookProps = { text: string; kicker?: string; position?: Position };

export const Hook: React.FC<HookProps> = ({ text, kicker, position = "top" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const size = fitSize(text.replace(/[*\n]/g, ""), 124, 22, 88);
  // Condensed caps run ~0.42em a character; leave room for the block padding.
  const maxChars = Math.max(8, Math.floor((SAFE_W - 60) / (size * 0.42)));
  const lines = superLines(text, maxChars);
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const blockIn = interpolate(frame, [0, 6], [0, 1], { extrapolateRight: "clamp" });
  let k = 0;
  return (
    <Band position={position}>
      <div style={{ width: SAFE_W * u, display: "flex", flexDirection: "column", alignItems: "center", opacity: exit }}>
        {kicker ? (
          <Kicker size={30} style={{ marginBottom: 14 * u, opacity: blockIn }}>
            {kicker}
          </Kicker>
        ) : null}
        {lines.map((line, li) => (
          <div
            key={li}
            style={{
              background: COLORS.bg,
              opacity: blockIn,
              padding: `${12 * u}px ${28 * u}px ${4 * u}px`,
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: size * u,
              lineHeight: 1.02,
              textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}
          >
            {line.map((w, wi) => {
              // Words land every ~2.5 frames; the marked phrase a beat later.
              const delay = 2 + k++ * 2.5 + (w.hl ? 2 : 0);
              const p = interpolate(frame, [delay, delay + 8], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              return (
                <span
                  key={wi}
                  style={{
                    display: "inline-block",
                    marginRight: wi < line.length - 1 ? 0.22 * size * u : 0,
                    color: w.hl ? COLORS.accent : COLORS.text,
                    opacity: p,
                    transform: `translateY(${(1 - p) * 12 * u}px)`,
                  }}
                >
                  {w.t}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </Band>
  );
};
