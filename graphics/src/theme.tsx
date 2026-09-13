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

/** Vertical centre of each band, as a fraction of frame height. */
const BAND_CENTRE: Record<Position, number> = { top: 0.14, center: 0.45, bottom: 0.72 };

/**
 * Places its child horizontally centred at the band's height. The child keeps
 * its own size; this only positions it.
 */
export const Band: React.FC<{ position?: Position; children: React.ReactNode }> = ({
  position = "top",
  children,
}) => {
  const { height } = useVideoConfig();
  const centre = BAND_CENTRE[position] ?? BAND_CENTRE.top;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: centre * height,
          transform: "translateY(-50%)",
          display: "flex",
          justifyContent: "center",
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
 * Laid out around the captions rather than under them — the content lives in
 * the upper 60% and the band where captions usually sit is left as quiet
 * background, so the words stay readable over it. The panel slides up over the
 * speaker and fades back off them; both are in the file's alpha, so the graphic
 * needs no transition in Premiere.
 */
export const FullFrame: React.FC<{
  kicker?: string;
  title?: string;
  source?: string;
  align?: "start" | "center";
  children: React.ReactNode;
}> = ({ kicker, title, source, align = "start", children }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { height, width, durationInFrames, fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200, mass: 0.7 }, durationInFrames: 12 });
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const head = interpolate(enter, [0.5, 1], [0, 1], { extrapolateLeft: "clamp" });
  // A slow drift so a long, text-heavy frame never looks frozen.
  const drift = interpolate(frame, [0, durationInFrames], [0, 1]);
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill
        style={{
          transform: `translateY(${(1 - enter) * height}px)`,
          background: "#0B0C10",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            width: width * 1.4,
            height: width * 1.4,
            left: -width * 0.2 + drift * 60 * u,
            top: -width * 0.55,
            background: `radial-gradient(circle, rgba(255,220,0,0.16) 0%, rgba(255,220,0,0) 60%)`,
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
            backgroundSize: `${90 * u}px ${90 * u}px`,
            backgroundPosition: `0 ${-drift * 90 * u}px`,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 72 * u,
            right: 72 * u,
            top: height * 0.075,
            bottom: height * 0.37,
            fontFamily: FONT,
            color: COLORS.text,
            display: "flex",
            flexDirection: "column",
          }}
        >
        <div style={{ flex: "none", opacity: head, transform: `translateY(${(1 - head) * 20 * u}px)` }}>
          {kicker ? (
            <div
              style={{
                display: "inline-block",
                background: COLORS.accent,
                color: COLORS.accentInk,
                fontWeight: 800,
                fontSize: 30 * u,
                letterSpacing: 2 * u,
                textTransform: "uppercase",
                padding: `${8 * u}px ${18 * u}px`,
                borderRadius: 10 * u,
                marginBottom: 22 * u,
              }}
            >
              {kicker}
            </div>
          ) : null}
          {title ? (
            <div style={{ fontWeight: 800, fontSize: fitSize(title, 88, 24, 56) * u, lineHeight: 1.1 }}>{title}</div>
          ) : null}
        </div>
        {/* Content follows the header rather than centring in what is left:
            a gap between title and list reads as two unrelated things. */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            marginTop: (title || kicker ? 64 : 0) * u,
            display: "flex",
            flexDirection: "column",
            justifyContent: align === "center" ? "center" : "flex-start",
          }}
        >
          {children}
        </div>
        </div>
        {source ? (
          <div
            style={{
              position: "absolute",
              left: 72 * u,
              right: 72 * u,
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
