"""Word[] -> utterances -> the compact text views an agent actually reads.

The reason this file exists at all is token budget. A 1-hour episode at ~150
wpm is ~9,000 words; the flat per-word JSON caption_engine already produces
would be several hundred KB and is not something to hand an agent as a first
move. Three views sit on top of the same utterance list, cheapest first:

* ``outline``      — one line per ~20s bucket. ~1 hour ≈ 3.5k tokens. The map.
* ``search``        — grep over utterance text, returns only the hits.
* ``get_transcript`` — the full text of a requested window, hard-capped.

There is exactly one utterance list per project, not one per camera — nothing
here merges several transcripts into a shared timeline. That works because the
transcribed source is expected to hear *everyone*: either a camera whose mic
picks up the whole room, or, when the cameras carry isolated per-subject mics, a
combined mix registered as an audio-only source and made primary.

Per-camera loudness at each utterance is the speaker-ID signal that would
otherwise need N transcripts or a diarization model. Isolated mics make that
signal sharper, not weaker — but the mix itself must stay out of the comparison,
since it contains every voice at once (see ``ingest.load_envelopes``).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caption_engine.transcriber.word import Word

from . import energy as energy_mod
from . import paths

GAP_SPLIT_SEC = 0.6     # a pause this long ends an utterance
MAX_UTTERANCE_SEC = 12.0  # even without a pause, cap so one line doesn't run on


@dataclass
class Utterance:
    index: int
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    # Set only when the transcript was built per-mic (see ``clipper.diarize``).
    # Empty means "unknown" — read the energy line instead.
    speaker: str = ""
    speaker_confidence: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_utterances(words: List[Word]) -> List[Utterance]:
    """Group words into utterances on timing gaps — the same idea as
    ``caption_engine.layout.builder.build_phrases``, but standalone (that one
    requires a ``CaptionStyle``) and coarser (transcript reading wants full
    sentences, not one-line reel captions)."""
    if not words:
        return []
    out: List[Utterance] = []
    bucket: List[Word] = [words[0]]
    for w in words[1:]:
        gap = w.start - bucket[-1].end
        span = w.end - bucket[0].start
        if gap > GAP_SPLIT_SEC or span > MAX_UTTERANCE_SEC:
            out.append(_utterance(len(out), bucket))
            bucket = [w]
        else:
            bucket.append(w)
    out.append(_utterance(len(out), bucket))
    return out


def _utterance(index: int, words: List[Word]) -> Utterance:
    return Utterance(index=index, start=words[0].start, end=words[-1].end,
                     text=" ".join(w.text for w in words).strip(), words=words)


# ── caching ──────────────────────────────────────────────────────────────────

def utterances_path(project) -> Path:
    return project.dir / "transcript.utterances.json"


def master_words(project) -> List[Word]:
    """The word list captions are cut from.

    A diarized ingest writes a merged, speaker-labelled master; otherwise the
    primary source's own transcript is the master. Everything downstream reads
    this rather than reaching for a camera's word file directly, so switching a
    project to per-mic transcription doesn't change any caller.
    """
    from caption_engine.transcriber.word import load_words

    merged = project.master_words_path
    if merged.exists():
        return load_words(str(merged))
    return load_words(str(project.words_path(project.primary_audio_camera)))


def save_utterances(utterances: List[Utterance], project) -> None:
    data = []
    for u in utterances:
        d = {"index": u.index, "start": u.start, "end": u.end, "text": u.text}
        if u.speaker:
            d["speaker"] = u.speaker
            d["speaker_confidence"] = u.speaker_confidence
        data.append(d)
    paths.write_json_atomic(utterances_path(project), data)


def load_utterances(project) -> List[Utterance]:
    data = paths.read_json(utterances_path(project), [])
    return [Utterance(index=d["index"], start=d["start"], end=d["end"],
                      text=d["text"], speaker=d.get("speaker", ""),
                      speaker_confidence=d.get("speaker_confidence", 0.0))
            for d in data]


# ── formatting ───────────────────────────────────────────────────────────────

def _fmt_t(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:04.1f}"


def energy_line(scores: Dict[str, int]) -> str:
    """``A88 B09 C04`` — hottest camera first, so the agent's eye lands on the
    likely speaker without scanning."""
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    return " ".join(f"{cam}{score:02d}" for cam, score in ordered)


def format_transcript(utterances: List[Utterance],
                      envelopes: Dict[str, dict],
                      start: float = 0.0, end: Optional[float] = None,
                      max_chars: int = 8000) -> dict:
    """Render utterances in [start, end) as compact lines, capped at max_chars.

    Truncates on an utterance boundary and reports where the next call should
    resume — the pattern that keeps an hour-long transcript from ever needing
    to be read in one shot.
    """
    end = end if end is not None else float("inf")
    lines, used, truncated, next_start, last_end = [], 0, False, None, start
    for u in utterances:
        if u.end <= start or u.start >= end:
            continue
        # A per-mic transcript already knows the speaker; the energy line is the
        # fallback guess for a single-source transcript, not a second opinion.
        if u.speaker:
            who = f"{u.speaker}:"
        else:
            who = energy_line(
                energy_mod.speaker_scores(envelopes, u.start, u.end))
        line = f"#{u.index:04d} {_fmt_t(u.start)}-{_fmt_t(u.end)} {who} | {u.text}"
        if used + len(line) + 1 > max_chars and lines:
            truncated = True
            next_start = u.start
            break
        lines.append(line)
        used += len(line) + 1
        last_end = u.end
    return {
        "text": "\n".join(lines),
        "range_returned": [start, last_end if lines else start],
        "next_start": next_start,
        "truncated": truncated,
        "n_utterances": len(lines),
    }


def build_outline(utterances: List[Utterance], envelopes: Dict[str, dict],
                  bucket_sec: float = 20.0,
                  start: float = 0.0, end: Optional[float] = None) -> str:
    """One line per bucket: dominant camera, utterance count, a text snippet.

    Buckets with no speech collapse to a single ``silence`` line instead of one
    per empty bucket — a 20-minute Q&A pause shouldn't cost 60 outline lines.
    """
    if not utterances:
        return "(no transcript yet — run ingest)"
    end = end if end is not None else utterances[-1].end
    lines: List[str] = []
    t = start
    silence_run_start = None

    while t < end:
        b_end = min(t + bucket_sec, end)
        in_bucket = [u for u in utterances if u.start < b_end and u.end > t]
        if not in_bucket:
            if silence_run_start is None:
                silence_run_start = t
        else:
            if silence_run_start is not None:
                lines.append(f"{_fmt_t(silence_run_start)}-{_fmt_t(t)}  --  silence")
                silence_run_start = None
            labelled = [u.speaker for u in in_bucket if u.speaker]
            if labelled:
                # Whoever holds the most utterances in the bucket.
                dom = max(set(labelled), key=labelled.count)
            else:
                scores = energy_mod.speaker_scores(envelopes, t, b_end)
                dom = max(scores, key=scores.get) if scores else "?"
            snippet = in_bucket[0].text
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            lines.append(f"{_fmt_t(t)}-{_fmt_t(b_end)}  {dom}  "
                        f"{len(in_bucket)}utt  \"{snippet}\"")
        t = b_end

    if silence_run_start is not None:
        lines.append(f"{_fmt_t(silence_run_start)}-{_fmt_t(end)}  --  silence")
    return "\n".join(lines)


def search(utterances: List[Utterance], query: str, regex: bool = False,
          max_hits: int = 30, context_sec: float = 4.0) -> List[dict]:
    """Find where something was said without reading the whole transcript."""
    import re
    pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    hits = []
    for u in utterances:
        if pattern.search(u.text):
            hits.append({"t": u.start, "index": u.index, "text": u.text})
            if len(hits) >= max_hits:
                break
    return hits
