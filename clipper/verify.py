"""Cut the audio, listen to it, and check it says what it should.

``check_segments`` reasons about the cut from the transcript and punctuation.
That catches a lot, but it is still reasoning about a plan rather than about the
result — and the failures that survive it are exactly the ones that only exist
in the rendered audio. Cutting OTG ep12 shipped two of them: a segment boundary
that landed inside the word "issues" so the clip says "...compliance issues.
issues. They said...", and a trim that left a stray "is" behind, so the audio
runs "...the same day. is there is no signatory". Both read perfectly in the
EDL. Both are obvious the moment you hear them.

So this renders the clip's audio exactly as the EDL concatenates it, transcribes
that render, and diffs it against the words the clip is *supposed* to contain.
The comparison is a plain sequence diff over normalized words: an insertion the
plan didn't predict is a stutter or a stray word, a deletion is speech the cut
swallowed.

It is a smoke test, not a proof. ASR disagrees with itself between runs,
especially on proper nouns and numbers, so a lone substitution usually means the
recognizer wavered rather than the cut broke. Repeated words and words appearing
right at a segment boundary are the signal worth acting on, and the report
scores findings that way.
"""
import difflib
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caption_engine.media import ffmpeg_bin
from caption_engine.transcriber.word import Word, load_words

# A boundary sits at a known program time; anything odd within this of one is
# far more likely to be the cut than the recognizer.
BOUNDARY_WINDOW_SEC = 0.6


def _norm(text: str) -> str:
    return re.sub(r"[^\w']", "", (text or "")).lower()


def export_clip_audio(compiled, out_path) -> Path:
    """Render just the clip's audio, concatenated exactly as the EDL cuts it.

    Uses the audible (enabled) audio track, so what gets transcribed is what a
    viewer hears — including any splice artifact.
    """
    items = compiled.program_audio()
    if not items:
        raise ValueError(f"clip {compiled.id!r} has no enabled audio track")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = float(compiled.timebase.fps)

    inputs: List[str] = []
    index: Dict[str, int] = {}
    for it in items:
        if it.path and it.path not in index:
            index[it.path] = len(inputs)
            inputs.append(it.path)

    filt = []
    for i, it in enumerate(items):
        s, e = it.in_ / fps, it.out / fps
        filt.append(f"[{index[it.path]}:a]atrim=start={s:.6f}:end={e:.6f},"
                    f"asetpts=PTS-STARTPTS[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(items)))
                + f"concat=n={len(items)}:v=0:a=1[out]")

    cmd = [ffmpeg_bin("ffmpeg"), "-y", "-nostdin"]
    for p in inputs:
        cmd += ["-i", p]
    cmd += ["-filter_complex", ";".join(filt), "-map", "[out]",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"audio export failed for {compiled.id!r}:\n"
                           f"{proc.stderr[-2000:]}")
    return out


def transcribe_file(audio_path, out_json, model_size: str = "base",
                    language: Optional[str] = None) -> List[Word]:
    """Transcribe a rendered clip in a child interpreter.

    Out-of-process for the same reason ingest is: WhisperX drags a third OpenMP
    runtime into a process that already has two, and Windows deadlocks on the
    loader lock. ``base`` is the default because this is a check on a 50-second
    clip, not the master transcript — it only has to be good enough to notice a
    word appearing twice.
    """
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "clipper._transcribe_worker",
           "--audio", str(audio_path), "--out", str(out_json),
           "--model-size", model_size, "--language", language or ""]
    log = out_json.with_suffix(".log")
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent.parent),
                              stdin=subprocess.DEVNULL, stdout=fh,
                              stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = ""
        try:
            tail = log.read_text(encoding="utf-8", errors="ignore")[-1500:]
        except OSError:
            pass
        raise RuntimeError(f"verification transcribe failed; see {log}\n{tail}")
    return load_words(str(out_json))


