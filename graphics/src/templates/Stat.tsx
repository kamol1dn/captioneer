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
  position = "top",
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
  return (
    <Band position={position}>
      <Card width={820} style={{ textAlign: "center" }}>
        <div
          style={{
            color: COLORS.accent,
            fontWeight: 900,
            fontSize: fitSize(final, 200, 5, 110) * u,
            lineHeight: 1,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {shown}
        </div>
        <div style={{ marginTop: 18 * u, fontWeight: 700, fontSize: fitSize(label, 50, 28, 34) * u, lineHeight: 1.2 }}>
          {label}
        </div>
        {sublabel ? (
          <div style={{ marginTop: 12 * u, color: COLORS.muted, fontWeight: 500, fontSize: 30 * u }}>{sublabel}</div>
        ) : null}
      </Card>
    </Band>
  );
};
