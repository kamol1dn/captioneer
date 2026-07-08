/* Word-level editor: a scrollable table of the caption words (text / start /
 * end / line-break / delete) bound directly to the app's words array.
 *
 * Edits mutate the array in place and fire onChange, which the app debounces
 * into a server re-layout — so the live preview follows every tweak. Clicking
 * a row's number seeks the video to that word, and highlight(t) follows
 * playback so you can spot typos while listening. */

const WordEditor = {
  build(container, words, { onChange, onSeek }) {
    this.container = container;
    this.words = words;
    this.onChange = onChange;
    this.onSeek = onSeek;
    this._rows = [];
    this._activeIdx = -1;
    container.innerHTML = "";
    const frag = document.createDocumentFragment();
    words.forEach(w => frag.appendChild(this._row(w)));
    container.appendChild(frag);
  },

  _row(w) {
    const row = wel("div", "word-row");
    const i = this._rows.length;

    const num = wel("button", "w-num", String(i + 1));
    num.title = "Jump video to this word";
    num.onclick = () => this.onSeek(w.start);

    const text = document.createElement("input");
    text.type = "text";
    text.className = "w-text";
    text.value = w.text;
    text.spellcheck = false;
    text.oninput = () => { w.text = text.value; this.onChange(false); };

    const start = this._num(w.start, v => { w.start = v; this.onChange(false); });
    const end = this._num(w.end, v => { w.end = v; this.onChange(false); });

    const br = wel("button", "w-break" + (w.line_break ? " on" : ""), "↵");
    br.title = "Line break after this word";
    br.onclick = () => {
      w.line_break = !w.line_break;
      br.classList.toggle("on", w.line_break);
      this.onChange(false);
    };

    const del = wel("button", "w-del", "×");
    del.title = "Delete word";
    del.onclick = () => {
      const idx = this.words.indexOf(w);
      if (idx >= 0) this.words.splice(idx, 1);
      // Rebuild: row numbers shift after a removal.
      this.build(this.container, this.words,
                 { onChange: this.onChange, onSeek: this.onSeek });
      this.onChange(true);
    };

    row.append(num, text, start, end, br, del);
    this._rows.push(row);
    return row;
  },

  _num(val, set) {
    const n = document.createElement("input");
    n.type = "number";
    n.step = "0.01";
    n.min = "0";
    n.className = "w-time";
    n.value = (+val).toFixed(2);
    n.oninput = () => {
      const v = parseFloat(n.value);
      if (!Number.isNaN(v)) set(v);
    };
    return n;
  },

  /* Follow playback: mark the word active at time t (last word started, same
   * rule as the canvas painter). autoScroll keeps it in view while playing —
   * off when paused so it never fights the user's own scrolling. */
  highlight(t, autoScroll) {
    const ws = this.words;
    if (!ws || !ws.length || !this._rows.length) return;
    let idx = -1;
    for (let i = 0; i < ws.length; i++) {
      if (ws[i].start <= t) idx = i;
      else break;
    }
    if (idx === this._activeIdx) return;
    if (this._activeIdx >= 0)
      this._rows[this._activeIdx]?.classList.remove("active");
    this._activeIdx = idx;
    if (idx >= 0) {
      const row = this._rows[idx];
      row.classList.add("active");
      if (autoScroll) row.scrollIntoView({ block: "nearest" });
    }
  },
};

function wel(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

window.WordEditor = WordEditor;
