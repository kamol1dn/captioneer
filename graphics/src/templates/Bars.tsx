import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { Band, COLORS, Card, DISPLAY, Position, fitSize, formatNumber, useUnit } from "../theme";

export type BarItem = { label: string; value: number; highlight?: boolean };
export type BarsProps = {
  title?: string;
  items: BarItem[];
  prefix?: string;
  suffix?: string;
  decimals?: number;
  position?: Position;
};

// Flat square bars on a hairline track; the highlighted one in the accent, the
// rest in white. Values in the condensed face.
export const Bars: React.FC<BarsProps> = ({ title, items, prefix = "", suffix = "", decimals = 0, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const shown = items.slice(0, 5);
  const max = Math.max(...shown.map((i) => Math.abs(i.value)), 1e-9);
  const longestLabel = shown.reduce((m, i) => Math.max(m, i.label.length), 0);
  const labelSize = fitSize("x".repeat(longestLabel), 36, 12, 28);
  return (
    <Band position={position}>
      <Card width={920}>
        {title ? (
          <div style={{ fontWeight: 700, fontSize: fitSize(title, 48, 26, 36) * u, marginBottom: 28 * u, lineHeight: 1.15 }}>{title}</div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 22 * u }}>
          {shown.map((item, i) => {
            const start = 8 + i * 5;
            const grow = interpolate(frame, [start, start + 22], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.out(Easing.cubic),
            });
            const colour = item.highlight ? COLORS.accent : COLORS.text;
            return (
              <div key={i}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 * u }}>
                  <span style={{ fontWeight: 400, fontSize: labelSize * u, color: item.highlight ? COLORS.text : COLORS.muted }}>
                    {item.label}
                  </span>
                  <span
                    style={{
                      fontFamily: DISPLAY,
                      fontWeight: 700,
                      fontSize: labelSize * 1.35 * u,
                      color: colour,
                      fontVariantNumeric: "tabular-nums",
                      opacity: grow,
                    }}
                  >
                    {prefix}
                    {formatNumber(item.value * grow, decimals)}
                    {suffix}
                  </span>
                </div>
                <div style={{ height: 18 * u, background: "#222" }}>
                  <div style={{ height: "100%", width: `${(Math.abs(item.value) / max) * 100 * grow}%`, background: colour }} />
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </Band>
  );
};
