"""Turn raw camera files into transcript + energy, in the background.

Whisper on an hour of audio takes minutes; an MCP tool call that blocks that
long will time out most clients. So ``ingest`` hands back a job id immediately
and does the work on a daemon thread, reusing
``caption_engine.web.jobs`` verbatim — it already solves exactly this problem
for the Flask app, right down to the SSE-friendly progress events (which the
MCP layer here just polls instead of streaming).
"""
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from caption_engine.transcriber.word import load_words
from caption_engine.web import jobs

from . import energy as energy_mod
from . import transcript as transcript_mod
from .project import Project


def start_ingest(project: Project, model_size: str = "large-v3",
                 language: Optional[str] = None,
                 cameras: Optional[List[str]] = None,
                 diarize: bool = False) -> jobs.Job:
    """Queue transcription plus an energy envelope for every camera. Returns
    immediately.

    ``diarize`` transcribes every *camera* mic instead of the single primary
    source and merges them into one speaker-labelled timeline. It costs one
    Whisper pass per camera rather than one per episode, and buys attributed
    lines and overlapping speech — see ``clipper.diarize``.
    """
    wanted = set(cameras) if cameras else None
    targets = [c for c in project.cameras if wanted is None or c.id in wanted]
    if not targets:
        raise ValueError("no matching cameras to ingest")

    # Per-mic diarization reads the camera mics, so the combined mix — which
    # hears every voice at once and would win every bleed comparison — is not a
    # transcription target here even when it is the primary source.
    video_ids = set(project.video_camera_ids)
    if diarize:
        speaker_ids = [c.id for c in targets if c.id in video_ids]
        if len(speaker_ids) < 2:
            raise ValueError(
                "diarize needs at least 2 camera mics; "
                f"got {speaker_ids or 'none'}")
    else:
        speaker_ids = []

    project.ingest_state = {"state": "running", "progress": 0.0, "message": ""}
    project.save()

    def run(job: jobs.Job):
        total = len(targets)
        per_camera = {}
        spoken: dict = {}          # camera id -> its own word list (diarize)
        try:
            for i, cam in enumerate(targets):
                job.progress(i, total, f"energy: {cam.id}")
                _ensure_energy(project, cam)
                per_camera[cam.id] = "energy_only"

                should_transcribe = (cam.id in speaker_ids if diarize
                                     else cam.transcribe)
                if should_transcribe:
                    job.progress(i, total, f"transcribing: {cam.id}")
                    words = _transcribe_out_of_process(
                        cam.path, project.words_path(cam.id),
                        model_size=model_size, language=language,
                    )
                    cam.model = model_size
                    from datetime import datetime
                    cam.transcribed_at = datetime.now().isoformat(timespec="seconds")
                    per_camera[cam.id] = "done"

                    if diarize:
                        spoken[cam.id] = words
                    elif cam.id == project.primary_audio_camera:
                        utterances = transcript_mod.build_utterances(words)
                        transcript_mod.save_utterances(utterances, project)

                project.ingest_state = {
                    "state": "running",
                    "progress": (i + 1) / total,
                    "message": f"finished {cam.id}",
                    "per_camera": per_camera,
                }
                project.save()

            merge_report = None
            if diarize:
                job.progress(total, total, "merging speakers")
                merge_report = _merge_speakers(project, spoken)

            project.ingest_state = {"state": "done", "progress": 1.0,
                                    "message": "", "per_camera": per_camera,
                                    "diarization": merge_report}
            project.save()
            return {"per_camera": per_camera, "diarization": merge_report}
        except Exception as e:
            project.ingest_state = {"state": "error", "progress": 0.0,
                                    "message": str(e), "per_camera": per_camera}
            project.save()
            raise

    return jobs.submit(run)


def _transcribe_out_of_process(audio_path: str, out_path: Path,
                               model_size: str = "large-v3",
                               language: Optional[str] = None) -> list:
    """Run Whisper in a child interpreter and read back the words it wrote.

    In-process transcription deadlocks: WhisperX loads sklearn's OpenMP runtime
    into a server that already holds torch's and ctranslate2's, and the Windows
    loader lock never comes back. See ``_transcribe_worker`` for the detail.
    Failures surface the child's log tail rather than a bare exit code.

    The child gets no inherited stdio: this server is launched by an MCP client
    over stdin/stdout pipes, and handing those down — through the venv launcher
    stub, which re-execs the base interpreter — hung the child in the kernel
    before it ran a single line. Whisper's chatter goes to a log file instead,
    which is also there to read afterwards.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_path.with_suffix(".log")
    cmd = [
        sys.executable, "-m", "clipper._transcribe_worker",
        "--audio", str(audio_path),
        "--out", str(out_path),
        "--model-size", model_size,
        "--language", language or "",
    ]
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd, cwd=str(Path(__file__).resolve().parent.parent),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
    if proc.returncode != 0:
        tail = ""
        try:
            tail = log_path.read_text(encoding="utf-8", errors="ignore")[-2000:]
        except OSError:
            pass
        raise RuntimeError(
            f"transcription failed (exit {proc.returncode}); see {log_path}\n{tail}"
        )
    return load_words(str(out_path))


def _merge_speakers(project: Project, spoken: dict) -> dict:
    """Fold per-mic transcripts into one speaker-labelled timeline and save it.

    The merged word list becomes the project's master, so captions are cut from
    each speaker's own isolated mic rather than the shared mix.
    """
    from caption_engine.transcriber.word import save_words

    from . import diarize as diarize_mod

    envelopes = load_envelopes(project)
    utterances, report = diarize_mod.merge_per_mic(spoken, envelopes)
    transcript_mod.save_utterances(utterances, project)
    save_words(diarize_mod.merged_words(utterances),
               str(project.master_words_path))
    return report


def _ensure_energy(project: Project, camera) -> None:
    """Compute and cache a camera's loudness envelope, skipping if already done."""
    out = project.energy_path(camera.id)
    if out.exists():
        return
    env = energy_mod.compute_envelope(camera.path)
    energy_mod.save_envelope(env, out)


def load_envelopes(project: Project, include_audio_only: bool = False) -> dict:
    """Cached energy envelopes, keyed by camera id. Missing ones are skipped
    rather than raising — a camera that hasn't been ingested yet just drops out
    of speaker-score comparisons instead of failing the whole call.

    Audio-only sources are excluded by default. Every caller of this function
    feeds speaker scoring, and a combined mix contains all the other mics at
    once: it would win every window, pin the top score to itself, and drag the
    real cameras down into the 40 dB shadow below it — turning the one signal
    that identifies the speaker into a constant. Pass ``include_audio_only`` if
    you genuinely want the mix's loudness.
    """
    allowed = set(project.camera_ids if include_audio_only
                  else project.video_camera_ids)
    out = {}
    for cam in project.cameras:
        if cam.id not in allowed:
            continue
        env = energy_mod.load_envelope(project.energy_path(cam.id))
        if env:
            out[cam.id] = env
    return out


def ingest_status(project: Project) -> dict:
    return project.ingest_state
