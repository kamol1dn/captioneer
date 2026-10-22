"""Where the people are in a program frame, and where a graphic can go.

Faces come from YuNet on the composited frame Premiere exports (so nests,
crops and punch-ins are already applied). Each face is grown into a body
estimate; the frame is then a coarse grid of occupied cells, and a graphic of
a given size is placed on the largest free run of cells, preferring a spot
beside the speaker's head when one is named.

All coordinates are normalised to the frame (0-1), independent of its size.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parents[1].parent / "reel-studio" / "models" / "face_detection_yunet_2023mar.onnx"

# A seated person, in face units: shoulders ~3.2 faces wide, the head a bit
# above the box, the torso down to the table (~4.5 face heights).
BODY_WIDTH = 3.2
BODY_UP = 0.6
BODY_DOWN = 4.5

COLS, ROWS = 48, 27
# Keep graphics off the frame edge and off the band where lower thirds sit.
MARGIN = {"left": 0.04, "right": 0.04, "top": 0.05, "bottom": 0.12}


def detect_faces(image_bgr) -> list[dict]:
    """YuNet faces on a BGR frame: [{x, y, w, h, score}] normalised."""
    import cv2
    h, w = image_bgr.shape[:2]
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.6, 0.3, 50)
    _, faces = det.detect(image_bgr)
    out = []
    if faces is not None:
        for x, y, bw, bh, s in faces[:, [0, 1, 2, 3, 14]]:
            out.append({"x": round(float(x) / w, 4), "y": round(float(y) / h, 4),
                        "w": round(float(bw) / w, 4), "h": round(float(bh) / h, 4), "score": round(float(s), 2)})
    out.sort(key=lambda f: f["x"])
    return out


SEATS = {"left": 0.2, "centre": 0.5, "right": 0.8}


def face_for(faces: list[dict], seat: str) -> dict | None:
    """The face in a seat. With every seat on screen, by order left to
    right; in a tighter shot, the face nearest the seat's usual place."""
    seat = {"center": "centre"}.get(seat, seat)
    if seat not in SEATS or not faces:
        return None
    if len(faces) >= len(SEATS):
        return faces[list(SEATS).index(seat)]
    cx = SEATS[seat]
    return min(faces, key=lambda f: abs(f["x"] + f["w"] / 2 - cx))


def body_of(face: dict) -> dict:
    cx = face["x"] + face["w"] / 2
    x0 = max(0.0, cx - face["w"] * BODY_WIDTH / 2)
    x1 = min(1.0, cx + face["w"] * BODY_WIDTH / 2)
    y0 = max(0.0, face["y"] - face["h"] * BODY_UP)
    y1 = min(1.0, face["y"] + face["h"] * BODY_DOWN)
    return {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}


def occupancy(faces: list[dict], extra: list[dict] | None = None) -> np.ndarray:
    """ROWS x COLS boolean grid: True where a person (or an ``extra`` box the
    caller wants kept clear, e.g. an existing graphic) is."""
    grid = np.zeros((ROWS, COLS), dtype=bool)
    for box in [body_of(f) for f in faces] + list(extra or []):
        c0, c1 = int(box["x"] * COLS), int(np.ceil((box["x"] + box["w"]) * COLS))
        r0, r1 = int(box["y"] * ROWS), int(np.ceil((box["y"] + box["h"]) * ROWS))
        grid[max(0, r0):min(ROWS, r1), max(0, c0):min(COLS, c1)] = True
    return grid


def _usable(margin: dict | None) -> tuple[int, int, int, int]:
    m = MARGIN | (margin or {})
    return (int(np.ceil(m["top"] * ROWS)), int(ROWS - np.ceil(m["bottom"] * ROWS)),
            int(np.ceil(m["left"] * COLS)), int(COLS - np.ceil(m["right"] * COLS)))


