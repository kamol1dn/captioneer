// Shared look and motion for every shorts template.
//
// The show's own broadcast language, not a motion-graphics kit: Helvetica only,
// flat near-black, white type, the layout's brand red as solid bars and bands,
// hairline rules between items instead of boxes, square corners. The bright red
// is an accent only — a number, one emphasised phrase, a thin rule. No
// gradients, glows, pills or scale pops; things fade in with a small slide.
//
// Everything is drawn in "units" of a 1080-wide frame, so the same template
// renders correctly at 1080x1920 and at the 1440x2560 the OTG episodes use —
// the renderer only ever changes the composition size, never the design.
import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

// Own family names, so these never collide with the long-form panels' faces
// (panel/theme.tsx) when both are registered in one bundle.
export const FONT = "Shorts Helvetica";
export const DISPLAY = "Shorts Helvetica Condensed";
const faces: [string, string, string][] = [
  [FONT, "fonts/Helvetica-Light.ttf", "300"],
  [FONT, "fonts/Helvetica.ttf", "400"],
  [FONT, "fonts/Helvetica-Medium.otf", "500"],
  [FONT, "fonts/Helvetica-Bold.ttf", "700"],
  // The show's headline-bar face: titles, names, numbers, dates, uppercase.
  [DISPLAY, "fonts/HelveticaNeue-CondensedBold.ttf", "700"],
];
// Renders wait on these through delayRender inside loadFont, so text never
// rasterises in a fallback face and then pops.
for (const [family, url, weight] of faces) void loadFont({ family, url: staticFile(url), weight });

export const COLORS = {
  bg: "#0B0B0B",
  text: "#FFFFFF",
  muted: "#9A9A9A",
  rule: "#333333",
  // The long-form layout's lower-third band: solid bars and bands.
  brand: "#880401",
  // Accent only: a number, one emphasised phrase, a thin rule. Also the
  // captions' highlight colour, so graphics and captions read as one system.
  accent: "#E0161D",
  // Text sitting on red.
  accentInk: "#FFFFFF",
};

export type Position = "top" | "center" | "bottom";

/** Pixels per design unit: 1 at 1080 wide. */
export const useUnit = () => useVideoConfig().width / 1080;

const EASE = Easing.out(Easing.cubic);
/** How far things travel on their way in, in design units. Small on purpose. */
export const SLIDE = 12;

/**
 * 0 -> 1 on the way in, 1 -> 0 on the way out. Every graphic enters and leaves
 * inside its own file, so nothing needs a dissolve applied in Premiere — which
 * matters, since a dissolve applied by hand does not survive a re-export.
 */
export const useEnterExit = (enterFrames = 10, exitFrames = 8) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const enter = interpolate(frame, [0, enterFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });
  const exit = interpolate(frame, [durationInFrames - exitFrames, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.cubic),
  });
  return { enter, exit, visible: Math.min(enter, exit) };
};

/** 0 -> 1 over ``frames`` starting at ``start``: the one reveal curve. */
export const useCue = (start: number, frames = 10) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [start, start + frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE,
  });
};

/** Fade plus a small rise, for a reveal value p in 0..1. */
export const reveal = (p: number, u: number, dx = 0): React.CSSProperties => ({
  opacity: p,
  transform: dx ? `translateX(${(1 - p) * dx * u}px)` : `translateY(${(1 - p) * SLIDE * u}px)`,
});

/**
 * The frame's reserved zones, as fractions of height.
 *
 * The top 20% carries the show's logo and the sponsor overlay, added in
 * Premiere — transparent and small, but graphics that sit under them read as
 * clutter. The captions sit around 66-78%, positioned by hand. Everything we
 * draw lives in the gap between.
 */
export const SAFE = { top: 0.215, bottom: 0.635, captions: [0.64, 0.8] as const, side: 100 };

