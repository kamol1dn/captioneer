// Long-form panel templates. See ./theme.tsx for the frame they fill and the
// rules of the look: flat black, Helvetica, hairlines, red only where it counts.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import {
  BODY,
  DISPLAY,
  FADE,
  Footer,
  Framed,
  Header,
  Label,
  PC,
  Panel,
  PanelBg,
  Rich,
  Rule,
  fit,
  fmt,
  panelAsset,
  plain,
  rise,
  useBuild,
  useDrift,
  usePanel,
  useReveal,
} from "./theme";

const longest = (xs: string[]) => xs.reduce((m, x) => Math.max(m, plain(x).length), 0);
const pad2 = (i: number) => String(i + 1).padStart(2, "0");

/** A flat brand-red band with one line of white text — the show's lower third. */
const Band: React.FC<{ text: string; p: number; size?: number }> = ({ text, p, size = 50 }) => {
  const { u } = usePanel();
  return (
    <div style={{ ...rise(p, u), background: PC.brand, padding: `${20 * u}px ${30 * u}px`, fontWeight: 700, fontSize: fit(text, size, 46, size * 0.76) * u, lineHeight: 1.2 }}>
      {plain(text)}
    </div>
  );
};

// ── PShot: a web page ───────────────────────────────────────────────────────

type Rect = { x: number; y: number; w: number; h: number };
/**
 * A mark drawn onto the page, in image fractions. "marker" is a highlighter
 * stroke wiping left to right over a line of text; "box", "underline" and
 * "circle" are drawn in red. `at` is when it starts, as a fraction of the
 * graphic's duration.
 */
type Mark = Rect & { style?: "marker" | "box" | "underline" | "circle"; at?: number };
export type PShotProps = {
  image: string;
  imgW: number;
  imgH: number;
  url?: string;
  source?: string; // outlet on the strip above the page, e.g. "TECHCRUNCH · 8 SEP"
  x0?: number; // image fraction at the window's left edge (crop)
  x1?: number; // ... and right edge
  y0?: number; // image fraction at the window's top edge, start
  y1?: number; // ... and end (scrolls between them)
  zoom?: number; // end scale of the slow push-in
  s0?: number; // scroll starts at this fraction of the duration
  s1?: number; // ... and settles here
  path?: [number, number][]; // [fraction of duration, y0-style image fraction] keyframes; overrides y0/y1
  marks?: Mark[];
  spotlight?: boolean; // dim the page around the last box/circle
  caption?: string; // optional takeaway line under the page
  // Back-compat: a single red box.
  highlight?: Rect;
  highlightAt?: number;
};

