/* Clipper-project mode for the caption editor.
 *
 * The single-file flow is: browse to a file, transcribe, paste refined JSON,
 * export to a path you type. A clipper episode needs none of that — the words
 * are already aligned, the style is already the project's preset, and the output
 * path is already baked into an exported Premiere XML. So this module swaps the
 * front of the workflow for a project → clip picker and points the Export button
 * at the overlay Premiere is linked to.
 *
 * The rest of the app is untouched: once a clip is open, `state.words` and
 * `state.style` are the same shapes the normal flow produces, so the word
 * editor, canvas painter and preset panel all work without knowing about any of
 * this. `active()` is how app.js decides which render path a click means.
 */

const Clipper = (() => {
  let current = null;         // {projectId, clipId, title, movName, duration}
  let clips = [];

  // ── boot ───────────────────────────────────────────────────────────────────
  async function init(cfg) {
    const card = $("clipperCard");
    if (!cfg.clipper || !cfg.clipper.available) {
      // No clipper in this checkout — hide the card rather than showing a
      // picker that can only ever fail.
      card.classList.add("hidden");
      if (cfg.clipper && cfg.clipper.error) {
        console.info("clipper unavailable:", cfg.clipper.error);
      }
      return;
    }
    $("clipperProject").onchange = () => openProject($("clipperProject").value);
    $("clipperRefresh").onclick = () => {
      const pid = $("clipperProject").value;
      pid ? openProject(pid) : loadProjects();
    };
    $("clipperReveal").onclick = reveal;
    await loadProjects();
  }

  async function loadProjects() {
    const r = await fetch("/api/clipper/projects").then(r => r.json());
    const sel = $("clipperProject");
    sel.innerHTML = "";
    sel.add(new Option("— select an episode —", ""));
    (r.projects || []).forEach(p => {
      sel.add(new Option(`${p.name} (${p.n_clips})`, p.id));
    });
    $("clipperClips").innerHTML =
      `<div class="muted small">${(r.projects || []).length} project(s) registered</div>`;
  }

  // ── clip list ──────────────────────────────────────────────────────────────
  async function openProject(projectId) {
    if (!projectId) { clips = []; $("clipperClips").innerHTML = ""; return; }
    setStatus("Loading project…", "busy");
    const r = await fetch(`/api/clipper/projects/${encodeURIComponent(projectId)}/clips`)
      .then(r => r.json());
    if (r.error) return setStatus(r.error, "error");
    clips = r.clips || [];
    renderList(projectId);
    setStatus(`${r.project.name} — ${clips.length} clips`, "ok");
  }

  function renderList(projectId) {
    const box = $("clipperClips");
    box.innerHTML = "";
    clips.forEach(c => {
      const row = document.createElement("div");
      row.className = "clip-row"
        + (current && current.clipId === c.id ? " active" : "");
      // The badges are the whole point of the list: which clips still need
      // attention, without opening each one.
      const badges = [];
      if (!c.polished) badges.push('<span class="badge warn">raw</span>');
      if (c.stale) badges.push('<span class="badge warn">stale</span>');
      if (c.rendered && !c.stale) badges.push('<span class="badge ok">rendered</span>');
      if (!c.rendered) badges.push('<span class="badge">no overlay</span>');
      row.innerHTML =
        `<div class="clip-title">${escapeHtml(c.title)}</div>
         <div class="clip-meta"><span class="mono small">${fmt(c.duration)}</span>
         ${badges.join(" ")}</div>`;
      row.onclick = () => openClip(projectId, c.id);
      box.appendChild(row);
    });
  }

  const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const escapeHtml = s => String(s).replace(/[&<>"]/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

  // ── open one clip ──────────────────────────────────────────────────────────
  async function openClip(projectId, clipId) {
    setStatus("Opening clip…", "busy");
    const r = await fetch(
      `/api/clipper/projects/${encodeURIComponent(projectId)}/clips/${encodeURIComponent(clipId)}`
    ).then(r => r.json());
    if (r.error) return setStatus(r.error, "error");

    current = {
      projectId, clipId,
      title: r.clip.title,
      duration: r.clip.duration,
      movName: r.mov_path.split(/[\\/]/).pop(),
      movPath: r.mov_path,
    };

    // Words and style land in the same globals the single-file flow uses, so
    // everything downstream (word editor, painter, preset panel) just works.
    state.words = r.words.map(w => ({
      text: w.text, start: +w.start, end: +w.end, line_break: !!w.line_break,
    }));
    state.style = r.style;
    state.style.font_path = fontLabelFor(r.style.font_path);
    state.presetName = r.preset;
    state.dirty = false;

    Editor.build($("editorFields"), state.style, state.fonts, onStyleChange);
    painter.setStyle(state.style);
    painter.loadFont(state.style.font_path);

    $("promptBox").value = r.prompt || "";
    showWordEditor();
    relayout();
    renderList(projectId);
    updateExportCard();

    setStatus(
      `${r.clip.title} — ${state.words.length} words`
      + (r.polished ? "" : " (unpolished: remapped from the master transcript)"),
      "ok");

    loadPreview(projectId, clipId);
  }

  // The clip's audio to scrub against — timing captions against silence is
  // guesswork. Audio-only by design (see the server route for why), so the stage
  // renders captions on black, which is the same thing the single-file flow does
  // for a podcast mp3.
  function loadPreview(projectId, clipId) {
    fetch(`/api/clipper/projects/${encodeURIComponent(projectId)}/clips/${encodeURIComponent(clipId)}/preview`,
          { method: "POST", headers: json(), body: "{}" })
      .then(r => r.json())
      .then(res => {
        if (res.url) return usePreview(res.url);
        if (res.error) return setStatus("Preview: " + res.error, "error");
        setStatus("Cutting clip audio…", "busy");
        const es = new EventSource(`/api/jobs/${res.job_id}/events`);
        es.onmessage = ev => {
          const d = JSON.parse(ev.data);
          if (d.type === "done") {
            es.close();
            usePreview(d.result.url);
            setStatus("Clip audio ready", "ok");
          } else if (d.type === "error") {
            es.close();
            // A missing preview is survivable — the words are still editable.
            setStatus("Preview failed: " + d.message, "error");
          }
        };
      });
  }

  function usePreview(url) {
    state.proxyUrl = url;
    state.audioOnly = true;
    $("stage").classList.add("audio-only");
    setLive(url);
  }

  function updateExportCard() {
    const on = !!current;
    $("clipperTarget").classList.toggle("hidden", !on);
    $("outputPath").classList.toggle("hidden", on);
    if (on) {
      $("clipperTarget").innerHTML =
        `Overwrites <span class="mono">${escapeHtml(current.movName)}</span>
         <div class="muted small">Premiere re-reads it on next refresh — no re-export.</div>`;
      $("renderBtn").textContent = "Render → overwrite overlay";
    } else {
      $("renderBtn").textContent = "Export ProRes .mov";
    }
  }

  // ── render in place ────────────────────────────────────────────────────────
  function renderInPlace() {
    if (!current) return;
    if (!state.words.length) return setStatus("Nothing to render", "error");
    askNotifyPermission();
    setBusy(true); setStatus("Rendering overlay…", "busy");
    const { projectId, clipId } = current;
    runJob(
      `/api/clipper/projects/${encodeURIComponent(projectId)}/clips/${encodeURIComponent(clipId)}/render`,
      { words: state.words, style: state.style },
      {
        onProgress: d => setProgress(d.current, d.total),
        onDone: r => {
          setBusy(false); hideProgress();
          if (r.replaced === false) {
            // Rendered fine, but couldn't take the target path.
            setStatus(r.note, "error");
            $("renderMsg").textContent = "⚠ " + r.note;
            notify("Overlay locked", r.note);
          } else {
            setStatus(`Overwrote ${current.movName}`, "ok");
            $("renderMsg").textContent = "✓ " + r.output;
            notify("Overlay re-rendered", current.title);
          }
          openProject(projectId);      // refresh badges (rendered / no longer stale)
        },
        onError: e => {
          setBusy(false); hideProgress();
          setStatus("Render failed: " + e, "error");
          notify("Render failed", String(e).slice(0, 200));
        },
      });
  }

  async function reveal() {
    const pid = $("clipperProject").value;
    if (!pid) return setStatus("Select a project first", "error");
    const r = await fetch(`/api/clipper/projects/${encodeURIComponent(pid)}/reveal`,
                          { method: "POST" }).then(r => r.json());
    if (r.error) setStatus(r.error, "error");
  }

  // Leaving clipper mode hands the Export button back to the single-file flow.
  function clear() { current = null; updateExportCard(); }

  return { init, active: () => current, renderInPlace, clear };
})();
