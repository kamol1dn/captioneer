// The hook title: the line a scrolling viewer reads in the first two seconds.
//
// Deliberately unlike the cards — no box around it, bigger type, words landing
// one by one — so it reads as the clip's headline rather than as another piece
// of context. The phrase that carries the tension is marked with *asterisks*
// and lands last, on a yellow highlighter, with a little overshoot.
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Band, COLORS, FONT, Position, SAFE_W, fitSize, useUnit } from "../theme";

export type HookProps = { text: string; kicker?: string; position?: Position };

type Unit = { text: string; hl: boolean; br?: boolean };

/**
 * "Meta wants your inbox *and your card*" -> word units, the marked phrase kept
 * whole. A newline forces a break ("$177M raised.\nStill shut down.") for when
 * the balanced wrap still splits a thought in the wrong place.
 */
const parse = (text: string): Unit[] => {
  const out: Unit[] = [];
  text.split("\n").forEach((line, li) => {
    if (li > 0) out.push({ text: "", hl: false, br: true });
    line.split("*").forEach((part, i) => {
      const hl = i % 2 === 1;
      const t = part.trim();
      if (!t) return;
      if (hl) out.push({ text: t, hl });
      else t.split(/\s+/).forEach((w) => out.push({ text: w, hl: false }));
    });
  });
  return out;
};

export const Hook: React.FC<HookProps> = ({ text, kicker, position = "top" }) => {
  const u = useUnit();
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const units = parse(text);
  const words = units.filter((x) => !x.br);
  const plain = text.replace(/[*\n]/g, "");
  const size = fitSize(plain, 110, 22, 72);
  const exit = interpolate(frame, [durationInFrames - 8, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // A soft shadow pool behind the words: enough contrast over a white wall
  // without the heaviness of a card.
  const pool = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  return (
    <Band position={position}>
      <div
        style={{
          position: "relative",
          width: SAFE_W * u,
          textAlign: "center",
          fontFamily: FONT,
          opacity: exit,
          transform: `translateY(${(1 - exit) * -24 * u}px)`,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: `${-60 * u}px ${-40 * u}px`,
            background: "radial-gradient(closest-side, rgba(0,0,0,0.5), rgba(0,0,0,0))",
            opacity: pool,
          }}
        />
        {kicker ? (
          <div
            style={{
              position: "relative",
              display: "inline-block",
              marginBottom: 18 * u,
              color: COLORS.accent,
              fontWeight: 800,
              fontSize: 32 * u,
              letterSpacing: 3 * u,
              textTransform: "uppercase",
              opacity: pool,
              textShadow: `0 ${3 * u}px ${12 * u}px rgba(0,0,0,0.6)`,
            }}
          >
            {kicker}
          </div>
        ) : null}
        {/* Balanced wrap: lines of similar length instead of a full first
            line and a one-word orphan. */}
        <div style={{ position: "relative", lineHeight: 1.16, fontWeight: 900, fontSize: size * u, textWrap: "balance" }}>
          {units.map((unit, i) => {
            if (unit.br) return <br key={i} />;
            // Words land every ~2.5 frames; the highlighted phrase lands on the
            // beat after the last plain word before it, and springs.
            const delay = 2 + words.indexOf(unit) * 2.5;
            const s = spring({
              frame: frame - delay,
              fps,
              config: unit.hl ? { damping: 11, mass: 0.6 } : { damping: 200, mass: 0.5 },
              durationInFrames: unit.hl ? 16 : 8,
            });
            const common: React.CSSProperties = {
              display: "inline-block",
              margin: `0 ${10 * u}px ${8 * u}px`,
              opacity: Math.min(1, s * 1.4),
              transform: `translateY(${(1 - s) * 26 * u}px) scale(${0.86 + 0.14 * s})`,
              whiteSpace: "nowrap",
            };
            return unit.hl ? (
              <span
                key={i}
                style={{
                  ...common,
                  color: COLORS.accentInk,
                  background: COLORS.accent,
                  padding: `0 ${16 * u}px`,
                  borderRadius: 14 * u,
                  boxShadow: `0 ${8 * u}px ${24 * u}px rgba(0,0,0,0.35)`,
                }}
              >
                {unit.text}
              </span>
            ) : (
              <span
                key={i}
                style={{
                  ...common,
                  color: COLORS.text,
                  textShadow: `0 ${4 * u}px ${18 * u}px rgba(0,0,0,0.55), 0 ${1 * u}px ${3 * u}px rgba(0,0,0,0.5)`,
                }}
              >
                {unit.text}
              </span>
            );
          })}
        </div>
      </div>
    </Band>
  );
};
