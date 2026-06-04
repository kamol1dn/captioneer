"""Tkinter GUI for the caption engine.

Workflow:
  1. Pick input file, choose preset/model, toggle emoji flag
  2. Hit "Transcribe & Copy Prompt" — runs Whisper, copies AI prompt to clipboard
  3. Paste prompt into Claude/Gemini, get refined JSON back
  4. Paste AI's JSON response into the text area
  5. Hit "Render" — renders the refined captions to a ProRes .mov

Run with:
  python -m caption_engine.gui
"""
from .app import CaptionApp, main
from .prompt import build_prompt

__all__ = ["CaptionApp", "main", "build_prompt"]
