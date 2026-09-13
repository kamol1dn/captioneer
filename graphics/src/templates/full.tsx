// Full-screen templates: they replace the picture, for information too big or
// too structured for a card — a list of conditions, a sequence of events, a
// side-by-side, a long article. All built on FullFrame (background, entrance,
// the block centred between the logo zone and the captions) and Glass panels,
// so they read as one family.
//
// Every size here is in 1080-wide design units, and the content block has
// roughly 800 of them vertically between the reserved zones — a title takes
// ~250, so content is sized to fit ~550, with a denser layout past four items.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FullFrame, Glass, assetSrc, fitSize, formatNumber, useStagger, useUnit } from "../theme";

type Framed = { kicker?: string; title?: string; source?: string };

const longest = (xs: string[]) => xs.reduce((m, x) => Math.max(m, x.length), 0);
const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");

// ── Breakdown ────────────────────────────────────────────────────────────────

export type BreakdownProps = Framed & { points: string[] };

export const Breakdown: React.FC<BreakdownProps> = ({ kicker, title, source, points }) => {
  const u = useUnit();
  const shown = points.slice(0, 6);
  const dense = shown.length > 4;
  const size = Math.min(fitSize("x".repeat(longest(shown)), 56, 30, 40), dense ? 42 : 56);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 12 : 20) * u }}>
        {shown.map((p, i) => (
          <BreakdownRow key={i} i={i} n={shown.length} text={p} size={size} dense={dense} />
        ))}
      </div>
    </FullFrame>
  );
};

const BreakdownRow: React.FC<{ i: number; n: number; text: string; size: number; dense: boolean }> = ({
  i,
  n,
  text,
  size,
  dense,
}) => {
  const u = useUnit();
  const p = useStagger(i, n);
  // The row that has just landed glows briefly, so the eye follows the count.
  const glow = interpolate(p, [0.6, 1], [0, 1], { extrapolateLeft: "clamp" });
  const badge = (dense ? 50 : 68) * u;
  return (
    <div style={{ opacity: p, transform: `translateX(${(1 - p) * 60 * u}px)` }}>
      <Glass padding={dense ? 14 : 22} style={{ display: "flex", alignItems: "center", gap: 24 * u }}>
        <div
          style={{
            flex: "none",
            width: badge,
            height: badge,
            borderRadius: badge * 0.3,
            background: `linear-gradient(145deg, ${COLORS.accent}, #FFB800)`,
            color: COLORS.accentInk,
            fontWeight: 900,
            fontSize: badge * 0.55,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: `0 0 ${28 * u * glow}px rgba(255,220,0,${0.55 * glow})`,
          }}
        >
          {i + 1}
        </div>
        <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.2 }}>{text}</div>
      </Glass>
    </div>
  );
};

// ── Timeline ─────────────────────────────────────────────────────────────────

export type TimelineProps = Framed & { events: { date: string; text: string }[] };

export const Timeline: React.FC<TimelineProps> = ({ kicker, title, source, events }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const shown = events.slice(0, 6);
  const dense = shown.length > 4;
  const line = interpolate(frame, [10, Math.max(20, durationInFrames * 0.42)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const size = Math.min(fitSize("x".repeat(longest(shown.map((e) => e.text))), 52, 28, 38), dense ? 40 : 52);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <Glass padding={dense ? 24 : 34}>
        <div style={{ position: "relative", paddingLeft: 60 * u }}>
          <div
            style={{
              position: "absolute",
              left: 16 * u,
              top: 14 * u,
              bottom: 14 * u,
              width: 6 * u,
              borderRadius: 3 * u,
              background: "rgba(255,255,255,0.12)",
            }}
          >
            <div
              style={{
                width: "100%",
                height: `${line * 100}%`,
                borderRadius: 3 * u,
                background: `linear-gradient(180deg, ${COLORS.cyan}, ${COLORS.accent})`,
                boxShadow: `0 0 ${16 * u}px rgba(255,220,0,0.5)`,
              }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 20 : 34) * u }}>
            {shown.map((e, i) => (
              <TimelineRow key={i} i={i} n={shown.length} event={e} size={size} last={i === shown.length - 1} />
            ))}
          </div>
        </div>
      </Glass>
    </FullFrame>
  );
};

const TimelineRow: React.FC<{ i: number; n: number; event: { date: string; text: string }; size: number; last: boolean }> = ({
  i,
  n,
  event,
  size,
  last,
}) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div style={{ position: "relative", opacity: p, transform: `translateY(${(1 - p) * 20 * u}px)` }}>
      <div
        style={{
          position: "absolute",
          left: -60 * u + 5 * u,
          top: 8 * u,
          width: 28 * u,
          height: 28 * u,
          borderRadius: 14 * u,
          background: last ? COLORS.accent : "#0B0D12",
          border: `${5 * u}px solid ${last ? COLORS.accent : COLORS.cyan}`,
          boxSizing: "border-box",
          transform: `scale(${p})`,
          boxShadow: last ? `0 0 ${22 * u}px rgba(255,220,0,0.7)` : "none",
        }}
      />
      <div
        style={{
          display: "inline-block",
          color: last ? COLORS.accentInk : COLORS.cyan,
          background: last ? COLORS.accent : "rgba(25,224,214,0.12)",
          fontWeight: 800,
          fontSize: 28 * u,
          letterSpacing: 1.5 * u,
          textTransform: "uppercase",
          padding: `${4 * u}px ${14 * u}px`,
          borderRadius: 10 * u,
        }}
      >
        {event.date}
      </div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.2, marginTop: 10 * u }}>{event.text}</div>
    </div>
  );
};

