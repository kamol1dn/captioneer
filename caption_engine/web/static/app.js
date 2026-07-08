/* App glue: state, API calls, SSE job handling, and wiring the editor ↔ canvas
 * painter ↔ preferences store together. */

const $ = id => document.getElementById(id);

const state = {
  config: null,
  fonts: [],
  style: null,       // working CaptionStyle dict (font_path held as a label)
  words: [],
  phrases: [],
  proxyUrl: null,
  inputPath: "",
  presetName: "",
  dirty: false,
  trueMode: false,
};

let painter;

// ── boot ─────────────────────────────────────────────────────────────────────
async function init() {
  painter = new CanvasPainter($("overlay"), $("video"));
  wireTransport();
  wireButtons();

  const cfg = await fetch("/api/config").then(r => r.json());
  state.config = cfg;
  state.fonts = cfg.fonts;

  // Languages
  const langSel = $("languageSel");
  Object.keys(cfg.languages).forEach(l => langSel.add(new Option(l, l)));
  langSel.value = cfg.app.last_language in cfg.languages ? cfg.app.last_language
                                                         : Object.keys(cfg.languages)[0];
  langSel.onchange = onLanguageChange;

  $("alignChk").checked = cfg.app.align;
  $("emojiChk").checked = cfg.app.emoji;

  // Preset group dropdown for the save form
  const grpSel = $("presetGroup");
  Object.keys(cfg.preset_groups).forEach(g => grpSel.add(new Option(g, g)));

  onLanguageChange();               // populates models + presets for the language
  window.addEventListener("resize", () => painter.resize());
}

function onLanguageChange() {
  const lang = $("languageSel").value;
  const lcfg = state.config.languages[lang];

  const modelSel = $("modelSel");
  modelSel.innerHTML = "";
  lcfg.models.forEach(m => modelSel.add(new Option(m, m)));
  modelSel.value = lcfg.default_model;
  modelSel.disabled = !lcfg.whisper;
  $("alignChk").disabled = !lcfg.whisper;

  // Presets for this language
  const presetSel = $("presetSel");
  presetSel.innerHTML = "";
  (state.config.preset_groups[lang] || []).forEach(n => presetSel.add(new Option(n, n)));
  presetSel.onchange = () => loadPreset(presetSel.value);
  $("presetGroup").value = lang;

  const first = (state.config.preset_groups[lang] || [])[0];
  if (first) { presetSel.value = first; loadPreset(first); }
  saveAppSettings();
}

// ── presets / style ──────────────────────────────────────────────────────────
function loadPreset(name) {
  const raw = state.config.presets[name];
  if (!raw) return;
  const style = JSON.parse(JSON.stringify(raw));
  delete style._group;
  style.font_path = fontLabelFor(style.font_path);
  state.style = style;
  state.presetName = name;
  state.dirty = false;
  $("presetName").value = name;
  $("presetSel").value = name;

  Editor.build($("editorFields"), state.style, state.fonts, onStyleChange);
  painter.setStyle(state.style);
  painter.loadFont(style.font_path).then(() => relayout());
  saveAppSettings();
}

function fontLabelFor(pathOrLabel) {
  if (!pathOrLabel) return state.fonts[0] || "";
  if (state.fonts.includes(pathOrLabel)) return pathOrLabel;
  const stem = pathOrLabel.replace(/\\/g, "/").split("/").pop().replace(/\.[^.]+$/, "");
  return state.fonts.find(f => f === stem)
      || state.fonts.find(f => f.startsWith(stem))
      || state.fonts[0] || "";
}

let _layoutTimer = null;
function onStyleChange(key, isLayout) {
  markDirty();
  if (key === "font_path") { painter.loadFont(state.style.font_path); return; }
  if (isLayout) {
    clearTimeout(_layoutTimer);
    _layoutTimer = setTimeout(relayout, 200);
  }
  // Non-layout changes are picked up automatically by the rAF paint loop.
}

function markDirty() {
  state.dirty = true;
  $("presetSel").value = "";   // no longer a saved preset until re-saved
}

// ── word-level editor ────────────────────────────────────────────────────────
function showWordEditor() {
  $("wordPanel").classList.remove("hidden");
  $("wordCount").textContent = state.words.length + " words";
  WordEditor.build($("wordEditor"), state.words, {
    onChange: wordsEdited,
    onSeek: t => {
      const v = $("video");
      if (isFinite(v.duration)) v.currentTime = Math.min(v.duration, Math.max(0, t + 0.01));
    },
  });
}

