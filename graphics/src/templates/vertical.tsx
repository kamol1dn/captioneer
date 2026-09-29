// Denser vertical templates for the shorts: the real page on screen, the number
// at full size, the flow drawn out, a line of the audio punched up. Full-screen
// ones build on FullFrame; cards build on Band/Card like the originals.
//
// Same broadcast language as the rest: Helvetica, flat near-black, hairlines
// between items, the brand-red bar as the signature, red only as an accent.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import {
  Band,
  COLORS,
  Card,
  DISPLAY,
  FONT,
  FullFrame,
  Position,
  Rich,
  Rule,
  SAFE,
  SAFE_W,
  assetSrc,
  fitSize,
  formatNumber,
  plain,
  reveal,
  superLines,
  useCue,
  useStagger,
  useUnit,
} from "../theme";

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
    return <div style={{ position: "absolute", left: x, top: y + h - 2 * u, width: w * p, height: 5 * u, background: COLORS.accent }} />;
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
          border: `${4 * u}px solid ${COLORS.accent}`,
          opacity: p,
        }}
      />
    );
  }
  // A flat red highlighter pass, multiplied into the page so the type stays black.
  return (
    <div
      style={{
        position: "absolute",
        left: x - 4 * u,
        top: y - 1 * u,
        width: (w + 8 * u) * p,
        height: h + 2 * u,
        background: "rgba(224, 22, 29, 0.28)",
        mixBlendMode: "multiply",
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
  const enter = useCue(2, 10);
  const capIn = useCue(Math.round(durationInFrames * Math.min(0.55, (marks[marks.length - 1]?.at ?? 0.3) + 0.12)), 10);
  const hair = Math.max(1, 2 * u);
  return (
    <FullFrame>
      <div style={{ position: "relative", height: winH, ...reveal(enter, u) }}>
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#141414", border: `${hair}px solid ${COLORS.rule}` }}>
          <div
            style={{
              height: WEB.bar * u,
              display: "flex",
              alignItems: "center",
              gap: 20 * u,
              padding: `0 ${24 * u}px`,
              borderBottom: `${hair}px solid ${COLORS.rule}`,
              fontFamily: FONT,
            }}
          >
            <div
              style={{
                flex: 1,
                minWidth: 0,
                color: COLORS.muted,
                fontWeight: 400,
                fontSize: 24 * u,
                overflow: "hidden",
                whiteSpace: "nowrap",
                textOverflow: "ellipsis",
              }}
            >
              {url ?? ""}
            </div>
            {source ? (
              <div
                style={{
                  flex: "none",
                  color: COLORS.accent,
                  fontFamily: DISPLAY,
                  fontWeight: 700,
                  fontSize: 30 * u,
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
          </div>
        </div>
        {caption ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 0,
              display: "flex",
              alignItems: "stretch",
              ...reveal(capIn, u),
            }}
          >
            <div style={{ width: 12 * u, background: COLORS.brand, flex: "none" }} />
            <div
              style={{
                flex: 1,
                background: COLORS.bg,
                color: COLORS.text,
                fontFamily: FONT,
                fontWeight: 700,
                fontSize: fitSize(plain(caption), 52, 34, 38) * u,
                lineHeight: 1.18,
                padding: `${26 * u}px ${32 * u}px`,
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
  // Sized to fill the safe width at its final length (condensed bold runs
  // ~0.5em a character).
  const size = Math.min(420, (SAFE_W - 20) / (final.length * 0.5));
  const lab = useStagger(0, 2, 0.3, 10);
  const ctx = useStagger(1, 2, 0.35, 10);
  return (
    <FullFrame kicker={kicker} source={source}>
      <div style={{ textAlign: "left" }}>
        <div
          style={{
            fontFamily: DISPLAY,
            fontWeight: 700,
            fontSize: size * u,
            lineHeight: 0.92,
            color: COLORS.accent,
            fontVariantNumeric: "tabular-nums",
            whiteSpace: "nowrap",
          }}
        >
          {shown}
        </div>
        <Rule style={{ margin: `${28 * u}px 0 ${24 * u}px` }} />
        <div style={{ fontWeight: 700, fontSize: fitSize(plain(label), 62, 26, 44) * u, lineHeight: 1.15, ...reveal(lab, u) }}>
          <Rich text={label} />
        </div>
        {context ? (
          <div style={{ marginTop: 18 * u, color: COLORS.muted, fontWeight: 400, fontSize: fitSize(plain(context), 42, 36, 32) * u, lineHeight: 1.25, ...reveal(ctx, u) }}>
            <Rich text={context} />
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
    <div style={{ display: "flex", alignItems: "stretch", gap: 28 * u, ...reveal(p, u) }}>
      <div style={{ flex: "none", width: 10 * u, background: hl ? COLORS.brand : COLORS.text }} />
      <div style={{ minWidth: 0, padding: `${4 * u}px 0` }}>
        <div
          style={{
            fontFamily: DISPLAY,
            fontWeight: 700,
            fontSize: fitSize(node.label, dense ? 60 : 72, 16, 46) * u,
            lineHeight: 1,
            textTransform: "uppercase",
            color: hl ? COLORS.accent : COLORS.text,
          }}
        >
          {node.label}
        </div>
        {node.sub ? (
          <div style={{ fontWeight: 400, fontSize: fitSize(node.sub, dense ? 30 : 34, 36, 26) * u, color: COLORS.muted, marginTop: 8 * u, lineHeight: 1.2 }}>
            {node.sub}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const FlowEdge: React.FC<{ i: number; n: number; label?: string; dense: boolean }> = ({ i, n, label, dense }) => {
  const u = useUnit();
  // The connector draws between this node landing and the next.
  const a = useStagger(i, n, 0.5);
  const b = useStagger(i + 1, n, 0.5);
  const draw = Math.min(1, a * 0.4 + b * 0.8);
  const h = (dense ? 52 : 76) * u;
  return (
    <div style={{ position: "relative", height: h, display: "flex", alignItems: "center" }}>
      <div style={{ position: "absolute", left: 4 * u, top: 6 * u, height: (h - 12 * u) * draw, width: Math.max(1, 2 * u), background: COLORS.muted }} />
      {label ? (
        <div style={{ marginLeft: 38 * u, opacity: b }}>
          <span
            style={{
              fontFamily: FONT,
              fontWeight: 500,
              fontSize: (dense ? 24 : 26) * u,
              letterSpacing: 3 * u,
              textTransform: "uppercase",
              color: COLORS.muted,
            }}
          >
            ↓ {label}
          </span>
        </div>
      ) : null}
    </div>
  );
};

// ── NewsStack: the pattern, as a run of headlines ───────────────────────────

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
      {shown.map((it, i) => (
        <NewsRow key={i} i={i} n={shown.length} item={it} />
      ))}
    </FullFrame>
  );
};

const NewsRow: React.FC<{ i: number; n: number; item: NewsStackProps["items"][number] }> = ({ i, n, item }) => {
  const u = useUnit();
  const p = useStagger(i, n, 0.5, 10);
  const last = i === n - 1;
  const dense = n > 3;
  return (
    <div style={reveal(p, u)}>
      {i > 0 ? <Rule /> : null}
      <div style={{ display: "flex", alignItems: "stretch", gap: 26 * u, padding: `${(dense ? 18 : 26) * u}px 0` }}>
        <div style={{ flex: "none", width: 10 * u, background: last ? COLORS.brand : "transparent" }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 18 * u, marginBottom: 8 * u }}>
            <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 38 * u, textTransform: "uppercase", color: last ? COLORS.accent : COLORS.text }}>
              {item.source}
            </span>
            {item.date ? <span style={{ color: COLORS.muted, fontWeight: 400, fontSize: 26 * u }}>{item.date}</span> : null}
          </div>
          <div style={{ fontWeight: 700, fontSize: fitSize(plain(item.headline), dense ? 42 : 50, 40, 34) * u, lineHeight: 1.18 }}>
            <Rich text={item.headline} />
          </div>
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
      <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 40 * u, textTransform: "uppercase", paddingBottom: 18 * u }}>{app}</div>
      <Rule />
      <div style={{ paddingTop: 28 * u, display: "flex", flexDirection: "column", gap: 20 * u }}>
        {shown.map((m, i) => (
          <Bubble key={i} i={i} n={n} m={m} />
        ))}
      </div>
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
  // The assistant "types" for part of its slot before the message lands.
  const typing = ai ? Math.min(slot * 0.5, fps * 0.8) : 0;
  const p = interpolate(frame, [start + typing, start + typing + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const dotsOn = ai && frame >= start && frame < start + typing;
  if (frame < start) return null;
  const box: React.CSSProperties = {
    maxWidth: "82%",
    padding: `${20 * u}px ${28 * u}px`,
    background: ai ? "#1C1C1C" : COLORS.brand,
    color: COLORS.text,
  };
  return (
    <div style={{ display: "flex", justifyContent: ai ? "flex-start" : "flex-end" }}>
      {dotsOn ? (
        <div style={{ ...box, display: "flex", gap: 10 * u, padding: `${24 * u}px ${28 * u}px` }}>
          {[0, 1, 2].map((d) => (
            <span
              key={d}
              style={{
                width: 12 * u,
                height: 12 * u,
                background: COLORS.muted,
                opacity: 0.35 + 0.65 * Math.max(0, Math.sin(((frame - start) / fps) * 9 - d * 0.9)),
              }}
            />
          ))}
        </div>
      ) : (
        <div style={{ ...box, fontWeight: ai ? 400 : 500, fontSize: fitSize(plain(m.text), 40, 50, 32) * u, lineHeight: 1.25, ...reveal(p, u) }}>
          <Rich text={m.text} />
        </div>
      )}
    </div>
  );
};

// ── Punch: one line of the audio, punched up on screen ──────────────────────

export type PunchProps = { text: string; position?: Position };

/**
 * The line a clip turns on, as a broadcast super: big condensed caps on flat
 * near-black blocks, one block per line, the marked phrase in red. Words fade
 * up one after another, so it lands twice — heard and read.
 */
export const Punch: React.FC<PunchProps> = ({ text, position = "bottom" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const flat = plain(text).replace(/\n/g, " ");
  const size = fitSize(flat, 104, 22, 76);
  // Condensed caps run ~0.42em a character.
  const maxChars = Math.max(8, Math.floor((SAFE_W - 60) / (size * 0.42)));
  const lines = superLines(text, maxChars);
  const blockIn = interpolate(frame, [0, 6], [0, 1], { extrapolateRight: "clamp" });
  let k = 0;
  return (
    <Band position={position}>
      <div style={{ width: SAFE_W * u, display: "flex", flexDirection: "column", alignItems: "center", opacity: exit }}>
        {lines.map((line, li) => (
          <div
            key={li}
            style={{
              background: COLORS.bg,
              opacity: blockIn,
              padding: `${10 * u}px ${26 * u}px ${2 * u}px`,
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: size * u,
              lineHeight: 1.04,
              textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}
          >
            {line.map((w, wi) => {
              const delay = 2 + k++ * 3;
              const p = interpolate(frame, [delay, delay + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              return (
                <span
                  key={wi}
                  style={{
                    display: "inline-block",
                    marginRight: wi < line.length - 1 ? 0.22 * size * u : 0,
                    color: w.hl ? COLORS.accent : COLORS.text,
                    opacity: p,
                    transform: `translateY(${(1 - p) * 12 * u}px)`,
                  }}
                >
                  {w.t}
                </span>
              );
            })}
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
  const R = 96;
  const C = 2 * Math.PI * R;
  // A sliver still shows for tiny shares, so "<0.01%" isn't an empty ring.
  const frac = Math.max(0.012, Math.min(1, value / 100)) * t;
  const final = `${prefix}${formatNumber(value, decimals)}${suffix}`;
  const text = useCue(8, 10);
  return (
    <Band position={position}>
      <Card width={940} padding={30} style={{ display: "flex", alignItems: "center", gap: 34 * u }}>
        <div style={{ position: "relative", flex: "none", width: 230 * u, height: 230 * u }}>
          <svg viewBox="0 0 230 230" width={230 * u} height={230 * u} style={{ transform: "rotate(-90deg)" }}>
            <circle cx={115} cy={115} r={R} fill="none" stroke={COLORS.rule} strokeWidth={14} />
            <circle cx={115} cy={115} r={R} fill="none" stroke={COLORS.accent} strokeWidth={14} strokeDasharray={`${C * frac} ${C}`} />
          </svg>
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: DISPLAY,
              fontWeight: 700,
              fontSize: fitSize(final, 76, 4, 48) * u,
              color: COLORS.text,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {prefix}
            {formatNumber(value * t, decimals)}
            {suffix}
          </div>
        </div>
        <div style={{ minWidth: 0, ...reveal(text, u) }}>
          <div style={{ fontWeight: 700, fontSize: fitSize(plain(label), 46, 26, 34) * u, lineHeight: 1.18 }}>
            <Rich text={label} />
          </div>
          {sublabel ? <div style={{ marginTop: 12 * u, color: COLORS.muted, fontWeight: 400, fontSize: 28 * u }}>{sublabel}</div> : null}
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
      <Card width={920} padding={38} style={{ paddingBottom: 22 * u }}>
        {title ? <div style={{ fontWeight: 700, fontSize: fitSize(title, 50, 24, 38) * u, lineHeight: 1.12, marginBottom: 16 * u }}>{title}</div> : null}
        {shown.map((it, i) => (
          <CheckRow key={i} i={i} n={shown.length} item={it} />
        ))}
      </Card>
    </Band>
  );
};

const CheckRow: React.FC<{ i: number; n: number; item: ChecklistProps["items"][number] }> = ({ i, n, item }) => {
  const u = useUnit();
  const p = useStagger(i, n, 0.45, 14);
  const tick = interpolate(p, [0.4, 1], [0, 1], { extrapolateLeft: "clamp" });
  const col = item.ok ? COLORS.text : COLORS.accent;
  return (
    <div style={reveal(p, u)}>
      <Rule />
      <div style={{ display: "flex", alignItems: "center", gap: 24 * u, padding: `${16 * u}px 0` }}>
        <svg width={40 * u} height={40 * u} viewBox="0 0 34 34" style={{ flex: "none" }}>
          {item.ok ? (
            <path d="M4 18 L13 27 L30 7" fill="none" stroke={col} strokeWidth={4} strokeLinecap="square" pathLength={1} strokeDasharray={`${tick} 1`} />
          ) : (
            <>
              <path d="M6 6 L28 28" fill="none" stroke={col} strokeWidth={4} strokeLinecap="square" pathLength={1} strokeDasharray={`${Math.min(1, tick * 2)} 1`} />
              <path d="M28 6 L6 28" fill="none" stroke={col} strokeWidth={4} strokeLinecap="square" pathLength={1} strokeDasharray={`${Math.max(0, tick * 2 - 1)} 1`} />
            </>
          )}
        </svg>
        <div style={{ fontWeight: item.ok ? 700 : 400, fontSize: fitSize(item.text, 42, 28, 32) * u, lineHeight: 1.2, color: item.ok ? COLORS.text : COLORS.muted }}>
          {item.text}
        </div>
      </div>
    </div>
  );
};
