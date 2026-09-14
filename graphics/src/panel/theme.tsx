// Long-form panel graphics: opaque frames that fill a pane of the OTG long-form
// layouts (the news layout's middle pane, the guest layout's right pane).
//
// Unlike the shorts' cards these carry no alpha and no exit: the layout itself
// cross-fades in and out over them (4 frames in the edit), so a panel only
// builds its content in once that fade is done and holds to the last frame.
//
// Sizes are in units of 1/1000 of the panel height. The news pane is ~1283
// units wide, the guest pane ~2059 — `wide` switches layouts between them.
import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

export const BODY = "Montserrat";
export const DISPLAY = "Bebas Neue";
void loadFont({ family: BODY, url: staticFile("fonts/Montserrat-VariableFont_wght.ttf"), weight: "100 900" });
void loadFont({ family: DISPLAY, url: staticFile("fonts/BebasNeue-Regular.ttf"), weight: "400" });

// Sampled from the layout PNGs: the lower-third band is #880401.
export const PC = {
  brand: "#880401",
  red: "#E0161D",
  redSoft: "rgba(224,22,29,0.16)",
  white: "#FFFFFF",
  paper: "#F5F2ED",
  ink: "#0B0B0C",
  muted: "rgba(255,255,255,0.62)",
  faint: "rgba(255,255,255,0.1)",
  panel: "rgba(255,255,255,0.055)",
  edge: "rgba(255,255,255,0.13)",
};

export const usePanel = () => {
  const { width, height } = useVideoConfig();
  const u = height / 1000;
  return { u, W: width, H: height, wide: width / height > 1.6, cols: width / u };
};

/** Frames the layout's own cross-fade takes; builds start after it. */
export const FADE = 4;

