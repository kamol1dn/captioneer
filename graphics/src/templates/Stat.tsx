import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Band, COLORS, Card, Position, fitSize, formatNumber, useUnit } from "../theme";

export type StatProps = {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  label: string;
  sublabel?: string;
  position?: Position;
};

export const Stat: React.FC<StatProps> = ({
  value,
  prefix = "",
  suffix = "",
  decimals = 0,
  label,
  sublabel,
  position = "bottom",
}) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  // Count for about a second, and never past half the graphic: the number has
  // to sit still long enough to be read.
  const countEnd = Math.max(6, Math.min(Math.round(fps * 1.1), Math.floor(durationInFrames / 2)));
  const t = interpolate(frame, [4, countEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const shown = `${prefix}${formatNumber(value * t, decimals)}${suffix}`;
  // Size from the final string so the number does not grow while it counts.
  const final = `${prefix}${formatNumber(value, decimals)}${suffix}`;
  // Number beside the label rather than above it: half the height, which is
  // what lets the card sit on the chest in a tight shot instead of the mouth.
  const numSize = fitSize(final, 150, 4, 96);
  return (
    <Band position={position}>
      <Card width={940} padding={36} style={{ display: "flex", alignItems: "center", gap: 32 * u }}>
        <div
          style={{
            flex: "none",
            color: COLORS.accent,
            fontWeight: 900,
            fontSize: numSize * u,
            lineHeight: 1,
            fontVariantNumeric: "tabular-nums",
            // Reserve the final width so the label doesn't slide as it counts.
            minWidth: `${final.length * 0.62}em`,
            textAlign: "center",
          }}
        >
          {shown}
        </div>
        <div style={{ borderLeft: `${4 * u}px solid rgba(255,220,0,0.5)`, paddingLeft: 28 * u }}>
          <div style={{ fontWeight: 700, fontSize: fitSize(label, 44, 26, 32) * u, lineHeight: 1.2 }}>{label}</div>
          {sublabel ? (
            <div style={{ marginTop: 10 * u, color: COLORS.muted, fontWeight: 500, fontSize: 28 * u }}>{sublabel}</div>
          ) : null}
        </div>
      </Card>
    </Band>
  );
};
