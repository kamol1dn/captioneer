"""Drive ffmpeg to encode rendered RGBA frames into a transparent .mov.

Why ProRes 4444? It's the de-facto standard for alpha-channel video in pro
NLEs (Premiere, Resolve, Final Cut). Editors can drop the .mov on a track and
see-through transparency just works.
"""
import subprocess
import threading
from typing import List, Optional, Callable

from ..style import CaptionStyle
from ..layout import Phrase
from .preview import render_frame


def render_to_mov(
    phrases: List[Phrase],
    style: CaptionStyle,
    output_path: str,
    duration: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Render all phrases to a transparent ProRes 4444 .mov.

    Pipeline, per frame: find the active phrase, find the active word in it,
    draw the lines centered on `vertical_anchor`, draw the active word with its
    highlight, then pipe the RGBA frame to ffmpeg's stdin.

    Args:
        phrases: result of layout.build_phrases()
        style: CaptionStyle to use
        output_path: .mov file path
        duration: total clip duration in seconds. If None, uses last word end.
        progress_cb: optional callback(current_frame, total_frames)
    """
    if duration is None:
        # Tail the clip by the hold so the last phrase's held frame is included.
        tail = max(style.phrase_hold, 0.5)
        duration = phrases[-1].end + tail if phrases else 1.0
    total_frames = int(duration * style.fps)

    # ── spin up ffmpeg ──────────────────────────────────────────────────────
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{style.width}x{style.height}",
        "-pix_fmt", "rgba",
        "-r", str(style.fps),
        "-i", "-",                       # stdin
        "-c:v", "prores_ks",
        "-profile:v", "4444",            # ProRes 4444 supports alpha
        "-pix_fmt", "yuva444p10le",
        "-vendor", "ap10",
        "-an",
        output_path,
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
    )

    # Drain stderr in a background thread. ffmpeg streams progress stats to
    # stderr continuously; if we don't read it while writing frames, the OS pipe
    # buffer (~64 KB) fills, ffmpeg blocks on its stderr write, stops consuming
    # stdin, and proc.stdin.write() deadlocks. (This is why long renders froze
    # at a fixed frame while short ones finished fine.)
    stderr_chunks: List[bytes] = []

    def _drain_stderr() -> None:
        for chunk in iter(lambda: proc.stderr.read(4096), b""):
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / style.fps
            img = render_frame(phrases, style, t)
            proc.stdin.write(img.tobytes())

            if progress_cb and frame_idx % style.fps == 0:
                progress_cb(frame_idx, total_frames)
    finally:
        proc.stdin.close()
        stderr_thread.join()
        ret = proc.wait()
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="ignore")
        if ret != 0:
            raise RuntimeError(f"ffmpeg failed (code {ret}):\n{stderr[-2000:]}")

    if progress_cb:
        progress_cb(total_frames, total_frames)