/** 0 -> 1 reveal for item i of n, all within the first ~35% of the graphic. */
export const useBuild = (i: number, n: number, share = 0.35, startAt = FADE + 3, len = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const window = Math.max(0, durationInFrames * share - startAt);
  const step = n > 1 ? Math.min(14, window / n) : 0;
  const start = startAt + i * step;
  return interpolate(frame, [start, start + len], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
};

/**
 * Like useBuild, but item i can be pinned to a moment — `reveal[i]` is a
 * fraction of the duration — so a card lands on the word that names it.
 */
export const useReveal = (i: number, n: number, reveal?: (number | null)[], share = 0.35) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const even = useBuild(i, n, share);
  const at = reveal?.[i];
  if (at == null) return even;
  const start = Math.max(FADE + 2, at * durationInFrames - 3);
  return interpolate(frame, [start, start + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
};

/** Linear 0 -> 1 over the whole graphic, for slow drift. */
export const useDrift = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return frame / Math.max(1, durationInFrames - 1);
};

/** Dark ground with the layout's red glow and vertical stripes. */
export const PanelBg: React.FC<{ children?: React.ReactNode; light?: boolean }> = ({ children }) => {
  const { u, W, H } = usePanel();
  const t = useDrift();
  const orb = (x: number, y: number, size: number, a: number): React.CSSProperties => ({
    position: "absolute",
    left: x * W - (size * H) / 2,
    top: y * H - (size * H) / 2,
    width: size * H,
    height: size * H,
    borderRadius: "50%",
    background: `radial-gradient(circle, rgba(200,14,20,${a}) 0%, rgba(200,14,20,0) 65%)`,
  });
  return (
    <AbsoluteFill style={{ background: "linear-gradient(160deg, #141011 0%, #09090A 50%, #0D0909 100%)", overflow: "hidden" }}>
      <div style={orb(0.92 - t * 0.05, 0.05 + t * 0.04, 1.5, 0.28)} />
      <div style={orb(0.05 + t * 0.05, 1.0 - t * 0.03, 1.2, 0.16)} />
      <AbsoluteFill
        style={{
          backgroundImage: `repeating-linear-gradient(90deg, rgba(255,255,255,0.028) 0 ${2 * u}px, transparent ${2 * u}px ${38 * u}px)`,
          backgroundPosition: `${-t * 38 * u}px 0`,
        }}
      />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 ${220 * u}px rgba(0,0,0,0.75)` }} />
      <AbsoluteFill style={{ fontFamily: BODY, color: PC.white }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

/** `*word*` in a string renders on a red highlighter. */
export const Rich: React.FC<{ text: string; mark?: string; ink?: string }> = ({ text, mark = PC.red, ink = PC.white }) => {
  const parts = text.split(/(\*[^*]+\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("*") && p.endsWith("*") ? (
          <span
            key={i}
            style={{
              background: mark,
              color: ink,
              padding: "0 0.18em",
              margin: "0 0.02em",
              borderRadius: "0.12em",
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
          >
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

/** Red chip with display lettering — the kicker, a date, a source tag. */
export const Chip: React.FC<{ children: React.ReactNode; size?: number; tone?: "red" | "white" | "ghost"; style?: React.CSSProperties }> = ({
  children,
  size = 40,
  tone = "red",
  style,
}) => {
  const { u } = usePanel();
  const bg = { red: PC.red, white: PC.white, ghost: "rgba(255,255,255,0.1)" }[tone];
  const fg = tone === "white" ? PC.ink : PC.white;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontFamily: DISPLAY,
        fontSize: size * u,
        lineHeight: 1,
        letterSpacing: 0.06 * size * u,
        padding: `${0.28 * size * u}px ${0.42 * size * u}px ${0.2 * size * u}px`,
        background: bg,
        color: fg,
        borderRadius: 6 * u,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
};

export type Framed = { kicker?: string; title?: string; source?: string };

/** Kicker chip, display title and a red rule that draws in. */
export const Header: React.FC<{ kicker?: string; title?: string; size?: number; align?: "left" | "center" }> = ({
  kicker,
  title,
  size = 140,
  align = "left",
}) => {
  const { u } = usePanel();
  const p = useBuild(0, 1, 0.1, FADE + 1, 10);
  const rule = useBuild(0, 1, 0.2, FADE + 6, 16);
  if (!kicker && !title) return null;
  return (
    <div style={{ opacity: p, transform: `translateY(${(1 - p) * 24 * u}px)`, textAlign: align }}>
      {kicker ? <Chip size={44}>{kicker}</Chip> : null}
      {title ? (
        <div
          style={{
            fontFamily: DISPLAY,
            fontSize: fit(title, size, 26, size * 0.62) * u,
            lineHeight: 0.98,
            letterSpacing: 1 * u,
            marginTop: (kicker ? 22 : 0) * u,
          }}
        >
          <Rich text={title} />
        </div>
      ) : null}
      <div
        style={{
          height: 8 * u,
          width: `${rule * 14}%`,
          minWidth: rule * 90 * u,
          background: PC.red,
          marginTop: 22 * u,
          marginLeft: align === "center" ? "auto" : 0,
          marginRight: align === "center" ? "auto" : 0,
        }}
      />
    </div>
  );
};

/** Source line bottom-left, show mark bottom-right. */
export const Footer: React.FC<{ source?: string }> = ({ source }) => {
  const { u } = usePanel();
  const p = useBuild(0, 1, 0.3, FADE + 10, 14);
  return (
    <div
      style={{
        position: "absolute",
        left: 64 * u,
        right: 64 * u,
        bottom: 34 * u,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-end",
        opacity: p,
      }}
    >
      <div style={{ color: PC.muted, fontWeight: 600, fontSize: 30 * u, maxWidth: "75%" }}>{source ? `Source: ${source}` : ""}</div>
      <div style={{ fontFamily: DISPLAY, fontSize: 34 * u, letterSpacing: 2 * u, color: "rgba(255,255,255,0.28)" }}>ON THE GROUND</div>
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
          left: 72 * u,
          right: 72 * u,
          top: 64 * u,
          bottom: 100 * u,
          display: "flex",
          flexDirection: "column",
          // "safe": content taller than the pane overflows downward, never off the top.
          justifyContent: center ? "safe center" : "flex-start",
          gap: 44 * u,
        }}
      >
        <Header kicker={kicker} title={title} size={titleSize} />
        <div style={{ flex: center ? "none" : 1, minHeight: 0 }}>{children}</div>
      </div>
      <Footer source={source} />
    </PanelBg>
  );
};

/** A frosted block the content is built from. */
export const Block: React.FC<{ children: React.ReactNode; tone?: "none" | "red" | "paper"; pad?: number; style?: React.CSSProperties }> = ({
  children,
  tone = "none",
  pad = 34,
  style,
}) => {
  const { u } = usePanel();
  const bg = { none: PC.panel, red: "rgba(224,22,29,0.14)", paper: PC.paper }[tone];
  const edge = { none: PC.edge, red: "rgba(224,22,29,0.6)", paper: "rgba(0,0,0,0.1)" }[tone];
  return (
    <div
      style={{
        position: "relative",
        background: bg,
        border: `${2 * u}px solid ${edge}`,
        borderRadius: 18 * u,
        padding: pad * u,
        color: tone === "paper" ? PC.ink : PC.white,
        boxShadow: `inset 0 ${2 * u}px 0 rgba(255,255,255,0.06), 0 ${18 * u}px ${44 * u}px rgba(0,0,0,0.4)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const panelAsset = (p: string) => (/^(https?:|data:)/.test(p) ? p : staticFile(p));

export const fmt = (v: number, decimals = 0) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