/**
 * The sides are reserved too. On a tall phone (19.5:9 or 20:9) Reels, TikTok
 * and Shorts scale a 9:16 video to fill the screen's height, which crops ~9%
 * off the left and right. Everything that must be read stays inside the middle
 * SAFE_W design units; only backgrounds run to the frame's edge.
 */
export const SAFE_W = 1080 - 2 * SAFE.side;

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

/**
 * The card most templates sit on: a flat near-black block, square, with the
 * brand-red bar down its left edge — the show's lower-third signature. Flat
 * rather than translucent, so it reads over a bright wall without a shadow.
 */
export const Card: React.FC<{
  children: React.ReactNode;
  width?: number;
  padding?: number;
  style?: React.CSSProperties;
}> = ({ children, width = 900, padding = 44, style }) => {
  const u = useUnit();
  const { enter, exit } = useEnterExit();
  width = Math.min(width, SAFE_W);
  return (
    <div
      style={{
        width: width * u,
        boxSizing: "border-box",
        display: "flex",
        alignItems: "stretch",
        opacity: Math.min(enter, exit),
        transform: `translateY(${(1 - enter) * SLIDE * u}px)`,
      }}
    >
      <div style={{ flex: "none", width: 12 * u, background: COLORS.brand }} />
      <div
        style={{
          flex: 1,
          minWidth: 0,
          padding: padding * u,
          background: COLORS.bg,
          color: COLORS.text,
          fontFamily: FONT,
          ...style,
        }}
      >
        {children}
      </div>
    </div>
  );
};

/** A hairline between items: the structure, in place of boxes. */
export const Rule: React.FC<{ vertical?: boolean; color?: string; style?: React.CSSProperties }> = ({
  vertical,
  color = COLORS.rule,
  style,
}) => {
  const u = useUnit();
  return (
    <div
      style={
        vertical
          ? { flex: "none", width: Math.max(1, 2 * u), alignSelf: "stretch", background: color, ...style }
          : { flex: "none", height: Math.max(1, 2 * u), width: "100%", background: color, ...style }
      }
    />
  );
};

