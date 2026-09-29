// Full-screen templates: they replace the picture, for information too big or
// too structured for a card — a list of conditions, a sequence of events, a
// side-by-side, a long article. All built on FullFrame (flat background, the
// header, the block centred between the logo zone and the captions), with
// hairline rules between items rather than boxes around them.
//
// Every size here is in 1080-wide design units, and the content block has
// roughly 800 of them vertically between the reserved zones — a header takes
// ~200, so content is sized to fit ~600, with a denser layout past four items.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, DISPLAY, FullFrame, Rule, assetSrc, fitSize, formatNumber, reveal, useStagger, useUnit } from "../theme";

type Framed = { kicker?: string; title?: string; source?: string };

const longest = (xs: string[]) => xs.reduce((m, x) => Math.max(m, x.length), 0);

// ── Breakdown ────────────────────────────────────────────────────────────────

export type BreakdownProps = Framed & { points: string[] };

export const Breakdown: React.FC<BreakdownProps> = ({ kicker, title, source, points }) => {
  const shown = points.slice(0, 6);
  const dense = shown.length > 4;
  const size = Math.min(fitSize("x".repeat(longest(shown)), 54, 30, 40), dense ? 42 : 54);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      {shown.map((p, i) => (
        <BreakdownRow key={i} i={i} n={shown.length} text={p} size={size} dense={dense} />
      ))}
    </FullFrame>
  );
};

const BreakdownRow: React.FC<{ i: number; n: number; text: string; size: number; dense: boolean }> = ({ i, n, text, size, dense }) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div style={reveal(p, u)}>
      {i > 0 ? <Rule /> : null}
      <div style={{ display: "flex", alignItems: "baseline", gap: 30 * u, padding: `${(dense ? 16 : 24) * u}px 0` }}>
        <div
          style={{
            flex: "none",
            width: (dense ? 56 : 70) * u,
            fontFamily: DISPLAY,
            fontWeight: 700,
            fontSize: (dense ? 64 : 84) * u,
            lineHeight: 0.9,
            color: COLORS.accent,
          }}
        >
          {i + 1}
        </div>
        <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.2 }}>{text}</div>
      </div>
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
  const size = Math.min(fitSize("x".repeat(longest(shown.map((e) => e.text))), 50, 28, 38), dense ? 40 : 50);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ position: "relative", paddingLeft: 48 * u }}>
        {/* The spine: a hairline, with the red progress drawing down it. */}
        <div style={{ position: "absolute", left: 7 * u, top: 12 * u, bottom: 12 * u, width: Math.max(1, 2 * u), background: COLORS.rule }}>
          <div style={{ width: Math.max(2, 3 * u), marginLeft: -0.5 * u, height: `${line * 100}%`, background: COLORS.accent }} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 22 : 36) * u }}>
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
    <div style={{ position: "relative", ...reveal(p, u) }}>
      <div
        style={{
          position: "absolute",
          left: -48 * u,
          top: 10 * u,
          width: 16 * u,
          height: 16 * u,
          background: last ? COLORS.accent : COLORS.text,
        }}
      />
      <div
        style={{
          fontFamily: DISPLAY,
          fontWeight: 700,
          fontSize: 38 * u,
          lineHeight: 1,
          textTransform: "uppercase",
          color: last ? COLORS.accent : COLORS.muted,
        }}
      >
        {event.date}
      </div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.2, marginTop: 8 * u }}>{event.text}</div>
    </div>
  );
};

// ── Compare ──────────────────────────────────────────────────────────────────

type Side = { name: string; points: string[] };
export type CompareProps = Framed & { left: Side; right: Side; verdict?: string };

