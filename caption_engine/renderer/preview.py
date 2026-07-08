"""Single-frame rendering and low-res preview helpers.

``render_frame`` is the per-frame logic the encoder runs in its export loop,
pulled out so the web preview ("Render Preview" / true-fidelity check) draws
frames through the *exact same* code path as the final ProRes export — no second
renderer to keep in sync.

``render_preview_overlay`` renders the caption overlay at low resolution and
composites it over a proxy of the source video with ffmpeg, producing a small
mp4 you can scrub in the browser to review timing/style before committing to a
full export.
"""
import subprocess
from pathlib import Path
from typing import List, Optional, Callable

from PIL import Image

from ..style import CaptionStyle
from ..layout import Phrase, find_active_word_index
from .phrase import find_active_phrase, draw_phrase, transition_opacity, apply_opacity


def render_frame(phrases: List[Phrase], style: CaptionStyle, t: float) -> Image.Image:
    """Draw the caption state at time ``t`` onto a fresh transparent RGBA image.

    This is the single source of truth for "what a caption frame looks like".
    Both the ProRes export loop and the preview compositor call it.
    """
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
    phrase_idx = find_active_phrase(phrases, t, style.phrase_hold)
    if phrase_idx is None:
        return img

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
    return img


def render_preview_overlay(
    phrases: List[Phrase],
    style: CaptionStyle,
    source_proxy: str,
    out_mp4: str,
    ffmpeg: str = "ffmpeg",
    duration: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    audio_only: bool = False,
    stage_size: Optional[tuple] = None,
) -> str:
    """Render the alpha overlay and burn it over ``source_proxy`` into an mp4.

    The overlay is rendered at ``style``'s (already-downscaled) resolution using
    the real encoder, then ffmpeg overlays it centered on the proxy video. The
    result is a browser-playable H.264 mp4 with the source audio — the
    review-before-export playback test.

    ``audio_only=True`` (podcast mp3/wav sources) composites onto a black
    ``stage_size`` canvas instead, keeping the proxy as the audio track.
    """
    from .encoder import render_to_mov  # local import to avoid a cycle

    out_path = Path(out_mp4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_mov = str(out_path.with_suffix(".overlay.mov"))

    render_to_mov(phrases, style, overlay_mov,
                  duration=duration, progress_cb=progress_cb)

    # Overlay the alpha .mov centered (horizontally) and anchored the same way
    # the caption strip is positioned. The overlay is a thin strip; place it so
    # its vertical center matches vertical_anchor over the full-height stage.
    #   overlay y = anchor*H - strip_h/2
    # eof_action=pass: when the caption clip ends before the audio/video, keep
    # playing the base instead of freezing the overlay's last frame.
    overlay_expr = ("overlay=x=(W-w)/2:y=main_h*{a}-h/2"
                    ":eof_action=pass:format=auto".format(a=style.vertical_anchor))
    if audio_only:
        w, h = stage_size or (480, 854)
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={style.fps}",
            "-i", source_proxy,
            "-i", overlay_mov,
            "-filter_complex", f"[0:v][2:v]{overlay_expr}[v]",
            "-map", "[v]", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-i", source_proxy,
            "-i", overlay_mov,
            "-filter_complex", f"[0:v][1:v]{overlay_expr}[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
    proc = subprocess.run(cmd, capture_output=True)
    try:
        Path(overlay_mov).unlink()
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg overlay failed:\n"
            + proc.stderr.decode("utf-8", errors="ignore")[-2000:])
    return str(out_path)
