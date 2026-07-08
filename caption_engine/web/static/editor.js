/* Preset editor: builds a control for every CaptionStyle knob, grouped, and
 * live-binds each to the working style object. Changing a control mutates the
 * style and calls onChange(key, isLayoutField) so app.js can repaint (cheap) or
 * re-run server layout (only for the three layout-affecting fields). */

const LAYOUT_FIELDS = new Set([
  "max_chars_per_line", "max_lines_visible", "phrase_gap_threshold",
]);

// [group, [ [key, label, type, opts?] ... ] ]
const SCHEMA = [
  ["Canvas", [
    ["width", "Width", "int", { min: 100, max: 4096, step: 2 }],
    ["height", "Height", "int", { min: 0, max: 4096, step: 2 }],
    ["fps", "FPS", "int", { min: 1, max: 60, step: 1 }],
  ]],
  ["Typography", [
    ["font_path", "Font", "font"],
    ["font_size", "Size", "int", { min: 8, max: 400, step: 1 }],
    ["line_spacing", "Line spacing", "float", { min: 0.5, max: 3, step: 0.05 }],
    ["letter_spacing", "Letter spacing", "int", { min: -20, max: 40, step: 1 }],
  ]],
  ["Layout", [
    ["max_chars_per_line", "Max chars/line", "int", { min: 4, max: 60, step: 1 }],
    ["max_lines_visible", "Max lines", "int", { min: 1, max: 5, step: 1 }],
    ["vertical_anchor", "Vertical anchor", "range", { min: 0, max: 1, step: 0.01 }],
    ["horizontal_padding", "Horizontal pad", "int", { min: 0, max: 400, step: 2 }],
  ]],
  ["Colors", [
    ["text_color", "Text", "color"],
    ["highlight_color", "Highlight", "color"],
    ["text_stroke_color", "Stroke", "color"],
    ["text_stroke_width", "Stroke width", "int", { min: 0, max: 40, step: 1 }],
  ]],
  ["Background", [
    ["bg_enabled", "Enabled", "bool"],
    ["bg_color", "Color", "color"],
    ["bg_padding", "Padding", "int", { min: 0, max: 120, step: 1 }],
    ["bg_radius", "Radius", "int", { min: 0, max: 120, step: 1 }],
    ["bg_offset_x", "Offset X", "int", { min: -200, max: 200, step: 1 }],
    ["bg_offset_y", "Offset Y", "int", { min: -200, max: 200, step: 1 }],
    ["bg_scale_x", "Scale X", "float", { min: 0.2, max: 3, step: 0.05 }],
    ["bg_scale_y", "Scale Y", "float", { min: 0.2, max: 3, step: 0.05 }],
  ]],
  ["Highlight", [
    ["highlight_mode", "Mode", "select", { options: ["none", "scale", "box"] }],
    ["highlight_scale", "Scale", "float", { min: 1, max: 2, step: 0.01 }],
    ["highlight_box_color", "Box color", "color"],
    ["highlight_box_padding", "Box padding", "int", { min: 0, max: 60, step: 1 }],
  ]],
  ["Animation", [
    ["entry_anim", "Entry", "select", { options: ["none", "pop"] }],
    ["entry_anim_duration", "Duration (s)", "float", { min: 0.01, max: 1, step: 0.01 }],
  ]],
  ["Transition", [
    ["transition", "Type", "select", { options: ["none", "fade"] }],
    ["transition_frames", "Frames", "int", { min: 0, max: 30, step: 1 }],
  ]],
  ["Timing", [
    ["phrase_gap_threshold", "Gap threshold (s)", "float", { min: 0.1, max: 3, step: 0.05 }],
    ["phrase_hold", "Hold (s)", "float", { min: 0, max: 10, step: 0.05 }],
  ]],
];

const Editor = {
  build(container, style, fonts, onChange) {
    container.innerHTML = "";
    this.style = style;
    this.onChange = onChange;
    this.fonts = fonts;

    for (const [group, rows] of SCHEMA) {
      const g = el("div", "field-group");
      g.appendChild(el("div", "group-title", group));
      for (const [key, label, type, opts] of rows) {
        g.appendChild(this._field(key, label, type, opts || {}));
      }
      container.appendChild(g);
    }
  },

  _emit(key) { this.onChange(key, LAYOUT_FIELDS.has(key)); },

  _field(key, label, type, opts) {
    const wrap = el("div", "field");
    wrap.appendChild(el("label", null, label));
    const ctrl = el("div", "control");
    const v = this.style[key];

    if (type === "bool") {
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = !!v;
      cb.onchange = () => { this.style[key] = cb.checked; this._emit(key); };
      ctrl.appendChild(cb);

    } else if (type === "select") {
      const sel = document.createElement("select");
      opts.options.forEach(o => sel.add(new Option(o, o)));
      sel.value = v;
      sel.onchange = () => { this.style[key] = sel.value; this._emit(key); };
      ctrl.appendChild(sel);

    } else if (type === "font") {
      const sel = document.createElement("select");
      this.fonts.forEach(f => sel.add(new Option(f, f)));
      if (this.fonts.includes(v)) sel.value = v;
      sel.onchange = () => { this.style[key] = sel.value; this._emit(key); };
      ctrl.appendChild(sel);

    } else if (type === "color") {
      const [hex, alpha] = rgbaToParts(v);
      const col = document.createElement("input");
      col.type = "color"; col.value = hex;
      const a = document.createElement("input");
      a.type = "number"; a.className = "alpha"; a.min = 0; a.max = 255; a.step = 1;
      a.value = alpha;
      const apply = () => {
        this.style[key] = partsToRgba(col.value, parseInt(a.value || "0", 10));
        this._emit(key);
      };
      col.oninput = apply; a.oninput = apply;
      ctrl.appendChild(col); ctrl.appendChild(a);

    } else if (type === "range") {
      const r = document.createElement("input");
      r.type = "range"; r.min = opts.min; r.max = opts.max; r.step = opts.step;
      r.value = v;
      const out = el("span", "numval", (+v).toFixed(2));
      r.oninput = () => {
        this.style[key] = parseFloat(r.value);
        out.textContent = parseFloat(r.value).toFixed(2);
        this._emit(key);
      };
      ctrl.appendChild(r); ctrl.appendChild(out);

    } else { // int / float
      const n = document.createElement("input");
      n.type = "number";
      if (opts.min !== undefined) n.min = opts.min;
      if (opts.max !== undefined) n.max = opts.max;
      n.step = type === "float" ? (opts.step || 0.1) : (opts.step || 1);
      n.value = v;
      n.oninput = () => {
        const val = type === "float" ? parseFloat(n.value) : parseInt(n.value, 10);
        if (!Number.isNaN(val)) { this.style[key] = val; this._emit(key); }
      };
      ctrl.appendChild(n);
    }

    wrap.appendChild(ctrl);
    return wrap;
  },
};

// ── helpers ──
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function rgbaToParts(c) {
  const [r, g, b, a = 255] = c || [0, 0, 0, 255];
  const hex = "#" + [r, g, b].map(x => x.toString(16).padStart(2, "0")).join("");
  return [hex, a];
}
function partsToRgba(hex, a) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b, a];
}

window.Editor = Editor;
