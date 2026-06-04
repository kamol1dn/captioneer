"""The Tkinter application window for the caption engine."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

from .. import engine, presets
from ..transcriber import Word
from .prompt import build_prompt


# Per-language UI config. Selecting a language drives the preset list (from
# presets.PRESET_GROUPS), the model dropdown, the alignment toggle and the hold.
# `code` is what we pass to engine.transcribe(language=...): None lets WhisperX
# auto-detect; "uz" routes to the Kotib backend (fixed model, always MMS-aligned).
_LANGUAGES = {
    "English": {
        "code": None,
        "models": ["tiny", "base", "small", "medium", "large-v3"],
        "default_model": "large-v3",
        "whisper": True,    # model size + WhisperX align apply
    },
    "Uzbek": {
        "code": "uz",
        "models": ["Kotib"],
        "default_model": "Kotib",
        "whisper": False,   # Kotib is a fixed model; align is always via MMS
    },
}


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

        # ── Language → Preset → Model → Hold (language drives the rest) ─────
        opts = ttk.Frame(f)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", **p)

        ttk.Label(opts, text="Language").pack(side="left")
        self._lang_var = tk.StringVar(value="English")
        self._lang_combo = ttk.Combobox(opts, textvariable=self._lang_var,
                                         values=list(_LANGUAGES.keys()),
                                         state="readonly", width=10)
        self._lang_combo.pack(side="left", padx=(4, 16))
        self._lang_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

        ttk.Label(opts, text="Preset").pack(side="left")
        self._preset_var = tk.StringVar()
        self._preset_combo = ttk.Combobox(opts, textvariable=self._preset_var,
                                          state="readonly", width=18)
        self._preset_combo.pack(side="left", padx=(4, 16))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_preset_changed)

        ttk.Label(opts, text="Model").pack(side="left")
        self._model_var = tk.StringVar()
        self._model_combo = ttk.Combobox(opts, textvariable=self._model_var,
                                         state="readonly", width=12)
        self._model_combo.pack(side="left", padx=4)

        ttk.Label(opts, text="Hold (s)").pack(side="left", padx=(16, 0))
        self._hold_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(opts, textvariable=self._hold_var, from_=0.0, to=10.0,
                    increment=0.25, width=6).pack(side="left", padx=4)

        # ── Emoji toggle ───────────────────────────────────────────────────
        self._emoji_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Include emoji instructions in AI prompt",
                         variable=self._emoji_var).grid(row=3, column=1, sticky="w", **p)

        # ── Alignment toggle ───────────────────────────────────────────────
        self._align_var = tk.BooleanVar(value=True)
        self._align_chk = ttk.Checkbutton(
            f, text="Align timings (WhisperX) — accurate word timing",
            variable=self._align_var)
        self._align_chk.grid(row=3, column=2, sticky="w", **p)

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

        # Populate preset/model/hold for the initial language.
        self._on_language_changed()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _on_language_changed(self, *_):
        """Language drives the preset list/default, model dropdown, alignment
        toggle and hold."""
        cfg = _LANGUAGES[self._lang_var.get()]
        group = presets.PRESET_GROUPS[self._lang_var.get()]

        self._preset_combo.configure(values=group)
        self._preset_var.set(group[0])                      # default = first

        self._model_combo.configure(
            values=cfg["models"],
            state="readonly" if cfg["whisper"] else "disabled",
        )
        self._model_var.set(cfg["default_model"])

        # WhisperX alignment only applies to the Whisper path; Kotib always
        # aligns via MMS, so disable the toggle for Uzbek.
        self._align_chk.configure(state="normal" if cfg["whisper"] else "disabled")

        self._sync_hold_to_preset()

    def _on_preset_changed(self, *_):
        self._sync_hold_to_preset()

    def _sync_hold_to_preset(self):
        """Set the hold field to the selected preset's own phrase_hold."""
        try:
            self._hold_var.set(presets.get(self._preset_var.get()).phrase_hold)
        except (ValueError, tk.TclError):
            pass

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
        language = _LANGUAGES[self._lang_var.get()]["code"]
        self._set_busy(True)
        self._status_var.set("Transcribing…")
        self._progress.configure(mode="indeterminate")
        self._progress.start(10)
        threading.Thread(
            target=self._transcribe_thread,
            args=(path, self._model_var.get(), self._emoji_var.get(),
                  self._align_var.get(), language),
            daemon=True,
        ).start()

    def _transcribe_thread(self, path: str, model: str, use_emojis: bool,
                           align: bool, language):
        try:
            words = engine.transcribe(path, model_size=model, align=align,
                                      language=language)
            prompt = build_prompt(words, use_emojis, language)
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
        try:
            style.phrase_hold = max(0.0, float(self._hold_var.get()))
        except (tk.TclError, ValueError):
            pass  # keep the preset default if the field is blank/invalid

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