// ── Compare ──────────────────────────────────────────────────────────────────

type Side = { name: string; points: string[] };
export type CompareProps = Framed & { left: Side; right: Side; verdict?: string };

export const Compare: React.FC<CompareProps> = ({ kicker, title, source, left, right, verdict }) => {
  const u = useUnit();
  const rows = Math.max(left.points.length, right.points.length, 1);
  const size = fitSize("x".repeat(longest([...left.points, ...right.points])), 46, 18, 34);
  const vs = useStagger(0, 1, 0.1, 8);
  const v = useStagger(rows, rows + 1);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ position: "relative", display: "flex", gap: 26 * u }}>
        {[left, right].map((side, s) => (
          <Glass key={s} tint={s === 0 ? "cyan" : "accent"} padding={28} style={{ flex: 1 }}>
            <div
              style={{
                fontWeight: 900,
                fontSize: fitSize(side.name, 58, 9, 40) * u,
                color: s === 0 ? COLORS.cyan : COLORS.accent,
                lineHeight: 1.05,
              }}
            >
              {side.name}
            </div>
            <div
              style={{
                height: 5 * u,
                width: 70 * u,
                borderRadius: 3 * u,
                background: s === 0 ? COLORS.cyan : COLORS.accent,
                margin: `${14 * u}px 0 ${20 * u}px`,
              }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 16 * u }}>
              {side.points.slice(0, 5).map((p, i) => (
                <CompareRow key={i} i={i} n={rows} text={p} size={size} colour={s === 0 ? COLORS.cyan : COLORS.accent} />
              ))}
            </div>
          </Glass>
        ))}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: 30 * u,
            width: 72 * u,
            height: 72 * u,
            marginLeft: -36 * u,
            borderRadius: 36 * u,
            background: "#0B0D12",
            border: `${3 * u}px solid rgba(255,255,255,0.25)`,
            color: COLORS.text,
            fontWeight: 900,
            fontSize: 26 * u,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: `scale(${vs})`,
          }}
        >
          VS
        </div>
      </div>
      {verdict ? (
        <div style={{ marginTop: 24 * u, opacity: v, transform: `translateY(${(1 - v) * 16 * u}px)` }}>
          <Glass padding={24} style={{ borderLeft: `${8 * u}px solid ${COLORS.accent}` }}>
            <div style={{ fontWeight: 800, fontSize: fitSize(verdict, 46, 30, 34) * u, lineHeight: 1.2 }}>{verdict}</div>
          </Glass>
        </div>
      ) : null}
    </FullFrame>
  );
};

const CompareRow: React.FC<{ i: number; n: number; text: string; size: number; colour: string }> = ({ i, n, text, size, colour }) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div
      style={{
        display: "flex",
        gap: 14 * u,
        alignItems: "baseline",
        opacity: p,
        transform: `translateY(${(1 - p) * 12 * u}px)`,
      }}
    >
      <span
        style={{
          flex: "none",
          width: 12 * u,
          height: 12 * u,
          borderRadius: 6 * u,
          background: colour,
          transform: `translateY(${-3 * u}px)`,
        }}
      />
      <span style={{ fontWeight: 600, fontSize: size * u, lineHeight: 1.22 }}>{text}</span>
    </div>
  );
};

// ── Chart ────────────────────────────────────────────────────────────────────

export type ChartProps = Framed & {
  items: { label: string; value: number; highlight?: boolean }[];
  prefix?: string;
  suffix?: string;
  decimals?: number;
};

export const Chart: React.FC<ChartProps> = ({ kicker, title, source, items, prefix = "", suffix = "", decimals = 0 }) => {
  const u = useUnit();
  const shown = items.slice(0, 8);
  const max = Math.max(...shown.map((i) => Math.abs(i.value)), 1e-9);
  const dense = shown.length > 5;
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <Glass padding={dense ? 24 : 34}>
        <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 16 : 28) * u }}>
          {shown.map((item, i) => (
            <ChartRow key={i} i={i} n={shown.length} item={item} max={max} prefix={prefix} suffix={suffix} decimals={decimals} dense={dense} />
          ))}
        </div>
      </Glass>
    </FullFrame>
  );
};

