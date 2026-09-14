// Denser vertical templates for the shorts: more motion, bigger type, and the
// real page on screen. Full-screen ones build on FullFrame (so they share the
// background, entrance and the block centred between the logo zone and the
// captions); cards build on Band/Card like the originals.
//
// Written after the first EP19 import read as empty: a talking head with a
// small dark card every 15 seconds. These are the beats in between — the
// article itself, the number at full size, the flow drawn out, a line of the
// audio punched up on screen.
import React from "react";
import { Easing, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import {
  Band,
  COLORS,
  Card,
  FONT,
  FullFrame,
  Glass,
  Position,
  SAFE,
  SAFE_W,
  assetSrc,
  fitSize,
  formatNumber,
  useStagger,
  useUnit,
} from "../theme";

const RED = "#FF4D4D";
const PAPER = "#FAFAF7";
const INK = "#0E0F12";

/** "Hokodo raised *$177M*" -> [{t:"Hokodo raised ", hl:false}, {t:"$177M", hl:true}] */
const rich = (text: string) =>
  text.split("*").map((t, i) => ({ t, hl: i % 2 === 1 })).filter((p) => p.t);
const plain = (text: string) => text.replace(/\*/g, "");

const Rich: React.FC<{ text: string; ink?: string; bg?: string }> = ({ text, ink = COLORS.accentInk, bg = COLORS.accent }) => (
  <>
    {rich(text).map((p, i) =>
      p.hl ? (
        <span
          key={i}
          style={{
            color: ink,
            background: bg,
            padding: "0 0.18em",
            borderRadius: "0.14em",
            boxDecorationBreak: "clone",
            WebkitBoxDecorationBreak: "clone",
          }}
        >
          {p.t}
        </span>
      ) : (
        <span key={i}>{p.t}</span>
      ),
    )}
  </>
);

// ── Website: the real page, in a browser window ─────────────────────────────

type Rect = { x: number; y: number; w: number; h: number };
type Mark = Rect & { style?: "marker" | "underline" | "box"; at?: number };

export type WebsiteProps = {
  image: string;
  imgW: number;
  imgH: number;
  url?: string;
  source?: string;
  x0?: number;
  x1?: number;
  path?: [number, number][];
  marks?: Mark[];
  focus?: Rect & { at?: number };
  zoom?: number;
  caption?: string;
};

const MarkView: React.FC<{ m: Mark; dispW: number; dispH: number; ix: number; scroll: number }> = ({ m, dispW, dispH, ix, scroll }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const style = m.style ?? "marker";
  const start = durationInFrames * (m.at ?? 0.3);
  const p = interpolate(frame, [start, start + 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  if (p <= 0) return null;
  const x = m.x * dispW + ix;
  const y = m.y * dispH - scroll;
  const w = m.w * dispW;
  const h = m.h * dispH;
  if (style === "underline") {
    return (
      <svg style={{ position: "absolute", left: x - 4 * u, top: y + h - 4 * u, overflow: "visible" }} width={w + 8 * u} height={20 * u}>
        <path
          d={`M0 ${8 * u} C ${w * 0.3} ${3 * u}, ${w * 0.7} ${13 * u}, ${w + 8 * u} ${6 * u}`}
          fill="none"
          stroke={RED}
          strokeWidth={6 * u}
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={`${p} 1`}
        />
      </svg>
    );
  }
  if (style === "box") {
    return (
      <div
        style={{
          position: "absolute",
          left: x - 8 * u,
          top: y - 6 * u,
          width: w + 16 * u,
          height: h + 12 * u,
          border: `${5 * u}px solid ${RED}`,
          borderRadius: 8 * u,
          opacity: p,
          boxShadow: `0 0 ${24 * u}px rgba(255,77,77,${0.5 * p})`,
        }}
      />
    );
  }
  return (
    <div
      style={{
        position: "absolute",
        left: x - 4 * u,
        top: y - 1 * u,
        width: (w + 8 * u) * p,
        height: h + 2 * u,
        background: "rgba(255, 214, 0, 0.62)",
        mixBlendMode: "multiply",
        borderRadius: `${3 * u}px ${8 * u}px ${5 * u}px ${9 * u}px`,
      }}
    />
  );
};

// Window geometry, in design units — clipper/webcard.py mirrors these numbers
// to plan the crop and the scroll, so change them together.
export const WEB = { bar: 64, capH: 190 };

export const Website: React.FC<WebsiteProps> = ({
  image,
  imgW,
  imgH,
  url,
  source,
  x0 = 0,
  x1 = 1,
  path,
  marks = [],
  focus: focusProp,
  zoom = 1.25,
  caption,
}) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames, height, width, fps } = useVideoConfig();
  const winW = width - SAFE.side * 2 * u;
  const winH = height * (SAFE.bottom - SAFE.top);
  const viewH = winH - WEB.bar * u;
  const k = winW / ((x1 - x0) * imgW);
  const ix = -x0 * imgW * k;
  const dispH = imgH * k;
  const maxScroll = Math.max(0, dispH - viewH);
  const yAt =
    path && path.length > 1
      ? interpolate(frame, path.map((p) => p[0] * durationInFrames), path.map((p) => p[1]), {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.inOut(Easing.cubic),
        })
      : path?.[0]?.[1] ?? 0;
  const scroll = Math.min(maxScroll, Math.max(0, yAt * dispH));
  // Push in on the focus phrase as it draws: the page reads as context first,
  // then the camera moves the line that matters to the middle of the window
  // and enlarges it to where it reads on a phone.
  const focus = focusProp ?? marks[0];
  const zStart = durationInFrames * Math.max(0, (focus?.at ?? 0.25) - 0.06);
  const zp = interpolate(frame, [zStart, zStart + fps * 0.9], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const drift = interpolate(frame, [0, durationInFrames], [0, 0.03]);
  const s = 1 + (zoom - 1) * zp + drift;
  const fx = focus ? (focus.x + focus.w / 2) * imgW * k + ix : winW / 2;
  const fy = focus ? (focus.y + focus.h / 2) * imgH * k - scroll : viewH / 2;
  // Where the focus centre sits on screen: where it is, easing to the middle
  // (a little high when a caption will cover the bottom).
  const cy = caption ? viewH * 0.36 : viewH * 0.45;
  const tx = fx + (winW / 2 - fx) * zp - s * fx;
  const ty = fy + (cy - fy) * zp - s * fy;
  const enter = spring({ frame: frame - 3, fps, config: { damping: 16, mass: 0.7 }, durationInFrames: 20 });
  const capIn = spring({
    frame: frame - Math.round(durationInFrames * Math.min(0.55, (marks[marks.length - 1]?.at ?? 0.3) + 0.12)),
    fps,
    config: { damping: 13, mass: 0.6 },
    durationInFrames: 18,
  });
  return (
    <FullFrame>
      <div style={{ position: "relative", height: winH }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: 26 * u,
            overflow: "hidden",
            background: "#1B1B1E",
            boxShadow: `0 ${30 * u}px ${80 * u}px rgba(0,0,0,0.65), 0 0 0 ${2 * u}px rgba(255,255,255,0.12)`,
            transform: `translateY(${(1 - enter) * 120 * u}px) scale(${0.92 + 0.08 * enter}) rotate(${(1 - enter) * -2}deg)`,
            opacity: Math.min(1, enter * 1.5),
          }}
        >
          <div style={{ height: WEB.bar * u, display: "flex", alignItems: "center", gap: 12 * u, padding: `0 ${22 * u}px`, background: "#26262B" }}>
            {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
              <span key={c} style={{ width: 18 * u, height: 18 * u, borderRadius: 9 * u, background: c, flex: "none" }} />
            ))}
            <div
              style={{
                marginLeft: 14 * u,
                flex: 1,
                minWidth: 0,
                height: 42 * u,
                borderRadius: 21 * u,
                background: "#141417",
                color: "rgba(255,255,255,0.75)",
                fontFamily: FONT,
                fontWeight: 600,
                fontSize: 24 * u,
                display: "flex",
                alignItems: "center",
                padding: `0 ${20 * u}px`,
                overflow: "hidden",
                whiteSpace: "nowrap",
                textOverflow: "ellipsis",
              }}
            >
              <span style={{ color: "#28C840", marginRight: 10 * u }}>●</span>
              {url ?? ""}
            </div>
            {source ? (
              <div
                style={{
                  flex: "none",
                  background: COLORS.accent,
                  color: COLORS.accentInk,
                  fontFamily: FONT,
                  fontWeight: 900,
                  fontSize: 24 * u,
                  letterSpacing: 1 * u,
                  padding: `${6 * u}px ${14 * u}px`,
                  borderRadius: 8 * u,
                  textTransform: "uppercase",
                }}
              >
                {source}
              </div>
            ) : null}
          </div>
          <div style={{ position: "relative", height: viewH, overflow: "hidden", background: "#fff" }}>
            <div style={{ position: "absolute", inset: 0, transform: `translate(${tx}px, ${ty}px) scale(${s})`, transformOrigin: "0 0" }}>
              {image ? <Img src={assetSrc(image)} style={{ position: "absolute", left: ix, top: -scroll, width: imgW * k, height: dispH }} /> : null}
              {marks.map((m, i) => (
                <MarkView key={i} m={m} dispW={imgW * k} dispH={dispH} ix={ix} scroll={scroll} />
              ))}
            </div>
            {/* Bottom fade so the caption sticker sits on something calm. */}
            {caption ? (
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: 0,
                  height: WEB.capH * 1.6 * u,
                  background: "linear-gradient(180deg, rgba(0,0,0,0), rgba(0,0,0,0.55))",
                  opacity: capIn,
                }}
              />
            ) : null}
          </div>
        </div>
        {caption ? (
          <div
            style={{
              position: "absolute",
              left: 28 * u,
              right: 28 * u,
              bottom: 26 * u,
              display: "flex",
              alignItems: "stretch",
              opacity: Math.min(1, capIn * 1.4),
              transform: `translateY(${(1 - capIn) * 60 * u}px) rotate(${(1 - capIn) * 2 - 0.6}deg)`,
              boxShadow: `0 ${16 * u}px ${40 * u}px rgba(0,0,0,0.5)`,
              borderRadius: 16 * u,
              overflow: "hidden",
            }}
          >
            <div style={{ width: 16 * u, background: COLORS.accent, flex: "none" }} />
            <div
              style={{
                flex: 1,
                background: INK,
                color: COLORS.text,
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: fitSize(plain(caption), 52, 34, 38) * u,
                lineHeight: 1.18,
                padding: `${24 * u}px ${30 * u}px`,
              }}
            >
              <Rich text={caption} />
            </div>
          </div>
        ) : null}
      </div>
    </FullFrame>
  );
};

