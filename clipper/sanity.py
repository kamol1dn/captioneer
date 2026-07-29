"""Does the kept text actually read as sentences?

``snap_to_silence`` proves a cut didn't land inside a word. It cannot tell you
whether the words that survived form a coherent line, and those are different
failures: a boundary can sit in a perfectly clean 300 ms pause and still open a
clip on "of 25 US tech companies" because "A coalition" fell into the trimmed
gap. That reads fine in the EDL, is inaudible to the silence detector, and is
the first thing a viewer notices.

The signal is **punctuation, not vocabulary**. A word list of "words that can't
start a sentence" sounds reasonable and immediately misfires: "A coalition
published...", "The OCC rejected...", and "Do you think it's a wise move?" all
open on words such a list would reject. Whisper already emits sentence
punctuation, so the honest question at a boundary is "did the word just before
this cut end a sentence?" — if it didn't, and it was still speaking a moment
earlier, the clause was cut into and words are missing.

Every finding carries the text either side of the cut, because the call is
ultimately the editor's: starting on "two months ago they moved..." and dropping
a preceding "the funny thing is" is a *good* trim that this check will still
flag, and one glance at the context settles it. Everything here is a warning;
nothing is an error.
"""
import re
from typing import Dict, List, Optional

from caption_engine.transcriber.word import Word

# Speech resuming within this long of a cut was mid-flow; a longer pause is a
# natural break and needs no punctuation to justify it.
JOIN_GAP_SEC = 1.0

# Not a trigger on its own — only used to raise a finding's confidence once
# punctuation already says the clause continues. Deliberately prepositions and
# comparatives only: "and", "but" and "so" open spoken sentences constantly, and
# "who"/"which"/"that" open questions ("Who is OpenRouter, Sam?"), so including
# them would rank good trims as confidently broken.
_CONTINUATION = {
    "of", "to", "than", "as", "at", "by", "for", "from", "in", "into", "on",
    "onto", "with", "within", "without", "upon", "toward", "towards",
}
_DANGLING = {
    "so", "and", "but", "or", "the", "a", "an", "of", "to", "in", "on", "at",
    "for", "with", "that", "which", "is", "are", "was", "were", "because",
    "if", "as", "by", "from", "into", "very", "just", "like", "my",
}
_FILLER_OPEN = {"so", "yeah", "yes", "okay", "ok", "well", "um", "uh",
                "anyway", "like"}

_ENDS_SENTENCE = re.compile(r"[.!?][\"')\]]*$")


def _bare(text: str) -> str:
    return re.sub(r"[^\w'-]", "", (text or "")).lower()


def ends_sentence(w: Optional[Word]) -> bool:
    return bool(w and _ENDS_SENTENCE.search((w.text or "").strip()))


def _context(words: List[Word], n: int = 4, tail: bool = False) -> str:
    picked = words[-n:] if tail else words[:n]
    return " ".join((w.text or "").strip() for w in picked).strip()


def _overlapping(master: List[Word], start: float, end: float) -> List[Word]:
    """Words a segment keeps — overlap, matching how captions clamp them."""
    return [w for w in master
            if w.start is not None and w.end is not None
            and w.end > start + 1e-9 and w.start < end - 1e-9]


