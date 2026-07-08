/* Live caption preview: paints the current caption state onto a <canvas>
 * overlaid on the source <video>, driven by video.currentTime.
 *
 * This is an approximation of the PIL renderer (draw_phrase) — close enough for
 * WYSIWYG editing. The "Render Preview" button runs the real engine when
 * pixel-accuracy matters, which is the point of the hybrid design.
 *
 * The active-phrase / active-word / fade logic mirrors the Python side
 * (renderer/phrase.py, layout/builder.py) so timing feels identical. */

class CanvasPainter {
  constructor(canvas, video) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.video = video;
    this.style = null;
    this.phrases = [];
    this.fontFamily = "sans-serif";
    this._loadedFonts = new Set();
    this._raf = null;
    this._loop = this._loop.bind(this);
  }

  setStyle(style) { this.style = style; }
  setPhrases(phrases) { this.phrases = phrases || []; }

  /* Load a bundled font by its label so canvas metrics track the PIL render. */
  async loadFont(label) {
    if (!label) return;
    const family = "cap_" + label.replace(/[^a-z0-9]/gi, "_");
    this.fontFamily = family;
    if (this._loadedFonts.has(label)) return;
    try {
      const face = new FontFace(family,
        `url(/api/fontfile?label=${encodeURIComponent(label)})`);
      await face.load();
      document.fonts.add(face);
      this._loadedFonts.add(label);
    } catch (e) { /* fall back to system font silently */ }
  }

  start() { if (!this._raf) this._raf = requestAnimationFrame(this._loop); }
  stop() {
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  _loop() {
    // A bad frame must never kill the loop (it would freeze a stale frame on
    // screen); log once and keep going.
    try {
      this._syncGeometry();
      this.paintAt(this.video.currentTime || 0);
    } catch (e) {
      if (!this._warned) { this._warned = true; console.error("preview paint error:", e); }
    }
    this._raf = requestAnimationFrame(this._loop);
  }

  /* Re-measure whenever the video element's rect changes (source switch,
   * metadata load, panel resize) so the canvas always tracks the video. */
  _syncGeometry() {
    const v = this.video;
    const r = v.getBoundingClientRect();
    if (r.width !== this._lastW || r.height !== this._lastH ||
        v.offsetLeft !== this._lastL || v.offsetTop !== this._lastT) {
      this._lastW = r.width; this._lastH = r.height;
      this._lastL = v.offsetLeft; this._lastT = v.offsetTop;
      this.resize();
    }
  }

  /* Match the canvas backing store to the video's displayed rect. (For
   * audio-only sources the <video> is CSS-sized to a black 9:16 stage, so the
   * rect is valid even though videoWidth is 0.) */
  resize() {
    const v = this.video;
    const rect = v.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.style.width = rect.width + "px";
    this.canvas.style.height = rect.height + "px";
    this.canvas.style.left = (v.offsetLeft) + "px";
    this.canvas.style.top = (v.offsetTop) + "px";
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._cssW = rect.width;
    this._cssH = rect.height;
  }

  // ── timing helpers (mirror renderer/phrase.py) ──
  _windowEnd(i, hold) {
    let end = this.phrases[i].end + hold;
    if (i + 1 < this.phrases.length)
      end = Math.min(end, this.phrases[i + 1].start);
    return end;
  }
  _activePhrase(t, hold) {
    for (let i = 0; i < this.phrases.length; i++)
      if (this.phrases[i].start <= t && t <= this._windowEnd(i, hold)) return i;
    return -1;
  }
  _opacity(i, t) {
    const s = this.style;
    if (s.transition !== "fade" || s.transition_frames <= 0) return 1;
    const fade = s.transition_frames / s.fps;
    const p = this.phrases[i];
    const end = this._windowEnd(i, s.phrase_hold);
    return Math.max(0, Math.min(1, (t - p.start) / fade, (end - t) / fade));
  }
  _activeWord(words, t) {
    if (!words.length) return -1;
    if (t < words[0].start) return -1;
    for (let i = 0; i < words.length; i++) {
      if (words[i].start <= t && t < words[i].end) return i;
      if (i + 1 < words.length && words[i].end <= t && t < words[i + 1].start) return i;
    }
    if (t >= words[words.length - 1].end) return words.length - 1;
    return -1;
  }

  _rgba(c) {
    if (!c) return "rgba(0,0,0,0)";
    const [r, g, b, a = 255] = c;
    return `rgba(${r},${g},${b},${a / 255})`;
  }

  paintAt(t) {
    const ctx = this.ctx, s = this.style;
    if (!this._cssW) this.resize();
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!s || !this.phrases.length || !this._cssW) return;

    const idx = this._activePhrase(t, s.phrase_hold);
    if (idx < 0) return;
    const phrase = this.phrases[idx];
    const opacity = this._opacity(idx, t);
    if (opacity <= 0) return;

    const W = this._cssW, H = this._cssH;
    const scale = W / s.width;                 // author-space → display-space
    const words = phrase.lines.flatMap(l => l.words);
    const activeWord = this._activeWord(words, t);

    ctx.save();
    ctx.globalAlpha = opacity;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.lineJoin = "round";
    if ("letterSpacing" in ctx)
      ctx.letterSpacing = (s.letter_spacing * scale) + "px";

    const fontSize = s.font_size * scale;
    const baseFont = `${fontSize}px "${this.fontFamily}", sans-serif`;
    ctx.font = baseFont;
    const spaceW = ctx.measureText(" ").width;
    const lineH = s.font_size * s.line_spacing * scale;
    const totalH = lineH * phrase.lines.length;
    const blockTop = H * s.vertical_anchor - totalH / 2;

    // measure line widths
    const lineWidths = phrase.lines.map(line => {
      let w = 0;
      line.words.forEach((word, i) => {
        w += ctx.measureText(word.text).width;
        if (i < line.words.length - 1) w += spaceW;
      });
      return w;
    });

    // ── background box ──
    if (s.bg_enabled) {
      const maxW = Math.max(0, ...lineWidths);
      const pad = s.bg_padding * scale;
      let left = (W - maxW) / 2 - pad;
      let right = left + maxW + pad * 2;
      let top = blockTop - pad;
      let bottom = blockTop + totalH + pad;
      const cx = (left + right) / 2, cy = (top + bottom) / 2;
      const hw = (right - left) / 2 * s.bg_scale_x;
      const hh = (bottom - top) / 2 * s.bg_scale_y;
      left = cx - hw + s.bg_offset_x * scale;
      right = cx + hw + s.bg_offset_x * scale;
      top = cy - hh + s.bg_offset_y * scale;
      bottom = cy + hh + s.bg_offset_y * scale;
      this._roundRect(ctx, left, top, right - left, bottom - top, s.bg_radius * scale);
      ctx.fillStyle = this._rgba(s.bg_color);
      ctx.fill();
    }

    // ── words ──
    let wi = 0;
    phrase.lines.forEach((line, li) => {
      let x = (W - lineWidths[li]) / 2;
      const y = blockTop + li * lineH;
      line.words.forEach(word => {
        const isActive = wi === activeWord;
        const ww = ctx.measureText(word.text).width;

        if (isActive && s.highlight_mode === "box") {
          const bp = s.highlight_box_padding * scale;
          this._roundRect(ctx, x - bp, y - bp / 2, ww + bp * 2, fontSize + bp * 1.5, 8 * scale);
          ctx.fillStyle = this._rgba(s.highlight_box_color);
          ctx.fill();
        }

        let wordScale = 1;
        if (isActive) {
          if (s.entry_anim === "pop") {
            const el = t - word.start;
            if (el >= 0 && el < s.entry_anim_duration)
              wordScale = 1 + 0.18 * Math.sin((el / s.entry_anim_duration) * Math.PI);
          }
          if (s.highlight_mode === "scale") wordScale *= s.highlight_scale;
        }

        const color = isActive ? this._rgba(s.highlight_color) : this._rgba(s.text_color);
        this._drawWord(ctx, word.text, x, y, ww, fontSize, wordScale, color, s, scale);
        x += ww + spaceW;
        wi++;
      });
    });
    ctx.restore();
  }

  _drawWord(ctx, text, x, y, ww, fontSize, wordScale, color, s, scale) {
    ctx.save();
    if (wordScale !== 1) {
      const cx = x + ww / 2, cy = y + fontSize / 2;
      ctx.translate(cx, cy);
      ctx.scale(wordScale, wordScale);
      ctx.translate(-cx, -cy);
    }
    if (s.text_stroke_width > 0 && (s.text_stroke_color[3] ?? 255) > 0) {
      ctx.lineWidth = s.text_stroke_width * 2 * scale;   // PIL stroke ~ radius
      ctx.strokeStyle = this._rgba(s.text_stroke_color);
      ctx.strokeText(text, x, y);
    }
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    ctx.restore();
  }

  _roundRect(ctx, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
}

window.CanvasPainter = CanvasPainter;
