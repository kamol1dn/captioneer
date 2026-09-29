// The Gashtak reel look, kept apart from the OTG one on purpose.
//
// OTG's graphics are a red-and-white system built on dark cards: a headline
// sits *on* something. Gashtak is the opposite show — a conversation, shot warm
// — and the long-form lower thirds already established its language: Helvetica,
// cream type on nothing, a hairline of accent, no box unless a box is the
// point. These are the same rules at reel size.
//
// Sharing `../theme` would have meant one file where a tweak for one show moves
// the other, and the two shows are edited by different people in different
// weeks. The only thing deliberately duplicated is the unit system.
import { loadFont } from "@remotion/fonts";
import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FONT = "Gashtak Helvetica";
// Loaded from fonts/, not _assets/: _assets is the image staging dir, named by
// content hash and safe to empty, and a font that vanishes takes every render
// with it.
void loadFont({ family: FONT, url: staticFile("fonts/Helvetica.ttf"), weight: "400" });
void loadFont({ family: FONT, url: staticFile("fonts/Helvetica-Bold.ttf"), weight: "700" });

export const COLORS = {
  // Not white. The long-form lower thirds sit at this warm off-white against
  // the show's lamp-lit set, and pure white reads as a different graphic system.
  ink: "#FAFAF7",
  inkMuted: "#E5E7E6",
  // Warm for things on paper — a book, a name, a quote.
  warm: "#E4D7BC",
  // Cool for things from outside the room — a question, a place, a number.
  cool: "#A4D9ED",
  // The full-frame ground: the set's own near-black, not the OTG card grey.
  ground: "#14120F",
  groundDeep: "#0A0908",
};

/** Pixels per design unit: 1 at 1080 wide, so one design works at any size. */
export const useUnit = () => useVideoConfig().width / 1080;

/**
 * The reel's reserved bands, as fractions of height.
 *
 * Gashtak reels carry no persistent logo — the mark only appears on the tail
 * card — so unlike OTG there is nothing reserved at the top. What *is* reserved
 * is the middle: the caption strip is a 1440x181 file laid in at 100% and
 * therefore centred, and the editor nudges it by hand from there. Graphics stay
 * clear of that band on both sides of it.
 */
export const SAFE = {
  top: 0.08,
  topLimit: 0.4,
  captions: [0.44, 0.58] as const,
  bottom: 0.9,
  // A tall phone crops ~9% off each side of a 9:16 reel. Anything that has to
  // be read stays inside the middle; only backgrounds reach the edge.
  side: 100,
};

export const SAFE_W = 1080 - 2 * SAFE.side;

export type Position = "top" | "bottom";

/**
 * Text drops in and lifts out under its own power, so nothing needs a dissolve
 * applied in Premiere — a dissolve applied by hand does not survive the next
 * XML export, and these files are re-exported constantly.
 */
export const useEnterExit = (enterFrames = 12, exitFrames = 9) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const enter = interpolate(frame, [0, enterFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const exit = interpolate(
    frame,
    [durationInFrames - exitFrames, durationInFrames - 1],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.in(Easing.cubic) },
  );
  return { enter, exit, visible: Math.min(enter, exit) };
};

/**
 * Anchored by the edge it must not cross, so a taller block grows away from the
 * captions rather than into them.
 */
export const Band: React.FC<{ position?: Position; children: React.ReactNode }> = ({
  position = "bottom",
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
          ...(position === "bottom"
            ? { bottom: (1 - SAFE.bottom) * height }
            : { top: SAFE.top * height }),
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};

/**
 * Cream type over moving footage with no card behind it. The shadow is the only
 * thing keeping it legible over a bright frame, which is why it is two shadows:
 * a tight dark one for edge contrast and a wide soft one for the halo.
 */
export const OVER_PICTURE: React.CSSProperties = {
  color: COLORS.ink,
  textShadow: "0 2px 5px rgba(0,0,0,0.8), 0 0 18px rgba(0,0,0,0.45)",
};

/** `*asterisks*` become accent-coloured runs; everything else is plain. */
export const marked = (text: string, accent: string): React.ReactNode[] =>
  text.split(/(\*[^*]+\*)/g).filter(Boolean).map((part, i) =>
    part.startsWith("*") && part.endsWith("*") && part.length > 2 ? (
      <span key={i} style={{ color: accent }}>{part.slice(1, -1)}</span>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    ),
  );