const MarkView: React.FC<{ m: Mark; dispW: number; dispH: number; ix: number; scroll: number; spotlight: boolean }> = ({ m, dispW, dispH, ix, scroll, spotlight }) => {
  const { u } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const style = m.style ?? "marker";
  const start = durationInFrames * (m.at ?? 0.3);
  const len = style === "marker" ? 16 : 14;
  const p = interpolate(frame, [start, start + len], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  if (p <= 0) return null;
  const x = m.x * dispW + ix;
  const y = m.y * dispH - scroll;
  const w = m.w * dispW;
  const h = m.h * dispH;
  if (style === "marker") {
    // Highlighter: slightly ragged ends, multiplied onto the page so text stays black.
    return (
      <div
        style={{
          position: "absolute",
          left: x - 6 * u,
          top: y - 2 * u,
          width: (w + 12 * u) * p,
          height: h + 4 * u,
          background: "rgba(255, 214, 0, 0.6)",
          mixBlendMode: "multiply",
          borderRadius: `${3 * u}px ${8 * u}px ${5 * u}px ${9 * u}px`,
          transform: "rotate(-0.4deg)",
        }}
      />
    );
  }
  if (style === "underline") {
    return (
      <svg style={{ position: "absolute", left: x - 6 * u, top: y + h - 6 * u, overflow: "visible" }} width={w + 12 * u} height={24 * u}>
        <path
          d={`M0 ${10 * u} C ${w * 0.3} ${4 * u}, ${w * 0.7} ${16 * u}, ${w + 12 * u} ${8 * u}`}
          fill="none"
          stroke={PC.red}
          strokeWidth={7 * u}
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={`${p} 1`}
        />
      </svg>
    );
  }
  if (style === "circle") {
    const pad = 22 * u;
    const rx = w / 2 + pad;
    const ry = h / 2 + pad * 0.8;
    const cx = rx + 10 * u;
    const cy = ry + 10 * u;
    // One loop and a little overshoot, like a pen.
    const d = `M ${cx + rx * 0.2} ${cy - ry} A ${rx} ${ry} 0 1 0 ${cx + rx * 0.99} ${cy + ry * 0.1} A ${rx} ${ry} 0 0 0 ${cx - rx * 0.1} ${cy - ry * 1.04}`;
    return (
      <svg
        style={{ position: "absolute", left: x - pad - 10 * u, top: y - pad * 0.8 - 10 * u, overflow: "visible" }}
        width={rx * 2 + 20 * u}
        height={ry * 2 + 20 * u}
      >
        <path d={d} fill="none" stroke={PC.red} strokeWidth={7 * u} strokeLinecap="round" pathLength={1} strokeDasharray={`${p} 1`} />
      </svg>
    );
  }
  return (
    <div
      style={{
        position: "absolute",
        left: x - 10 * u,
        top: y - 8 * u,
        width: w + 20 * u,
        height: h + 16 * u,
        border: `${5 * u}px solid ${PC.red}`,
        opacity: p,
        boxShadow: spotlight ? `0 0 0 ${4000 * u}px rgba(0,0,0,${0.36 * p})` : "none",
      }}
    />
  );
};

export const PShot: React.FC<PShotProps> = ({
  image,
  imgW,
  imgH,
  url,
  source,
  x0 = 0,
  x1 = 1,
  y0 = 0,
  y1,
  zoom = 1.05,
  s0 = 0.12,
  s1 = 0.7,
  path,
  marks,
  spotlight = false,
  highlight,
  highlightAt = 0.3,
  caption,
}) => {
  const allMarks: Mark[] = marks ?? (highlight ? [{ ...highlight, style: "box", at: highlightAt }] : []);
  const focus = allMarks.length ? allMarks[allMarks.length - 1] : undefined;
  const { u, W, H } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = useDrift();
  const padL = 62 * u;
  const pad = 46 * u;
  const bar = 64 * u;
  const capH = caption ? 132 * u : 0;
  const winW = W - padL - pad;
  const winH = H - pad * 2 - capH - (caption ? 22 * u : 0);
  const viewH = winH - bar;
  // x0..x1 of the image spans the window: a crop onto the article column.
  const k = winW / ((x1 - x0) * imgW);
  const dispW = imgW * k;
  const dispH = imgH * k;
  const ix = -x0 * dispW;
  const maxScroll = Math.max(0, dispH - viewH);
  const end = y1 ?? y0;
  const s = interpolate(frame, [durationInFrames * s0, durationInFrames * Math.max(s0 + 0.05, s1)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const yAt =
    path && path.length > 1
      ? interpolate(frame, path.map((p) => p[0] * durationInFrames), path.map((p) => p[1]), {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.inOut(Easing.cubic),
        })
      : y0 + (end - y0) * s;
  const scroll = Math.min(maxScroll, Math.max(0, yAt * dispH));
  const scale = 1 + (zoom - 1) * t;
  const enter = useBuild(0, 1, 0.1, 1, 10);
  const cap = useBuild(0, 1, 0.3, FADE + 14, 12);
  // Push-in centred on the last mark (or the middle of the view).
  const ox = focus ? (focus.x + focus.w / 2) * dispW + ix : winW / 2;
  const oy = focus ? Math.min(viewH, Math.max(0, (focus.y + focus.h / 2) * dispH - scroll)) : viewH / 2;
  return (
    <PanelBg>
      <div style={{ position: "absolute", left: padL, top: pad, width: winW, height: winH, overflow: "hidden", background: "#161616", ...rise(enter, u, 16) }}>
        <div style={{ height: bar, display: "flex", alignItems: "center", gap: 24 * u, padding: `0 ${26 * u}px`, borderBottom: `${2 * u}px solid ${PC.brand}` }}>
          {source ? (
            <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 34 * u, textTransform: "uppercase", whiteSpace: "nowrap", color: PC.white, letterSpacing: 0.5 * u }}>{source}</div>
          ) : null}
          <div style={{ flex: 1, color: PC.dim, fontSize: 22 * u, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis", textAlign: source ? "right" : "left" }}>{url ?? ""}</div>
        </div>
        <div style={{ position: "relative", height: viewH, overflow: "hidden", background: "#fff" }}>
          <div style={{ position: "absolute", inset: 0, transform: `scale(${scale})`, transformOrigin: `${ox}px ${oy}px` }}>
            <Img src={panelAsset(image)} style={{ position: "absolute", left: ix, top: -scroll, width: dispW, height: dispH }} />
            {allMarks.map((m, i) => (
              <MarkView key={i} m={m} dispW={dispW} dispH={dispH} ix={ix} scroll={scroll} spotlight={spotlight && m === focus} />
            ))}
          </div>
        </div>
      </div>
      {caption ? (
        <div style={{ position: "absolute", left: padL, right: pad, bottom: pad, height: capH, display: "flex", alignItems: "center", gap: 28 * u, ...rise(cap, u) }}>
          <div style={{ width: 10 * u, alignSelf: "stretch", background: PC.red, flex: "none" }} />
          <div style={{ fontWeight: 700, fontSize: fit(caption, 52, 48, 36) * u, lineHeight: 1.15 }}>
            <Rich text={caption} />
          </div>
        </div>
      ) : null}
    </PanelBg>
  );
};

// ── PHeadline: a story, as a clipping ───────────────────────────────────────

export type PHeadlineProps = {
  outlet: string;
  date?: string;
  headline: string;
  dek?: string;
  byline?: string;
  facts?: string[];
  kicker?: string;
};

export const PHeadline: React.FC<PHeadlineProps> = ({ outlet, date, headline, dek, byline, facts = [], kicker }) => {
  const { u, wide } = usePanel();
  const card = useBuild(0, 1, 0.1, FADE + 1, 12);
  const shown = facts.slice(0, wide ? 4 : 3);
  return (
    <PanelBg>
      <div
        style={{
          position: "absolute",
          inset: `${70 * u}px ${80 * u}px ${100 * u}px ${96 * u}px`,
          display: "flex",
          flexDirection: wide ? "row" : "column",
          gap: 56 * u,
          justifyContent: "center",
          alignItems: wide ? "center" : "stretch",
        }}
      >
        <div style={{ flex: wide ? 1.35 : "none", ...rise(card, u, 16) }}>
          {kicker ? <Label style={{ marginBottom: 18 * u }}>{kicker}</Label> : null}
          <div style={{ background: PC.paper, color: PC.ink, padding: `${30 * u}px ${40 * u}px ${40 * u}px` }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", borderBottom: `${3 * u}px solid ${PC.ink}`, paddingBottom: 14 * u }}>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 46 * u, textTransform: "uppercase" }}>{outlet}</div>
              {date ? <div style={{ fontWeight: 500, fontSize: 26 * u, color: "#666" }}>{date}</div> : null}
            </div>
            <div style={{ fontWeight: 700, fontSize: fit(headline, 72, 52, 48) * u, lineHeight: 1.1, letterSpacing: -0.5 * u, marginTop: 26 * u }}>
              <Rich text={headline} mark={PC.brand} />
            </div>
            {dek ? <div style={{ marginTop: 20 * u, fontWeight: 400, fontSize: 34 * u, lineHeight: 1.35, color: "#444" }}>{dek}</div> : null}
            {byline ? <div style={{ marginTop: 18 * u, fontWeight: 500, fontSize: 26 * u, color: "#777" }}>{byline}</div> : null}
          </div>
        </div>
        {shown.length ? (
          <div style={{ flex: wide ? 1 : "none" }}>
            {shown.map((f, i) => (
              <Fact key={i} i={i} n={shown.length} text={f} />
            ))}
          </div>
        ) : null}
      </div>
    </PanelBg>
  );
};

const Fact: React.FC<{ i: number; n: number; text: string }> = ({ i, n, text }) => {
  const { u } = usePanel();
  const p = useBuild(i + 1, n + 1);
  return (
    <div style={{ ...rise(p, u), borderTop: `${2 * u}px solid ${i === 0 ? PC.ruleStrong : PC.rule}`, padding: `${20 * u}px 0` }}>
      <div style={{ fontWeight: 700, fontSize: fit(text, 38, 40, 30) * u, lineHeight: 1.25 }}>
        <Rich text={text} />
      </div>
    </div>
  );
};

// ── PStat: one number, big ──────────────────────────────────────────────────

export type PStatProps = Framed & {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  label: string;
  context?: string;
  ring?: boolean; // for percentages: a thin arc fills to value/100
};

export const PStat: React.FC<PStatProps> = ({ kicker, title, source, value, prefix = "", suffix = "", decimals = 0, label, context, ring }) => {
  const { u, wide } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const count = interpolate(frame, [FADE + 4, Math.max(FADE + 20, durationInFrames * 0.35)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const head = useBuild(0, 3, 0.2);
  const num = useBuild(1, 3, 0.2);
  const lab = useBuild(2, 3, 0.3);
  const text = `${prefix}${fmt(value, decimals)}${suffix}`;
  const numSize = fit(text, wide ? 560 : 440, 4, wide ? 340 : 260);
  const r = 210;
  const circ = 2 * Math.PI * r;
  const big = ring ? (
    <svg width={560 * u} height={560 * u} viewBox="0 0 500 500" style={{ flex: "none" }}>
      <circle cx={250} cy={250} r={r} fill="none" stroke={PC.rule} strokeWidth={14} />
      <circle cx={250} cy={250} r={r} fill="none" stroke={PC.red} strokeWidth={14} strokeDasharray={`${circ * (value / 100) * count} ${circ}`} transform="rotate(-90 250 250)" />
      <text x={250} y={300} textAnchor="middle" fill="#fff" style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 170 }}>
        {prefix}
        {fmt(value * count, decimals)}
        {suffix}
      </text>
    </svg>
  ) : (
    <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: numSize * u, lineHeight: 0.82, whiteSpace: "nowrap", flex: "none", letterSpacing: -0.01 * numSize * u, ...rise(num, u, 20) }}>
      {prefix ? <span style={{ color: PC.red }}>{prefix}</span> : null}
      {fmt(value * count, decimals)}
      {suffix ? <span style={{ color: PC.red }}>{suffix}</span> : null}
    </div>
  );
  return (
    <PanelBg>
      <div style={{ position: "absolute", left: 96 * u, right: 80 * u, top: 70 * u, bottom: 96 * u, display: "flex", flexDirection: "column", justifyContent: "safe center" }}>
        <div style={rise(head, u)}>
          {kicker ? <Label>{kicker}</Label> : null}
          {title ? <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: fit(title, 72, 30, 52) * u, textTransform: "uppercase", marginTop: 10 * u, lineHeight: 1 }}>{title}</div> : null}
        </div>
        <div style={{ display: "flex", flexDirection: wide ? "row" : "column", alignItems: wide ? "flex-end" : "flex-start", gap: (wide ? 70 : 30) * u, marginTop: 40 * u }}>
          {big}
          <div style={{ flex: 1, paddingBottom: (wide ? 24 : 0) * u, borderLeft: wide ? `${2 * u}px solid ${PC.ruleStrong}` : "none", paddingLeft: (wide ? 50 : 0) * u, ...rise(lab, u) }}>
            <div style={{ fontWeight: 700, fontSize: fit(label, 60, 30, 44) * u, lineHeight: 1.15, textTransform: "uppercase", letterSpacing: 0.5 * u }}>
              <Rich text={label} />
            </div>
            {context ? (
              <div style={{ marginTop: 20 * u, color: "#C8C8C8", fontWeight: 400, fontSize: fit(context, 44, 60, 34) * u, lineHeight: 1.3 }}>
                <Rich text={context} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <Footer source={source} />
    </PanelBg>
  );
};

// ── PPoints: numbered points ────────────────────────────────────────────────

export type PPointsProps = Framed & { points: (string | { title: string; text?: string })[]; reveal?: number[] };

export const PPoints: React.FC<PPointsProps> = ({ kicker, title, source, points, reveal }) => {
  const { u, wide } = usePanel();
  const shown = points.slice(0, 6).map((p) => (typeof p === "string" ? { title: p } : p));
  // Wide pane with titled points: columns. Everything else: rows.
  const columns = wide && shown.some((p) => p.text) && shown.length <= 4;
  const tsize = columns
    ? fit("x".repeat(longest(shown.map((p) => p.title))), 72, 18, 52)
    : fit("x".repeat(longest(shown.map((p) => p.title))), wide ? 66 : 62, wide ? 44 : 26, 44);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      {columns ? (
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${shown.length}, 1fr)` }}>
          {shown.map((p, i) => (
            <PointColumn key={i} i={i} n={shown.length} title={p.title} text={p.text} size={tsize} reveal={reveal} />
          ))}
        </div>
      ) : (
        <div>
          {shown.map((p, i) => (
            <PointRow key={i} i={i} n={shown.length} title={p.title} text={p.text} size={tsize} reveal={reveal} />
          ))}
        </div>
      )}
    </Panel>
  );
};

const PointRow: React.FC<{ i: number; n: number; title: string; text?: string; size: number; reveal?: number[] }> = ({ i, n, title, text, size, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i, n, reveal);
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 34 * u, padding: `${22 * u}px 0`, borderBottom: i < n - 1 ? `${2 * u}px solid ${PC.rule}` : "none", ...rise(p, u) }}>
      <div style={{ flex: "none", width: 70 * u, fontFamily: DISPLAY, fontWeight: 700, fontSize: 52 * u, color: PC.red, lineHeight: 1 }}>{pad2(i)}</div>
      <div>
        <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.15 }}>
          <Rich text={title} />
        </div>
        {text ? <div style={{ marginTop: 8 * u, color: "#BDBDBD", fontWeight: 400, fontSize: size * 0.7 * u, lineHeight: 1.3 }}><Rich text={text} /></div> : null}
      </div>
    </div>
  );
};

const PointColumn: React.FC<{ i: number; n: number; title: string; text?: string; size: number; reveal?: number[] }> = ({ i, n, title, text, size, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i, n, reveal);
  return (
    <div style={{ padding: `0 ${36 * u}px`, paddingLeft: (i === 0 ? 0 : 36) * u, borderLeft: i > 0 ? `${2 * u}px solid ${PC.rule}` : "none", ...rise(p, u) }}>
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 64 * u, color: PC.red, lineHeight: 1 }}>{pad2(i)}</div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.12, marginTop: 18 * u }}>
        <Rich text={title} />
      </div>
      {text ? <div style={{ marginTop: 12 * u, color: "#BDBDBD", fontWeight: 400, fontSize: size * 0.72 * u, lineHeight: 1.3 }}><Rich text={text} /></div> : null}
    </div>
  );
};

// ── PCompare: A vs B ────────────────────────────────────────────────────────

type Side = { name: string; tag?: string; points: string[] };
export type PCompareProps = Framed & { left: Side; right: Side; verdict?: string };

export const PCompare: React.FC<PCompareProps> = ({ kicker, title, source, left, right, verdict }) => {
  const { u, wide } = usePanel();
  const rows = Math.max(left.points.length, right.points.length, 1);
  const size = fit("x".repeat(longest([...left.points, ...right.points])), wide ? 58 : 46, wide ? 30 : 22, wide ? 44 : 36);
  const v = useBuild(rows + 1, rows + 2);
  return (
    <Panel kicker={kicker} title={title} source={source} titleSize={110}>
      <div style={{ display: "flex" }}>
        {[left, right].map((side, s) => (
          <CompareSide key={s} side={side} s={s} rows={rows} size={size} />
        ))}
      </div>
      {verdict ? (
        <div style={{ marginTop: 30 * u }}>
          <Band text={verdict} p={v} size={56} />
        </div>
      ) : null}
    </Panel>
  );
};

const CompareSide: React.FC<{ side: Side; s: number; rows: number; size: number }> = ({ side, s, rows, size }) => {
  const { u } = usePanel();
  const h = useBuild(s, 2, 0.12);
  return (
    <div style={{ flex: 1, paddingLeft: (s ? 44 : 0) * u, paddingRight: (s ? 0 : 44) * u, borderLeft: s ? `${2 * u}px solid ${PC.ruleStrong}` : "none" }}>
      <div style={rise(h, u)}>
        {side.tag ? <Label size={26} color={s ? PC.red : PC.muted}>{side.tag}</Label> : null}
        <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: fit(side.name, 96, 14, 66) * u, lineHeight: 1, marginTop: (side.tag ? 10 : 0) * u, textTransform: "uppercase", color: s ? PC.white : "#CFCFCF" }}>
          {side.name}
        </div>
      </div>
      <div style={{ marginTop: 18 * u }}>
        {side.points.slice(0, 5).map((p, i) => (
          <CompareRow key={i} i={i} n={rows} text={p} size={size} good={s === 1} />
        ))}
      </div>
    </div>
  );
};

const CompareRow: React.FC<{ i: number; n: number; text: string; size: number; good: boolean }> = ({ i, n, text, size, good }) => {
  const { u } = usePanel();
  const p = useBuild(i + 1, n + 2);
  return (
    <div style={{ display: "flex", gap: 18 * u, alignItems: "baseline", padding: `${14 * u}px 0`, borderTop: `${2 * u}px solid ${PC.rule}`, ...rise(p, u) }}>
      <span style={{ flex: "none", width: 22 * u, height: 4 * u, background: good ? PC.red : PC.dim, transform: `translateY(${-10 * u}px)` }} />
      <span style={{ fontWeight: good ? 700 : 500, fontSize: size * u, lineHeight: 1.25, color: good ? PC.white : "#D0D0D0" }}>
        <Rich text={text} />
      </span>
    </div>
  );
};

// ── PTimeline: dated events, left to right ──────────────────────────────────

export type PTimelineProps = Framed & { events: { date: string; text: string; hot?: boolean }[]; reveal?: number[] };

export const PTimeline: React.FC<PTimelineProps> = ({ kicker, title, source, events, reveal }) => {
  const { u, wide } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const shown = events.slice(0, 6);
  const n = shown.length;
  const line = interpolate(frame, [FADE + 4, Math.max(FADE + 20, durationInFrames * 0.4)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const size = fit("x".repeat(longest(shown.map((e) => e.text))), wide ? 58 : 48, 26, wide ? 44 : 38);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      <div style={{ position: "relative", paddingTop: 10 * u }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 10 * u + 9 * u, height: 4 * u, background: PC.rule }}>
          <div style={{ height: "100%", width: `${line * 100}%`, background: PC.ruleStrong }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, 1fr)`, gap: 36 * u }}>
          {shown.map((e, i) => (
            <TimelineStop key={i} i={i} n={n} ev={e} size={size} last={i === n - 1} reveal={reveal} />
          ))}
        </div>
      </div>
    </Panel>
  );
};