// ── BigNumber: one figure, at full size ─────────────────────────────────────

export type BigNumberProps = {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  label: string;
  context?: string;
  kicker?: string;
  source?: string;
};

export const BigNumber: React.FC<BigNumberProps> = ({ value, prefix = "", suffix = "", decimals = 0, label, context, kicker, source }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const countEnd = Math.max(10, Math.min(Math.round(fps * 1.2), Math.floor(durationInFrames * 0.45)));
  const t = interpolate(frame, [6, countEnd], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const final = `${prefix}${formatNumber(value, decimals)}${suffix}`;
  const shown = `${prefix}${formatNumber(value * t, decimals)}${suffix}`;
  // Sized to fill the safe width at its final length (Montserrat Black runs
  // ~0.78em a character).
  const size = Math.min(300, (SAFE_W - 20) / (final.length * 0.78));
  // A beat when the count lands: a pulse of the number and two rings out.
  const land = spring({ frame: frame - countEnd, fps, config: { damping: 9, mass: 0.5 }, durationInFrames: 18 });
  const ring = (delay: number) =>
    interpolate(frame, [countEnd + delay, countEnd + delay + 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const lab = useStagger(0, 2, 0.3, 10);
  const ctx = useStagger(1, 2, 0.35, 10);
  return (
    <FullFrame kicker={kicker} source={source}>
      <div style={{ position: "relative", textAlign: "center" }}>
        {[0, 7].map((d) => {
          const r = ring(d);
          return (
            <div
              key={d}
              style={{
                position: "absolute",
                left: "50%",
                top: size * 0.55 * u,
                width: 900 * u * (0.4 + r),
                height: 900 * u * (0.4 + r),
                marginLeft: -450 * u * (0.4 + r),
                marginTop: -450 * u * (0.4 + r),
                borderRadius: "50%",
                border: `${6 * u}px solid rgba(255,220,0,${0.5 * (1 - r)})`,
                opacity: r > 0 ? 1 : 0,
              }}
            />
          );
        })}
        <div
          style={{
            position: "relative",
            fontWeight: 900,
            fontSize: size * u,
            lineHeight: 1.05,
            letterSpacing: -4 * u,
            color: COLORS.accent,
            fontVariantNumeric: "tabular-nums",
            textShadow: `0 0 ${60 * u}px rgba(255,220,0,0.35)`,
            transform: `scale(${0.9 + 0.1 * Math.min(1, t * 1.2) + 0.05 * (land - Math.min(1, land))})`,
            whiteSpace: "nowrap",
          }}
        >
          {shown}
        </div>
        <div
          style={{
            position: "relative",
            marginTop: 18 * u,
            fontWeight: 800,
            fontSize: fitSize(plain(label), 66, 26, 44) * u,
            lineHeight: 1.15,
            opacity: lab,
            transform: `translateY(${(1 - lab) * 30 * u}px)`,
          }}
        >
          <Rich text={label} />
        </div>
        {context ? (
          <div style={{ marginTop: 34 * u, display: "flex", justifyContent: "center", opacity: ctx, transform: `translateY(${(1 - ctx) * 20 * u}px)` }}>
            <Glass tint="cyan" padding={20} style={{ fontWeight: 700, fontSize: fitSize(plain(context), 42, 36, 32) * u, lineHeight: 1.2, color: COLORS.text }}>
              <Rich text={context} ink={INK} bg={COLORS.cyan} />
            </Glass>
          </div>
        ) : null}
      </div>
    </FullFrame>
  );
};

// ── Flow: how the money (or the data) moves ─────────────────────────────────

export type FlowProps = {
  kicker?: string;
  title?: string;
  source?: string;
  nodes: { label: string; sub?: string; highlight?: boolean }[];
  edges?: string[];
};

export const Flow: React.FC<FlowProps> = ({ kicker, title, source, nodes, edges = [] }) => {
  const u = useUnit();
  const shown = nodes.slice(0, 5);
  const n = shown.length;
  const dense = n > 3;
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch" }}>
        {shown.map((node, i) => (
          <React.Fragment key={i}>
            <FlowNode i={i} n={n} node={node} dense={dense} />
            {i < n - 1 ? <FlowEdge i={i} n={n} label={edges[i]} dense={dense} /> : null}
          </React.Fragment>
        ))}
      </div>
    </FullFrame>
  );
};

const FlowNode: React.FC<{ i: number; n: number; node: FlowProps["nodes"][number]; dense: boolean }> = ({ i, n, node, dense }) => {
  const u = useUnit();
  const p = useStagger(i, n, 0.5);
  const hl = !!node.highlight;
  return (
    <div style={{ opacity: p, transform: `scale(${0.85 + 0.15 * p})` }}>
      <Glass tint={hl ? "accent" : "none"} padding={dense ? 18 : 26} style={{ display: "flex", alignItems: "center", gap: 24 * u }}>
        <div
          style={{
            flex: "none",
            width: (dense ? 58 : 72) * u,
            height: (dense ? 58 : 72) * u,
            borderRadius: 18 * u,
            background: hl ? `linear-gradient(145deg, ${COLORS.accent}, #FFB800)` : `linear-gradient(145deg, ${COLORS.cyan}, #0FA8A0)`,
            color: COLORS.accentInk,
            fontWeight: 900,
            fontSize: (dense ? 30 : 36) * u,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {i + 1}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 900, fontSize: fitSize(node.label, dense ? 46 : 54, 20, 38) * u, lineHeight: 1.1, color: hl ? COLORS.accent : COLORS.text }}>
            {node.label}
          </div>
          {node.sub ? (
            <div style={{ fontWeight: 600, fontSize: fitSize(node.sub, dense ? 30 : 34, 36, 26) * u, color: COLORS.muted, marginTop: 6 * u, lineHeight: 1.2 }}>
              {node.sub}
            </div>
          ) : null}
        </div>
      </Glass>
    </div>
  );
};

const FlowEdge: React.FC<{ i: number; n: number; label?: string; dense: boolean }> = ({ i, n, label, dense }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // The edge draws between this node landing and the next.
  const a = useStagger(i, n, 0.5);
  const b = useStagger(i + 1, n, 0.5);
  const draw = Math.min(1, a * 0.4 + b * 0.8);
  const h = (dense ? 58 : 84) * u;
  // A packet travelling down the edge, forever, once it has drawn.
  const cycle = fps * 1.1;
  const pk = ((frame + i * 9) % cycle) / cycle;
  return (
    <div style={{ position: "relative", height: h, display: "flex", alignItems: "center" }}>
      <div style={{ position: "absolute", left: (dense ? 56 : 62) * u, top: 0, height: h * draw, width: 6 * u, borderRadius: 3 * u, background: `linear-gradient(180deg, ${COLORS.cyan}, ${COLORS.accent})` }} />
      <div
        style={{
          position: "absolute",
          left: (dense ? 49 : 55) * u,
          top: h * draw - 12 * u,
          width: 0,
          height: 0,
          borderLeft: `${10 * u}px solid transparent`,
          borderRight: `${10 * u}px solid transparent`,
          borderTop: `${14 * u}px solid ${COLORS.accent}`,
          opacity: draw > 0.95 ? 1 : 0,
        }}
      />
      {draw >= 1 ? (
        <div
          style={{
            position: "absolute",
            left: (dense ? 51 : 57) * u,
            top: pk * (h - 16 * u),
            width: 16 * u,
            height: 16 * u,
            borderRadius: 8 * u,
            background: "#fff",
            boxShadow: `0 0 ${18 * u}px ${COLORS.accent}`,
            opacity: Math.sin(pk * Math.PI),
          }}
        />
      ) : null}
      {label ? (
        <div
          style={{
            marginLeft: 110 * u,
            color: COLORS.cyan,
            fontWeight: 800,
            fontSize: (dense ? 28 : 32) * u,
            letterSpacing: 1 * u,
            textTransform: "uppercase",
            opacity: b,
          }}
        >
          {label}
        </div>
      ) : null}
    </div>
  );
};

// ── NewsStack: the pattern, as a pile of headlines ──────────────────────────

export type NewsStackProps = {
  kicker?: string;
  title?: string;
  source?: string;
  items: { source: string; headline: string; date?: string }[];
};

export const NewsStack: React.FC<NewsStackProps> = ({ kicker, title, source, items }) => {
  const shown = items.slice(0, 4);
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {shown.map((it, i) => (
          <NewsCard key={i} i={i} n={shown.length} item={it} />
        ))}
      </div>
    </FullFrame>
  );
};

const NewsCard: React.FC<{ i: number; n: number; item: NewsStackProps["items"][number] }> = ({ i, n, item }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const window = Math.max(n * 8, durationInFrames * 0.5 - 10);
  const start = 10 + (i * window) / n;
  const p = spring({ frame: frame - start, fps, config: { damping: 14, mass: 0.7 }, durationInFrames: 20 });
  const last = i === n - 1;
  const dense = n > 3;
  const tilt = (i % 2 === 0 ? -1.4 : 1.2) * (last ? 0.4 : 1);
  return (
    <div
      style={{
        position: "relative",
        zIndex: i,
        marginTop: i === 0 ? 0 : (dense ? -8 : 4) * u,
        opacity: Math.min(1, p * 1.6),
        transform: `translateX(${(1 - p) * (i % 2 === 0 ? -700 : 700) * u}px) rotate(${tilt}deg)`,
      }}
    >
      <div
        style={{
          background: PAPER,
          color: INK,
          borderRadius: 18 * u,
          padding: `${(dense ? 20 : 28) * u}px ${32 * u}px`,
          boxShadow: `0 ${18 * u}px ${44 * u}px rgba(0,0,0,0.5)`,
          borderLeft: `${12 * u}px solid ${last ? COLORS.accent : "#D8D8D2"}`,
          fontFamily: FONT,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 * u, marginBottom: 10 * u }}>
          <span style={{ background: INK, color: "#fff", fontWeight: 900, fontSize: 24 * u, letterSpacing: 1.5 * u, padding: `${4 * u}px ${12 * u}px`, borderRadius: 6 * u, textTransform: "uppercase" }}>
            {item.source}
          </span>
          {item.date ? <span style={{ color: "#6B6B66", fontWeight: 700, fontSize: 24 * u, textTransform: "uppercase", letterSpacing: 1 * u }}>{item.date}</span> : null}
        </div>
        <div style={{ fontWeight: 800, fontSize: fitSize(plain(item.headline), dense ? 40 : 46, 44, 32) * u, lineHeight: 1.18 }}>
          <Rich text={item.headline} />
        </div>
      </div>
    </div>
  );
};

// ── Chat: what asking the AI looks like ─────────────────────────────────────

export type ChatProps = {
  kicker?: string;
  title?: string;
  source?: string;
  app?: string;
  messages: { from: "user" | "ai"; text: string }[];
};

export const Chat: React.FC<ChatProps> = ({ kicker, title, source, app = "AI assistant", messages }) => {
  const u = useUnit();
  const shown = messages.slice(0, 4);
  const n = shown.length;
  return (
    <FullFrame kicker={kicker} title={title} source={source}>
      <Glass padding={0} style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 * u, padding: `${20 * u}px ${28 * u}px`, borderBottom: `${2 * u}px solid rgba(255,255,255,0.1)`, background: "rgba(255,255,255,0.04)" }}>
          <div style={{ width: 52 * u, height: 52 * u, borderRadius: 26 * u, background: `conic-gradient(${COLORS.cyan}, ${COLORS.accent}, ${COLORS.cyan})` }} />
          <div style={{ fontWeight: 800, fontSize: 36 * u }}>{app}</div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 * u, color: COLORS.cyan, fontWeight: 700, fontSize: 24 * u }}>
            <span style={{ width: 12 * u, height: 12 * u, borderRadius: 6 * u, background: COLORS.cyan }} />
            online
          </div>
        </div>
        <div style={{ padding: `${26 * u}px ${24 * u}px`, display: "flex", flexDirection: "column", gap: 18 * u }}>
          {shown.map((m, i) => (
            <Bubble key={i} i={i} n={n} m={m} />
          ))}
        </div>
      </Glass>
    </FullFrame>
  );
};

