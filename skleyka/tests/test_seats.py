from skleyka.occupancy import face_for


def face(cx):
    return {"x": cx - 0.03, "y": 0.2, "w": 0.06, "h": 0.12, "score": 0.9}


THREE = [face(0.22), face(0.52), face(0.71)]


def test_all_seats_visible_go_by_order():
    assert face_for(THREE, "left") is THREE[0]
    assert face_for(THREE, "centre") is THREE[1]
    assert face_for(THREE, "center") is THREE[1]
    assert face_for(THREE, "right") is THREE[2]


def test_tight_shot_uses_the_nearest_usual_place():
    two = [face(0.3), face(0.75)]           # a split screen: left and right seats
    assert face_for(two, "right") is two[1]
    assert face_for(two, "left") is two[0]
    assert face_for([face(0.5)], "centre")["x"] == 0.47


def test_unknown_seat_or_no_faces():
    assert face_for(THREE, "middle") is None
    assert face_for([], "left") is None
