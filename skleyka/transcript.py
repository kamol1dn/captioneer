"""What is said in the program, when, and by whom.

The voice (the recorder's mix) is transcribed once per source file, in file
time, with the clipper's out-of-process Kotib worker, and cached. A re-trim
then costs nothing: words are mapped onto sequence time through the voice
track's clips, the same way overlays are re-anchored. Speakers come from the
recorder's isolated mics: the loudest mic during a word is the one speaking
(reel-studio's method), and each mic is matched to a person by which camera
angle the user cuts to while it is loud.

Files, all under <episode>/skleyka/:
  episode.json                  voice track + file, mic file per speaker
  transcripts/<stem>.words.json the cached file-time transcript (+ .log, .job.json)
  transcripts/*.env.npy         mic envelopes (audio.py)
  transcript_<sequence>.json    words and utterances in sequence time
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import audio, timeline

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "venv" / "Scripts" / "python.exe"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".aif", ".aiff", ".ogg"}

# Utterance grouping: a new line at a speaker change, after this much silence,
# or when a line gets this long.
GAP_S = 0.8
MAX_UTT_S = 15.0


class TranscriptError(RuntimeError):
    pass


# --- episode config -------------------------------------------------------------

def _episode_path(project_path: str) -> Path:
    return timeline.workdir(project_path) / "episode.json"


def load_episode(project_path: str) -> dict:
    p = _episode_path(project_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_episode(project_path: str, data: dict) -> None:
    _episode_path(project_path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def transcripts_dir(project_path: str) -> Path:
    d = timeline.workdir(project_path) / "transcripts"
    d.mkdir(exist_ok=True)
    return d


# --- the voice track --------------------------------------------------------------

def voice_candidates(tl: dict) -> list[dict]:
    """Audio tracks that could carry the program voice, best first: unmuted,
    one audio-only file, the widest coverage; a name with "mix" wins."""
    out = []
    for t in tl["audio"]:
        clips = t["clips"]
        if not clips or t["muted"]:
            continue
        files = {c["media_path"] for c in clips if c["media_path"]}
        if len(files) != 1:
            continue
        file = next(iter(files))
        cover = sum(c["end"] - c["start"] for c in clips)
        out.append({
            "track": t["index"],
            "label": f"A{t['index'] + 1}",
            "file": file,
            "covered_s": round(cover, 1),
            "audio_only": Path(file).suffix.lower() in AUDIO_EXT,
            "mix_name": "mix" in Path(file).stem.lower(),
        })
    out.sort(key=lambda c: (c["mix_name"], c["audio_only"], c["covered_s"]), reverse=True)
    return out


def voice_clips(tl: dict, track: int) -> list[dict]:
    """The voice track's clips as [start, end, in_point, out_point] in seconds."""
    t = tl["audio"][track]
    clips = []
    for c in t["clips"]:
        dur = c["end"] - c["start"]
        clips.append({"start": c["start"], "end": c["end"], "in": c["in_point"], "out": c["in_point"] + dur})
    return sorted(clips, key=lambda c: c["start"])


def to_file_time(clips: list[dict], t: float) -> float | None:
    for c in clips:
        if c["start"] <= t < c["end"]:
            return c["in"] + (t - c["start"])
    return None


# --- the transcription job ---------------------------------------------------------

def _job_paths(project_path: str, voice_file: str) -> dict:
    d = transcripts_dir(project_path)
    stem = Path(voice_file).stem
    return {"words": d / f"{stem}.words.json", "log": d / f"{stem}.log", "job": d / f"{stem}.job.json"}


def _source_sig(path: str) -> dict:
    st = Path(path).stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:  # 0 is the Idle process; a stopped job is recorded as pid 0
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in out.stdout