export const Compare: React.FC<CompareProps> = ({ kicker, title, source, left, right, verdict }) => {
  const u = useUnit();
  const rows = Math.max(left.points.length, right.points.length, 1);
  const size = fitSize("x".repeat(longest([...left.points, ...right.points])), 42, 18, 32);
  const v = useStagger(rows, rows + 1);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", gap: 36 * u }}>
        {[left, right].map((side, s) => (
          <React.Fragment key={s}>
            {s === 1 ? <Rule vertical /> : null}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontFamily: DISPLAY,
                  fontWeight: 700,
                  fontSize: fitSize(side.name, 64, 10, 44) * u,
                  lineHeight: 1,
                  textTransform: "uppercase",
                  color: s === 0 ? COLORS.text : COLORS.accent,
                  paddingBottom: 18 * u,
                }}
              >
                {side.name}
              </div>
              {side.points.slice(0, 5).map((p, i) => (
                <CompareRow key={i} i={i} n={rows} text={p} size={size} />
              ))}
            </div>
          </React.Fragment>
        ))}
      </div>
      {verdict ? (
        <div style={{ display: "flex", alignItems: "stretch", gap: 24 * u, marginTop: 40 * u, ...reveal(v, u) }}>
          <div style={{ flex: "none", width: 10 * u, background: COLORS.brand }} />
          <div style={{ fontWeight: 700, fontSize: fitSize(verdict, 46, 30, 34) * u, lineHeight: 1.2, padding: `${4 * u}px 0` }}>{verdict}</div>
        </div>
      ) : null}
    </FullFrame>
  );
};

const CompareRow: React.FC<{ i: number; n: number; text: string; size: number }> = ({ i, n, text, size }) => {
  const u = useUnit();
  const p = useStagger(i, n);
  return (
    <div style={reveal(p, u)}>
      <Rule />
      <div style={{ fontWeight: 400, fontSize: size * u, lineHeight: 1.22, padding: `${14 * u}px 0` }}>{text}</div>
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
      <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 18 : 30) * u }}>
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
  const grow =
    appear *
    interpolate(frame, [0, Math.max(10, durationInFrames * 0.45)], [0.6, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
  const hl = !!item.highlight;
  const colour = hl ? COLORS.accent : COLORS.text;
  return (
    <div style={{ opacity: appear }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 * u }}>
        <span style={{ fontWeight: hl ? 700 : 400, fontSize: (dense ? 32 : 40) * u, color: hl ? COLORS.text : COLORS.muted }}>{item.label}</span>
        <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: (dense ? 46 : 60) * u, color: colour, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
          {prefix}
          {formatNumber(item.value * grow, decimals)}
          {suffix}
        </span>
      </div>
      <div style={{ height: (dense ? 18 : 26) * u, background: "#1E1E1E" }}>
        <div style={{ height: "100%", width: `${(Math.abs(item.value) / max) * 100 * grow}%`, background: colour }} />
      </div>
    </div>
  );
};

// ── Quote ────────────────────────────────────────────────────────────────────

export type QuoteProps = Framed & { quote: string; author: string; role?: string };

// Large Helvetica Bold against a brand-red bar; the author in the condensed
// face, the role in grey. No giant quote-mark glyph.
export const Quote: React.FC<QuoteProps> = ({ kicker, title, source, quote, author, role }) => {
  const u = useUnit();
  const q = useStagger(0, 2, 0.25);
  const a = useStagger(1, 2, 0.35);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", alignItems: "stretch", gap: 36 * u }}>
        <div style={{ flex: "none", width: 12 * u, background: COLORS.brand }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: fitSize(quote, 72, 50, 48) * u, lineHeight: 1.18, ...reveal(q, u) }}>{quote}</div>
          <div style={{ marginTop: 40 * u, ...reveal(a, u) }}>
            <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 46 * u, lineHeight: 1.05, textTransform: "uppercase" }}>{author}</div>
            {role ? <div style={{ color: COLORS.muted, fontWeight: 400, fontSize: 32 * u, marginTop: 8 * u }}>{role}</div> : null}
          </div>
        </div>
      </div>
    </FullFrame>
  );
};

// ── Scroll ───────────────────────────────────────────────────────────────────

export type ScrollProps = Framed & { image: string };

// A long screenshot — an article, a filing, a thread — scrolled top to bottom
// through a plain window. Hold the top so the headline registers, then scroll,
// then hold the end.
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
      <div style={{ border: `${Math.max(1, 2 * u)}px solid ${COLORS.rule}` }}>
        {source ? (
          <div style={{ padding: `${12 * u}px ${20 * u}px`, color: COLORS.muted, fontWeight: 400, fontSize: 26 * u, borderBottom: `${Math.max(1, 2 * u)}px solid ${COLORS.rule}` }}>
            {source}
          </div>
        ) : null}
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
      </div>
    </FullFrame>
  );
};