const Bubble: React.FC<{ i: number; n: number; m: ChatProps["messages"][number] }> = ({ i, n, m }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const window = Math.max(n * 14, durationInFrames * 0.62 - 10);
  const slot = window / n;
  const start = 10 + i * slot;
  const ai = m.from === "ai";
  // The assistant "types" for part of its slot before the bubble lands.
  const typing = ai ? Math.min(slot * 0.5, fps * 0.8) : 0;
  const p = spring({ frame: frame - start - typing, fps, config: { damping: 15, mass: 0.6 }, durationInFrames: 14 });
  const dotsOn = ai && frame >= start && frame < start + typing;
  if (frame < start) return null;
  return (
    <div style={{ display: "flex", justifyContent: ai ? "flex-start" : "flex-end" }}>
      {dotsOn ? (
        <div style={{ display: "flex", gap: 10 * u, padding: `${22 * u}px ${28 * u}px`, borderRadius: 30 * u, background: "rgba(255,255,255,0.1)" }}>
          {[0, 1, 2].map((d) => (
            <span
              key={d}
              style={{
                width: 14 * u,
                height: 14 * u,
                borderRadius: 7 * u,
                background: "#fff",
                opacity: 0.35 + 0.65 * Math.max(0, Math.sin(((frame - start) / fps) * 9 - d * 0.9)),
              }}
            />
          ))}
        </div>
      ) : (
        <div
          style={{
            maxWidth: "82%",
            padding: `${20 * u}px ${28 * u}px`,
            borderRadius: 30 * u,
            borderBottomRightRadius: ai ? 30 * u : 8 * u,
            borderBottomLeftRadius: ai ? 8 * u : 30 * u,
            background: ai ? "rgba(255,255,255,0.1)" : `linear-gradient(145deg, ${COLORS.cyan}, #0FA8A0)`,
            color: ai ? COLORS.text : INK,
            fontWeight: ai ? 600 : 700,
            fontSize: fitSize(plain(m.text), 40, 50, 32) * u,
            lineHeight: 1.25,
            opacity: p,
            transform: `translateY(${(1 - p) * 24 * u}px) scale(${0.9 + 0.1 * p})`,
            transformOrigin: ai ? "left bottom" : "right bottom",
          }}
        >
          <Rich text={m.text} />
        </div>
      )}
    </div>
  );
};