def start_job(project_path: str, voice_file: str, language: str = "uz") -> dict:
    """Transcribe the voice file in a child process (returns at once). A cached
    transcript of the same file is reused."""
    paths = _job_paths(project_path, voice_file)
    sig = _source_sig(voice_file)
    if paths["job"].exists():
        job = json.loads(paths["job"].read_text(encoding="utf-8"))
        if job.get("source") == sig:
            if paths["words"].exists():
                return {"state": "done", "cached": True, "words_file": str(paths["words"])}
            if job.get("pid") and _pid_alive(job["pid"]):
                return {"state": "running", "started": job["started"], "log": str(paths["log"])}
    cmd = [str(PYTHON), "-m", "clipper._transcribe_worker", "--audio", voice_file,
           "--out", str(paths["words"]), "--language", language, "--backend", "auto"]
    log = open(paths["log"], "w", encoding="utf-8")
    # No inherited stdio: this server's stdin/stdout are the MCP pipes.
    proc = subprocess.Popen(cmd, cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    job = {"pid": proc.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "audio": voice_file,
           "out": str(paths["words"]), "source": sig}
    paths["job"].write_text(json.dumps(job, indent=1), encoding="utf-8")
    return {"state": "running", "pid": proc.pid, "log": str(paths["log"])}


def job_status(project_path: str, voice_file: str) -> dict:
    paths = _job_paths(project_path, voice_file)
    if not paths["job"].exists():
        return {"state": "not_started"}
    job = json.loads(paths["job"].read_text(encoding="utf-8"))
    if paths["words"].exists():
        return {"state": "done", "words_file": str(paths["words"]), "started": job["started"]}
    tail = ""
    try:
        tail = paths["log"].read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    last = tail.replace("\r", "\n").strip().split("\n")[-1] if tail else ""
    # The worker rewrites one progress line with \r; the last match is current.
    found = re.findall(r"(\d+(?:\.\d+)?)%\s*\(window (\d+)/(\d+)", tail.replace("\r", "\n"))
    progress = None
    if found:
        pct, w, n = found[-1]
        progress = {"percent": float(pct), "window": int(w), "windows": int(n)}
    if _pid_alive(job["pid"]):
        return {"state": "running", "started": job["started"], "progress": progress, "last_line": last[-200:]}
    return {"state": "failed", "started": job["started"], "log": str(paths["log"]), "log_tail": tail[-1500:]}


# --- speakers -----------------------------------------------------------------------

def mic_envelopes(project_path: str, mic_files: dict[str, str]) -> dict[str, "audio.np.ndarray"]:
    d = transcripts_dir(project_path)
    return {name: audio.envelope(path, d) for name, path in mic_files.items()}


def label_speakers(words: list[dict], envs: dict, offsets: dict | None = None) -> None:
    """In place: the loudest mic during each word, and its margin over the
    runner-up (dB). Words are in file time."""
    offsets = offsets or {}
    for w in words:
        levels = {name: audio.mean_db(env, w["src_start"], w["src_end"], offsets.get(name, 0.0))
                  for name, env in envs.items()}
        ranked = sorted(levels.items(), key=lambda kv: kv[1], reverse=True)
        w["spk"] = ranked[0][0]
        w["margin_db"] = round(ranked[0][1] - ranked[1][1], 1) if len(ranked) > 1 else None


def angle_mic_matrix(tl: dict, clips: list[dict], envs: dict, offsets: dict | None = None) -> dict:
    """Mean level of each mic while each camera angle is on screen (dB), and
    the proposed mic for each single-person angle."""
    offsets = offsets or {}
    prog = timeline.program(tl)
    by_angle: dict = {}
    for s in prog:
        if s["angle"] is None:
            continue
        t0, t1 = s["start"], s["end"]
        f0 = to_file_time(clips, t0)
        if f0 is None:
            continue
        f1 = f0 + (t1 - t0)
        rec = by_angle.setdefault(s["angle"], {"camera": s["camera"], "seconds": 0.0, "power": {n: 0.0 for n in envs}})
        rec["seconds"] += t1 - t0
        for name, env in envs.items():
            lvl = audio.mean_db(env, f0, f1, offsets.get(name, 0.0))
            rec["power"][name] += (10 ** (lvl / 10)) * (t1 - t0)
    matrix = {}
    for angle, rec in sorted(by_angle.items()):
        matrix[angle] = {"camera": rec["camera"], "seconds": round(rec["seconds"], 1),
                         "db": {n: round(audio.db(p / rec["seconds"]), 1) for n, p in rec["power"].items()}}
    # A mic belongs to the angle where it stands out most against the others.
    proposal = {}
    for name in envs:
        best, best_adv = None, -1e9
        for angle, rec in matrix.items():
            others = [v for n, v in rec["db"].items() if n != name]
            adv = rec["db"][name] - (max(others) if others else -120.0)
            if adv > best_adv:
                best, best_adv = angle, adv
        if best is not None:
            proposal[name] = {"angle": best, "camera": matrix[best]["camera"], "margin_db": round(best_adv, 1)}
    return {"matrix": matrix, "proposal": proposal}


# --- building the sequence-time transcript --------------------------------------------

def map_words(words: list[dict], clips: list[dict]) -> list[dict]:
    """File-time words onto sequence time through the voice clips. A word cut
    by an edit is dropped; reused material yields the word twice."""
    out = []
    for c in clips:
        for w in words:
            if w["src_start"] < c["in"] or w["src_start"] >= c["out"]:
                continue
            start = c["start"] + (w["src_start"] - c["in"])
            end = min(c["start"] + (w["src_end"] - c["in"]), c["end"])
            if end - start < 0.03:
                continue
            out.append(w | {"start": round(start, 3), "end": round(end, 3)})
    out.sort(key=lambda w: w["start"])
    return out


def group_utterances(words: list[dict]) -> list[dict]:
    utts: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            utts.append({"start": cur[0]["start"], "end": cur[-1]["end"], "spk": cur[0].get("spk"),
                         "text": " ".join(w["text"] for w in cur)})

    for w in words:
        if cur and (w.get("spk") != cur[0].get("spk") or w["start"] - cur[-1]["end"] > GAP_S
                    or w["end"] - cur[0]["start"] > MAX_UTT_S):
            flush()
            cur = []
        cur.append(w)
    flush()
    return utts


def _transcript_path(project_path: str, seq_name: str) -> Path:
    name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in seq_name)
    return timeline.workdir(project_path) / f"transcript_{name}.json"


