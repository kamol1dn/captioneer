"""Clipper engine — multicam edit decisions from transcripts, exported to Premiere.

Pipeline: export each camera from Premiere sharing a common t=0 -> transcribe at
word level (reusing caption_engine) -> an agent reads the transcript over MCP and
writes an EDL -> the EDL compiles to FCP7 XML you import, review, and tweak.

The engine never renders the final video. It decides, and Premiere executes.
"""
from .compile import compile_clip, compile_edl
from .edl import EDL, BRoll, CameraCut, Clip, Marker, Segment, validate
from .timebase import Timebase
from .xmeml import write_xmeml

__version__ = "0.1.0"

__all__ = [
    "EDL", "Clip", "Segment", "CameraCut", "BRoll", "Marker", "validate",
    "Timebase", "compile_clip", "compile_edl", "write_xmeml",
]