const TimelineStop: React.FC<{ i: number; n: number; ev: { date: string; text: string; hot?: boolean }; size: number; last: boolean; reveal?: number[] }> = ({ i, n, ev, size, last, reveal }) => {
  const { u, wide } = usePanel();
  const p = useReveal(i, n, reveal, 0.4);
  const hot = ev.hot ?? last;
  return (
    <div style={rise(p, u)}>
      <div style={{ width: 22 * u, height: 22 * u, background: hot ? PC.red : PC.white }} />
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: (wide ? 88 : 64) * u, lineHeight: 1, color: hot ? PC.red : PC.white, marginTop: 26 * u, whiteSpace: "nowrap", textTransform: "uppercase" }}>{ev.date}</div>
      <div style={{ fontWeight: 500, fontSize: size * u, lineHeight: 1.25, marginTop: 12 * u, color: hot ? PC.white : "#D0D0D0" }}>
        <Rich text={ev.text} />
      </div>
    </div>
  );
};

// ── PQuote ──────────────────────────────────────────────────────────────────

export type PQuoteProps = Framed & { quote: string; author: string; role?: string; photo?: string };

export const PQuote: React.FC<PQuoteProps> = ({ kicker, source, quote, author, role, photo }) => {
  const { u, wide } = usePanel();
  const q = useBuild(0, 2, 0.2);
  const a = useBuild(1, 2, 0.3);
  const bar = useBuild(0, 1, 0.15, FADE + 1, 14);
  return (
    <PanelBg>
      <div style={{ position: "absolute", inset: `${70 * u}px ${wide ? 150 : 80}px ${110 * u}px ${wide ? 130 : 96}px`, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {kicker ? <Label style={{ opacity: a, marginBottom: 36 * u }}>{kicker}</Label> : null}
        <div style={{ display: "flex", gap: 44 * u }}>
          <div style={{ flex: "none", width: 12 * u, background: PC.red, transform: `scaleY(${bar})`, transformOrigin: "top" }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: fit(quote, wide ? 112 : 96, 60, wide ? 80 : 64) * u, lineHeight: 1.2, letterSpacing: -0.4 * u, ...rise(q, u, 16) }}>
              <Rich text={quote} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 24 * u, marginTop: 40 * u, ...rise(a, u) }}>
              {photo ? <Img src={panelAsset(photo)} style={{ width: 104 * u, height: 104 * u, objectFit: "cover", filter: "grayscale(0.2)" }} /> : null}
              <div>
                <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 58 * u, lineHeight: 1, textTransform: "uppercase" }}>{author}</div>
                {role ? <div style={{ color: PC.muted, fontWeight: 400, fontSize: 34 * u, marginTop: 8 * u }}>{role}</div> : null}
              </div>
            </div>
          </div>
        </div>
      </div>
      <Footer source={source} />
    </PanelBg>
  );
};