const ChartRow: React.FC<{
  i: number;
  n: number;
  item: { label: string; value: number; highlight?: boolean };
  max: number;
  prefix: string;
  suffix: string;
  decimals: number;
  dense: boolean;
}> = ({ i, n, item, max, prefix, suffix, decimals, dense }) => {
  const u = useUnit();
  const appear = useStagger(i, n, 0.3);
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const grow =
    appear *
    interpolate(frame, [0, Math.max(10, durationInFrames * 0.45)], [0.6, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
  const hl = !!item.highlight;
  const bar = hl
    ? `linear-gradient(90deg, #FFB800, ${COLORS.accent})`
    : "linear-gradient(90deg, rgba(255,255,255,0.45), rgba(255,255,255,0.8))";
  return (
    <div style={{ opacity: appear }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          fontWeight: 700,
          fontSize: (dense ? 34 : 44) * u,
          marginBottom: 10 * u,
        }}
      >
        <span style={{ color: hl ? COLORS.accent : COLORS.text }}>{item.label}</span>
        <span style={{ color: hl ? COLORS.accent : COLORS.text, fontWeight: 900, fontVariantNumeric: "tabular-nums" }}>
          {prefix}
          {formatNumber(item.value * grow, decimals)}
          {suffix}
        </span>
      </div>
      <div style={{ height: (dense ? 22 : 34) * u, borderRadius: 17 * u, background: "rgba(255,255,255,0.07)", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${(Math.abs(item.value) / max) * 100 * grow}%`,
            background: bar,
            borderRadius: 17 * u,
            boxShadow: hl ? `0 0 ${22 * u}px rgba(255,220,0,0.55)` : "none",
          }}
        />
      </div>
    </div>
  );
};

// ── Quote ────────────────────────────────────────────────────────────────────

export type QuoteProps = Framed & { quote: string; author: string; role?: string };

export const Quote: React.FC<QuoteProps> = ({ kicker, title, source, quote, author, role }) => {
  const u = useUnit();
  const q = useStagger(0, 2, 0.25);
  const a = useStagger(1, 2, 0.35);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <Glass padding={44} style={{ overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            right: 24 * u,
            top: -70 * u,
            color: COLORS.accent,
            opacity: 0.16,
            fontWeight: 900,
            fontSize: 380 * u,
            lineHeight: 1,
          }}
        >
          ”
        </div>
        <div style={{ color: COLORS.accent, fontWeight: 900, fontSize: 150 * u, lineHeight: 0.6, height: 70 * u }}>“</div>
        <div
          style={{
            position: "relative",
            fontWeight: 700,
            fontSize: fitSize(quote, 60, 60, 42) * u,
            lineHeight: 1.26,
            opacity: q,
            transform: `translateY(${(1 - q) * 20 * u}px)`,
          }}
        >
          {quote}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 * u, marginTop: 34 * u, opacity: a }}>
          <div
            style={{
              flex: "none",
              width: 84 * u,
              height: 84 * u,
              borderRadius: 42 * u,
              background: `linear-gradient(145deg, ${COLORS.accent}, ${COLORS.cyan})`,
              color: COLORS.accentInk,
              fontWeight: 900,
              fontSize: 34 * u,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {initials(author)}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 44 * u }}>{author}</div>
            {role ? <div style={{ color: COLORS.muted, fontWeight: 600, fontSize: 32 * u, marginTop: 4 * u }}>{role}</div> : null}
          </div>
        </div>
      </Glass>
    </FullFrame>
  );
};

// ── Scroll ───────────────────────────────────────────────────────────────────

export type ScrollProps = Framed & { image: string };

// A long screenshot — an article, a filing, a thread — scrolled top to bottom
// through a browser-like window. Hold the top so the headline registers, then
// scroll, then hold the end.
export const Scroll: React.FC<ScrollProps> = ({ kicker, title, source, image }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [durationInFrames * 0.18, durationInFrames * 0.85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  return (
    <FullFrame kicker={kicker} title={title}>
      <Glass padding={0} style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10 * u,
            padding: `${14 * u}px ${20 * u}px`,
            background: "rgba(255,255,255,0.06)",
            borderBottom: `${2 * u}px solid rgba(255,255,255,0.1)`,
          }}
        >
          {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
            <span key={c} style={{ width: 16 * u, height: 16 * u, borderRadius: 8 * u, background: c }} />
          ))}
          <span style={{ marginLeft: 12 * u, color: COLORS.muted, fontWeight: 600, fontSize: 26 * u }}>{source || ""}</span>
        </div>
        <div style={{ position: "relative", height: 520 * u, overflow: "hidden", background: "#fff", containerType: "size" }}>
          {image ? (
            <Img
              src={assetSrc(image)}
              style={{
                position: "absolute",
                width: "100%",
                top: 0,
                // Percentages of the image's own height; ends with its bottom on the window's.
                transform: `translateY(calc(${-t * 100}% + ${t * 100}cqh))`,
              }}
            />
          ) : null}
        </div>
      </Glass>
    </FullFrame>
  );
};
