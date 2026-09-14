"""Retitle a Premiere text layer across a whole timeline, via XML.

Essential Graphics text can't be authored from scratch in FCP7 XML: Premiere
stores it as an opaque "Source Text" blob. But one exported text clip is a
perfect template. The blob is a FlatBuffer in which the string sits behind a
single 4-byte length prefix and nothing else refers to its length — so a new
headline of the *same byte length* can be written in place, and every font,
size, colour and position setting carries over untouched. Shorter headlines
are padded with trailing spaces (invisible on left-aligned text); longer ones
are refused, which is also the honest limit of the bar they sit in.

    python -m clipper.headlines headlines.json

headlines.json:
    {"name": "...", "template": "<Premiere-exported XML>", "out": "<xml>",
     "track": 3,                                    # optional: template's video track
     "headlines": [[start_seconds, "TEXT"], ...]}   # each runs to the next

Each distinct text gets its own blob hash: Premiere caches Source Text by
hash, and reusing the template's would make every clip show the original.
"""
import base64
import copy
import json
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .timebase import Timebase

FPS = Timebase(30, ntsc=True)
TICKS_PER_SECOND = 254016000000


def _source_text(effect):
    return next(p for p in effect.findall("parameter") if p.findtext("name") == "Source Text")


def find_template(root, track=None):
    """(sequence, track index, clipitem, effect, blob, text) of the first text
    clip — on video track ``track`` (1-based) when given."""
    for seq in root.iter("sequence"):
        for ti, tr in enumerate(seq.findall("media/video/track"), start=1):
            if track is not None and ti != track:
                continue
            for ci in tr.findall("clipitem"):
                for eff in ci.iter("effect"):
                    if eff.findtext("effectid") != "GraphicAndType":
                        continue
                    val = _source_text(eff).findtext("value")
                    if val:
                        return seq, ti, ci, eff, base64.b64decode(val), eff.findtext("name")
    raise ValueError("no Essential Graphics text clip with a Source Text value in the template")


def retext(blob: bytes, old: str, new: str) -> bytes:
    """Swap ``old`` for ``new`` inside the blob, keeping its byte length."""
    ob, nb = old.encode("utf-8"), new.encode("utf-8")
    at = blob.find(len(ob).to_bytes(4, "little") + ob)
    if at < 0 or blob.count(ob) != 1:
        raise ValueError(f"template text {old!r} not found exactly once behind its length prefix")
    if len(nb) > len(ob):
        raise ValueError(f"{new!r} is {len(nb)} bytes; the template holds {len(ob)}")
    nb = nb + b" " * (len(ob) - len(nb))
    at += 4
    return blob[:at] + nb + blob[at + len(ob):]


def _hash() -> str:
    h = uuid.uuid4().hex
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def build(spec: dict) -> Path:
    root = ET.parse(spec["template"]).getroot()
    tseq, track_index, tclip, teff, blob, old = find_template(root, spec.get("track"))
    clip_rate = int(tclip.findtext("rate/timebase"))       # the clip's own in/out rate
    in0 = int(tclip.findtext("in"))
    total = int(tseq.findtext("duration"))

    heads = sorted(spec["headlines"])
    for _, text in heads:  # fail before writing anything
        retext(blob, old, text)

    out = ET.Element("xmeml", version="5")
    b = ET.SubElement(out, "bin")
    ET.SubElement(b, "name").text = spec["name"]
    seq = ET.SubElement(ET.SubElement(b, "children"), "sequence", id="headlines-seq")
    ET.SubElement(seq, "uuid").text = str(uuid.uuid5(uuid.NAMESPACE_URL, spec["name"]))
    ET.SubElement(seq, "duration").text = str(total)
    seq.append(copy.deepcopy(tseq.find("rate")))
    ET.SubElement(seq, "name").text = spec["name"]
    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    video.append(copy.deepcopy(tseq.find("media/video/format")))
    tracks = [ET.SubElement(video, "track") for _ in range(track_index)]
    target = tracks[-1]

    hashes = {}
    file_id = tclip.find("file").get("id")
    # Premiere defines a file once per export, so the template clip may carry
    # only a bare reference (``<file id="file-17"/>``) to a definition on some
    # other track. The new document has no such clip: fetch the full one.
    full_file = next((f for f in root.iter("file") if f.get("id") == file_id and len(f)), None)
    if full_file is None:
        raise ValueError(f"no full definition of {file_id} anywhere in the template")
    for n, (start, text) in enumerate(heads):
        s = FPS.to_frames(start)
        e = FPS.to_frames(heads[n + 1][0]) if n + 1 < len(heads) else total
        c = copy.deepcopy(tclip)
        c.set("id", f"headline-{n + 1}")
        # In/out in the clip's own rate; each clip takes a fresh stretch of the
        # generator's (12-hour) media, as Premiere does with a razored graphic.
        length = round((e - s) * clip_rate / float(FPS.fps))
        cin = in0 + sum(round((FPS.to_frames(heads[k + 1][0]) - FPS.to_frames(heads[k][0])) * clip_rate / float(FPS.fps))
                        for k in range(n))
        for tag, val in (("start", s), ("end", e), ("in", cin), ("out", cin + length)):
            c.find(tag).text = str(val)
        tpf = TICKS_PER_SECOND // clip_rate
        for tag, val in (("pproTicksIn", cin * tpf), ("pproTicksOut", (cin + length) * tpf)):
            if c.find(tag) is not None:
                c.find(tag).text = str(val)
        # The file is defined once, on the first clip, and referenced after.
        f = c.find("file")
        idx = list(c).index(f)
        c.remove(f)
        c.insert(idx, copy.deepcopy(full_file) if n == 0 else ET.Element("file", id=file_id))
        eff = next(x for x in c.iter("effect") if x.findtext("effectid") == "GraphicAndType")
        eff.find("name").text = text
        st = _source_text(eff)
        if text in hashes:  # same text again: reference the blob by hash only
            st.find("hash").text = hashes[text]
            v = st.find("value")
            if v is not None:
                st.remove(v)
        else:
            hashes[text] = st.find("hash").text = _hash()
            v = st.find("value")
            if v is None:
                v = ET.SubElement(st, "value")
            v.text = base64.b64encode(retext(blob, old, text)).decode("ascii")
        target.append(c)
    for tr in tracks:
        ET.SubElement(tr, "enabled").text = "TRUE"
        ET.SubElement(tr, "locked").text = "FALSE"

    ET.indent(out, space="\t")
    path = Path(spec["out"])
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                    + ET.tostring(out, encoding="unicode"), encoding="utf-8")
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(build(spec))


if __name__ == "__main__":
    main()