// ── PBars: a few values compared ────────────────────────────────────────────

export type PBarsProps = Framed & {
  items: { label: string; value: number; display?: string; note?: string; highlight?: boolean }[];
  prefix?: string;
  suffix?: string;
  decimals?: number;
  note?: string;
};

export const PBars: React.FC<PBarsProps> = ({ kicker, title, source, items, prefix = "", suffix = "", decimals = 0, note }) => {
  const { u, wide } = usePanel();
  const shown = items.slice(0, 6);
  const max = Math.max(...shown.map((i) => Math.abs(i.value)), 1e-9);
  // The wide pane is shorter in units, so three bars already need the compact rows.
  const dense = shown.length > (wide ? 2 : 4);
  const nb = useBuild(shown.length + 1, shown.length + 2);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 26 : 38) * u }}>
        {shown.map((item, i) => (
          <BarRow key={i} i={i} n={shown.length} item={item} max={max} prefix={prefix} suffix={suffix} decimals={decimals} dense={dense} />
        ))}
      </div>
      {note ? <div style={{ marginTop: 28 * u, color: PC.muted, fontWeight: 400, fontSize: 32 * u, opacity: nb }}><Rich text={note} /></div> : null}
    </Panel>
  );
};

const BarRow: React.FC<{
  i: number;
  n: number;
  item: { label: string; value: number; display?: string; note?: string; highlight?: boolean };
  max: number;
  prefix: string;
  suffix: string;
  decimals: number;
  dense: boolean;
}> = ({ i, n, item, max, prefix, suffix, decimals, dense }) => {
  const { u } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const appear = useBuild(i, n, 0.3);
  const grow = appear * interpolate(frame, [FADE, Math.max(FADE + 12, durationInFrames * 0.45)], [0.3, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const hl = !!item.highlight;
  const shownValue = item.display ?? `${prefix}${fmt(item.value * grow, decimals)}${suffix}`;
  return (
    <div style={{ opacity: appear }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 * u }}>
        <span style={{ fontWeight: 700, fontSize: (dense ? 38 : 52) * u, textTransform: "uppercase", letterSpacing: 0.5 * u }}>
          {item.label}
          {item.note ? <span style={{ color: PC.muted, fontWeight: 400, fontSize: (dense ? 28 : 36) * u, marginLeft: 16 * u, textTransform: "none" }}>{item.note}</span> : null}
        </span>
        <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: (dense ? 74 : 110) * u, lineHeight: 0.9, color: hl ? PC.red : PC.white }}>{shownValue}</span>
      </div>
      <div style={{ height: (dense ? 22 : 36) * u, background: "#1C1C1C" }}>
        <div style={{ height: "100%", width: `${Math.max(0.6, (Math.abs(item.value) / max) * 100 * grow)}%`, background: hl ? PC.red : "#8A8A8A" }} />
      </div>
    </div>
  );
};

