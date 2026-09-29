import React from "react";
import { Band, COLORS, DISPLAY, FONT, Position, SAFE_W, fitSize, reveal, useCue, useEnterExit, useUnit } from "../theme";

export type LowerThirdProps = { name: string; role: string; position?: Position };

// The show's own lower third: the name in the condensed headline face on a
// near-black block, the role on the brand-red band under it. The band wipes in
// a beat after the name, the way the long-form super does.
export const LowerThird: React.FC<LowerThirdProps> = ({ name, role, position = "bottom" }) => {
  const u = useUnit();
  const { exit } = useEnterExit();
  const nameIn = useCue(0, 10);
  const band = useCue(6, 12);
  const roleIn = useCue(10, 10);
  return (
    <Band position={position}>
      <div style={{ width: SAFE_W * u, opacity: exit }}>
        <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "stretch", maxWidth: SAFE_W * u }}>
          <div
            style={{
              background: COLORS.bg,
              color: COLORS.text,
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: fitSize(name, 84, 16, 58) * u,
              lineHeight: 1.0,
              textTransform: "uppercase",
              padding: `${22 * u}px ${34 * u}px ${16 * u}px`,
              ...reveal(nameIn, u),
            }}
          >
            {name}
          </div>
          <div
            style={{
              background: COLORS.brand,
              clipPath: `inset(0 ${(1 - band) * 100}% 0 0)`,
              padding: `${14 * u}px ${34 * u}px`,
            }}
          >
            <div
              style={{
                color: COLORS.text,
                fontFamily: FONT,
                fontWeight: 500,
                fontSize: fitSize(role, 36, 34, 26) * u,
                lineHeight: 1.2,
                opacity: roleIn,
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
