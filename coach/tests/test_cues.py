from coach.cues import Box, CueThrottle, Direction, Point, cue_for, cue_line


def test_directions_and_arrival():
    wide = Box(100, 100, 40, 20)
    assert cue_for(Point(0, 110), wide) is Direction.RIGHT
    assert cue_for(Point(200, 110), wide) is Direction.LEFT
    assert cue_for(Point(120, 0), wide) is Direction.DOWN
    assert cue_for(Point(120, 200), wide) is Direction.UP
    assert cue_for(wide.center, wide) is Direction.ARRIVED
    assert cue_for(Point(110, 105), wide) is Direction.ARRIVED


def test_tie_is_vertical():
    box = Box(30, 30, 2, 2)
    assert cue_for(Point(0, 0), box, arrive_px=0) is Direction.DOWN


def test_cue_lines_are_one_breath():
    assert cue_line(Direction.RIGHT, repeat=False) == "Đưa chuột qua phải."
    assert cue_line(Direction.RIGHT, repeat=True) == "Qua phải."
    assert cue_line(Direction.ARRIVED, repeat=False) == "Tới rồi."


def test_throttle_blocks_a_burst():
    throttle = CueThrottle(0.8)
    assert throttle.allow(0.0)
    assert not throttle.allow(0.5)
    assert throttle.allow(0.8)
