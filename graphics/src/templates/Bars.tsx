import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { Band, COLORS, Card, Position, fitSize, formatNumber, useUnit } from "../theme";

export type BarItem = { label: string; value: number; highlight?: boolean };
export type BarsProps = {
  title?: string;
  items: BarItem[];
  prefix?: string;
  suffix?: string;
  decimals?: number;
  position?: Position;
};

export const Bars: React.FC<BarsProps> = ({ title, items, prefix = "", suffix = "", decimals = 0, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const shown = items.slice(0, 5);
  const max = Math.max(...shown.map((i) => Math.abs(i.value)), 1e-9);
  const longestLabel = shown.reduce((m, i) => Math.max(m, i.label.length), 0);
  const labelSize = fitSize("x".repeat(longestLabel), 38, 10, 28);
  return (
    <Band position={position}>
      <Card width={920}>
        {title ? (
          <div style={{ fontWeight: 800, fontSize: fitSize(title, 50, 26, 36) * u, marginBottom: 30 * u }}>{title}</div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 22 * u }}>
          {shown.map((item, i) => {
            const start = 8 + i * 4;
            const grow = interpolate(frame, [start, start + 22], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.out(Easing.cubic),
            });
            const colour = item.highlight ? COLORS.accent : "rgba(255,255,255,0.78)";
            return (
              <div key={i}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontWeight: 700,
                    fontSize: labelSize * u,
                    marginBottom: 8 * u,
                  }}
                >
                  <span>{item.label}</span>
                  <span style={{ color: colour, fontVariantNumeric: "tabular-nums", opacity: grow }}>
                    {prefix}
                    {formatNumber(item.value * grow, decimals)}
                    {suffix}
                  </span>
                </div>
                <div
                  style={{
                    height: 26 * u,
                    borderRadius: 13 * u,
                    background: "rgba(255,255,255,0.08)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${(Math.abs(item.value) / max) * 100 * grow}%`,
                      background: colour,
                      borderRadius: 13 * u,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </Band>
  );
};
