// Long-form panel templates. See ./theme.tsx for the frame they fill.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import {
  Block,
  Chip,
  DISPLAY,
  FADE,
  Footer,
  Framed,
  Header,
  PC,
  Panel,
  PanelBg,
  Rich,
  fit,
  fmt,
  panelAsset,
  plain,
  useBuild,
  useDrift,
  usePanel,
  useReveal,
} from "./theme";

const longest = (xs: string[]) => xs.reduce((m, x) => Math.max(m, plain(x).length), 0);

// ── PShot: a web page in a browser window ───────────────────────────────────

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
  source?: string; // chip on the right of the URL bar, e.g. "TECHCRUNCH · 8 SEP"
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
  caption?: string; // optional takeaway band at the bottom
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
          background: "rgba(255, 214, 0, 0.62)",
          mixBlendMode: "multiply",
          borderRadius: `${4 * u}px ${10 * u}px ${6 * u}px ${12 * u}px`,
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
          strokeWidth={8 * u}
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
        <path d={d} fill="none" stroke={PC.red} strokeWidth={8 * u} strokeLinecap="round" pathLength={1} strokeDasharray={`${p} 1`} />
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
        border: `${6 * u}px solid ${PC.red}`,
        borderRadius: 10 * u,
        opacity: p,
        transform: `scale(${1.04 - 0.04 * p})`,
        boxShadow: spotlight
          ? `0 0 0 ${4000 * u}px rgba(0,0,0,${0.36 * p}), 0 0 ${30 * u}px rgba(224,22,29,${0.6 * p})`
          : `0 0 ${30 * u}px rgba(224,22,29,${0.5 * p})`,
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
  zoom = 1.06,
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
  const pad = 46 * u;
  const bar = 64 * u;
  const capH = caption ? 132 * u : 0;
  const winW = W - pad * 2;
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
  const cap = useBuild(0, 1, 0.3, FADE + 14, 14);
  // Push-in centred on the last mark (or the middle of the view).
  const ox = focus ? (focus.x + focus.w / 2) * dispW + ix : winW / 2;
  const oy = focus ? Math.min(viewH, Math.max(0, (focus.y + focus.h / 2) * dispH - scroll)) : viewH / 2;
  return (
    <PanelBg>
      <div
        style={{
          position: "absolute",
          left: pad,
          top: pad,
          width: winW,
          height: winH,
          borderRadius: 18 * u,
          overflow: "hidden",
          background: "#1B1B1E",
          boxShadow: `0 ${24 * u}px ${70 * u}px rgba(0,0,0,0.6), 0 0 0 ${2 * u}px rgba(255,255,255,0.1)`,
          opacity: enter,
          transform: `translateY(${(1 - enter) * 30 * u}px)`,
        }}
      >
        <div style={{ height: bar, display: "flex", alignItems: "center", gap: 12 * u, padding: `0 ${22 * u}px`, background: "#232327" }}>
          {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
            <span key={c} style={{ width: 18 * u, height: 18 * u, borderRadius: 9 * u, background: c, flex: "none" }} />
          ))}
          <div
            style={{
              marginLeft: 18 * u,
              flex: 1,
              height: 40 * u,
              borderRadius: 20 * u,
              background: "#111113",
              color: "rgba(255,255,255,0.7)",
              fontWeight: 600,
              fontSize: 22 * u,
              display: "flex",
              alignItems: "center",
              padding: `0 ${22 * u}px`,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {url ?? ""}
          </div>
          {source ? <Chip size={30}>{source}</Chip> : null}
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
        <div
          style={{
            position: "absolute",
            left: pad,
            right: pad,
            bottom: pad,
            height: capH,
            display: "flex",
            alignItems: "stretch",
            opacity: cap,
            transform: `translateY(${(1 - cap) * 20 * u}px)`,
          }}
        >
          <div style={{ width: 14 * u, background: PC.red, flex: "none" }} />
          <div
            style={{
              flex: 1,
              background: PC.white,
              color: PC.ink,
              display: "flex",
              alignItems: "center",
              padding: `0 ${34 * u}px`,
              fontWeight: 800,
              fontSize: fit(caption, 52, 48, 36) * u,
              lineHeight: 1.12,
            }}
          >
            <div>
              <Rich text={caption} />
            </div>
          </div>
        </div>
      ) : null}
    </PanelBg>
  );
};

