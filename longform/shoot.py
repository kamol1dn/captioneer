"""Screenshot web pages for the long-form panels.

    python -m longform.shoot <out.png> <url> [--width 1440] [--height 1800] [--scale 2]
                    [--mark "exact phrase"]... [--hide "css selector"]...

Headless installed Chrome with a fresh profile (no logins). Fixed/sticky
overlays — cookie bars, consent walls, newsletter popups, sticky headers — are
hidden (never clicked), so nothing is accepted on anyone's behalf.

Every --mark phrase is located on the page and its line boxes are written to
<out>.json as fractions of the image, ready to become PShot marks.
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HIDE_JS = r"""
(extra) => {
  const rx = /(cookie|consent|gdpr|onetrust|didomi|sp_message|truste|newsletter|paywall|interstitial|ad-slot|advert)/i;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    const tag = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
    if (cs.position === 'fixed' || cs.position === 'sticky') {
      el.style.setProperty('display', 'none', 'important');
    } else if (rx.test(tag) && !el.querySelector('article, h1')) {
      el.style.setProperty('display', 'none', 'important');
    }
  }
  for (const sel of extra) document.querySelectorAll(sel).forEach(e => e.style.setProperty('display','none','important'));
  for (const el of [document.documentElement, document.body]) {
    el.style.setProperty('overflow', 'auto', 'important');
  }
}
"""

# Line boxes of the first occurrence of `phrase` in the visible text, in page
# pixels. Walks text nodes and builds a Range across them, so a phrase may
# span links/emphasis.
FIND_JS = r"""
(phrase) => {
  const norm = s => s.replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/\s+/g, ' ');
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentElement && n.parentElement.offsetParent !== null) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
  });
  const nodes = []; let text = '';
  const starts = [];
  while (walker.nextNode()) { const n = walker.currentNode; starts.push(text.length); nodes.push(n); text += n.data; }
  const flat = norm(text); // same length as text: replacements are 1:1 except whitespace runs
  // Build a map from normalised index back to raw index.
  const map = []; let raw = 0; let out = '';
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const isWs = /\s/.test(c);
    if (isWs && out.endsWith(' ')) continue;
    map.push(i); out += isWs ? ' ' : norm(c);
  }
  const at = out.toLowerCase().indexOf(norm(phrase).toLowerCase());
  if (at < 0) return null;
  const a = map[at], b = map[at + norm(phrase).length - 1] + 1;
  const locate = (idx) => { let k = 0; while (k + 1 < starts.length && starts[k + 1] <= idx) k++; return [nodes[k], idx - starts[k]]; };
  const r = document.createRange();
  const [sn, so] = locate(a); const [en, eo] = locate(b - 1);
  r.setStart(sn, so); r.setEnd(en, eo + 1);
  const rects = [];
  for (const q of r.getClientRects()) {
    if (q.width < 2 || q.height < 2) continue;
    const last = rects[rects.length - 1];
    // Merge fragments on the same line.
    if (last && Math.abs(last.top - q.top) < q.height * 0.5) {
      const l = Math.min(last.left, q.left), rr = Math.max(last.left + last.width, q.right);
      last.left = l; last.width = rr - l; last.height = Math.max(last.height, q.height);
    } else rects.push({ left: q.left + scrollX, top: q.top + scrollY, width: q.width, height: q.height });
  }
  // The paragraph the phrase sits in, so a crop can keep whole lines.
  let el = r.commonAncestorContainer;
  if (el.nodeType === 3) el = el.parentElement;
  while (el && el.parentElement && getComputedStyle(el).display.startsWith('inline')) el = el.parentElement;
  const box = el.getBoundingClientRect();
  return { rects, block: { left: box.left + scrollX, width: box.width } };
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("url")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1800)
    ap.add_argument("--scale", type=float, default=2)
    ap.add_argument("--wait", type=float, default=3.0)
    ap.add_argument("--mark", action="append", default=[])
    ap.add_argument("--hide", action="append", default=[])
    ap.add_argument("--start", default=None, help="phrase: crop so the page starts a bit above it")
    a = ap.parse_args()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(viewport={"width": a.width, "height": a.height},
                            device_scale_factor=a.scale, locale="en-US",
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
        page = ctx.new_page()
        try:
            page.goto(a.url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("goto:", e, file=sys.stderr)
        page.wait_for_timeout(int(a.wait * 1000))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        page.evaluate(HIDE_JS, a.hide)
        page.wait_for_timeout(400)

        top = 0
        if a.start:
            found = page.evaluate(FIND_JS, a.start)
            if found and found["rects"]:
                top = max(0, int(found["rects"][0]["top"] - 160))
        clip = {"x": 0, "y": top, "width": a.width, "height": a.height}
        page.screenshot(path=a.out, clip=clip, full_page=True)
        marks = []
        for ph in a.mark:
            found = page.evaluate(FIND_JS, ph)
            if not found:
                print(f"mark not found: {ph!r}", file=sys.stderr)
                marks.append({"phrase": ph, "rects": []})
                continue
            rs, blk = found["rects"], found["block"]
            marks.append({"phrase": ph, "rects": [
                {"x": round(r["left"] / a.width, 4), "y": round((r["top"] - top) / a.height, 4),
                 "w": round(r["width"] / a.width, 4), "h": round(r["height"] / a.height, 4)} for r in rs],
                "block": {"x": round(blk["left"] / a.width, 4), "w": round(blk["width"] / a.width, 4)}})
        meta = {"url": a.url, "title": page.title(), "imgW": int(a.width * a.scale),
                "imgH": int(a.height * a.scale), "top": top, "marks": marks}
        Path(a.out).with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        Path(a.out).with_suffix(".txt").write_text(page.evaluate("document.body.innerText"), encoding="utf-8")
        print(json.dumps({"title": meta["title"], "marks": [(m["phrase"][:40], len(m["rects"])) for m in marks]}))
        b.close()


if __name__ == "__main__":
    main()
