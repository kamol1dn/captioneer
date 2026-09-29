import React from "react";
import { Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Band, COLORS, Card, Position, assetSrc, fitSize, useUnit } from "../theme";

export type ImageCardProps = { image: string; caption?: string; credit?: string; position?: Position };

export const ImageCard: React.FC<ImageCardProps> = ({ image, caption, credit, position = "center" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // A slow push-in across the whole entry: enough to keep a still image alive,
  // not so much that text in a screenshot drifts out of reading.
  const zoom = interpolate(frame, [0, durationInFrames], [1, 1.05]);
  return (
    <Band position={position}>
      <Card width={960} padding={20}>
        <div style={{ overflow: "hidden", maxHeight: 1100 * u, display: "flex" }}>
          {image ? (
            <Img
              src={assetSrc(image)}
              style={{
                width: "100%",
                objectFit: "cover",
                objectPosition: "top",
                transform: `scale(${zoom})`,
                transformOrigin: "50% 30%",
              }}
            />
          ) : (
            <div style={{ width: "100%", height: 600 * u, background: "#222" }} />
          )}
        </div>
        {caption || credit ? (
          <div style={{ padding: `${20 * u}px ${10 * u}px ${6 * u}px` }}>
            {caption ? (
              <div style={{ fontWeight: 700, fontSize: fitSize(caption, 42, 34, 30) * u, lineHeight: 1.2 }}>{caption}</div>
            ) : null}
            {credit ? (
              <div style={{ marginTop: 8 * u, color: COLORS.muted, fontWeight: 400, fontSize: 26 * u }}>{credit}</div>
            ) : null}
          </div>
        ) : null}
      </Card>
    </Band>
  );
};