// ── PHeadline: a story, when there is no clean page to screenshot ────────────

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
          inset: `${70 * u}px ${80 * u}px ${110 * u}px`,
          display: "flex",
          flexDirection: wide ? "row" : "column",
          gap: 40 * u,
          justifyContent: "center",
          alignItems: wide ? "center" : "stretch",
        }}
      >
        <div style={{ flex: wide ? 1.35 : "none", opacity: card, transform: `translateY(${(1 - card) * 40 * u}px)` }}>
          {kicker ? <Chip size={36} style={{ marginBottom: 20 * u }}>{kicker}</Chip> : null}
          <Block tone="paper" pad={0} style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `${26 * u}px ${40 * u}px`, borderBottom: `${3 * u}px solid ${PC.ink}` }}>
              <div style={{ fontWeight: 900, fontSize: 44 * u, letterSpacing: -0.5 * u, textTransform: "uppercase" }}>{outlet}</div>
              {date ? <div style={{ fontWeight: 700, fontSize: 28 * u, color: "rgba(0,0,0,0.55)" }}>{date}</div> : null}
            </div>
            <div style={{ display: "flex" }}>
              <div style={{ width: 14 * u, background: PC.red, flex: "none" }} />
              <div style={{ padding: `${36 * u}px ${40 * u}px ${40 * u}px` }}>
                <div style={{ fontWeight: 800, fontSize: fit(headline, 74, 52, 50) * u, lineHeight: 1.1, letterSpacing: -1 * u }}>
                  <Rich text={headline} />
                </div>
                {dek ? <div style={{ marginTop: 22 * u, fontWeight: 500, fontSize: 34 * u, lineHeight: 1.35, color: "rgba(0,0,0,0.7)" }}>{dek}</div> : null}
                {byline ? <div style={{ marginTop: 22 * u, fontWeight: 700, fontSize: 26 * u, color: "rgba(0,0,0,0.5)" }}>{byline}</div> : null}
              </div>
            </div>
          </Block>
        </div>
        {shown.length ? (
          <div style={{ flex: wide ? 1 : "none", display: "flex", flexDirection: wide ? "column" : "row", gap: 20 * u }}>
            {shown.map((f, i) => (
              <Fact key={i} i={i} n={shown.length} text={f} />
            ))}
          </div>
        ) : null}
      </div>
      <Footer />
    </PanelBg>
  );
};

