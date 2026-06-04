"""Decode any audio/video file to a 16 kHz mono float32 waveform via ffmpeg.

ffmpeg is already a hard dependency of this project (the renderer pipes frames
to it), so this adds nothing new and reliably handles video containers (.mp4
reels) that torchaudio.load can't always open.
"""
import subprocess
import numpy as np

SAMPLE_RATE = 16000


def load_audio(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return a 1-D float32 numpy array of mono samples at `sample_rate`."""
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "1", "-ar", str(sample_rate),
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg failed to decode {path!r}:\n{stderr[-2000:]}")
    return np.frombuffer(proc.stdout, np.float32).copy()