/** Small uppercase label, letter-spaced, grey. Not a pill. */
export const Kicker: React.FC<{ children: React.ReactNode; size?: number; color?: string; style?: React.CSSProperties }> = ({
  children,
  size = 28,
  color = COLORS.muted,
  style,
}) => {
  const u = useUnit();
  return (
    <div
      style={{
        fontFamily: FONT,
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

/** "Hokodo raised *$177M*" -> the marked words in red. A colour change, not a pill. */
export const rich = (text: string) => text.split("*").map((t, i) => ({ t, hl: i % 2 === 1 })).filter((p) => p.t);
export const plain = (text: string) => text.replace(/\*/g, "");
export const Rich: React.FC<{ text: string; color?: string }> = ({ text, color = COLORS.accent }) => (
  <>
    {rich(text).map((p, i) =>
      p.hl ? (
        <span key={i} style={{ color, fontWeight: 700 }}>
          {p.t}
        </span>
      ) : (
        <span key={i}>{p.t}</span>
      ),
    )}
  </>
);

export type SuperWord = { t: string; hl: boolean };

/**
 * Lines for a broadcast super (the hook, a punch line): breaks where the
 * thought breaks — after a sentence, and either side of the *marked* phrase —
 * and only wraps inside a piece that won't fit on one line, into lines of even
 * length. A newline in the text always breaks. ``maxChars`` is what fits the
 * width at the chosen size.
 */
export const superLines = (text: string, maxChars: number): SuperWord[][] => {
  const pieces: SuperWord[][] = [];
  for (const forced of text.split("\n")) {
    let cur: SuperWord[] = [];
    const flush = () => {
      if (cur.length) pieces.push(cur);
      cur = [];
    };
    rich(forced).forEach((part) => {
      if (part.hl) {
        flush();
        pieces.push([{ t: part.t.trim(), hl: true }]);
        return;
      }
      for (const w of part.t.trim().split(/\s+/).filter(Boolean)) {
        cur.push({ t: w, hl: false });
        if (/[.!?:]$/.test(w)) flush();
      }
      flush();
    });
    flush();
  }
  const width = (ws: SuperWord[]) => ws.reduce((m, w) => m + w.t.length, 0) + ws.length - 1;
  // A lone short word ("The *fabric*…") would stand on a line of its own:
  // keep it with the piece after it when they fit together.
  for (let i = pieces.length - 2; i >= 0; i--) {
    const p = pieces[i];
    if (p.length === 1 && !p[0].hl && p[0].t.length <= 4 && width([...p, ...pieces[i + 1]]) <= maxChars) {
      pieces.splice(i, 2, [...p, ...pieces[i + 1]]);
    }
  }
  const lines: SuperWord[][] = [];
  for (const piece of pieces) {
    const total = width(piece);
    if (total <= maxChars || piece.length === 1) {
      lines.push(piece);
      continue;
    }
    // The fewest lines that fit, as even as possible: widen the limit from the
    // even split until the greedy wrap needs no more lines than that.
    const n = Math.ceil(total / maxChars);
    const wrap = (limit: number) => {
      const out: SuperWord[][] = [];
      let cur: SuperWord[] = [];
      for (const w of piece) {
        if (cur.length && width([...cur, w]) > limit) {
          out.push(cur);
          cur = [];
        }
        cur.push(w);
      }
      if (cur.length) out.push(cur);
      return out;
    };
    let best = wrap(maxChars);
    for (let limit = Math.ceil(total / n); limit < maxChars; limit++) {
      const tried = wrap(limit);
      if (tried.length <= n) {
        best = tried;
        break;
      }
    }
    lines.push(...best);
  }
  return lines;
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
    easing: EASE,
  });
};

/**
 * Full-screen frame: replaces the picture for its duration.
 *
 * Flat near-black, laid out around the reserved zones rather than under them:
 * the logo and sponsor overlay own the top 20%, the captions own a band lower
 * down, and the whole block — header and content together — is centred in the
 * space between. Both zones are left as plain background, so the overlay and
 * the captions stay readable over it. The frame fades up over the speaker and
 * back off them; both are in the file's alpha, so it needs no transition.
 */
export const FullFrame: React.FC<{
  kicker?: string;
  title?: string;
  source?: string;
  children: React.ReactNode;
}> = ({ kicker, title, source, children }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { height, durationInFrames } = useVideoConfig();
  const bg = interpolate(frame, [0, 7], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const head = useCue(4);
  const body = useCue(8);
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill style={{ background: COLORS.bg, opacity: bg }} />
      <div
        style={{
          position: "absolute",
          left: SAFE.side * u,
          right: SAFE.side * u,
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
          <div style={{ flex: "none", marginBottom: 40 * u, ...reveal(head, u) }}>
            {kicker ? <Kicker style={{ marginBottom: 14 * u }}>{kicker}</Kicker> : null}
            {title ? (
              <div
                style={{
                  fontFamily: DISPLAY,
                  fontWeight: 700,
                  fontSize: fitSize(title, 92, 22, 62) * u,
                  lineHeight: 1.02,
                  textTransform: "uppercase",
                }}
              >
                {title}
              </div>
            ) : null}
            <Rule style={{ marginTop: 26 * u }} />
          </div>
        ) : null}
        <div style={{ flex: "none", opacity: body }}>{children}</div>
      </div>
      {source ? (
        <div
          style={{
            position: "absolute",
            left: SAFE.side * u,
            right: SAFE.side * u,
            bottom: height * 0.055,
            fontFamily: FONT,
            color: COLORS.muted,
            fontWeight: 400,
            fontSize: 26 * u,
            opacity: bg,
          }}
        >
          {source}
        </div>
      ) : null}
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
