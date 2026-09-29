// Long-form panel graphics: opaque frames that fill a pane of the OTG long-form
// layouts (the news layout's middle pane, the guest layout's right pane).
//
// Unlike the shorts' cards these carry no alpha and no exit: the layout itself
// cross-fades in and out over them (4 frames in the edit), so a panel only
// builds its content in once that fade is done and holds to the last frame.
//
// The look is the show's own broadcast package, not a UI kit: flat black,
// Helvetica (the condensed bold of the V3 headline bar for display type), the
// layout's #880401 as a solid bar, hairline rules between items instead of
// boxes, red only on the thing that matters. No glow, gradients, rounded cards
// or pills — those are what made the first version read as generated.
//
// Sizes are in units of 1/1000 of the panel height. The news pane is ~1283
// units wide, the guest pane ~2059 — `wide` switches layouts between them.
import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

export const BODY = "OTG Helvetica";
export const DISPLAY = "OTG Helvetica Condensed";
void loadFont({ family: BODY, url: staticFile("fonts/Helvetica-Light.ttf"), weight: "300" });
void loadFont({ family: BODY, url: staticFile("fonts/Helvetica.ttf"), weight: "400" });
void loadFont({ family: BODY, url: staticFile("fonts/Helvetica-Medium.ttf"), weight: "500" });
void loadFont({ family: BODY, url: staticFile("fonts/Helvetica-Bold.ttf"), weight: "700" });
void loadFont({ family: DISPLAY, url: staticFile("fonts/HelveticaNeue-CondensedBold.ttf"), weight: "700" });

// Sampled from the layout PNGs: the lower-third band is #880401.
export const PC = {
  brand: "#880401",
  red: "#E82620",
  white: "#FFFFFF",
  paper: "#F4F1EC",
  ink: "#0B0B0B",
  bg: "#0B0B0B",
  muted: "#9A9A9A",
  dim: "#6A6A6A",
  rule: "#2E2E2E",
  ruleStrong: "#4A4A4A",
};

export const usePanel = () => {
  const { width, height } = useVideoConfig();
  const u = height / 1000;
  return { u, W: width, H: height, wide: width / height > 1.6, cols: width / u };
};

/** Frames the layout's own cross-fade takes; builds start after it. */
export const FADE = 4;

const ease = Easing.out(Easing.quad);

/** 0 -> 1 reveal for item i of n, all within the first ~35% of the graphic. */
export const useBuild = (i: number, n: number, share = 0.35, startAt = FADE + 3, len = 10) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const window = Math.max(0, durationInFrames * share - startAt);
  const step = n > 1 ? Math.min(12, window / n) : 0;
  const start = startAt + i * step;
  return interpolate(frame, [start, start + len], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
};

/**
 * Like useBuild, but item i can be pinned to a moment — `reveal[i]` is a
 * fraction of the duration — so an item lands on the word that names it.
 */
export const useReveal = (i: number, n: number, reveal?: (number | null)[], share = 0.35) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const even = useBuild(i, n, share);
  const at = reveal?.[i];
  if (at == null) return even;
  const start = Math.max(FADE + 2, at * durationInFrames - 3);
  return interpolate(frame, [start, start + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
};

/** Linear 0 -> 1 over the whole graphic, for slow drift. */
export const useDrift = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return frame / Math.max(1, durationInFrames - 1);
};

/** Fade plus a short rise — the only entrance anything makes. */
export const rise = (p: number, u: number, dist = 12): React.CSSProperties => ({
  opacity: p,
  transform: `translateY(${(1 - p) * dist * u}px)`,
});

/** Flat black ground with the brand bar down the left edge. */
export const PanelBg: React.FC<{ children?: React.ReactNode; bar?: boolean }> = ({ children, bar = true }) => {
  const { u } = usePanel();
  const p = useBuild(0, 1, 0.1, 1, 8);
  return (
    <AbsoluteFill style={{ background: PC.bg, overflow: "hidden" }}>
      {bar ? <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 16 * u, background: PC.brand, transform: `scaleY(${p})`, transformOrigin: "top" }} /> : null}
      <AbsoluteFill style={{ fontFamily: BODY, color: PC.white }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

/** `*word*` in a string turns red — a colour change, not a highlighter pill. */
export const Rich: React.FC<{ text: string; mark?: string }> = ({ text, mark = PC.red }) => {
  const parts = text.split(/(\*[^*]+\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("*") && p.endsWith("*") ? (
          <span key={i} style={{ color: mark }}>
            {p.slice(1, -1)}
          </span>
        ) : (
          <React.Fragment key={i}>{p}</React.Fragment>
        ),
      )}
    </>
  );
};

export const plain = (s: string) => s.replace(/\*/g, "");