const Fact: React.FC<{ i: number; n: number; text: string }> = ({ i, n, text }) => {
  const { u } = usePanel();
  const p = useBuild(i + 1, n + 1);
  return (
    <div style={{ flex: 1, opacity: p, transform: `translateY(${(1 - p) * 24 * u}px)` }}>
      <Block pad={26} style={{ borderLeft: `${8 * u}px solid ${PC.red}`, height: "100%", boxSizing: "border-box" }}>
        <div style={{ fontWeight: 700, fontSize: fit(text, 36, 40, 28) * u, lineHeight: 1.25 }}>
          <Rich text={text} />
        </div>
      </Block>
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
  ring?: boolean; // for percentages: a ring fills to value/100
};

export const PStat: React.FC<PStatProps> = ({ kicker, title, source, value, prefix = "", suffix = "", decimals = 0, label, context, ring }) => {
  const { u, wide } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const count = interpolate(frame, [FADE + 4, Math.max(FADE + 20, durationInFrames * 0.4)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const lab = useBuild(1, 3);
  const ctx = useBuild(2, 3);
  const numSize = fit(`${prefix}${fmt(value, decimals)}${suffix}`, 400, 5, 240);
  const r = 210;
  const circ = 2 * Math.PI * r;
  return (
    <Panel kicker={kicker} title={title} source={source} titleSize={96}>
      <div style={{ display: "flex", alignItems: "center", gap: 60 * u, flexDirection: wide || ring ? "row" : "column" }}>
        {ring ? (
          <svg width={580 * u} height={580 * u} viewBox="0 0 500 500" style={{ flex: "none" }}>
            <circle cx={250} cy={250} r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth={46} />
            <circle
              cx={250}
              cy={250}
              r={r}
              fill="none"
              stroke={PC.red}
              strokeWidth={46}
              strokeDasharray={`${circ * (value / 100) * count} ${circ}`}
              transform="rotate(-90 250 250)"
              strokeLinecap="butt"
            />
            <text x={250} y={295} textAnchor="middle" fill="#fff" style={{ fontFamily: DISPLAY, fontSize: 150 }}>
              {prefix}
              {fmt(value * count, decimals)}
              {suffix}
            </text>
          </svg>
        ) : (
          <div style={{ fontFamily: DISPLAY, fontSize: numSize * u, lineHeight: 0.85, whiteSpace: "nowrap", flex: "none" }}>
            <span style={{ color: PC.red }}>{prefix}</span>
            {fmt(value * count, decimals)}
            <span style={{ color: PC.red }}>{suffix}</span>
          </div>
        )}
        <div style={{ flex: 1, textAlign: wide || ring ? "left" : "center" }}>
          <div style={{ fontWeight: 800, fontSize: fit(label, 74, 40, 52) * u, lineHeight: 1.15, opacity: lab, transform: `translateY(${(1 - lab) * 20 * u}px)` }}>
            <Rich text={label} />
          </div>
          {context ? (
            <div style={{ marginTop: 24 * u, color: PC.muted, fontWeight: 600, fontSize: fit(context, 46, 60, 36) * u, lineHeight: 1.3, opacity: ctx }}>
              <Rich text={context} />
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
};

// ── PPoints: numbered points in a grid ──────────────────────────────────────

export type PPointsProps = Framed & { points: (string | { title: string; text?: string })[]; reveal?: number[] };

export const PPoints: React.FC<PPointsProps> = ({ kicker, title, source, points, reveal }) => {
  const { u, wide } = usePanel();
  const shown = points.slice(0, 6).map((p) => (typeof p === "string" ? { title: p } : p));
  const cols = wide ? Math.min(shown.length, shown.length === 4 ? 4 : 3) : shown.length <= 3 ? 1 : 2;
  const sizes = longest(shown.map((p) => p.title));
  const tsize = fit("x".repeat(sizes), cols === 1 ? 66 : 60, cols === 1 ? 34 : 18, 42);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 24 * u }}>
        {shown.map((p, i) => (
          <PointCard key={i} i={i} n={shown.length} title={p.title} text={p.text} size={tsize} row={cols === 1} reveal={reveal} />
        ))}
      </div>
    </Panel>
  );
};

const PointCard: React.FC<{ i: number; n: number; title: string; text?: string; size: number; row: boolean; reveal?: number[] }> = ({ i, n, title, text, size, row, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i, n, reveal);
  const glow = interpolate(p, [0.5, 1], [0, 1], { extrapolateLeft: "clamp" });
  return (
    <div style={{ opacity: p, transform: `translateY(${(1 - p) * 30 * u}px)` }}>
      <Block pad={30} style={{ display: "flex", flexDirection: row ? "row" : "column", alignItems: row ? "center" : "flex-start", gap: 24 * u, height: "100%", boxSizing: "border-box" }}>
        <div
          style={{
            flex: "none",
            width: 104 * u,
            height: 104 * u,
            background: PC.red,
            borderRadius: 12 * u,
            fontFamily: DISPLAY,
            fontSize: 80 * u,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            paddingTop: 6 * u,
            boxSizing: "border-box",
            boxShadow: `0 0 ${30 * u * glow}px rgba(224,22,29,${0.6 * glow})`,
          }}
        >
          {i + 1}
        </div>
        <div>
          <div style={{ fontWeight: 800, fontSize: size * u, lineHeight: 1.15 }}>
            <Rich text={title} />
          </div>
          {text ? <div style={{ marginTop: 10 * u, color: PC.muted, fontWeight: 600, fontSize: size * 0.72 * u, lineHeight: 1.3 }}><Rich text={text} /></div> : null}
        </div>
      </Block>
    </div>
  );
};

// ── PCompare: A vs B ────────────────────────────────────────────────────────

type Side = { name: string; tag?: string; points: string[] };
export type PCompareProps = Framed & { left: Side; right: Side; verdict?: string };

export const PCompare: React.FC<PCompareProps> = ({ kicker, title, source, left, right, verdict }) => {
  const { u } = usePanel();
  const rows = Math.max(left.points.length, right.points.length, 1);
  const size = fit("x".repeat(longest([...left.points, ...right.points])), 48, 22, 38);
  const vs = useBuild(0, 1, 0.1, FADE + 6, 10);
  const v = useBuild(rows + 1, rows + 2);
  return (
    <Panel kicker={kicker} title={title} source={source} titleSize={104}>
      <div style={{ position: "relative", display: "flex", gap: 28 * u }}>
        {[left, right].map((side, s) => (
          <Block key={s} tone={s === 1 ? "red" : "none"} pad={34} style={{ flex: 1 }}>
            {side.tag ? <Chip size={34} tone={s === 1 ? "red" : "ghost"}>{side.tag}</Chip> : null}
            <div style={{ fontFamily: DISPLAY, fontSize: fit(side.name, 96, 12, 72) * u, lineHeight: 1, marginTop: (side.tag ? 16 : 0) * u, color: s === 1 ? PC.white : "rgba(255,255,255,0.88)" }}>
              {side.name}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 18 * u, marginTop: 24 * u }}>
              {side.points.slice(0, 5).map((p, i) => (
                <CompareRow key={i} i={i} n={rows} text={p} size={size} good={s === 1} />
              ))}
            </div>
          </Block>
        ))}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: 40 * u,
            width: 96 * u,
            height: 96 * u,
            marginLeft: -48 * u,
            borderRadius: 48 * u,
            background: PC.ink,
            border: `${4 * u}px solid ${PC.red}`,
            fontFamily: DISPLAY,
            fontSize: 48 * u,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            paddingTop: 4 * u,
            boxSizing: "border-box",
            transform: `scale(${vs})`,
          }}
        >
          VS
        </div>
      </div>
      {verdict ? (
        <div style={{ marginTop: 26 * u, opacity: v, transform: `translateY(${(1 - v) * 16 * u}px)` }}>
          <div style={{ display: "flex" }}>
            <div style={{ width: 14 * u, background: PC.red }} />
            <div style={{ flex: 1, background: PC.white, color: PC.ink, padding: `${22 * u}px ${30 * u}px`, fontWeight: 800, fontSize: fit(verdict, 54, 44, 40) * u, lineHeight: 1.2 }}>
              <Rich text={verdict} />
            </div>
          </div>
        </div>
      ) : null}
    </Panel>
  );
};