def check_clip(master_words: List[Word], clip) -> Dict[str, object]:
    """Read every segment of a clip and report joins that don't read cleanly."""
    segments = sorted(clip.segments, key=lambda s: s.start)
    issues: List[dict] = []
    ordered = [w for w in master_words if w.start is not None and w.end is not None]

    for i, seg in enumerate(segments):
        kept = _overlapping(ordered, seg.start, seg.end)
        if not kept:
            issues.append({
                "kind": "empty_segment", "where": f"segment {i + 1}",
                "t": seg.start, "confidence": "high", "context": "",
                "detail": "no words fall inside this segment — it is silence, "
                          "or the times are wrong",
            })
            continue

        before = [w for w in ordered if w.end <= kept[0].start + 1e-9]
        after = [w for w in ordered if w.start >= kept[-1].end - 1e-9]
        prev_w = before[-1] if before else None
        next_w = after[0] if after else None

        # ── opening into a live clause ───────────────────────────────────────
        # What counts as "the word before" depends on where you are. At the
        # clip's open there is no earlier picture, so the master neighbour is
        # the only evidence. Inside the clip the viewer hears the *previous
        # segment*, so that join is what has to read — judging a mid-clip
        # segment against the master word it was cut away from flags every
        # deliberate trim.
        if i == 0:
            if prev_w is not None:
                gap = kept[0].start - prev_w.end
                if gap < JOIN_GAP_SEC and not ends_sentence(prev_w):
                    strong = _bare(kept[0].text) in _CONTINUATION
                    issues.append({
                        "kind": "orphan_open", "where": "segment 1 (clip open)",
                        "t": kept[0].start,
                        "confidence": "high" if strong else "medium",
                        "context": f"...{(prev_w.text or '').strip()} ⟩CUT⟨ "
                                   f"{_context(kept)}...",
                        "detail": f"the previous word ended {gap:.2f}s earlier "
                                  f"without closing a sentence — the clip opens "
                                  f"mid-clause",
                    })
        else:
            prev_kept = _overlapping(ordered, segments[i - 1].start,
                                     segments[i - 1].end)
            prev_last = prev_kept[-1] if prev_kept else None
            # A previous segment that stopped mid-sentence simply continues into
            # this one, which is what a trim is supposed to do. It's the pairing
            # of a *finished* sentence with a fragment that misreads.
            if prev_last is not None and ends_sentence(prev_last):
                head = (kept[0].text or "").strip()
                fragment = (_bare(head) in _CONTINUATION
                            or (head[:1].islower() if head else False))
                if fragment:
                    issues.append({
                        "kind": "orphan_open", "where": f"segment {i + 1}",
                        "t": kept[0].start, "confidence": "high",
                        "context": f"...{_context(prev_kept, 3, tail=True)} "
                                   f"⟩JOIN⟨ {_context(kept)}...",
                        "detail": "the previous segment closed a sentence and "
                                  "this one opens on a fragment — words are "
                                  "missing between them",
                    })

        # ── closing mid-thought ──────────────────────────────────────────────
        if next_w is not None:
            gap = next_w.start - kept[-1].end
            if gap < JOIN_GAP_SEC and not ends_sentence(kept[-1]):
                strong = _bare(kept[-1].text) in _DANGLING
                issues.append({
                    "kind": "orphan_close",
                    "where": f"segment {i + 1}"
                             + (" (clip end)" if i == len(segments) - 1 else ""),
                    "t": kept[-1].end,
                    "confidence": "high" if strong else "medium",
                    "context": f"...{_context(kept, tail=True)} ⟩CUT⟨ "
                               f"{(next_w.text or '').strip()}...",
                    "detail": f"this segment stops without closing a sentence "
                              f"and speech resumes {gap:.2f}s later — the "
                              f"thought continues past the cut",
                })

        # ── the hook ─────────────────────────────────────────────────────────
        if i == 0 and _bare(kept[0].text) in _FILLER_OPEN:
            issues.append({
                "kind": "hook", "where": "clip open", "t": kept[0].start,
                "confidence": "medium", "context": _context(kept, 6),
                "detail": f"opens on filler {(kept[0].text or '').strip()!r} — "
                          f"the first 2 seconds decide whether anyone watches",
            })

    return {
        "clip_id": clip.id,
        "title": clip.title,
        "n_segments": len(segments),
        "issues": issues,
        "ok": not issues,
    }


def format_report(reports: List[Dict[str, object]],
                  min_confidence: str = "high") -> str:
    """A readable rundown — what to show before asking for sign-off.

    Defaults to high-confidence only. Every deliberate trim technically starts
    mid-clause, so showing everything buries the handful of real breakages in a
    list the reader stops reading. Pass ``min_confidence="medium"`` to see the
    rest.
    """
    show_all = min_confidence != "high"
    lines: List[str] = []
    total = high = shown = 0
    for r in reports:
        issues = r.get("issues") or []
        total += len(issues)
        high += sum(1 for i in issues if i.get("confidence") == "high")
        picked = [i for i in issues
                  if show_all or i.get("confidence") == "high"]
        shown += len(picked)
        head = f"{r['clip_id']} — {r.get('title') or ''}".rstrip(" —")
        if not picked:
            lines.append(f"{head}: clean"
                         + (f" ({len(issues)} low-confidence)" if issues else ""))
            continue
        lines.append(f"{head}: {len(picked)} issue(s)")
        for it in picked:
            m, s = divmod(max(0.0, float(it.get("t") or 0.0)), 60)
            lines.append(f"    [{it['kind']}/{it['confidence']}] "
                         f"{int(m):02d}:{s:04.1f} {it['where']}")
            if it.get("context"):
                lines.append(f"        {it['context']}")
            lines.append(f"        -> {it['detail']}")
    lines.append("")
    hidden = total - shown
    summary = (f"{shown} shown of {total} finding(s) across {len(reports)} "
               f"clip(s); {high} high-confidence.")
    if hidden and not show_all:
        summary += (f" {hidden} lower-confidence hidden — most are deliberate "
                    f"trims; pass min_confidence='medium' to see them.")
    lines.append(summary)
    lines.append("Warnings, not errors: read the context and decide.")
    return "\n".join(lines)