// ── Punch: one line of the audio, punched up on screen ──────────────────────

export type PunchProps = { text: string; position?: Position };

/**
 * A sticker, not a card: white boxes with black type, the marked phrase on
 * yellow, popping in with overshoot and a slight tilt. For the line the clip
 * turns on — "Necessary and *irrelevant*" — so it lands twice, heard and read.
 */
export const Punch: React.FC<PunchProps> = ({ text, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const lines = text.split("\n");
  const size = fitSize(plain(text).replace(/\n/g, " "), 84, 24, 58);
  let k = 0;
  return (
    <Band position={position}>
      <div
        style={{
          width: SAFE_W * u,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 10 * u,
          fontFamily: FONT,
          opacity: exit,
          transform: `rotate(-2deg) scale(${1 - (1 - exit) * 0.1})`,
        }}
      >
        {lines.map((line, li) => (
          <div key={li} style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 10 * u }}>
            {rich(line).flatMap((part) =>
              (part.hl ? [part.t.trim()] : part.t.trim().split(/\s+/)).filter(Boolean).map((w) => {
                const idx = k++;
                const s = spring({
                  frame: frame - 2 - idx * 3,
                  fps,
                  config: { damping: part.hl ? 8 : 12, mass: 0.5 },
                  durationInFrames: 16,
                });
                return (
                  <span
                    key={`${li}-${idx}`}
                    style={{
                      display: "inline-block",
                      background: part.hl ? COLORS.accent : "#fff",
                      color: INK,
                      fontWeight: 900,
                      fontSize: size * u,
                      lineHeight: 1.12,
                      padding: `${4 * u}px ${18 * u}px`,
                      borderRadius: 12 * u,
                      boxShadow: `0 ${10 * u}px ${28 * u}px rgba(0,0,0,0.4)`,
                      opacity: Math.min(1, s * 2),
                      transform: `scale(${0.4 + 0.6 * s}) rotate(${(1 - s) * (idx % 2 ? 8 : -8)}deg)`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {w}
                  </span>
                );
              }),
            )}
          </div>
        ))}
      </div>
    </Band>
  );
};

// ── Ring: a share, as a ring that fills ─────────────────────────────────────

export type RingProps = { value: number; label: string; sublabel?: string; prefix?: string; suffix?: string; decimals?: number; position?: Position };

export const Ring: React.FC<RingProps> = ({ value, label, sublabel, prefix = "", suffix = "%", decimals = 0, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const end = Math.max(8, Math.min(Math.round(fps * 1.2), Math.floor(durationInFrames / 2)));
  const t = interpolate(frame, [6, end], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const R = 92;
  const C = 2 * Math.PI * R;
  // A sliver still shows for tiny shares, so "<0.01%" isn't an empty ring.
  const frac = Math.max(0.012, Math.min(1, value / 100)) * t;
  const final = `${prefix}${formatNumber(value, decimals)}${suffix}`;
  return (
    <Band position={position}>
      <Card width={940} padding={30} style={{ display: "flex", alignItems: "center", gap: 34 * u }}>
        <div style={{ position: "relative", flex: "none", width: 230 * u, height: 230 * u }}>
          <svg viewBox="0 0 230 230" width={230 * u} height={230 * u} style={{ transform: "rotate(-90deg)" }}>
            <circle cx={115} cy={115} r={R} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth={26} />
            <circle
              cx={115}
              cy={115}
              r={R}
              fill="none"
              stroke={COLORS.accent}
              strokeWidth={26}
              strokeLinecap="round"
              strokeDasharray={`${C * frac} ${C}`}
              style={{ filter: "drop-shadow(0 0 8px rgba(255,220,0,0.6))" }}
            />
          </svg>
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 900,
              fontSize: fitSize(final, 64, 4, 40) * u,
              color: COLORS.accent,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {prefix}
            {formatNumber(value * t, decimals)}
            {suffix}
          </div>
        </div>
        <div>
          <div style={{ fontWeight: 800, fontSize: fitSize(plain(label), 48, 26, 34) * u, lineHeight: 1.18 }}>
            <Rich text={label} />
          </div>
          {sublabel ? <div style={{ marginTop: 12 * u, color: COLORS.muted, fontWeight: 500, fontSize: 28 * u }}>{sublabel}</div> : null}
        </div>
      </Card>
    </Band>
  );
};

// ── Checklist: what it has, and what it doesn't ─────────────────────────────

export type ChecklistProps = { title?: string; items: { text: string; ok: boolean }[]; position?: Position };

export const Checklist: React.FC<ChecklistProps> = ({ title, items, position = "bottom" }) => {
  const u = useUnit();
  const shown = items.slice(0, 4);
  return (
    <Band position={position}>
      <Card width={920} padding={38}>
        {title ? <div style={{ fontWeight: 900, fontSize: fitSize(title, 52, 24, 38) * u, lineHeight: 1.1, marginBottom: 24 * u }}>{title}</div> : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 * u }}>
          {shown.map((it, i) => (
            <CheckRow key={i} i={i} n={shown.length} item={it} />
          ))}
        </div>
      </Card>
    </Band>
  );
};

const CheckRow: React.FC<{ i: number; n: number; item: ChecklistProps["items"][number] }> = ({ i, n, item }) => {
  const u = useUnit();
  const p = useStagger(i, n, 0.45, 14);
  const tick = interpolate(p, [0.4, 1], [0, 1], { extrapolateLeft: "clamp" });
  const col = item.ok ? COLORS.cyan : RED;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 22 * u, opacity: Math.min(1, p * 1.5), transform: `translateX(${(1 - p) * 40 * u}px)` }}>
      <div
        style={{
          flex: "none",
          width: 64 * u,
          height: 64 * u,
          borderRadius: 32 * u,
          border: `${5 * u}px solid ${col}`,
          background: `rgba(${item.ok ? "25,224,214" : "255,77,77"},${0.18 * tick})`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxSizing: "border-box",
        }}
      >
        <svg width={34 * u} height={34 * u} viewBox="0 0 34 34">
          {item.ok ? (
            <path d="M5 18 L14 26 L29 8" fill="none" stroke={col} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={`${tick} 1`} />
          ) : (
            <>
              <path d="M8 8 L26 26" fill="none" stroke={col} strokeWidth={5} strokeLinecap="round" pathLength={1} strokeDasharray={`${Math.min(1, tick * 2)} 1`} />
              <path d="M26 8 L8 26" fill="none" stroke={col} strokeWidth={5} strokeLinecap="round" pathLength={1} strokeDasharray={`${Math.max(0, tick * 2 - 1)} 1`} />
            </>
          )}
        </svg>
      </div>
      <div style={{ fontWeight: 700, fontSize: fitSize(item.text, 44, 28, 32) * u, lineHeight: 1.2 }}>{item.text}</div>
    </div>
  );
};