def free_rects(grid: np.ndarray, margin: dict | None = None, limit: int = 6) -> list[dict]:
    """The largest free rectangles (normalised), none contained in another."""
    r_lo, r_hi, c_lo, c_hi = _usable(margin)
    occ = np.zeros((ROWS + 1, COLS + 1), dtype=np.int32)
    occ[1:, 1:] = np.cumsum(np.cumsum(grid.astype(np.int32), axis=0), axis=1)

    def filled(r0, r1, c0, c1):  # cells [r0, r1) x [c0, c1)
        return occ[r1, c1] - occ[r0, c1] - occ[r1, c0] + occ[r0, c0]

    rects = []
    for r0 in range(r_lo, r_hi):
        for c0 in range(c_lo, c_hi):
            if grid[r0, c0]:
                continue
            best_c1 = c_hi
            for r1 in range(r0 + 1, r_hi + 1):
                # Widest run of free cells starting at c0 across rows r0..r1-1.
                c1 = c0
                while c1 < best_c1 and filled(r1 - 1, r1, c1, c1 + 1) == 0:
                    c1 += 1
                best_c1 = c1
                if c1 == c0:
                    break
                rects.append((r0, r1, c0, c1))
    # Drop rectangles contained in another, keep the largest.
    rects.sort(key=lambda r: -((r[1] - r[0]) * (r[3] - r[2])))
    kept: list[tuple] = []
    for r in rects:
        if any(k[0] <= r[0] and k[1] >= r[1] and k[2] <= r[2] and k[3] >= r[3] for k in kept):
            continue
        kept.append(r)
        if len(kept) >= limit:
            break
    return [{"x": round(c0 / COLS, 4), "y": round(r0 / ROWS, 4),
             "w": round((c1 - c0) / COLS, 4), "h": round((r1 - r0) / ROWS, 4)} for r0, r1, c0, c1 in kept]


def place(grid: np.ndarray, w: float, h: float, near: dict | None = None,
          margin: dict | None = None, limit: int = 5) -> list[dict]:
    """Positions (top-left, normalised) where a w x h graphic sits on free
    cells. With ``near`` (a face box), the closest spots at head height come
    first; otherwise the ones farthest from everyone, i.e. roomiest."""
    r_lo, r_hi, c_lo, c_hi = _usable(margin)
    cw, ch = int(np.ceil(w * COLS)), int(np.ceil(h * ROWS))
    occ = np.zeros((ROWS + 1, COLS + 1), dtype=np.int32)
    occ[1:, 1:] = np.cumsum(np.cumsum(grid.astype(np.int32), axis=0), axis=1)
    spots = []
    for r0 in range(r_lo, r_hi - ch + 1):
        for c0 in range(c_lo, c_hi - cw + 1):
            r1, c1 = r0 + ch, c0 + cw
            if occ[r1, c1] - occ[r0, c1] - occ[r1, c0] + occ[r0, c0]:
                continue
            x, y = c0 / COLS, r0 / ROWS
            if near:
                hx, hy = near["x"] + near["w"] / 2, near["y"] + near["h"] / 2
                gx, gy = x + w / 2, y + h / 2
                score = -(((gx - hx) * 1.0) ** 2 + ((gy - hy) * 2.5) ** 2)  # same height matters more
            else:
                # Distance to the nearest occupied cell, bigger is better.
                rr, cc = np.nonzero(grid)
                if len(rr):
                    d = np.sqrt(((rr / ROWS) - (y + h / 2)) ** 2 + ((cc / COLS) - (x + w / 2)) ** 2)
                    score = float(d.min())
                else:
                    score = -abs(y + h / 2 - 0.5) - abs(x + w / 2 - 0.5)
            spots.append((score, round(x, 4), round(y, 4)))
    spots.sort(key=lambda s: -s[0])
    out, seen = [], []
    for score, x, y in spots:
        # Thin the list: skip spots within a quarter of the graphic of one kept.
        if any(abs(x - sx) < w / 4 and abs(y - sy) < h / 4 for sx, sy in seen):
            continue
        seen.append((x, y))
        out.append({"x": x, "y": y, "w": round(w, 4), "h": round(h, 4), "score": round(float(score), 4)})
        if len(out) >= limit:
            break
    return out