// ── PFlow: how something moves, step by step ────────────────────────────────

/** Step reveal times -> interleaved step/arrow times (arrow just before its step). */
const stepTimes = (r: number[]) => r.flatMap((t, i) => (i === 0 ? [t] : [Math.max(0, t - 0.02), t])) as number[];

export type PFlowProps = Framed & { steps: { title: string; text?: string }[]; foot?: string; reveal?: number[] };

export const PFlow: React.FC<PFlowProps> = ({ kicker, title, source, steps, foot, reveal }) => {
  const { u, wide } = usePanel();
  const shown = steps.slice(0, 5);
  const n = shown.length;
  const tsize = fit("x".repeat(longest(shown.map((s) => s.title))), wide ? 72 : 60, 12, wide ? 50 : 40);
  const ft = useBuild(n + 1, n + 2);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", alignItems: "stretch" }}>
        {shown.map((s, i) => (
          <React.Fragment key={i}>
            <FlowStep i={i} n={n} step={s} size={tsize} reveal={reveal} />
            {i < n - 1 ? <FlowArrow i={i} n={n} reveal={reveal} /> : null}
          </React.Fragment>
        ))}
      </div>
      {foot ? (
        <div style={{ marginTop: 34 * u }}>
          <Band text={foot} p={ft} size={46} />
        </div>
      ) : null}
    </Panel>
  );
};

