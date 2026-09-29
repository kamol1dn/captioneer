import React from "react";
import { Img } from "remotion";
import { Band, COLORS, Card, DISPLAY, Position, Rule, assetSrc, fitSize, reveal, useCue, useUnit } from "../theme";

export type HeadlineProps = {
  source: string;
  headline: string;
  date?: string;
  logo?: string;
  position?: Position;
};

// A news card: the outlet in the condensed face, the date in grey, a hairline,
// then the headline. The headline lands a beat after, so the eye reads the
// source first.
export const Headline: React.FC<HeadlineProps> = ({ source, headline, date, logo, position = "bottom" }) => {
  const u = useUnit();
  const body = useCue(7, 10);
  return (
    <Band position={position}>
      <Card width={940}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 18 * u }}>
          {logo ? (
            <Img src={assetSrc(logo)} style={{ height: 48 * u, width: 48 * u, objectFit: "contain", alignSelf: "center" }} />
          ) : null}
          <div
            style={{
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: 40 * u,
              lineHeight: 1.05,
              textTransform: "uppercase",
              color: COLORS.accent,
              minWidth: 0,
            }}
          >
            {source}
          </div>
          {date ? (
            <div style={{ color: COLORS.muted, fontWeight: 400, fontSize: 28 * u, marginLeft: "auto", flex: "none", textAlign: "right" }}>
              {date}
            </div>
          ) : null}
        </div>
        <Rule style={{ margin: `${20 * u}px 0 ${22 * u}px` }} />
        <div
          style={{
            fontWeight: 700,
            fontSize: fitSize(headline, 60, 42, 40) * u,
            lineHeight: 1.18,
            ...reveal(body, u),
          }}
        >
          {headline}
        </div>
      </Card>
    </Band>
  );
};
