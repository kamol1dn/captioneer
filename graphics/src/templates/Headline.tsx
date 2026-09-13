import React from "react";
import { Img, interpolate } from "remotion";
import { Band, COLORS, Card, Position, assetSrc, fitSize, useEnterExit, useUnit } from "../theme";

export type HeadlineProps = {
  source: string;
  headline: string;
  date?: string;
  logo?: string;
  position?: Position;
};

export const Headline: React.FC<HeadlineProps> = ({ source, headline, date, logo, position = "top" }) => {
  const u = useUnit();
  const { enter } = useEnterExit();
  // The headline lands a beat after the card, so the eye reads source first.
  const body = interpolate(enter, [0.4, 1], [0, 1], { extrapolateLeft: "clamp" });
  return (
    <Band position={position}>
      <Card width={940}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 * u }}>
          {logo ? (
            <Img
              src={assetSrc(logo)}
              style={{ height: 56 * u, width: 56 * u, objectFit: "contain", borderRadius: 12 * u }}
            />
          ) : null}
          <div
            style={{
              background: COLORS.accent,
              color: COLORS.accentInk,
              fontWeight: 800,
              fontSize: 30 * u,
              letterSpacing: 1.5 * u,
              textTransform: "uppercase",
              padding: `${8 * u}px ${18 * u}px`,
              borderRadius: 10 * u,
            }}
          >
            {source}
          </div>
          {date ? (
            <div style={{ color: COLORS.muted, fontWeight: 600, fontSize: 30 * u, marginLeft: "auto" }}>
              {date}
            </div>
          ) : null}
        </div>
        <div
          style={{
            marginTop: 28 * u,
            fontWeight: 800,
            fontSize: fitSize(headline, 64, 42, 40) * u,
            lineHeight: 1.18,
            opacity: body,
            transform: `translateY(${(1 - body) * 16 * u}px)`,
          }}
        >
          {headline}
        </div>
      </Card>
    </Band>
  );
};
