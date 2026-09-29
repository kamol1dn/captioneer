// Gashtak reel graphics: three, on purpose.
//
// The OTG set is twenty templates because an OTG short is a news brief that
// argues with charts. A Gashtak reel is a man talking, and the brief for these
// was "b-roll, and maybe a simple card if something needs explaining" — so the
// set is a note over the picture, a full frame when the note is too long to sit
// over a face, and the tail card. Anything beyond that would be reaching for
// something the show does not do.
import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import {
  Band,
  COLORS,
  FONT,
  OVER_PICTURE,
  Position,
  SAFE_W,
  marked,
  useEnterExit,
  useUnit,
} from "./theme";

type Tone = "warm" | "cool";
const toneColor = (tone?: Tone) => (tone === "cool" ? COLORS.cool : COLORS.warm);

// ── a note over the picture ──────────────────────────────────────────────────

export type GashtakNoteProps = {
  label?: string;
  title: string;
  detail?: string;
  tone?: Tone;
  position?: Position;
};

/**
 * A book, a term, a name, a place — whatever he just said that a viewer might
 * not know. No card: a rule down the left edge and cream type, which is the
 * long-form show's own lower third read at reel distance.
 */
export const GashtakNote: React.FC<GashtakNoteProps> = ({
  label,
  title,
  detail,
  tone,
  position = "bottom",
}) => {
  const u = useUnit();
  const { enter, exit } = useEnterExit();
  const accent = toneColor(tone);
  return (
    <Band position={position}>
      <div
        style={{
          fontFamily: FONT,
          width: SAFE_W * u,
          opacity: enter * exit,
          transform: `translateY(${((1 - enter) * 26 + (1 - exit) * 12) * u}px)`,
          display: "flex",
          gap: 24 * u,
          ...OVER_PICTURE,
        }}
      >
        {/* The rule draws itself down as the note arrives, which is the only
            motion in the whole template. */}
        <div
          style={{
            width: 5 * u,
            borderRadius: 3 * u,
            background: accent,
            transformOrigin: "top",
            transform: `scaleY(${enter})`,
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1, paddingTop: 2 * u }}>
          {label ? (
            <div
              style={{
                color: accent,
                fontSize: 26 * u,
                fontWeight: 700,
                letterSpacing: 4 * u,
                textTransform: "uppercase",
                marginBottom: 14 * u,
              }}
            >
              {label}
            </div>
          ) : null}
          <div style={{ fontSize: 62 * u, fontWeight: 700, lineHeight: 1.18, letterSpacing: -0.8 * u }}>
            {marked(title, accent)}
          </div>
          {detail ? (
            <div
              style={{
                fontSize: 40 * u,
                fontWeight: 400,
                lineHeight: 1.36,
                marginTop: 16 * u,
                color: COLORS.inkMuted,
              }}
            >
              {marked(detail, accent)}
            </div>
          ) : null}
        </div>
      </div>
    </Band>
  );
};

// ── a full frame when the note is too long to sit over a face ────────────────

export type GashtakFactsProps = {
  label?: string;
  title: string;
  lines?: string[];
  source?: string;
  tone?: Tone;
};

