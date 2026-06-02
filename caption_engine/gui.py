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
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

from . import engine, presets
from .transcriber import Word


# ── Prompt template ────────────────────────────────────────────────────────────

_PROMPT = """\
Refine these captions for a short-form social media video (Reels/TikTok/Shorts).

RULES:
- Return ONLY a valid JSON array — no explanation, no markdown, no code blocks
- Each object must have "text" (string), "start" (number), "end" (number); it may also include "line_break" (boolean)
- Do NOT change start/end timestamps
- Fix transcription errors, use natural capitalization for captions
- Set "line_break": true on the LAST word of a line to end the line there. Break at sentence ends and natural pauses so each on-screen line is one complete, coherent thought — never split mid-clause
{emoji_rule}\
Transcription JSON:
{words_json}"""

_EMOJI_RULE = """\
- Add emojis to amplify key moments — not every line, roughly 1 per 2-3 sentences
- The emoji MUST be appended directly to the end of an existing word's "text" value with no space — e.g. "fire🔥", "goals💪", "finance🎯". Do NOT create a separate JSON entry for the emoji; a standalone emoji entry gets pushed to the next line on screen, which is wrong
- If the word the emoji is attached to ends with "." "!" or "?", DROP that punctuation — "done.✨" looks wrong, write "done✨". Same for "!" and "?"
- Match the energy of the content: 🔥 💪 😤 🎯 ✨ 😂 etc.
"""


def _build_prompt(words: list, use_emojis: bool) -> str:
    return _PROMPT.format(
        emoji_rule=_EMOJI_RULE if use_emojis else "",
        words_json=json.dumps([w.to_dict() for w in words], indent=2, ensure_ascii=False),
    )


# ── Main app ───────────────────────────────────────────────────────────────────

class CaptionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Caption Engine")
        self.resizable(False, False)
        self._words: list = []
        self._q: queue.Queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        f = ttk.Frame(self, padding=16)
        f.grid(sticky="nsew")
        p = dict(padx=8, pady=4)

        # ── Input ──────────────────────────────────────────────────────────
        ttk.Label(f, text="Input").grid(row=0, column=0, sticky="w", **p)
        self._input_var = tk.StringVar()
        self._input_var.trace_add("write", self._on_input_changed)
        ttk.Entry(f, textvariable=self._input_var, width=52).grid(row=0, column=1, sticky="ew", **p)
        ttk.Button(f, text="Browse…", command=self._browse).grid(row=0, column=2, **p)

        # ── Output ─────────────────────────────────────────────────────────
        ttk.Label(f, text="Output").grid(row=1, column=0, sticky="w", **p)
        self._output_var = tk.StringVar(value="captions.mov")
        ttk.Entry(f, textvariable=self._output_var, width=52).grid(row=1, column=1, sticky="ew", **p)

        # ── Preset + Model ─────────────────────────────────────────────────
        opts = ttk.Frame(f)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", **p)

        ttk.Label(opts, text="Preset").pack(side="left")
        self._preset_var = tk.StringVar(value="otg_cyan")
        ttk.Combobox(opts, textvariable=self._preset_var,
                     values=list(presets.PRESETS.keys()),
                     state="readonly", width=18).pack(side="left", padx=(4, 16))

        ttk.Label(opts, text="Model").pack(side="left")
        self._model_var = tk.StringVar(value="large-v3")
        ttk.Combobox(opts, textvariable=self._model_var,
                     values=["tiny", "base", "small", "medium", "large-v3"],
                     state="readonly", width=12).pack(side="left", padx=4)

        # ── Emoji toggle ───────────────────────────────────────────────────
        self._emoji_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Include emoji instructions in AI prompt",
                         variable=self._emoji_var).grid(row=3, column=1, sticky="w", **p)

        # ── Alignment toggle ───────────────────────────────────────────────
        self._align_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Align timings (WhisperX) — accurate word timing",
                         variable=self._align_var).grid(row=3, column=2, sticky="w", **p)

        # ── Transcribe ─────────────────────────────────────────────────────
        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self._transcribe_btn = ttk.Button(
            f, text="Transcribe & Copy Prompt", command=self._start_transcribe)
        self._transcribe_btn.grid(row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

        # ── Refined captions paste area ────────────────────────────────────
        ttk.Separator(f, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="Paste AI response here (refined captions JSON)").grid(
            row=7, column=0, columnspan=3, sticky="w", **p)
        self._json_text = scrolledtext.ScrolledText(f, width=72, height=14, wrap="word",
                                                     font=("Consolas", 9))
        self._json_text.grid(row=8, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

        # ── Render ─────────────────────────────────────────────────────────
        self._render_btn = ttk.Button(f, text="Render", command=self._start_render)
        self._render_btn.grid(row=9, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

        # ── Status ─────────────────────────────────────────────────────────
        ttk.Separator(f, orient="horizontal").grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=4)
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self._status_var).grid(
            row=11, column=0, columnspan=3, sticky="w", **p)
        self._progress = ttk.Progressbar(f, mode="determinate", length=520)
        self._progress.grid(row=12, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[("Video / Audio", "*.mp4 *.mov *.avi *.mkv *.mp3 *.wav *.m4a"),
                       ("All files", "*.*")])
        if path:
            self._input_var.set(path)

    def _on_input_changed(self, *_):
        p = Path(self._input_var.get())
        if p.suffix:
            self._output_var.set(str(p.with_suffix(".mov")))

    def _set_busy(self, busy: bool):
        state = ["disabled"] if busy else ["!disabled"]
        self._transcribe_btn.state(state)
        self._render_btn.state(state)

    # ── Transcribe ─────────────────────────────────────────────────────────────

    def _start_transcribe(self):
        path = self._input_var.get().strip()
        if not path:
            messagebox.showerror("Error", "Select an input file first.")
            return
        self._set_busy(True)
        self._status_var.set("Transcribing…")
        self._progress.configure(mode="indeterminate")
        self._progress.start(10)
        threading.Thread(
            target=self._transcribe_thread,
            args=(path, self._model_var.get(), self._emoji_var.get(),
                  self._align_var.get()),
            daemon=True,
        ).start()

    def _transcribe_thread(self, path: str, model: str, use_emojis: bool,
                           align: bool):
        try:
            words = engine.transcribe(path, model_size=model, align=align)
            prompt = _build_prompt(words, use_emojis)
            self._q.put(("transcribe_ok", words, prompt))
        except Exception as e:
            self._q.put(("error", str(e)))

    # ── Render ─────────────────────────────────────────────────────────────────

    def _start_render(self):
        raw = self._json_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showerror("Error", "Paste the AI's JSON response first.")
            return
        try:
            data = json.loads(raw)
            words = [Word(text=item["text"], start=item["start"], end=item["end"],
                          line_break=bool(item.get("line_break", False)))
                     for item in data]
        except Exception as e:
            messagebox.showerror("Invalid JSON", f"Could not parse the pasted JSON:\n{e}")
            return

        output = self._output_var.get().strip() or "captions.mov"
        style = presets.get(self._preset_var.get())

        self._set_busy(True)
        self._status_var.set("Rendering…")
        self._progress.configure(mode="determinate")
        self._progress["value"] = 0
        threading.Thread(
            target=self._render_thread,
            args=(words, style, output),
            daemon=True,
        ).start()

    def _render_thread(self, words, style, output):
        def progress_cb(cur, total):
            self._q.put(("progress", cur, total))
        try:
            engine.make_captions(words=words, output_mov=output,
                                  style=style, progress_cb=progress_cb)
            self._q.put(("render_ok", output))
        except Exception as e:
            self._q.put(("error", str(e)))

    # ── Queue poll (main thread only) ──────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]

                if kind == "transcribe_ok":
                    _, words, prompt = msg
                    self._words = words
                    self._progress.stop()
                    self._progress.configure(mode="determinate")
                    self._progress["value"] = 100
                    self._set_busy(False)
                    self.clipboard_clear()
                    self.clipboard_append(prompt)
                    self._status_var.set(
                        f"Done — {len(words)} words transcribed. Prompt copied to clipboard.")

                elif kind == "progress":
                    _, cur, total = msg
                    if total:
                        self._progress["value"] = cur / total * 100
                    self._status_var.set(f"Rendering… {cur}/{total} frames")

                elif kind == "render_ok":
                    _, output = msg
                    self._set_busy(False)
                    self._progress["value"] = 100
                    self._status_var.set(f"Done → {output}")

                elif kind == "error":
                    _, err = msg
                    self._progress.stop()
                    self._progress.configure(mode="determinate")
                    self._set_busy(False)
                    self._status_var.set("Error — see dialog")
                    messagebox.showerror("Error", err)

        except queue.Empty:
            pass

        self.after(50, self._poll_queue)


def main():
    app = CaptionApp()
    app.mainloop()


if __name__ == "__main__":
    main()
