// Batch renderer for the clipper engine: node render.mjs <jobs.json>
//
// jobs.json: {"jobs": [{template, props, width, height, fps, frames, out, still?,
//                       proResProfile?, stillOnly?}]}
//
// `proResProfile` defaults to "4444" with alpha (the shorts' overlays); opaque
// long-form panels pass "standard"/"hq", or `codec: "h264"` (+ `crf`).
// `stillOnly` renders just the still to `out` (a PNG) and no video.
//
// Bundles once and renders every job against that bundle — bundling is most of
// the cost of a single `npx remotion render`, and a b-roll pass renders a dozen
// graphics at a time. Size, rate and length come from the job, not the
// composition: they are the clip's sequence settings and the exact frame count
// of the b-roll entry the file will fill, so the overlay lands frame-for-frame.
//
// Output is one JSON line per job on stdout, then a final {"done": true}. Remotion's
// own progress goes to stderr so stdout stays machine-readable.
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));

const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");

const serveUrl = await bundle({
  entryPoint: path.join(here, "src", "index.ts"),
  publicDir: path.join(here, "public"),
  onProgress: () => {},
});

let failed = 0;
for (const job of spec.jobs) {
  try {
    const base = await selectComposition({ serveUrl, id: job.template, inputProps: job.props });
    const composition = {
      ...base,
      width: job.width,
      height: job.height,
      fps: job.fps,
      durationInFrames: job.frames,
      props: job.props,
    };
    if (job.stillOnly) {
      const frame = Math.min(job.frames - 1, Math.max(0, Math.round(job.frames * (job.stillAt ?? 0.6))));
      await renderStill({ composition, serveUrl, inputProps: job.props, output: job.out, frame, imageFormat: "png", overwrite: true });
      emit({ ok: true, out: job.out, still: job.out });
      continue;
    }
    if (job.codec === "h264") {
      // Opaque panels: an hour of long-form graphics as ProRes is tens of GB.
      await renderMedia({
        composition,
        serveUrl,
        inputProps: job.props,
        codec: "h264",
        crf: job.crf ?? 15,
        concurrency: job.concurrency ?? null,
        pixelFormat: "yuv420p",
        imageFormat: "jpeg",
        jpegQuality: 95,
        outputLocation: job.out,
        overwrite: true,
      });
    } else {
      const profile = job.proResProfile ?? "4444";
      const alpha = profile === "4444" || profile === "4444-xq";
      await renderMedia({
        composition,
        serveUrl,
        inputProps: job.props,
        codec: "prores",
        proResProfile: profile,
        ...(alpha ? { imageFormat: "png" } : { imageFormat: "jpeg", jpegQuality: 95 }),
        pixelFormat: alpha ? "yuva444p10le" : "yuv422p10le",
        outputLocation: job.out,
        overwrite: true,
      });
    }
    let still = null;
    if (job.still) {
      // Past the entrance, before the exit: the graphic fully on screen.
      const frame = Math.min(job.frames - 1, Math.max(0, Math.round(job.frames * 0.6)));
      await renderStill({
        composition,
        serveUrl,
        inputProps: job.props,
        output: job.still,
        frame,
        imageFormat: "png",
        overwrite: true,
      });
      still = job.still;
    }
    emit({ ok: true, out: job.out, still });
  } catch (e) {
    failed += 1;
    emit({ ok: false, out: job.out, error: String(e && e.stack ? e.stack : e).slice(0, 2000) });
  }
}
emit({ done: true, failed });
process.exit(failed ? 1 : 0);