export const GashtakFacts: React.FC<GashtakFactsProps> = ({
  label,
  title,
  lines = [],
  source,
  tone,
}) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const { enter, exit } = useEnterExit(14, 10);
  const accent = toneColor(tone);
  // Lines arrive one after another rather than together: the viewer is being
  // asked to read, and three lines landing at once is a wall.
  const lineIn = (i: number) =>
    interpolate(frame, [10 + i * 7, 22 + i * 7], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  // A slow drift, so a still frame held for four seconds is not actually still.
  const drift = interpolate(frame, [0, durationInFrames], [0, -14 * u]);
  return (
    <AbsoluteFill style={{ fontFamily: FONT, opacity: exit }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 70% at 50% 22%, ${COLORS.ground} 0%, ${COLORS.groundDeep} 100%)`,
        }}
      />
      <AbsoluteFill
        style={{
          padding: `0 ${(SAFE_W === 1080 ? 90 : 100) * u}px`,
          justifyContent: "center",
          transform: `translateY(${drift}px)`,
          ...OVER_PICTURE,
        }}
      >
        {label ? (
          <div
            style={{
              color: accent,
              fontSize: 28 * u,
              fontWeight: 700,
              letterSpacing: 5 * u,
              textTransform: "uppercase",
              opacity: enter,
              marginBottom: 22 * u,
            }}
          >
            {label}
          </div>
        ) : null}
        <div
          style={{
            fontSize: 78 * u,
            fontWeight: 700,
            lineHeight: 1.14,
            letterSpacing: -1.2 * u,
            opacity: enter,
            transform: `translateY(${(1 - enter) * 20 * u}px)`,
          }}
        >
          {marked(title, accent)}
        </div>
        <div
          style={{
            height: 4 * u,
            width: 140 * u,
            background: accent,
            margin: `${40 * u}px 0`,
            transformOrigin: "left",
            transform: `scaleX(${enter})`,
          }}
        />
        {lines.map((line, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 20 * u,
              marginBottom: 26 * u,
              opacity: lineIn(i),
              transform: `translateY(${(1 - lineIn(i)) * 14 * u}px)`,
            }}
          >
            <div
              style={{
                width: 11 * u,
                height: 11 * u,
                borderRadius: "50%",
                background: accent,
                marginTop: 20 * u,
                flexShrink: 0,
              }}
            />
            <div style={{ fontSize: 44 * u, fontWeight: 400, lineHeight: 1.34, color: COLORS.inkMuted }}>
              {marked(line, accent)}
            </div>
          </div>
        ))}
        {source ? (
          <div
            style={{
              marginTop: 24 * u,
              fontSize: 26 * u,
              fontWeight: 400,
              letterSpacing: 1.4 * u,
              color: "rgba(250,250,247,0.5)",
              opacity: lineIn(lines.length),
            }}
          >
            {source}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ── the tail card ────────────────────────────────────────────────────────────

export type GashtakOutroProps = {
  text: string;
  logo?: string;
  logoKey?: "alpha" | "luminance";
  handle?: string;
  scrim?: number;
};

/**
 * The show's mark, drawn in cream rather than pasted in.
 *
 * `gashtak-logo_bw.png` is a white wordmark on opaque black with no alpha at
 * all, so dropping it in as an image puts a black rectangle on the scrim. Under
 * `logoKey="luminance"` the file is used as a mask instead: its white pixels
 * become the shape and everything else is genuinely transparent, which also
 * lets the mark take the card's own ink colour.
 */
const Mark: React.FC<{ src: string; mode: "alpha" | "luminance"; width: number; style: React.CSSProperties }> = ({
  src,
  mode,
  width,
  style,
}) => {
  const url = src.startsWith("http") || src.startsWith("data:") ? src : staticFile(src);
  if (mode === "alpha") return <Img src={url} style={{ width, ...style }} />;
  return (
    <div
      style={{
        width,
        // 1358 x 1062 is the file's own shape; the mask needs a box to fill.
        height: width * (1062 / 1358),
        background: COLORS.ink,
        WebkitMaskImage: `url(${url})`,
        maskImage: `url(${url})`,
        WebkitMaskMode: "luminance",
        maskMode: "luminance",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        ...style,
      } as React.CSSProperties}
    />
  );
};

/**
 * What every reel ends on, over the last of the conversation still running
 * underneath.
 *
 * The reference did this with an adjustment layer carrying a Gaussian blur, and
 * that does not survive an FCP7 round trip — Premiere's own translation log
 * calls the adjustment layer an untranslated synthetic item and hands back
 * black video. So the separation between card and picture is a scrim baked in
 * here, which re-exports as many times as the editor likes.
 */
export const GashtakOutro: React.FC<GashtakOutroProps> = ({
  text,
  logo,
  logoKey = "alpha",
  handle,
  scrim = 0.55,
}) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const wash = interpolate(frame, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const out = interpolate(frame, [durationInFrames - 13, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const mark = interpolate(frame, [10, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const line = interpolate(frame, [22, 44], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ fontFamily: FONT, opacity: out }}>
      <AbsoluteFill style={{ background: "#000", opacity: scrim * wash }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 70 * u }}>
        {logo ? (
          <Mark
            src={logo}
            mode={logoKey}
            width={440 * u}
            style={{ opacity: mark, transform: `translateY(${(1 - mark) * 18 * u}px)` }}
          />
        ) : null}
        <div
          style={{
            width: SAFE_W * u,
            textAlign: "center",
            fontSize: 64 * u,
            fontWeight: 700,
            lineHeight: 1.26,
            letterSpacing: -0.6 * u,
            opacity: line,
            transform: `translateY(${(1 - line) * 16 * u}px)`,
            ...OVER_PICTURE,
          }}
        >
          {marked(text, COLORS.warm)}
        </div>
        {handle ? (
          <div
            style={{
              fontSize: 32 * u,
              fontWeight: 400,
              letterSpacing: 3 * u,
              color: COLORS.warm,
              opacity: line,
            }}
          >
            {handle}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