def diff_words(expected: List[Word], heard: List[Word],
               boundaries: List[float]) -> List[dict]:
    """Diff what the cut should say against what it does say."""
    exp = [_norm(w.text) for w in expected]
    got = [_norm(w.text) for w in heard]
    exp_i = [i for i, t in enumerate(exp) if t]
    got_i = [i for i, t in enumerate(got) if t]
    a = [exp[i] for i in exp_i]
    b = [got[i] for i in got_i]

    def near_boundary(t: Optional[float]) -> Optional[float]:
        if t is None or not boundaries:
            return None
        d = min(abs(t - x) for x in boundaries)
        return d if d <= BOUNDARY_WINDOW_SEC else None

    findings: List[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag == "equal":
            continue
        heard_words = [heard[got_i[j]] for j in range(j1, j2)]
        exp_words = [expected[exp_i[i]] for i in range(i1, i2)]
        at = (heard_words[0].start if heard_words
              else (exp_words[0].start if exp_words else None))
        dist = near_boundary(at)

        # A word the plan already had immediately before it is a stutter — the
        # single most likely thing a bad boundary produces.
        stutter = False
        if tag == "insert" and heard_words:
            first = _norm(heard_words[0].text)
            prev = b[j1 - 1] if j1 > 0 else ""
            nxt = b[j2] if j2 < len(b) else ""
            stutter = first and (first == prev or first == nxt)

        if tag == "insert":
            kind, detail = "extra_speech", (
                f"the render says {' '.join(x.text for x in heard_words)!r} "
                f"but the cut doesn't plan it")
        elif tag == "delete" and dist is not None:
            # The dominant real-world case. A planned word that the render
            # doesn't say, sitting on a boundary, is a word the cut sliced into:
            # too little of it survives to be recognised, which is exactly what
            # a truncated syllable sounds like.
            kind, detail = "clipped_word", (
                f"{' '.join(x.text for x in exp_words)!r} is planned but the "
                f"render doesn't say it, and the boundary is {dist:.2f}s away — "
                f"the cut is slicing it into a fragment. Move the boundary to "
                f"include the whole word or exclude it cleanly")
        elif tag == "delete":
            kind, detail = "missing_speech", (
                f"the cut plans {' '.join(x.text for x in exp_words)!r} "
                f"but the render doesn't say it")
        else:
            kind, detail = "mismatch", (
                f"planned {' '.join(x.text for x in exp_words)!r}, "
                f"heard {' '.join(x.text for x in heard_words)!r}")

        if stutter:
            confidence = "high"
        elif dist is not None and kind != "mismatch":
            confidence = "high"
        elif kind == "mismatch":
            confidence = "low"      # ASR wobble on names and numbers
        else:
            confidence = "medium"

        findings.append({
            "kind": "stutter" if stutter else kind,
            "t": round(at, 2) if at is not None else None,
            "at_boundary": None if dist is None else round(dist, 2),
            "confidence": confidence,
            "detail": detail,
        })
    return findings


def format_report(results: List[dict], min_confidence: str = "high") -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    floor = order.get(min_confidence, 3)
    lines, total, shown = [], 0, 0
    for r in results:
        f = r.get("findings") or []
        total += len(f)
        picked = [x for x in f if order.get(x["confidence"], 0) >= floor]
        shown += len(picked)
        head = f"{r['clip_id']} — {r.get('title') or ''}".rstrip(" —")
        if not picked:
            lines.append(f"{head}: sounds right"
                         + (f" ({len(f)} low-confidence)" if f else ""))
            continue
        lines.append(f"{head}: {len(picked)} issue(s)")
        for x in picked:
            t = x["t"]
            stamp = "--:--" if t is None else f"{int(t // 60):02d}:{t % 60:04.1f}"
            near = (f" (0.{int(x['at_boundary'] * 100):02d}s from a cut)"
                    if x["at_boundary"] is not None else "")
            lines.append(f"    [{x['kind']}/{x['confidence']}] {stamp}{near}")
            lines.append(f"        -> {x['detail']}")
    lines.append("")
    lines.append(f"{shown} shown of {total} finding(s) across {len(results)} "
                 f"clip(s). Substitutions are usually the recognizer, not the "
                 f"cut; repeated words and findings next to a boundary are the "
                 f"ones worth acting on.")
    return "\n".join(lines)
