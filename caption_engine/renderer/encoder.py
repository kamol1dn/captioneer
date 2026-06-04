"""Drive ffmpeg to encode rendered RGBA frames into a transparent .mov.

Why ProRes 4444? It's the de-facto standard for alpha-channel video in pro
NLEs (Premiere, Resolve, Final Cut). Editors can drop the .mov on a track and
see-through transparency just works.
"""
import subprocess
from typing import List, Optional, Callable
from PIL import Image

from ..style import CaptionStyle
from ..layout import Phrase, find_active_word_index
from .phrase import find_active_phrase, draw_phrase, transition_opacity, apply_opacity


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
        cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE
    )

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / style.fps
            img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))

            phrase_idx = find_active_phrase(phrases, t, style.phrase_hold)
            if phrase_idx is not None:
                phrase = phrases[phrase_idx]
                active_word = find_active_word_index(phrase, t)
                opacity = transition_opacity(phrases, phrase_idx, t, style)
                if opacity >= 0.999:
                    draw_phrase(img, phrase, active_word, style, t)
                elif opacity > 0.0:
                    # Fade: draw onto a layer, scale its alpha, composite.
                    layer = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
                    draw_phrase(layer, phrase, active_word, style, t)
                    apply_opacity(layer, opacity)
                    img.alpha_composite(layer)

            proc.stdin.write(img.tobytes())

            if progress_cb and frame_idx % style.fps == 0:
                progress_cb(frame_idx, total_frames)
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="ignore")
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg failed (code {ret}):\n{stderr[-2000:]}")

    if progress_cb:
        progress_cb(total_frames, total_frames)
