from skleyka.angles import jump_risks
from skleyka.timeline import mark_joins


def shot(start, end, src, angle):
    return {"start": start, "end": end, "in_point": src, "out_point": src + end - start, "angle": angle}


PROG = mark_joins([
    shot(0, 2, 10, 1),
    shot(2, 4, 20, 0),   # trim against the previous cut (source jumps 12 -> 20)
    shot(4, 6, 22, 2),   # plain switch
    shot(6, 8, 30, 3),   # trim against the previous cut
])


def test_whole_cut_cannot_match_across_a_trim():
    assert jump_risks(PROG, 1, 1, whole_cut=True)        # same as the cut before the trim
    assert not jump_risks(PROG, 1, 3, whole_cut=True)    # any other angle is fine
    assert not jump_risks(PROG, 1, 2, whole_cut=True)    # matching across a plain switch is fine


def test_next_cut_across_a_trim_counts_too():
    assert jump_risks(PROG, 2, 3, whole_cut=True)        # cut 3 is angle 3 across a trim
    assert jump_risks(PROG, 2, 3, whole_cut=False)       # also when switching only the tail


def test_tail_switch_ignores_the_previous_join():
    assert not jump_risks(PROG, 1, 1, whole_cut=False)   # the head keeps angle 0
