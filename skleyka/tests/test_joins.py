from skleyka.timeline import mark_joins


def shot(start, end, src, angle):
    return {"start": start, "end": end, "in_point": src, "out_point": src + end - start, "angle": angle}


def test_join_kinds():
    shots = mark_joins([
        shot(0, 2, 10, 0),
        shot(2, 4, 12, 1),   # source continues, angle changes
        shot(4, 6, 20, 2),   # source jumps, angle changes: hidden trim
        shot(6, 8, 30, 2),   # source jumps, same angle: jump cut
        shot(8, 9, 32, 2),   # continuous, same angle
        shot(10, 11, 40, 0), # gap before it
    ])
    assert [s["join"] for s in shots] == [None, "switch", "trim", "jump", "same", None]