let _wordsTimer = null;
function wordsEdited() {
  $("wordCount").textContent = state.words.length + " words";
  clearTimeout(_wordsTimer);
  _wordsTimer = setTimeout(relayout, 250);   // debounce typing → re-layout → canvas
}

// ── layout (server) ──────────────────────────────────────────────────────────
async function relayout() {
  if (!state.words.length || !state.style) { painter.setPhrases([]); return; }
  const res = await fetch("/api/layout", {
    method: "POST", headers: json(), body: JSON.stringify({
      words: state.words, style: state.style,
    })
  }).then(r => r.json());
  state.phrases = res.phrases || [];
  painter.setPhrases(state.phrases);
}

// ── transcribe / refine ──────────────────────────────────────────────────────
function transcribe() {
  if (!state.inputPath) return setStatus("Select a source file first", "error");
  const lang = $("languageSel").value;
  setBusy(true); setStatus("Transcribing…", "busy");
  runJob("/api/transcribe", {
    input: state.inputPath, language: lang,
    model: $("modelSel").value, align: $("alignChk").checked,
    emoji: $("emojiChk").checked,
  }, {
    onProgress: d => setStatus(d.message || "Working…", "busy"),
    onDone: r => {
      setBusy(false);
      state.words = r.words;
      $("promptBox").value = r.prompt;
      navigator.clipboard?.writeText(r.prompt).catch(() => {});
      setStatus(`Transcribed ${r.words.length} words — prompt copied`, "ok");
      showWordEditor();
      relayout();
    },
    onError: e => { setBusy(false); setStatus("Error: " + e, "error"); },
  });
  saveAppSettings();
}

function applyJson() {
  const raw = $("jsonBox").value.trim();
  if (!raw) return setStatus("Paste the refined JSON first", "error");
  let data;
  try { data = JSON.parse(raw); }
  catch (e) { return setStatus("Invalid JSON: " + e.message, "error"); }
  state.words = data.map(w => ({
    text: w.text, start: +w.start, end: +w.end, line_break: !!w.line_break,
  }));
  setStatus(`Analyzed ${state.words.length} words — edit them in the Review panel`, "ok");
  showWordEditor();
  relayout();
}

// ── source / proxy ───────────────────────────────────────────────────────────
async function browse() {
  const r = await fetch("/api/browse", { method: "POST" }).then(r => r.json());
  if (r.error) return setStatus("Browse failed: " + r.error, "error");
  if (!r.path) return;
  state.inputPath = r.path;
  $("inputPath").value = r.path;
  $("outputPath").value = r.path.replace(/\.[^.\\/]+$/, "") + ".mov";
  loadProxy();
}

async function loadProxy() {
  setStatus("Preparing preview…", "busy");
  const r = await fetch("/api/proxy", {
    method: "POST", headers: json(), body: JSON.stringify({ input: state.inputPath }),
  }).then(r => r.json());
  if (r.error) return setStatus("Preview failed: " + r.error, "error");
  state.proxyUrl = r.url;
  state.audioOnly = !!r.audio_only;
  $("stage").classList.toggle("audio-only", state.audioOnly);
  setLive(r.url);
  setStatus(state.audioOnly ? "Ready (audio source — captions on black)" : "Ready", "ok");
}

function setLive(url) {
  state.trueMode = false;
  $("previewMode").textContent = "live";
  $("previewMode").classList.remove("true");
  $("overlay").classList.remove("hidden");
  const v = $("video");
  v.src = url;
  v.load();
  v.onloadedmetadata = () => {
    $("stagePlaceholder").classList.add("hidden");
    painter.resize();
    if (!state.trueMode) painter.start();
  };
}

