"""Captioneer as an MCP server: transcription, script alignment, caption
overlays, and reference-video research, for any project's agent to call.

Every tool is a thin wrapper over ``caption_engine.toolkit`` /
``caption_engine.research``; ``python -m caption_engine.toolkit`` is the CLI
mirror of the same functions.

Wire it into a project's ``.mcp.json``:

    "captioneer": {
      "command": "D:\\coding\\captioneer-english\\venv\\Scripts\\python.exe",
      "args": ["-m", "caption_engine.mcp_server"],
      "cwd": "D:\\coding\\captioneer-english"
    }

Same stdout rule as ``clipper.mcp_server``: stdout is the JSON-RPC channel and
WhisperX/tqdm/HuggingFace print to it, so it is pointed at stderr before any
of them import, and the transport is wired to the saved real handle.
"""
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

_real_stdout = sys.stdout
sys.stdout = sys.stderr

import warnings as _warnings  # noqa: E402
from typing import Optional  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from . import toolkit  # noqa: E402

_warnings.filterwarnings("default")

mcp = FastMCP("captioneer")


@mcp.tool()
def transcribe_media(path: str, language: str = "en", model: str = "large-v3",
                     out_json: Optional[str] = None) -> dict:
    """Transcribe an audio/video file to word-level timestamps (WhisperX
    forced alignment, ~20-50ms). Writes <stem>.words.json next to the file
    unless out_json is given. Returns the path, word count, and full text.
    language: ISO code, or "auto" to detect."""
    return toolkit.transcribe_media(path, None if language == "auto" else language, model, out_json)


@mcp.tool()
def align_script(audio_path: str, text: str, language: str = "en",
                 out_json: Optional[str] = None) -> dict:
    """Get exact word timings for audio whose script you already know (TTS
    output, a scripted voiceover). Forced alignment only, with no recognition,
    so every word is the script's own word. Spell numbers out in the spoken
    script; digits/symbols get interpolated times (reported as
    `interpolated`)."""
    return toolkit.align_script(audio_path, text, language, out_json)


@mcp.tool()
def render_caption_overlay(words_json: str, output_mov: str, preset: str = "reels_classic",
                           width: Optional[int] = None, height: Optional[int] = None,
                           fps: Optional[int] = None) -> dict:
    """Render word-by-word animated captions from a words.json to a
    transparent overlay: .mov = ProRes 4444 (NLE timelines), .webm = VP9+alpha
    (small; Remotion/browsers). See list_presets."""
    return toolkit.render_overlay(words_json, output_mov, preset, width, height, fps)


@mcp.tool()
def list_presets() -> dict:
    """Caption style presets available to render_caption_overlay."""
    return toolkit.list_presets()


@mcp.tool()
def research_video(source: str, out_dir: str = "research", language: str = "en",
                   model: str = "large-v3", scene_threshold: float = 0.3,
                   cookies_from_browser: Optional[str] = None) -> dict:
    """Break a reference video (URL via yt-dlp, or local file) down for
    study: keyframe per shot + contact sheet, a first-3-seconds hook strip,
    aligned transcript, and pacing metrics (shot length, cuts/10s, WPM,
    pauses, time-to-first-word, views/likes when available). Writes
    <out_dir>/<slug>/report.md. Read contact.jpg and hook.jpg to see it.
    cookies_from_browser: only when the user explicitly allows it (e.g. "chrome")."""
    from .research import research_video as _research
    return _research(source, out_dir, None if language == "auto" else language,
                     model, scene_threshold, cookies_from_browser)


async def _run_stdio() -> None:
    """See clipper.mcp_server._run_stdio: bind the transport to the real stdout."""
    import anyio
    from mcp.server.stdio import stdio_server

    async with stdio_server(stdout=anyio.wrap_file(_real_stdout)) as (read, write):
        await mcp._mcp_server.run(read, write, mcp._mcp_server.create_initialization_options())


def main() -> None:
    import anyio
    anyio.run(_run_stdio)


if __name__ == "__main__":
    main()