const FlowStep: React.FC<{ i: number; n: number; step: { title: string; text?: string }; size: number; reveal?: number[] }> = ({ i, n, step, size, reveal }) => {
  const { u } = usePanel();
  const { wide } = usePanel();
  const p = useReveal(i * 2, n * 2 - 1, reveal ? stepTimes(reveal) : undefined, 0.45);
  const last = i === n - 1;
  return (
    <div style={{ flex: 1, minWidth: 0, ...rise(p, u) }}>
      <div style={{ height: (last ? 8 : 4) * u, background: last ? PC.red : PC.ruleStrong }} />
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: (wide ? 48 : 40) * u, color: PC.red, lineHeight: 1, marginTop: 22 * u }}>{pad2(i)}</div>
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: size * u, lineHeight: 1, marginTop: 10 * u, textTransform: "uppercase" }}>{step.title}</div>
      {step.text ? <div style={{ marginTop: 14 * u, fontWeight: 400, fontSize: (wide ? 44 : 36) * u, lineHeight: 1.3, color: "#C8C8C8" }}><Rich text={step.text} /></div> : null}
    </div>
  );
};

const FlowArrow: React.FC<{ i: number; n: number; reveal?: number[] }> = ({ i, n, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i * 2 + 1, n * 2 - 1, reveal ? stepTimes(reveal) : undefined, 0.45);
  return (
    <div style={{ flex: "none", width: 64 * u, paddingTop: 70 * u, display: "flex", justifyContent: "center" }}>
      <svg width={40 * u} height={24 * u} viewBox="0 0 40 24" style={{ opacity: p }}>
        <path d="M2 12 H36 M28 4 L36 12 L28 20" fill="none" stroke={PC.muted} strokeWidth={2.5} strokeLinecap="square" />
      </svg>
    </div>
  );
};