// ── true render preview ──────────────────────────────────────────────────────
function truePreview() {
  if (!state.proxyUrl) return setStatus("Load a source file first", "error");
  if (!state.words.length) return setStatus("No captions to preview yet", "error");
  setBusy(true); setStatus("Rendering true preview…", "busy");
  runJob("/api/render-preview", {
    proxy_url: state.proxyUrl, words: state.words, style: state.style,
  }, {
    onProgress: d => setProgress(d.current, d.total),
    onDone: r => {
      setBusy(false); hideProgress();
      state.trueMode = true;
      painter.stop();                       // canvas off — the pixels ARE the render
      $("overlay").classList.add("hidden");
      $("previewMode").textContent = "true render — click for live";
      $("previewMode").classList.add("true");
      const v = $("video");
      v.src = r.url;
      v.load();
      // play() is outside a user gesture here; if the browser blocks it the
      // user can just hit the transport play button.
      v.play().catch(() => setStatus("True render ready — press ▶ to play", "ok"));
      setStatus("True render ready", "ok");
    },
    onError: e => { setBusy(false); hideProgress(); setStatus("Error: " + e, "error"); },
  });
}

// ── export ───────────────────────────────────────────────────────────────────
function render() {
  if (!state.words.length) return setStatus("Nothing to export yet", "error");
  const output = $("outputPath").value.trim() || "captions.mov";
  setBusy(true); setStatus("Exporting…", "busy");
  runJob("/api/render", { words: state.words, style: state.style, output }, {
    onProgress: d => setProgress(d.current, d.total),
    onDone: r => {
      setBusy(false); hideProgress();
      setStatus("Exported → " + r.output, "ok");
      $("renderMsg").textContent = "✓ Saved to " + r.output;
    },
    onError: e => { setBusy(false); hideProgress(); setStatus("Error: " + e, "error"); },
  });
}

// ── preset save/delete ───────────────────────────────────────────────────────
async function savePreset() {
  const name = $("presetName").value.trim();
  if (!name) return setStatus("Enter a preset name", "error");
  const group = $("presetGroup").value;
  const r = await fetch("/api/presets", {
    method: "POST", headers: json(),
    body: JSON.stringify({ name, group, style: state.style }),
  }).then(r => r.json());
  if (r.error) return setStatus(r.error, "error");
  state.config.presets = r.presets;
  state.config.preset_groups = r.preset_groups;
  state.dirty = false;
  refreshPresetList(name);
  setStatus(`Saved preset “${name}”`, "ok");
}

async function deletePreset() {
  const name = $("presetSel").value || $("presetName").value.trim();
  if (!name || !state.config.presets[name]) return setStatus("Select a preset to delete", "error");
  const r = await fetch("/api/presets/" + encodeURIComponent(name), { method: "DELETE" })
    .then(r => r.json());
  state.config.presets = r.presets;
  state.config.preset_groups = r.preset_groups;
  refreshPresetList();
  setStatus(`Deleted “${name}”`, "ok");
}

async function resetPresets() {
  const r = await fetch("/api/presets/reset", { method: "POST" }).then(r => r.json());
  state.config.presets = r.presets;
  state.config.preset_groups = r.preset_groups;
  onLanguageChange();
  setStatus("Presets reset to defaults", "ok");
}

function refreshPresetList(select) {
  const lang = $("languageSel").value;
  const presetSel = $("presetSel");
  presetSel.innerHTML = "";
  (state.config.preset_groups[lang] || []).forEach(n => presetSel.add(new Option(n, n)));
  if (select) presetSel.value = select;
}

// ── transport ────────────────────────────────────────────────────────────────
function wireTransport() {
  const v = $("video"), seek = $("seek");
  $("playBtn").onclick = () => v.paused ? v.play() : v.pause();
  v.onplay = () => { $("playBtn").textContent = "⏸"; };
  v.onpause = () => { $("playBtn").textContent = "▶"; };
  v.ontimeupdate = () => {
    if (!v.duration) return;
    seek.value = Math.round((v.currentTime / v.duration) * 1000);
    $("timeLabel").textContent = `${v.currentTime.toFixed(1)} / ${v.duration.toFixed(1)}`;
    WordEditor.highlight(v.currentTime, false);   // covers paused seeks
  };
  // timeupdate only fires ~4×/s; a light interval keeps the follow-highlight
  // snappy while playing (autoscroll only then, so it never fights the user).
  setInterval(() => { if (!v.paused && v.duration) WordEditor.highlight(v.currentTime, true); }, 120);
  seek.oninput = () => { if (v.duration) v.currentTime = (seek.value / 1000) * v.duration; };
  v.onresize = () => painter.resize();
  // Durable listeners (survive the per-mode onloadedmetadata assignment):
  v.addEventListener("loadedmetadata", () => {
    seek.value = 0;
    $("timeLabel").textContent = `0.0 / ${v.duration.toFixed(1)}`;
    // Orient the review split around the picture: portrait video (or the
    // audio-only 9:16 stage) → editor beside it; landscape → editor below.
    const portrait = state.audioOnly || (v.videoWidth ? v.videoHeight >= v.videoWidth : true);
    $("reviewSplit").classList.toggle("side", portrait);
    $("reviewSplit").classList.toggle("stack", !portrait);
    painter.resize();
  });
  v.addEventListener("error", () => {
    const codes = { 1: "aborted", 2: "network error", 3: "decode failed", 4: "format unsupported" };
    setStatus("Video failed to load: " + (codes[v.error?.code] || "unknown")
      + " (" + (v.currentSrc || "no src") + ")", "error");
  });
}

