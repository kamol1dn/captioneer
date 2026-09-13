import React from "react";
import { interpolate } from "remotion";
import { Band, COLORS, FONT, Position, fitSize, useEnterExit, useUnit } from "../theme";

export type LowerThirdProps = { name: string; role: string; position?: Position };

// Not a card: a name plate with an accent bar that draws in first, then the
// text slides out from behind it. Lighter than a card, because a person's name
// should not cover more of them than it has to.
export const LowerThird: React.FC<LowerThirdProps> = ({ name, role, position = "top" }) => {
  const u = useUnit();
  const { enter, exit } = useEnterExit(16, 9);
  const bar = interpolate(enter, [0, 0.5], [0, 1], { extrapolateRight: "clamp" });
  const text = interpolate(enter, [0.3, 1], [0, 1], { extrapolateLeft: "clamp" });
  return (
    <Band position={position}>
      <div style={{ display: "flex", alignItems: "stretch", opacity: exit, fontFamily: FONT }}>
        <div
          style={{
            width: 14 * u,
            background: COLORS.accent,
            borderRadius: 7 * u,
            transform: `scaleY(${bar})`,
          }}
        />
        <div
          style={{
            overflow: "hidden",
            paddingLeft: 28 * u,
          }}
        >
          <div
            style={{
              transform: `translateX(${(1 - text) * -40 * u}px)`,
              opacity: text,
              background: COLORS.card,
              borderRadius: 22 * u,
              padding: `${26 * u}px ${40 * u}px`,
              maxWidth: 860 * u,
            }}
          >
            <div
              style={{
                color: COLORS.text,
                fontWeight: 800,
                fontSize: fitSize(name, 72, 18, 48) * u,
                lineHeight: 1.1,
              }}
            >
              {name}
            </div>
            <div
              style={{
                color: COLORS.accent,
                fontWeight: 600,
                fontSize: fitSize(role, 40, 30, 28) * u,
                lineHeight: 1.25,
                marginTop: 10 * u,
              }}
            >
              {role}
            </div>
          </div>
        </div>
      </div>
    </Band>
  );
};