// ── PExplainer: what a company / person / thing is ──────────────────────────

export type PExplainerProps = Framed & {
  name: string;
  logo?: string; // image path; shown on white
  lead: string;
  facts?: { label: string; value: string }[];
};

export const PExplainer: React.FC<PExplainerProps> = ({ kicker, source, name, logo, lead, facts = [] }) => {
  const { u, wide } = usePanel();
  const a = useBuild(0, 3, 0.15);
  const b = useBuild(1, 3, 0.2);
  const shown = facts.slice(0, 4);
  return (
    <PanelBg>
      <div
        style={{
          position: "absolute",
          inset: `${70 * u}px ${80 * u}px ${100 * u}px ${96 * u}px`,
          display: "flex",
          flexDirection: wide ? "row" : "column",
          gap: (wide ? 70 : 44) * u,
          justifyContent: "center",
          alignItems: wide ? "center" : "stretch",
        }}
      >
        <div style={{ flex: wide ? 1.1 : "none" }}>
          <div style={rise(a, u)}>
            {kicker ? <Label>{kicker}</Label> : null}
            <div style={{ display: "flex", alignItems: "center", gap: 30 * u, marginTop: 14 * u }}>
              {logo ? (
                <div style={{ flex: "none", width: 170 * u, height: 170 * u, background: PC.white, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                  <Img src={panelAsset(logo)} style={{ maxWidth: "80%", maxHeight: "80%", objectFit: "contain" }} />
                </div>
              ) : null}
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: fit(name, 150, 13, 92) * u, lineHeight: 0.92, textTransform: "uppercase" }}>{name}</div>
            </div>
          </div>
          <div style={{ fontWeight: 400, fontSize: fit(lead, wide ? 58 : 50, 70, wide ? 44 : 38) * u, lineHeight: 1.3, marginTop: 30 * u, color: "#E4E4E4", ...rise(b, u) }}>
            <Rich text={lead} />
          </div>
        </div>
        {shown.length ? (
          <div style={{ flex: wide ? 1 : "none" }}>
            {shown.map((f, i) => (
              <ExplainFact key={i} i={i} n={shown.length} f={f} />
            ))}
          </div>
        ) : null}
      </div>
      <Footer source={source} />
    </PanelBg>
  );
};

