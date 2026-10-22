from skleyka.anchors import Segment, anchor, relocate, segments, seq_at, src_at

F = 10  # one "frame" in these tests


def cut(track, start, end, src, disabled=0):
    return [track, str(start), str(end), str(src), str(src + end - start), disabled]


def test_segments_merge_and_layering():
    segs = segments([
        cut(0, 0, 100, 1000),
        cut(0, 100, 200, 1100),   # continues the same source: merged
        cut(1, 50, 80, 5000),     # higher track covers 50-80
        cut(0, 200, 300, 2000),
    ])
    assert segs == [
        Segment(0, 50, 1000, 0),
        Segment(50, 80, 5000, 1),
        Segment(80, 200, 1080, 0),
        Segment(200, 300, 2000, 0),
    ]


def test_disabled_clips_are_not_on_screen():
    segs = segments([cut(0, 0, 100, 1000), cut(1, 0, 100, 9000, disabled=1)])
    assert segs == [Segment(0, 100, 1000, 0)]


def test_src_and_seq_round_trip():
    segs = segments([cut(0, 0, 100, 1000), cut(0, 100, 200, 3000)])
    assert src_at(segs, 150) == 3050
    assert seq_at(segs, 3050) == 150
    assert seq_at(segs, 2000) is None  # never in the edit
    assert src_at(segs, 250) is None


def test_reused_material_resolves_near():
    segs = segments([cut(0, 0, 100, 1000), cut(0, 500, 600, 1000)])
    assert seq_at(segs, 1050, near=540) == 550
    assert seq_at(segs, 1050, near=10) == 50


def test_relocate_after_ripple_trim_before_overlay():
    before = segments([cut(0, 0, 100, 1000), cut(0, 100, 300, 1100)])
    a = anchor(before, 150, 200, F)
    assert a == {"src_start": 1150, "src_last": 1190}
    # The user removes 30 ticks of material near the start: everything after shifts left.
    after = segments([cut(0, 0, 70, 1000), cut(0, 70, 270, 1100)])
    assert relocate(after, a, 150, 200, F) == {"status": "moved", "start": 120, "end": 170}


def test_relocate_flags_trim_inside_and_orphans():
    before = segments([cut(0, 0, 300, 1000)])
    a = anchor(before, 100, 200, F)
    # Material from source 1140-1160 is cut out, inside the overlay's span.
    inside = segments([cut(0, 0, 140, 1000), cut(0, 140, 280, 1160)])
    assert relocate(inside, a, 100, 200, F)["status"] == "span_changed"
    # The overlay's first moment is cut out entirely.
    gone = segments([cut(0, 0, 100, 1000), cut(0, 100, 250, 1150)])
    assert relocate(gone, a, 100, 200, F)["status"] == "orphaned"
    # Nothing changed.
    assert relocate(before, a, 100, 200, F) == {"status": "ok", "start": 100, "end": 200}