const CompareRow: React.FC<{ i: number; n: number; text: string; size: number; good: boolean }> = ({ i, n, text, size, good }) => {
  const { u } = usePanel();
  const p = useBuild(i + 1, n + 2);
  return (
    <div style={{ display: "flex", gap: 16 * u, alignItems: "baseline", opacity: p, transform: `translateX(${(1 - p) * 20 * u}px)` }}>
      <span style={{ flex: "none", width: 14 * u, height: 14 * u, background: good ? PC.red : "rgba(255,255,255,0.5)", transform: `translateY(${-4 * u}px) rotate(45deg)` }} />
      <span style={{ fontWeight: 600, fontSize: size * u, lineHeight: 1.25 }}>
        <Rich text={text} />
      </span>
    </div>
  );
};

// ── PTimeline: dated events, left to right ──────────────────────────────────

export type PTimelineProps = Framed & { events: { date: string; text: string; hot?: boolean }[]; reveal?: number[] };

export const PTimeline: React.FC<PTimelineProps> = ({ kicker, title, source, events, reveal }) => {
  const { u } = usePanel();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const shown = events.slice(0, 6);
  const n = shown.length;
  const line = interpolate(frame, [FADE + 4, Math.max(FADE + 20, durationInFrames * 0.4)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const size = fit("x".repeat(longest(shown.map((e) => e.text))), 52, 26, 40);
  return (
    <Panel kicker={kicker} title={title} source={source}>
      <div style={{ position: "relative", paddingTop: 30 * u }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 30 * u + 26 * u, height: 8 * u, background: "rgba(255,255,255,0.12)" }}>
          <div style={{ height: "100%", width: `${line * 100}%`, background: PC.red, boxShadow: `0 0 ${20 * u}px rgba(224,22,29,0.6)` }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${n}, 1fr)`, gap: 28 * u }}>
          {shown.map((e, i) => (
            <TimelineStop key={i} i={i} n={n} ev={e} size={size} last={i === n - 1} reveal={reveal} />
          ))}
        </div>
      </div>
    </Panel>
  );
};

const TimelineStop: React.FC<{ i: number; n: number; ev: { date: string; text: string; hot?: boolean }; size: number; last: boolean; reveal?: number[] }> = ({ i, n, ev, size, last, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i, n, reveal, 0.4);
  const hot = ev.hot ?? last;
  return (
    <div style={{ opacity: p, transform: `translateY(${(1 - p) * 26 * u}px)` }}>
      <div
        style={{
          width: 60 * u,
          height: 60 * u,
          borderRadius: 30 * u,
          background: hot ? PC.red : PC.ink,
          border: `${6 * u}px solid ${hot ? PC.white : PC.red}`,
          boxSizing: "border-box",
          transform: `scale(${p})`,
          boxShadow: hot ? `0 0 ${30 * u}px rgba(224,22,29,0.8)` : "none",
        }}
      />
      <div style={{ fontFamily: DISPLAY, fontSize: 88 * u, lineHeight: 1, color: hot ? PC.red : PC.white, marginTop: 28 * u }}>{ev.date}</div>
      <div style={{ fontWeight: 700, fontSize: size * u, lineHeight: 1.22, marginTop: 12 * u }}>
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
  const t = useDrift();
  return (
    <PanelBg>
      <div
        style={{
          position: "absolute",
          inset: `${70 * u}px ${wide ? 140 : 80}px ${120 * u}px`,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        {kicker ? <div style={{ opacity: a, position: "relative", zIndex: 2 }}><Chip size={40}>{kicker}</Chip></div> : null}
        <div style={{ position: "relative", marginTop: (kicker ? 150 : 20) * u }}>
          <div style={{ position: "absolute", left: -20 * u, top: -150 * u, fontFamily: DISPLAY, fontSize: 420 * u, lineHeight: 1, color: PC.red, opacity: 0.9 * q }}>“</div>
          <div
            style={{
              position: "relative",
              paddingTop: 110 * u,
              fontWeight: 800,
              fontSize: fit(quote, wide ? 120 : 110, 34, 52) * u,
              lineHeight: 1.24,
              opacity: q,
              transform: `translateY(${(1 - q) * 30 * u}px) scale(${1 + t * 0.015})`,
              transformOrigin: "left center",
            }}
          >
            <Rich text={quote} />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 26 * u, marginTop: 44 * u, opacity: a, transform: `translateY(${(1 - a) * 16 * u}px)` }}>
          {photo ? (
            <Img src={panelAsset(photo)} style={{ width: 110 * u, height: 110 * u, borderRadius: 55 * u, objectFit: "cover", border: `${4 * u}px solid ${PC.red}` }} />
          ) : (
            <div style={{ width: 12 * u, height: 100 * u, background: PC.red }} />
          )}
          <div>
            <div style={{ fontFamily: DISPLAY, fontSize: 84 * u, lineHeight: 1 }}>{author}</div>
            {role ? <div style={{ color: PC.muted, fontWeight: 600, fontSize: 38 * u, marginTop: 8 * u }}>{role}</div> : null}
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
      <div style={{ display: "flex", flexDirection: "column", gap: (dense ? 22 : 34) * u }}>
        {shown.map((item, i) => (
          <BarRow key={i} i={i} n={shown.length} item={item} max={max} prefix={prefix} suffix={suffix} decimals={decimals} dense={dense} />
        ))}
      </div>
      {note ? <div style={{ marginTop: 30 * u, color: PC.muted, fontWeight: 600, fontSize: 38 * u, opacity: nb }}><Rich text={note} /></div> : null}
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
        <span style={{ fontWeight: 800, fontSize: (dense ? 44 : 60) * u }}>
          {item.label}
          {item.note ? <span style={{ color: PC.muted, fontWeight: 600, fontSize: (dense ? 30 : 40) * u, marginLeft: 16 * u }}>{item.note}</span> : null}
        </span>
        <span style={{ fontFamily: DISPLAY, fontSize: (dense ? 80 : 120) * u, lineHeight: 0.9, color: hl ? PC.red : PC.white }}>{shownValue}</span>
      </div>
      <div style={{ height: (dense ? 36 : 64) * u, background: "rgba(255,255,255,0.08)", borderRadius: 6 * u, overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${Math.max(0.6, (Math.abs(item.value) / max) * 100 * grow)}%`,
            background: hl ? `linear-gradient(90deg, ${PC.brand}, ${PC.red})` : "linear-gradient(90deg, rgba(255,255,255,0.45), rgba(255,255,255,0.85))",
            boxShadow: hl ? `0 0 ${24 * u}px rgba(224,22,29,0.6)` : "none",
          }}
        />
      </div>
    </div>
  );
};