def build(tl: dict, episode: dict) -> dict:
    """Words and utterances in sequence time for the timeline as read now."""
    project_path = tl["project_path"]
    voice = episode.get("voice")
    if not voice:
        raise TranscriptError("No voice track chosen yet; run transcribe_program first")
    paths = _job_paths(project_path, voice["file"])
    if not paths["words"].exists():
        raise TranscriptError("The voice file is not transcribed yet; check transcript_status")
    raw = json.loads(paths["words"].read_text(encoding="utf-8"))
    words = [{"text": w["text"], "src_start": round(w["start"], 3), "src_end": round(w["end"], 3),
              "p": round(w.get("probability", 1.0), 2)} for w in raw]
    mics = episode.get("mics") or {}
    if mics:
        label_speakers(words, mic_envelopes(project_path, mics), episode.get("mic_offsets"))
    clips = voice_clips(tl, voice["track"])
    mapped = map_words(words, clips)
    data = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sequence": tl["sequence"]["name"],
        "voice_file": voice["file"],
        "speakers": sorted(mics),
        "words": mapped,
        "utterances": group_utterances(mapped),
    }
    _transcript_path(project_path, tl["sequence"]["name"]).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load(project_path: str, seq_name: str) -> dict:
    p = _transcript_path(project_path, seq_name)
    if not p.exists():
        raise TranscriptError("No transcript built for this sequence yet; run build_transcript")
    return json.loads(p.read_text(encoding="utf-8"))


# --- reading it ------------------------------------------------------------------------

def _fmt(t: float) -> str:
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def outline(data: dict, bucket_s: float = 30.0, start: float = 0.0, end: float | None = None) -> str:
    """One line per bucket: who holds the floor, how many lines, the first words."""
    utts = data["utterances"]
    if not utts:
        return "(empty transcript)"
    end = end if end is not None else utts[-1]["end"]
    lines = []
    silent_from = None
    t = start
    while t < end:
        b = min(t + bucket_s, end)
        inside = [u for u in utts if u["start"] < b and u["end"] > t]
        if not inside:
            silent_from = t if silent_from is None else silent_from
        else:
            if silent_from is not None:
                lines.append(f"{_fmt(silent_from)}-{_fmt(t)}  --  silence")
                silent_from = None
            spk = [u["spk"] for u in inside if u.get("spk")]
            dom = max(set(spk), key=spk.count) if spk else "?"
            snippet = " ".join(u["text"] for u in inside)
            snippet = snippet[:70] + ("..." if len(snippet) > 70 else "")
            lines.append(f"{_fmt(t)}  {dom:<10} {len(inside):2d}  {snippet}")
        t = b
    if silent_from is not None:
        lines.append(f"{_fmt(silent_from)}-{_fmt(end)}  --  silence")
    return "\n".join(lines)


