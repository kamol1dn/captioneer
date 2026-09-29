"""Where a cut can go without clipping anyone — decided from the words, not the level.

``energy.snap`` looks for >=0.35 s stretches under a fixed -38 dBFS and moves a
cut into the middle of the nearest one. That misses both ways. Natural speech
rarely pauses that long between words, so most cuts find no silence and stay
where they were put — inside a word, if the word times were off. And a "pause"
can be a filled one: an "uhhh" at -30 dBFS on a quiet guest passes as silence,
and a cut lands halfway through it.

With a verbatim transcript every sound a speaker makes is a timed token — words
*and* fillers — and each token's extent was measured from the audio (see
``caption_engine.transcriber.verbatim_backend``). The legal places to cut are
then exactly the gaps between tokens, taken across **every** speaker, so a cut
between the guest's words cannot slice through a host's "yeah" either.

Inside a gap, where exactly depends on the job the cut does:

* an **out** point (a kept stretch ends here) sits just after the last word, so
  it keeps its natural decay and not the pause that follows;
* an **in** point sits just before the first word, keeping a breath of room
  tone ahead of the onset rather than a hard start.

Either way the result is snapped to a frame boundary *inside* the gap — the
compiler rounds to frames, so a time that is legal in seconds can still round
into a word.
"""
from dataclasses import dataclass
from typing import List, Optional, Sequence

from caption_engine.transcriber.word import Word, is_filler

from .timebase import Timebase

# Room kept after an out point's last token and before an in point's first.
# Two joined segments meet with TAIL + LEAD of room tone between the words:
# about 100 ms, a tight but natural edit.
TAIL = 0.06
LEAD = 0.04
# Nothing lands closer than this to a token edge, whatever the gap.
GUARD = 0.015


@dataclass
class Gap:
    start: float
    end: float
    before: Optional[Word]      # the token that ends at ``start``
    after: Optional[Word]       # the token that starts at ``end``

    @property
    def length(self) -> float:
        return self.end - self.start


def gaps(words: Sequence[Word], duration: Optional[float] = None) -> List[Gap]:
    """Every boundary between tokens, over the union of every speaker's tokens.

    A boundary can have zero length: in running speech one word ends exactly
    where the next begins, and that is still where a cut between them belongs.
    Skipping to the nearest real pause instead — the obvious rule — drops or
    keeps whole words without saying so ("that would be" vanished that way in
    testing). Overlapping speech (two people at once) is one occupied stretch
    with no boundary inside it, which is the point.
    """
    toks = sorted((w for w in words if w.start is not None and w.end is not None),
                  key=lambda w: (w.start, w.end))
    out: List[Gap] = []
    if not toks:
        return out
    if toks[0].start > 0:
        out.append(Gap(0.0, toks[0].start, None, toks[0]))
    reach, last = toks[0].end, toks[0]
    for w in toks[1:]:
        if w.start >= reach - 1e-6:
            out.append(Gap(reach, max(reach, w.start), last, w))
        if w.end >= reach:
            reach, last = w.end, w
    if duration is not None and duration > reach:
        out.append(Gap(reach, duration, last, None))
    return out


def place(t: float, gap_list: Sequence[Gap], role: Optional[str] = None,
          tb: Optional[Timebase] = None, max_shift: float = 0.5) -> dict:
    """Move ``t`` to a safe cut point. Returns the new time and why.

    ``role`` is "in" (a kept stretch starts here), "out" (one ends here), or
    None — keep ``t`` if it is already clear of every token, else move it just
    far enough to be. Ignored when ``t`` is more than ``max_shift`` from any gap:
    then ``t`` is returned unchanged with ``ok: False`` and the token it sits in,
    because moving a cut half a second changes the edit, not just its polish.
    """
    gap = _nearest_gap(t, gap_list, max_shift)
    if gap is None:
        inside = _containing(t, gap_list)
        return {"t": round(t, 3), "ok": False, "moved": 0.0,
                "note": (f"inside {inside!r} with no gap within {max_shift:g}s — "
                         f"choose another word boundary") if inside
                        else f"no gap within {max_shift:g}s"}

    lo, hi = gap.start + GUARD, gap.end - GUARD
    mid = (gap.start + gap.end) / 2.0
    if hi < lo:
        lo = hi = mid
    if role == "out":
        target = min(gap.start + TAIL, mid)
    elif role == "in":
        target = max(gap.end - LEAD, mid)
    else:
        target = t
    target = min(max(target, lo), hi)

    tight = False
    if tb is not None:
        target, tight = _on_frame(target, lo, hi, mid, tb)
    elif hi - lo <= 0:
        tight = True

    res = {"t": round(target, 3), "ok": True, "moved": round(target - t, 3),
           "gap": [round(gap.start, 3), round(gap.end, 3)],
           "context": f"{_text(gap.before)} ⟩|⟨ {_text(gap.after)}"}
    if tight:
        res["note"] = ("words run together here — the cut sits on the boundary, "
                       "not in silence" if gap.length < 2 * GUARD else
                       f"only {gap.length * 1000:.0f} ms between the words — no "
                       f"frame fits cleanly") + "; listen to this join"
    return res


def _nearest_gap(t: float, gap_list: Sequence[Gap], max_shift: float) -> Optional[Gap]:
    best, best_d = None, max_shift + 1e-9
    for g in gap_list:
        if g.start <= t <= g.end:
            return g
        d = g.start - t if t < g.start else t - g.end
        if d < best_d:
            best, best_d = g, d
        if g.start > t + max_shift:
            break
    return best


def _containing(t: float, gap_list: Sequence[Gap]) -> Optional[str]:
    for a, b in zip(gap_list, gap_list[1:]):
        if a.end < t < b.start:
            return _text(a.after)
    return None


def _on_frame(target: float, lo: float, hi: float, mid: float,
              tb: Timebase) -> tuple:
    """The frame boundary inside [lo, hi] nearest ``target``.

    When none fits (a gap shorter than a frame) take the one nearest the gap's
    middle and report it: it is the least bad frame, not a clean one.
    """
    best = None
    k0, k1 = tb.to_frames(lo), tb.to_frames(hi)
    for k in range(k0 - 1, k1 + 2):
        s = tb.to_seconds(k)
        if lo - 1e-9 <= s <= hi + 1e-9 and (best is None or abs(s - target) < abs(best - target)):
            best = s
    if best is not None:
        return best, False
    return tb.to_seconds(tb.to_frames(mid)), True


def _text(w: Optional[Word]) -> str:
    return (w.text or "").strip() if w is not None else "·"


# ── inspecting a cut that is already in an EDL ───────────────────────────────

def token_at(t: float, words: Sequence[Word], slack: float = 0.0) -> Optional[Word]:
    """The token a cut at ``t`` would slice through, if any."""
    for w in words:
        if w.start is None or w.end is None:
            continue
        if w.start + slack < t < w.end - slack:
            return w
    return None


def lexical(words: Sequence[Word]) -> List[Word]:
    """Words only — what a sentence is made of, and what captions show."""
    return [w for w in words if not is_filler(w.text)]
