// Shared look and motion for every template.
//
// Everything is drawn in "units" of a 1080-wide frame, so the same template
// renders correctly at 1080x1920 and at the 1440x2560 the OTG episodes use —
// the renderer only ever changes the composition size, never the design.
import { loadFont } from "@remotion/fonts";
import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FONT = "Montserrat";
const fontsReady = loadFont({
  family: FONT,
  url: staticFile("fonts/Montserrat-VariableFont_wght.ttf"),
  weight: "100 900",
});
// Renders wait on this through delayRender inside loadFont, so text never
// rasterises in the fallback face and then pops.
void fontsReady;

export const COLORS = {
  card: "rgba(14, 15, 18, 0.9)",
  cardEdge: "rgba(255, 255, 255, 0.08)",
  text: "#FFFFFF",
  muted: "rgba(255, 255, 255, 0.62)",
  // The caption highlight colour, so graphics and captions read as one system.
  accent: "#FFDC00",
  accentInk: "#0E0F12",
  // The OTG caption highlight, the second colour on full-screen frames.
  cyan: "#19E0D6",
};

export type Position = "top" | "center" | "bottom";

/** Pixels per design unit: 1 at 1080 wide. */
export const useUnit = () => useVideoConfig().width / 1080;

/**
 * 0 -> 1 on the way in, 1 -> 0 on the way out. Every graphic enters and leaves
 * inside its own file, so nothing needs a dissolve applied in Premiere — which
 * matters, since a dissolve applied by hand does not survive a re-export.
 */
export const useEnterExit = (enterFrames = 14, exitFrames = 9) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const enter = spring({
    frame,
    fps,
    config: { damping: 200, mass: 0.6 },
    durationInFrames: enterFrames,
  });
  const exit = interpolate(
    frame,
    [durationInFrames - exitFrames, durationInFrames - 1],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.in(Easing.cubic) },
  );
  return { enter, exit, visible: Math.min(enter, exit) };
};

/**
 * The frame's reserved zones, as fractions of height.
 *
 * The top 20% carries the show's logo and the sponsor overlay, added in
 * Premiere — transparent and small, but graphics that sit under them read as
 * clutter. The captions sit around 66-78%, positioned by hand. Everything we
 * draw lives in the gap between.
 */
export const SAFE = { top: 0.215, bottom: 0.635, captions: [0.64, 0.8] as const };

/**
 * Where each band puts a graphic. Anchored by an edge, not a centre, so a
 * taller card grows *away* from the zone it must not enter: "top" hangs from
 * just under the logo zone, "bottom" stands on just above the captions.
 */
const BAND_STYLE = (position: Position, height: number): React.CSSProperties => {
  if (position === "bottom") return { bottom: (1 - SAFE.bottom) * height };
  if (position === "center") return { top: 0.45 * height, transform: "translateY(-50%)" };
  return { top: SAFE.top * height };
};

/**
 * Places its child horizontally centred in the band. The child keeps its own
 * size; this only positions it.
 */
export const Band: React.FC<{ position?: Position; children: React.ReactNode }> = ({
  position = "top",
  children,
}) => {
  const { height } = useVideoConfig();
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          ...BAND_STYLE(position, height),
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};