def window(data: dict, start: float, end: float) -> str:
    """The utterances in [start, end) as readable lines."""
    rows = [f"[{_fmt(u['start'])}-{_fmt(u['end'])}] {u.get('spk') or '?'}: {u['text']}"
            for u in data["utterances"] if u["start"] < end and u["end"] > start]
    return "\n".join(rows) if rows else "(nothing said in that window)"


def words_in(data: dict, start: float, end: float) -> list[dict]:
    return [w for w in data["words"] if w["start"] < end and w["end"] > start]


def retranscribe(tl: dict, episode: dict, start: float, end: float, source: str = "voice",
                 pad: float = 1.5, language: str = "uz") -> dict:
    """Run Kotib again on just [start, end) of the program (padded), from the
    voice file or one speaker's own mic (``source`` = the speaker's name).
    For checking a doubtful word before using it in a graphic. Synchronous:
    about half a minute, mostly model loading."""
    voice = episode.get("voice")
    if not voice:
        raise TranscriptError("No voice track chosen yet; run transcribe_program first")
    clips = voice_clips(tl, voice["track"])
    f0 = to_file_time(clips, start)
    f1 = to_file_time(clips, max(start, end - 0.001))
    if f0 is None or f1 is None or f1 < f0:
        raise TranscriptError("The window must lie inside one clip of the voice track")
    if source == "voice":
        file, offset = voice["file"], 0.0
    else:
        mics = episode.get("mics") or {}
        if source not in mics:
            raise TranscriptError(f"No mic for '{source}'; speakers: {sorted(mics)}")
        file, offset = mics[source], (episode.get("mic_offsets") or {}).get(source, 0.0)
    a = max(0.0, f0 - pad + offset)
    dur = (f1 - f0) + 2 * pad
    d = transcripts_dir(tl["project_path"]) / "snippets"
    d.mkdir(exist_ok=True)
    stem = f"{int(start * 1000):09d}_{int(end * 1000):09d}_{source}"
    wav, out, log = d / f"{stem}.wav", d / f"{stem}.words.json", d / f"{stem}.log"
    subprocess.run([str(audio.FFMPEG), "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", file,
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(log, "w", encoding="utf-8") as lf:
        proc = subprocess.run([str(PYTHON), "-m", "clipper._transcribe_worker", "--audio", str(wav),
                               "--out", str(out), "--language", language, "--backend", "auto"],
                              cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT)
    if proc.returncode != 0 or not out.exists():
        raise TranscriptError(f"snippet transcription failed; see {log}")
    raw = json.loads(out.read_text(encoding="utf-8"))
    # Snippet time -> file time of the voice (undo the pad and the mic offset)
    # -> sequence time through the voice clips.
    words = [{"text": w["text"], "src_start": round(w["start"] + a - offset, 3),
              "src_end": round(w["end"] + a - offset, 3), "p": round(w.get("probability", 1.0), 2)} for w in raw]
    mapped = [w for w in map_words(words, clips) if w["start"] < end + pad and w["end"] > start - pad]
    wav.unlink(missing_ok=True)
    return {"source": source, "window": [start, end], "text": " ".join(w["text"] for w in mapped),
            "words": [{k: w[k] for k in ("text", "start", "end", "p")} for w in mapped]}


def search(data: dict, query: str, limit: int = 40) -> list[dict]:
    """Utterances whose text contains ``query`` (case-insensitive; the Uzbek
    apostrophes ʻ ʼ ' ` are treated alike)."""
    def norm(s: str) -> str:
        return re.sub(r"[ʻʼ'`’‘]", "'", s.lower())
    q = norm(query)
    hits = [u for u in data["utterances"] if q in norm(u["text"])]
    return [{"start": u["start"], "end": u["end"], "spk": u.get("spk"), "text": u["text"]} for u in hits[:limit]]
