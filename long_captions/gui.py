"""Tkinter GUI for long-form subtitle generation.

A thin front-end over `subtitle_gen.generate_subtitles`: pick a media file,
choose language / backend model / output format, tweak cue layout, hit
Generate. Follows the same thread + queue + poll pattern as
`caption_engine.gui.app` so the window stays responsive while models run.

Run with:
  python -m long_captions.gui
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# Same script-mode path fix as subtitle_gen: allow
# `python long_captions/gui.py` as well as `python -m long_captions.gui`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# subtitle_gen is imported lazily (in the worker thread) — it drags in numpy
# and the transcription backends, which would stall the window on startup.
DEFAULT_WINDOW_S = 30.0  # mirrors subtitle_gen.DEFAULT_WINDOW_S

# Language dropdown → the `language` argument of generate_subtitles().
# None lets WhisperX auto-detect; "uz" routes to the windowed Kotib + MMS path
# (fixed model, so the model dropdown is disabled and the window knob applies).
_LANGUAGES = {
    "Auto-detect": {"code": None, "kotib": False},
    "English":     {"code": "en", "kotib": False},
    "Uzbek":       {"code": "uz", "kotib": True},
}

_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
_MEDIA_FILETYPES = [
    ("Video / Audio", "*.mp4 *.mov *.avi *.mkv *.webm *.mp3 *.wav *.m4a *.flac *.ogg"),
    ("All files", "*.*"),
]


class SubtitleApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Long Captions — Subtitle Generator")
        self.resizable(False, False)
        self._q: queue.Queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        f = ttk.Frame(self, padding=16)
        f.grid(sticky="nsew")
        f.columnconfigure(1, weight=1)
        p = dict(padx=8, pady=4)

        # ── Input ──────────────────────────────────────────────────────────
        ttk.Label(f, text="Input").grid(row=0, column=0, sticky="w", **p)
        self._input_var = tk.StringVar()
        self._input_var.trace_add("write", self._on_input_changed)
        ttk.Entry(f, textvariable=self._input_var, width=52).grid(
            row=0, column=1, sticky="ew", **p)
        ttk.Button(f, text="Browse…", command=self._browse_input).grid(row=0, column=2, **p)

        # ── Output ─────────────────────────────────────────────────────────
        ttk.Label(f, text="Output").grid(row=1, column=0, sticky="w", **p)
        self._output_var = tk.StringVar(value="subtitles.srt")
        ttk.Entry(f, textvariable=self._output_var, width=52).grid(
            row=1, column=1, sticky="ew", **p)
        ttk.Button(f, text="Browse…", command=self._browse_output).grid(row=1, column=2, **p)

        # ── Language → Model → Format → Device ─────────────────────────────
        opts = ttk.Frame(f)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", **p)

        ttk.Label(opts, text="Language").pack(side="left")
        self._lang_var = tk.StringVar(value="Auto-detect")
        self._lang_combo = ttk.Combobox(opts, textvariable=self._lang_var,
                                        values=list(_LANGUAGES.keys()),
                                        state="readonly", width=11)
        self._lang_combo.pack(side="left", padx=(4, 16))
        self._lang_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

        ttk.Label(opts, text="Model").pack(side="left")
        self._model_var = tk.StringVar(value="base")
        self._model_combo = ttk.Combobox(opts, textvariable=self._model_var,
                                         values=_MODELS, state="readonly", width=10)
        self._model_combo.pack(side="left", padx=(4, 16))

        ttk.Label(opts, text="Format").pack(side="left")
        self._fmt_var = tk.StringVar(value="srt")
        self._fmt_combo = ttk.Combobox(opts, textvariable=self._fmt_var,
                                       values=["srt", "vtt"], state="readonly", width=5)
        self._fmt_combo.pack(side="left", padx=(4, 16))
        self._fmt_combo.bind("<<ComboboxSelected>>", self._on_format_changed)

        ttk.Label(opts, text="Device").pack(side="left")
        self._device_var = tk.StringVar(value="auto")
        ttk.Combobox(opts, textvariable=self._device_var,
                     values=["auto", "cuda", "cpu"],
                     state="readonly", width=6).pack(side="left", padx=4)

        # Word-level = inline WebVTT per-word timestamps; VTT-only, so ticking it
        # forces the format and locks the dropdown.
        self._word_level_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Word-level (VTT)",
                        variable=self._word_level_var,
                        command=self._on_word_level_changed).pack(side="left", padx=(16, 0))

        # ── Cue layout + Uzbek windowing ────────────────────────────────────
        adv = ttk.LabelFrame(f, text="Cue layout", padding=(8, 4))
        adv.grid(row=3, column=0, columnspan=3, sticky="ew", **p)

        ttk.Label(adv, text="Chars / line").pack(side="left")
        self._chars_var = tk.IntVar(value=42)
        ttk.Spinbox(adv, textvariable=self._chars_var, from_=16, to=80,
                    increment=1, width=5).pack(side="left", padx=(4, 16))

        ttk.Label(adv, text="Lines").pack(side="left")
        self._lines_var = tk.IntVar(value=2)
        ttk.Spinbox(adv, textvariable=self._lines_var, from_=1, to=4,
                    increment=1, width=4).pack(side="left", padx=(4, 16))

        ttk.Label(adv, text="Max cue (s)").pack(side="left")
        self._cuedur_var = tk.DoubleVar(value=6.0)
        ttk.Spinbox(adv, textvariable=self._cuedur_var, from_=1.0, to=15.0,
                    increment=0.5, width=5).pack(side="left", padx=(4, 16))

        ttk.Label(adv, text="Window (s)").pack(side="left")
        self._window_var = tk.DoubleVar(value=DEFAULT_WINDOW_S)
        self._window_spin = ttk.Spinbox(adv, textvariable=self._window_var,
                                        from_=10.0, to=60.0, increment=5.0, width=5)
        self._window_spin.pack(side="left", padx=4)

        # ── Generate ────────────────────────────────────────────────────────
        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self._generate_btn = ttk.Button(
            f, text="Generate Subtitles", command=self._start_generate)
        self._generate_btn.grid(row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

        # ── Status ─────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self._status_var).grid(
            row=6, column=0, columnspan=3, sticky="w", **p)
        self._progress = ttk.Progressbar(f, mode="indeterminate", length=520)
        self._progress.grid(row=7, column=0, columnspan=3, sticky="ew", padx=8, pady=4)

        self._on_language_changed()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _on_language_changed(self, *_):
        """Uzbek uses the fixed Kotib model (model dropdown off, window knob
        on); every other language is Whisper-sized and streams internally."""
        kotib = _LANGUAGES[self._lang_var.get()]["kotib"]
        self._model_combo.configure(state="disabled" if kotib else "readonly")
        self._window_spin.configure(state="normal" if kotib else "disabled")

    def _browse_input(self):
        path = filedialog.askopenfilename(filetypes=_MEDIA_FILETYPES)
        if path:
            self._input_var.set(path)

    def _browse_output(self):
        fmt = self._fmt_var.get()
        path = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}",
            filetypes=[("SubRip", "*.srt"), ("WebVTT", "*.vtt")],
            initialfile=Path(self._output_var.get()).name,
        )
        if path:
            self._output_var.set(path)
            ext = Path(path).suffix.lower().lstrip(".")
            if ext in ("srt", "vtt"):
                self._fmt_var.set(ext)

    def _on_input_changed(self, *_):
        p = Path(self._input_var.get())
        if p.suffix:
            self._output_var.set(str(p.with_suffix(f".{self._fmt_var.get()}")))

    def _on_format_changed(self, *_):
        out = self._output_var.get().strip()
        if out:
            self._output_var.set(str(Path(out).with_suffix(f".{self._fmt_var.get()}")))

    def _on_word_level_changed(self):
        """Word-level emits inline WebVTT timestamps, so force VTT and lock the
        format dropdown while it's on."""
        if self._word_level_var.get():
            self._fmt_var.set("vtt")
            self._fmt_combo.configure(state="disabled")
            self._on_format_changed()
        else:
            self._fmt_combo.configure(state="readonly")

    def _set_busy(self, busy: bool):
        self._generate_btn.state(["disabled"] if busy else ["!disabled"])

    # ── Generate ───────────────────────────────────────────────────────────

    def _start_generate(self):
        path = self._input_var.get().strip()
        if not path:
            messagebox.showerror("Error", "Select an input file first.")
            return
        if not Path(path).is_file():
            messagebox.showerror("Error", f"Input file not found:\n{path}")
            return

        language = _LANGUAGES[self._lang_var.get()]["code"]
        kwargs = dict(
            output=self._output_var.get().strip() or None,
            language=language,
            device=self._device_var.get(),
            model_size=self._model_var.get(),
            fmt=self._fmt_var.get(),
            word_level=self._word_level_var.get(),
            window_s=float(self._window_var.get()),
            max_chars_per_line=int(self._chars_var.get()),
            max_lines=int(self._lines_var.get()),
            max_cue_dur=float(self._cuedur_var.get()),
            progress=False,
        )

        self._set_busy(True)
        self._status_var.set("Transcribing… (long files can take a while)")
        self._progress.start(10)
        threading.Thread(
            target=self._generate_thread, args=(path, kwargs), daemon=True,
        ).start()

    def _generate_thread(self, path: str, kwargs: dict):
        try:
            from long_captions.subtitle_gen import generate_subtitles
            output = generate_subtitles(path, **kwargs)
            self._q.put(("ok", output))
        except Exception as e:
            self._q.put(("error", str(e)))

    # ── Queue poll (main thread only) ──────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]

                if kind == "ok":
                    _, output = msg
                    self._progress.stop()
                    self._set_busy(False)
                    self._status_var.set(f"Done → {output}")

                elif kind == "error":
                    _, err = msg
                    self._progress.stop()
                    self._set_busy(False)
                    self._status_var.set("Error — see dialog")
                    messagebox.showerror("Error", err)

        except queue.Empty:
            pass

        self.after(50, self._poll_queue)


def main():
    app = SubtitleApp()
    app.mainloop()


if __name__ == "__main__":
    main()
