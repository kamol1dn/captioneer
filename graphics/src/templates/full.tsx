// Full-screen templates: they replace the picture, for information too big or
// too structured for a card — a list of conditions, a sequence of events, a
// side-by-side, a long article. All built on FullFrame, so they share the
// background, the entrance and the caption-safe layout.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FullFrame, assetSrc, fitSize, formatNumber, useStagger, useUnit } from "../theme";

type Framed = { kicker?: string; title?: string; source?: string };

// ── Breakdown ────────────────────────────────────────────────────────────────

export type BreakdownProps = Framed & { points: string[] };

export const Breakdown: React.FC<BreakdownProps> = ({ kicker, title, source, points }) => {
  const u = useUnit();
  const shown = points.slice(0, 6);
  const longest = shown.reduce((m, p) => Math.max(m, p.length), 0);
  // Fewer, shorter points get bigger type; six long ones still fit the region.
  const size = Math.min(fitSize("x".repeat(longest), 62, 24, 42), shown.length > 4 ? 48 : 62);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", flexDirection: "column", gap: (shown.length > 4 ? 30 : 46) * u }}>
        {shown.map((p, i) => (
          <BreakdownRow key={i} i={i} n={shown.length} text={p} size={size} />
        ))}
      </div>
    </FullFrame>
  );
};

const BreakdownRow: React.FC<{ i: number; n: number; text: string; size: number }> = ({ i, n, text, size }) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 28 * u,
        opacity: p,
        transform: `translateX(${(1 - p) * 40 * u}px)`,
      }}
    >
      <div
        style={{
          flex: "none",
          width: 86 * u,
          height: 86 * u,
          borderRadius: 22 * u,
          background: COLORS.accent,
          color: COLORS.accentInk,
          fontWeight: 900,
          fontSize: 48 * u,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {i + 1}
      </div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.22 }}>{text}</div>
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
  const line = interpolate(frame, [10, Math.max(20, durationInFrames * 0.4)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const longest = shown.reduce((m, e) => Math.max(m, e.text.length), 0);
  const size = fitSize("x".repeat(longest), 58, 26, 40);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ position: "relative", paddingLeft: 56 * u }}>
        <div
          style={{
            position: "absolute",
            left: 14 * u,
            top: 10 * u,
            bottom: 10 * u,
            width: 6 * u,
            borderRadius: 3 * u,
            background: "rgba(255,255,255,0.14)",
          }}
        >
          <div style={{ width: "100%", height: `${line * 100}%`, background: COLORS.accent, borderRadius: 3 * u }} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: (shown.length > 4 ? 34 : 54) * u }}>
          {shown.map((e, i) => (
            <TimelineRow key={i} i={i} n={shown.length} event={e} size={size} last={i === shown.length - 1} />
          ))}
        </div>
      </div>
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
          left: -56 * u + 3 * u,
          top: 8 * u,
          width: 28 * u,
          height: 28 * u,
          borderRadius: 14 * u,
          background: last ? COLORS.accent : "#0B0C10",
          border: `${5 * u}px solid ${COLORS.accent}`,
          boxSizing: "border-box",
          transform: `scale(${p})`,
        }}
      />
      <div style={{ color: COLORS.accent, fontWeight: 800, fontSize: 40 * u, letterSpacing: 1 * u }}>{event.date}</div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.22, marginTop: 6 * u }}>{event.text}</div>
    </div>
  );
};

// ── Compare ──────────────────────────────────────────────────────────────────

type Side = { name: string; points: string[] };
export type CompareProps = Framed & { left: Side; right: Side; verdict?: string };