// ── PFlow: how something moves, step by step ────────────────────────────────

/** Step reveal times -> interleaved step/arrow times (arrow just before its step). */
const stepTimes = (r: number[]) => r.flatMap((t, i) => (i === 0 ? [t] : [Math.max(0, t - 0.02), t])) as number[];

export type PFlowProps = Framed & { steps: { title: string; text?: string }[]; foot?: string; reveal?: number[] };

export const PFlow: React.FC<PFlowProps> = ({ kicker, title, source, steps, foot, reveal }) => {
  const { u } = usePanel();
  const shown = steps.slice(0, 5);
  const n = shown.length;
  const tsize = fit("x".repeat(longest(shown.map((s) => s.title))), 60, 12, 40);
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
        <div style={{ marginTop: 34 * u, opacity: ft, display: "flex" }}>
          <div style={{ width: 14 * u, background: PC.red }} />
          <div style={{ flex: 1, background: PC.white, color: PC.ink, padding: `${20 * u}px ${28 * u}px`, fontWeight: 800, fontSize: fit(foot, 50, 50, 38) * u, lineHeight: 1.2 }}>
            <Rich text={foot} />
          </div>
        </div>
      ) : null}
    </Panel>
  );
};

const FlowStep: React.FC<{ i: number; n: number; step: { title: string; text?: string }; size: number; reveal?: number[] }> = ({ i, n, step, size, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i * 2, n * 2 - 1, reveal ? stepTimes(reveal) : undefined, 0.45);
  return (
    <div style={{ flex: 1, opacity: p, transform: `translateY(${(1 - p) * 30 * u}px)` }}>
      <Block tone={i === n - 1 ? "red" : "none"} pad={28} style={{ height: "100%", boxSizing: "border-box" }}>
        <div style={{ fontFamily: DISPLAY, fontSize: 46 * u, color: PC.red, lineHeight: 1 }}>STEP {i + 1}</div>
        <div style={{ fontFamily: DISPLAY, fontSize: size * u, lineHeight: 1, marginTop: 10 * u }}>{step.title}</div>
        {step.text ? <div style={{ marginTop: 14 * u, fontWeight: 600, fontSize: 38 * u, lineHeight: 1.3, color: "rgba(255,255,255,0.82)" }}><Rich text={step.text} /></div> : null}
      </Block>
    </div>
  );
};