/** The dark rounded card most templates sit on, with the shared entrance. */
export const Card: React.FC<{
  children: React.ReactNode;
  width?: number;
  padding?: number;
  style?: React.CSSProperties;
}> = ({ children, width = 900, padding = 48, style }) => {
  const u = useUnit();
  const { enter, exit } = useEnterExit();
  const rise = (1 - enter) * 60 * u;
  const scale = 0.94 + 0.06 * enter - (1 - exit) * 0.03;
  return (
    <div
      style={{
        width: width * u,
        boxSizing: "border-box",
        padding: padding * u,
        background: COLORS.card,
        border: `${2 * u}px solid ${COLORS.cardEdge}`,
        borderRadius: 34 * u,
        boxShadow: `0 ${18 * u}px ${60 * u}px rgba(0,0,0,0.45)`,
        color: COLORS.text,
        fontFamily: FONT,
        opacity: Math.min(enter, exit),
        transform: `translateY(${rise}px) scale(${scale})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/**
 * Progress 0 -> 1 for item ``i`` of ``n`` revealed one after another. The whole
 * reveal fits in ``share`` of the graphic, so the last item is on screen for
 * most of it however long the entry is — a list that finishes appearing just as
 * the graphic leaves was never read.
 */
export const useStagger = (i: number, n: number, share = 0.4, startAt = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const window = Math.max(n * 6, durationInFrames * share - startAt);
  const step = n > 1 ? window / n : 0;
  const start = startAt + i * step;
  return interpolate(frame, [start, start + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
};

/**
 * Full-screen frame: replaces the picture for its duration.
 *
 * Laid out around the reserved zones rather than under them: the logo and
 * sponsor overlay own the top 20%, the captions own a band lower down, and the
 * whole block — title and content together — is centred in the space between.
 * Both zones are left as quiet background, so the overlay and the captions stay
 * readable over it. The panel slides up over the speaker and fades back off
 * them; both are in the file's alpha, so it needs no transition in Premiere.
 */
export const FullFrame: React.FC<{
  kicker?: string;
  title?: string;
  source?: string;
  children: React.ReactNode;
}> = ({ kicker, title, source, children }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { height, width, durationInFrames, fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200, mass: 0.7 }, durationInFrames: 12 });
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const head = interpolate(enter, [0.5, 1], [0, 1], { extrapolateLeft: "clamp" });
  const rule = interpolate(frame, [10, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  // Slow drift on every layer, so a long text-heavy frame never looks frozen.
  const t = frame / Math.max(1, durationInFrames);
  const orb = (x: number, y: number, size: number, rgb: string, a: number): React.CSSProperties => ({
    position: "absolute",
    left: x * width - (size * width) / 2,
    top: y * height - (size * width) / 2,
    width: size * width,
    height: size * width,
    borderRadius: "50%",
    background: `radial-gradient(circle, rgba(${rgb},${a}) 0%, rgba(${rgb},0) 62%)`,
  });
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill
        style={{
          transform: `translateY(${(1 - enter) * height}px)`,
          background: "linear-gradient(170deg, #0D1017 0%, #07080C 55%, #0A0D14 100%)",
          overflow: "hidden",
        }}
      >
        {/* Two colour pools: the graphics' yellow and the captions' cyan, so
            the frame and the words over it read as one palette. */}
        <div style={orb(0.88 - t * 0.06, 0.3 + t * 0.03, 1.25, "255,220,0", 0.2)} />
        <div style={orb(0.08 + t * 0.07, 0.62 - t * 0.04, 1.15, "25,224,214", 0.13)} />
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
            backgroundSize: `${96 * u}px ${96 * u}px`,
            backgroundPosition: `0 ${-t * 96 * u}px`,
            // The grid fades toward the edges and the reserved zones.
            maskImage: "radial-gradient(ellipse 75% 45% at 50% 42%, #000 30%, transparent 100%)",
            WebkitMaskImage: "radial-gradient(ellipse 75% 45% at 50% 42%, #000 30%, transparent 100%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 64 * u,
            right: 64 * u,
            top: height * SAFE.top,
            bottom: height * (1 - SAFE.bottom),
            fontFamily: FONT,
            color: COLORS.text,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
          }}
        >
          {kicker || title ? (
            <div style={{ flex: "none", opacity: head, transform: `translateY(${(1 - head) * 20 * u}px)` }}>
              {kicker ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 14 * u,
                    color: COLORS.accent,
                    fontWeight: 800,
                    fontSize: 30 * u,
                    letterSpacing: 3 * u,
                    textTransform: "uppercase",
                    marginBottom: 16 * u,
                  }}
                >
                  <span
                    style={{
                      width: 14 * u,
                      height: 14 * u,
                      borderRadius: 7 * u,
                      background: COLORS.accent,
                      boxShadow: `0 0 ${18 * u}px ${COLORS.accent}`,
                    }}
                  />
                  {kicker}
                </div>
              ) : null}
              {title ? (
                <div style={{ fontWeight: 900, fontSize: fitSize(title, 84, 24, 54) * u, lineHeight: 1.08, letterSpacing: -1 * u }}>
                  {title}
                </div>
              ) : null}
              <div
                style={{
                  marginTop: 22 * u,
                  height: 8 * u,
                  width: `${rule * 26}%`,
                  borderRadius: 4 * u,
                  background: `linear-gradient(90deg, ${COLORS.accent}, ${COLORS.cyan})`,
                }}
              />
            </div>
          ) : null}
          <div style={{ flex: "none", marginTop: (title || kicker ? 44 : 0) * u }}>{children}</div>
        </div>
        {source ? (
          <div
            style={{
              position: "absolute",
              left: 64 * u,
              right: 64 * u,
              bottom: height * 0.055,
              fontFamily: FONT,
              color: COLORS.muted,
              fontWeight: 500,
              fontSize: 28 * u,
            }}
          >
            {source}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** A frosted panel — the unit the full-screen templates build their content from. */
export const Glass: React.FC<{
  children: React.ReactNode;
  tint?: "none" | "accent" | "cyan";
  padding?: number;
  style?: React.CSSProperties;
}> = ({ children, tint = "none", padding = 30, style }) => {
  const u = useUnit();
  const bg = { none: "rgba(255,255,255,0.055)", accent: "rgba(255,220,0,0.09)", cyan: "rgba(25,224,214,0.08)" }[tint];
  const edge = { none: "rgba(255,255,255,0.12)", accent: "rgba(255,220,0,0.45)", cyan: "rgba(25,224,214,0.4)" }[tint];
  return (
    <div
      style={{
        position: "relative",
        background: bg,
        border: `${2 * u}px solid ${edge}`,
        borderRadius: 28 * u,
        padding: padding * u,
        boxShadow: `inset 0 ${2 * u}px 0 rgba(255,255,255,0.07), 0 ${20 * u}px ${50 * u}px rgba(0,0,0,0.35)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/**
 * Font size that shrinks as text grows, so a long headline wraps to a few lines
 * instead of overflowing the card. Deliberately a heuristic on character count:
 * it needs no measuring pass, and the renderer's still is where a bad fit gets
 * caught.
 */
export const fitSize = (text: string, base: number, comfortableChars: number, min: number) => {
  const n = Math.max(text.length, 1);
  if (n <= comfortableChars) return base;
  return Math.max(min, base * Math.sqrt(comfortableChars / n));
};

/** Resolves an image prop: staged files are served from public/, URLs pass through. */
export const assetSrc = (p: string) => (/^(https?:|data:)/.test(p) ? p : staticFile(p));

export const formatNumber = (v: number, decimals = 0) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