function wireButtons() {
  $("browseBtn").onclick = browse;
  $("transcribeBtn").onclick = transcribe;
  $("copyPromptBtn").onclick = () => {
    navigator.clipboard?.writeText($("promptBox").value);
    setStatus("Prompt copied", "ok");
  };
  $("applyJsonBtn").onclick = applyJson;
  $("copyWordsBtn").onclick = () => {
    navigator.clipboard?.writeText(JSON.stringify(state.words, null, 1));
    setStatus("Words JSON copied", "ok");
  };
  $("renderBtn").onclick = render;
  $("truePreviewBtn").onclick = truePreview;
  $("savePresetBtn").onclick = savePreset;
  $("deletePresetBtn").onclick = deletePreset;
  $("resetPresetsBtn").onclick = resetPresets;
  $("previewMode").onclick = () => { if (state.trueMode && state.proxyUrl) setLive(state.proxyUrl); };
}

// ── SSE job helper ───────────────────────────────────────────────────────────
function runJob(url, body, { onProgress, onDone, onError }) {
  fetch(url, { method: "POST", headers: json(), body: JSON.stringify(body) })
    .then(r => r.json())
    .then(({ job_id, error }) => {
      if (error) return onError(error);
      const es = new EventSource(`/api/jobs/${job_id}/events`);
      es.onmessage = ev => {
        const d = JSON.parse(ev.data);
        if (d.type === "progress") onProgress && onProgress(d);
        else if (d.type === "done") { es.close(); onDone(d.result); }
        else if (d.type === "error") { es.close(); onError(d.message); }
      };
      es.onerror = () => { es.close(); onError("connection lost"); };
    })
    .catch(e => onError(String(e)));
}

// ── misc ─────────────────────────────────────────────────────────────────────
function saveAppSettings() {
  const lcfg = state.config?.languages[$("languageSel").value];
  fetch("/api/preferences", {
    method: "PUT", headers: json(), body: JSON.stringify({
      last_language: $("languageSel").value,
      last_model: $("modelSel").value,
      last_preset: state.presetName,
      last_font: state.style?.font_path || "",
      align: $("alignChk").checked,
      emoji: $("emojiChk").checked,
    })
  }).catch(() => {});
}

function json() { return { "Content-Type": "application/json" }; }
function setStatus(msg, kind) {
  const p = $("statusPill");
  // Long errors (ffmpeg stderr) don't fit a pill: show the tail, log the rest.
  if (kind === "error") {
    console.error(msg);
    $("renderMsg").textContent = msg;
    if (msg.length > 120) msg = "…" + msg.slice(-117);
  }
  p.textContent = msg;
  p.title = msg;
  p.className = "status-pill" + (kind ? " " + kind : "");
  activateStep();
}
function setBusy(b) {
  ["transcribeBtn", "renderBtn", "truePreviewBtn", "applyJsonBtn", "browseBtn"]
    .forEach(id => $(id).disabled = b);
}
function setProgress(cur, total) {
  const bar = $("progressBar"); bar.classList.remove("hidden");
  $("progressFill").style.width = total ? (cur / total * 100) + "%" : "0%";
}
function hideProgress() { $("progressBar").classList.add("hidden"); $("progressFill").style.width = "0%"; }

function activateStep() {
  const steps = document.querySelectorAll(".step");
  let active = 1;
  if (state.inputPath) active = 2;
  if (state.words.length) active = state.phrases.length ? 4 : 3;
  steps.forEach(s => s.classList.toggle("active", +s.dataset.step <= active));
}

init();