export const Compare: React.FC<CompareProps> = ({ kicker, title, source, left, right, verdict }) => {
  const u = useUnit();
  const rows = Math.max(left.points.length, right.points.length, 1);
  const all = [...left.points, ...right.points];
  const longest = all.reduce((m, p) => Math.max(m, p.length), 0);
  const size = fitSize("x".repeat(longest), 46, 16, 32);
  const v = useStagger(rows, rows + 1);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", gap: 28 * u }}>
        {[left, right].map((side, s) => (
          <div
            key={s}
            style={{
              flex: 1,
              background: s === 0 ? "rgba(255,255,255,0.06)" : "rgba(255,220,0,0.08)",
              border: `${2 * u}px solid ${s === 0 ? "rgba(255,255,255,0.1)" : "rgba(255,220,0,0.35)"}`,
              borderRadius: 26 * u,
              padding: `${30 * u}px ${28 * u}px`,
            }}
          >
            <div
              style={{
                fontWeight: 900,
                fontSize: fitSize(side.name, 60, 9, 38) * u,
                color: s === 0 ? COLORS.text : COLORS.accent,
                marginBottom: 22 * u,
              }}
            >
              {side.name}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 18 * u }}>
              {side.points.slice(0, 5).map((p, i) => (
                <CompareRow key={i} i={i} n={rows} text={p} size={size} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {verdict ? (
        <div
          style={{
            marginTop: 34 * u,
            fontWeight: 800,
            fontSize: fitSize(verdict, 54, 32, 38) * u,
            lineHeight: 1.2,
            opacity: v,
            transform: `translateY(${(1 - v) * 16 * u}px)`,
          }}
        >
          {verdict}
        </div>
      ) : null}
    </FullFrame>
  );
};

const CompareRow: React.FC<{ i: number; n: number; text: string; size: number }> = ({ i, n, text, size }) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div style={{ fontWeight: 600, fontSize: size * u, lineHeight: 1.22, opacity: p, transform: `translateY(${(1 - p) * 12 * u}px)` }}>
      {text}
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
      <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 26 : 44) * u }}>
        {shown.map((item, i) => (
          <ChartRow key={i} i={i} n={shown.length} item={item} max={max} prefix={prefix} suffix={suffix} decimals={decimals} dense={dense} />
        ))}
      </div>
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
  const grow = interpolate(appear, [0, 1], [0, 1]) *
    interpolate(frame, [0, Math.max(10, durationInFrames * 0.45)], [0.6, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
  const colour = item.highlight ? COLORS.accent : "rgba(255,255,255,0.8)";
  return (
    <div style={{ opacity: appear }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontWeight: 700,
          fontSize: (dense ? 40 : 52) * u,
          marginBottom: 10 * u,
        }}
      >
        <span>{item.label}</span>
        <span style={{ color: colour, fontVariantNumeric: "tabular-nums" }}>
          {prefix}
          {formatNumber(item.value * grow, decimals)}
          {suffix}
        </span>
      </div>
      <div style={{ height: (dense ? 30 : 46) * u, borderRadius: 23 * u, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${(Math.abs(item.value) / max) * 100 * grow}%`, background: colour, borderRadius: 18 * u }} />
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
    <FullFrame kicker={kicker} title={title} source={source} align="center">
      <div style={{ color: COLORS.accent, fontWeight: 900, fontSize: 220 * u, lineHeight: 0.7, height: 90 * u }}>“</div>
      <div
        style={{
          fontWeight: 700,
          fontSize: fitSize(quote, 78, 56, 50) * u,
          lineHeight: 1.25,
          opacity: q,
          transform: `translateY(${(1 - q) * 20 * u}px)`,
        }}
      >
        {quote}
      </div>
      <div style={{ marginTop: 36 * u, opacity: a }}>
        <div style={{ fontWeight: 800, fontSize: 50 * u }}>{author}</div>
        {role ? <div style={{ color: COLORS.muted, fontWeight: 600, fontSize: 38 * u, marginTop: 8 * u }}>{role}</div> : null}
      </div>
    </FullFrame>
  );
};

// ── Scroll ───────────────────────────────────────────────────────────────────

export type ScrollProps = Framed & { image: string };

// A long screenshot — an article, a filing, a thread — scrolled top to bottom
// over the entry. The window is the same caption-safe region as everything
// else, so the captions never sit on the text being scrolled.
export const Scroll: React.FC<ScrollProps> = ({ kicker, title, source, image }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // Hold the top for a beat so the headline registers, then scroll, then hold.
  const t = interpolate(frame, [durationInFrames * 0.18, durationInFrames * 0.85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div
        style={{
          position: "relative",
          height: "100%",
          borderRadius: 24 * u,
          overflow: "hidden",
          border: `${2 * u}px solid rgba(255,255,255,0.12)`,
          background: "#fff",
          // Makes cqh below mean "percent of this window's height".
          containerType: "size",
        }}
      >
        {image ? (
          <Img
            src={assetSrc(image)}
            style={{
              position: "absolute",
              width: "100%",
              top: 0,
              // translateY percentages are of the image's own height, so this
              // ends with the image's bottom at the window's bottom.
              transform: `translateY(calc(${-t * 100}% + ${t * 100}cqh))`,
            }}
          />
        ) : null}
      </div>
    </FullFrame>
  );
};