const FlowArrow: React.FC<{ i: number; n: number; reveal?: number[] }> = ({ i, n, reveal }) => {
  const { u } = usePanel();
  const p = useReveal(i * 2 + 1, n * 2 - 1, reveal ? stepTimes(reveal) : undefined, 0.45);
  return (
    <div style={{ flex: "none", width: 70 * u, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg width={56 * u} height={40 * u} viewBox="0 0 56 40" style={{ opacity: p }}>
        <path d={`M2 20 H${2 + 40 * p}`} stroke={PC.red} strokeWidth={7} strokeLinecap="round" />
        <path d="M34 6 L52 20 L34 34" fill="none" stroke={PC.red} strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" style={{ opacity: p > 0.8 ? 1 : 0 }} />
      </svg>
    </div>
  );
};

// ── PExplainer: what a company / thing is ───────────────────────────────────

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
          inset: `${70 * u}px ${80 * u}px ${110 * u}px`,
          display: "flex",
          flexDirection: wide ? "row" : "column",
          gap: 50 * u,
          justifyContent: "center",
          alignItems: wide ? "center" : "stretch",
        }}
      >
        <div style={{ flex: wide ? 1.1 : "none", opacity: a, transform: `translateY(${(1 - a) * 30 * u}px)` }}>
          {kicker ? <Chip size={36}>{kicker}</Chip> : null}
          <div style={{ display: "flex", alignItems: "center", gap: 34 * u, marginTop: 24 * u }}>
            {logo ? (
              <div style={{ flex: "none", width: 190 * u, height: 190 * u, borderRadius: 26 * u, background: PC.white, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                <Img src={panelAsset(logo)} style={{ maxWidth: "80%", maxHeight: "80%", objectFit: "contain" }} />
              </div>
            ) : null}
            <div style={{ fontFamily: DISPLAY, fontSize: fit(name, 150, 12, 96) * u, lineHeight: 0.92 }}>{name}</div>
          </div>
          <div style={{ height: 8 * u, width: 140 * u, background: PC.red, margin: `${28 * u}px 0` }} />
          <div style={{ fontWeight: 700, fontSize: fit(lead, 60, 60, 44) * u, lineHeight: 1.25, opacity: b }}>
            <Rich text={lead} />
          </div>
        </div>
        {shown.length ? (
          <div style={{ flex: wide ? 1 : "none", display: "grid", gridTemplateColumns: wide || shown.length < 3 ? "1fr" : "1fr 1fr", gap: 18 * u }}>
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
  const { u } = usePanel();
  const p = useBuild(i + 2, n + 2);
  return (
    <div style={{ opacity: p, transform: `translateX(${(1 - p) * 30 * u}px)` }}>
      <Block pad={24} style={{ borderLeft: `${8 * u}px solid ${PC.red}` }}>
        <div style={{ fontFamily: DISPLAY, fontSize: 44 * u, letterSpacing: 1.5 * u, color: PC.red, lineHeight: 1 }}>{f.label}</div>
        <div style={{ fontWeight: 800, fontSize: fit(f.value, 54, 26, 40) * u, lineHeight: 1.2, marginTop: 8 * u }}>
          <Rich text={f.value} />
        </div>
      </Block>
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
  const { u } = usePanel();
  const shown = layers.slice(0, 5);
  const n = shown.length;
  return (
    <Panel kicker={kicker} title={title} source={source} titleSize={110}>
      <div style={{ display: "flex", flexDirection: "column-reverse", gap: 14 * u }}>
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
  // Each layer is a little narrower than the one under it: a stack, not a list.
  const inset = (i / Math.max(1, n - 1)) * 6;
  return (
    <div style={{ margin: `0 ${inset}%`, opacity: p, transform: `translateY(${(1 - p) * -40 * u}px)` }}>
      <Block tone={hot ? "red" : "none"} pad={22} style={{ display: "flex", alignItems: "center", gap: 30 * u, boxShadow: hot ? `0 0 ${40 * u}px rgba(224,22,29,0.45)` : undefined }}>
        <div style={{ fontFamily: DISPLAY, fontSize: 70 * u, lineHeight: 1, flex: "none", minWidth: 520 * u }}>{layer.title}</div>
        {layer.text ? <div style={{ flex: 1, fontWeight: 600, fontSize: 38 * u, lineHeight: 1.25, color: "rgba(255,255,255,0.85)" }}><Rich text={layer.text} /></div> : <div style={{ flex: 1 }} />}
        {layer.tag ? <Chip size={40} tone={hot ? "white" : "ghost"}>{layer.tag}</Chip> : null}
      </Block>
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

// Silence unused-import lint for Header in files that re-export it.
export { Header };