/** Shrinks with length: base at `comfortable` chars, never below `min`. */
export const fit = (text: string, base: number, comfortable: number, min: number) => {
  const n = Math.max(plain(text).length, 1);
  return n <= comfortable ? base : Math.max(min, base * Math.sqrt(comfortable / n));
};

/** Small letter-spaced uppercase label: kicker, tag, fact label. */
export const Label: React.FC<{ children: React.ReactNode; size?: number; color?: string; style?: React.CSSProperties }> = ({
  children,
  size = 30,
  color = PC.muted,
  style,
}) => {
  const { u } = usePanel();
  return (
    <div
      style={{
        fontFamily: BODY,
        fontWeight: 500,
        fontSize: size * u,
        letterSpacing: 0.14 * size * u,
        textTransform: "uppercase",
        color,
        lineHeight: 1.2,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/** Back-compat name: kickers and tags are plain labels now. */
export const Chip: React.FC<{ children: React.ReactNode; size?: number; tone?: "red" | "white" | "ghost"; style?: React.CSSProperties }> = ({
  children,
  size = 30,
  tone = "ghost",
  style,
}) => <Label size={size} color={tone === "red" ? PC.red : tone === "white" ? PC.white : PC.muted} style={style}>{children}</Label>;

/** A hairline that draws left to right. */
export const Rule: React.FC<{ p?: number; color?: string; weight?: number; style?: React.CSSProperties }> = ({ p = 1, color = PC.rule, weight = 2, style }) => {
  const { u } = usePanel();
  return <div style={{ height: weight * u, background: color, width: `${p * 100}%`, ...style }} />;
};

export type Framed = { kicker?: string; title?: string; source?: string };

/** Kicker label, condensed title, and a full-width hairline under both. */
export const Header: React.FC<{ kicker?: string; title?: string; size?: number; align?: "left" | "center" }> = ({
  kicker,
  title,
  size = 130,
  align = "left",
}) => {
  const { u } = usePanel();
  const p = useBuild(0, 1, 0.1, FADE + 1, 10);
  const rule = useBuild(0, 1, 0.2, FADE + 4, 18);
  if (!kicker && !title) return null;
  return (
    <div style={{ textAlign: align }}>
      <div style={rise(p, u)}>
        {kicker ? <Label>{kicker}</Label> : null}
        {title ? (
          <div
            style={{
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: fit(title, size, 26, size * 0.6) * u,
              lineHeight: 0.96,
              textTransform: "uppercase",
              marginTop: (kicker ? 16 : 0) * u,
            }}
          >
            <Rich text={title} />
          </div>
        ) : null}
      </div>
      <Rule p={rule} color={PC.ruleStrong} style={{ marginTop: 30 * u }} />
    </div>
  );
};

/** Source line, bottom-left. Nothing else: no show mark, no episode. */
export const Footer: React.FC<{ source?: string }> = ({ source }) => {
  const { u } = usePanel();
  const p = useBuild(0, 1, 0.3, FADE + 10, 12);
  if (!source) return null;
  return (
    <div style={{ position: "absolute", left: 80 * u, right: 64 * u, bottom: 36 * u, opacity: p, color: PC.dim, fontWeight: 400, fontSize: 28 * u }}>
      Source: {source}
    </div>
  );
};

/** The standard panel: background, header, content area, footer. */
export const Panel: React.FC<Framed & { children: React.ReactNode; titleSize?: number; center?: boolean }> = ({
  kicker,
  title,
  source,
  children,
  titleSize,
  center = true,
}) => {
  const { u } = usePanel();
  return (
    <PanelBg>
      <div
        style={{
          position: "absolute",
          left: 88 * u,
          right: 72 * u,
          top: 70 * u,
          bottom: 96 * u,
          display: "flex",
          flexDirection: "column",
          // "safe": content taller than the pane overflows downward, never off the top.
          justifyContent: center ? "safe center" : "flex-start",
          gap: 40 * u,
        }}
      >
        <Header kicker={kicker} title={title} size={titleSize} />
        <div style={{ flex: center ? "none" : 1, minHeight: 0 }}>{children}</div>
      </div>
      <Footer source={source} />
    </PanelBg>
  );
};

/** Back-compat: a plain container. No fill, no border, no radius. */
export const Block: React.FC<{ children: React.ReactNode; tone?: "none" | "red" | "paper"; pad?: number; style?: React.CSSProperties }> = ({
  children,
  tone = "none",
  pad = 0,
  style,
}) => {
  const { u } = usePanel();
  const bg = { none: "transparent", red: PC.brand, paper: PC.paper }[tone];
  return <div style={{ background: bg, padding: pad * u, color: tone === "paper" ? PC.ink : PC.white, ...style }}>{children}</div>;
};

export const panelAsset = (p: string) => (/^(https?:|data:)/.test(p) ? p : staticFile(p));

export const fmt = (v: number, decimals = 0) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
