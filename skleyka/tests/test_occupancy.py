from skleyka.occupancy import COLS, ROWS, body_of, free_rects, occupancy, place


FACE_LEFT = {"x": 0.10, "y": 0.25, "w": 0.06, "h": 0.12, "score": 0.9}
FACE_RIGHT = {"x": 0.80, "y": 0.22, "w": 0.06, "h": 0.12, "score": 0.9}


def test_body_grows_from_the_face_and_stays_in_frame():
    b = body_of(FACE_LEFT)
    assert b["x"] < FACE_LEFT["x"]            # shoulders wider than the face
    assert b["y"] < FACE_LEFT["y"]            # a little above the head
    assert b["y"] + b["h"] > 0.7              # down to the table
    edge = body_of(FACE_LEFT | {"x": 0.01})
    assert edge["x"] == 0.0                   # clipped at the frame edge


def test_two_people_leave_the_middle_free():
    grid = occupancy([FACE_LEFT, FACE_RIGHT])
    assert grid.shape == (ROWS, COLS)
    rects = free_rects(grid)
    biggest = rects[0]
    assert biggest["x"] > 0.2 and biggest["x"] + biggest["w"] < 0.8
    assert biggest["w"] * biggest["h"] > 0.15


def test_place_beside_the_speaker_at_head_height():
    grid = occupancy([FACE_LEFT, FACE_RIGHT])
    spots = place(grid, w=0.25, h=0.15, near=FACE_LEFT)
    assert spots
    best = spots[0]
    assert best["x"] > 0.2                                     # to the right of the left person
    assert abs((best["y"] + best["h"] / 2) - 0.31) < 0.12       # roughly at head height


def test_nothing_fits_returns_empty():
    grid = occupancy([FACE_LEFT, FACE_RIGHT])
    assert place(grid, w=0.9, h=0.9) == []