const ExplainFact: React.FC<{ i: number; n: number; f: { label: string; value: string } }> = ({ i, n, f }) => {
  const { u, wide } = usePanel();
  const p = useBuild(i + 2, n + 2);
  return (
    <div style={{ borderTop: `${2 * u}px solid ${i === 0 ? PC.ruleStrong : PC.rule}`, padding: `${18 * u}px 0`, ...rise(p, u) }}>
      <Label size={26}>{f.label}</Label>
      <div style={{ fontWeight: 700, fontSize: fit(f.value, wide ? 56 : 48, 28, wide ? 42 : 36) * u, lineHeight: 1.2, marginTop: 6 * u }}>
        <Rich text={f.value} />
      </div>
    </div>
  );
};

// ── PStack: layers of a system, built from the bottom up ────────────────────

export type PStackProps = Framed & {
  layers: { title: string; text?: string; tag?: string }[]; // bottom layer first
  highlight?: number; // index of the layer to mark in red
  reveal?: number[];
};

export const PStack: React.FC<PStackProps> = ({ kicker, title, source, layers, highlight, reveal }) => {
  const shown = layers.slice(0, 5);
  const n = shown.length;
  return (
    <Panel kicker={kicker} title={title} source={source} titleSize={110}>
      <div style={{ display: "flex", flexDirection: "column-reverse" }}>
        {shown.map((l, i) => (
          <StackLayer key={i} i={i} n={n} layer={l} hot={i === highlight} reveal={reveal} />
        ))}
      </div>
    </Panel>
  );
};

const StackLayer: React.FC<{ i: number; n: number; layer: { title: string; text?: string; tag?: string }; hot: boolean; reveal?: number[] }> = ({
  i,
  n,
  layer,
  hot,
  reveal,
}) => {
  const { u } = usePanel();
  const p = useReveal(i, n, reveal, 0.4);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 34 * u,
        padding: `${18 * u}px ${hot ? 26 : 0}px`,
        background: hot ? PC.brand : "transparent",
        borderTop: i < n - 1 && !hot ? `${2 * u}px solid ${PC.rule}` : `${2 * u}px solid transparent`,
        opacity: p,
        transform: `translateY(${(1 - p) * -14 * u}px)`,
      }}
    >
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 76 * u, lineHeight: 1, flex: "none", minWidth: 560 * u, textTransform: "uppercase" }}>{layer.title}</div>
      {layer.text ? <div style={{ flex: 1, fontWeight: 400, fontSize: 44 * u, lineHeight: 1.25, color: hot ? PC.white : "#C8C8C8" }}><Rich text={layer.text} mark={hot ? PC.white : PC.red} /></div> : <div style={{ flex: 1 }} />}
      {layer.tag ? <Label size={26} color={hot ? PC.white : PC.muted}>{layer.tag}</Label> : null}
    </div>
  );
};

export const PANEL_TEMPLATES = {
  PStack,
  PShot,
  PHeadline,
  PStat,
  PPoints,
  PCompare,
  PTimeline,
  PQuote,
  PBars,
  PFlow,
  PExplainer,
};

// Kept for files that import them from here.
export { Header, BODY };
