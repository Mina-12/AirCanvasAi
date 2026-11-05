from pathlib import Path

import cv2
import numpy as np

from drawing_engine import DrawingEngine


def test_draws_stroke_between_points():
    engine = DrawingEngine(100, 80)
    engine.add_point((10, 10), (255, 0, 0), 6)
    engine.add_point((40, 10), (255, 0, 0), 6)
    assert np.any(engine.canvas[7:14, 20:30] != engine.background)


def test_interruption_starts_new_stroke_without_connector():
    engine = DrawingEngine(100, 80)
    engine.add_point((10, 10), thickness=4)
    engine.end_stroke()
    engine.add_point((80, 60), thickness=4)
    assert not np.any(engine.canvas[30:45, 35:55] != engine.background)


def test_draws_again_after_interruption_as_a_separate_stroke():
    engine = DrawingEngine(100, 80)
    engine.add_interpolated_point((10, 10), thickness=4)
    engine.add_interpolated_point((20, 10), thickness=4)
    engine.end_stroke()  # the app calls this when the gesture is released or hand disappears
    engine.add_interpolated_point((80, 60), thickness=4)
    engine.add_interpolated_point((90, 60), thickness=4)
    assert len(engine._undo) == 1  # second stroke remains active until its release
    assert not np.any(engine.canvas[30:45, 35:55] != engine.background)


def test_interpolated_stroke_has_no_gaps_on_fast_movement():
    engine = DrawingEngine(100, 80)
    engine.add_interpolated_point((10, 20), (255, 0, 0), 4)
    engine.add_interpolated_point((90, 20), (255, 0, 0), 4)
    assert np.all(np.any(engine.canvas[18:23, 10:91] != engine.background, axis=2))


def test_frame_pixel_coordinates_map_to_canvas_coordinates():
    engine = DrawingEngine(960, 640)
    # The camera is mirrored before tracking, so its pixel coordinates map directly
    # to the similarly oriented canvas. They must be divided by frame size first.
    assert engine.map_frame_point((320, 240), 640, 480, 960, 640) == (480, 320)
    assert engine.map_frame_point((640, 480), 640, 480, 960, 640) == (959, 639)


def test_clear_canvas():
    engine = DrawingEngine(100, 80)
    engine.add_point((20, 20))
    engine.clear()
    assert np.all(engine.canvas == engine.background)


def test_erase_simulation():
    engine = DrawingEngine(100, 80)
    engine.add_point((50, 40), (255, 0, 0), 12)
    engine.erase_at((50, 40), 30)
    assert np.all(engine.canvas[35:46, 45:56] == engine.background)


def test_save_canvas(tmp_path: Path):
    engine = DrawingEngine(100, 80)
    engine.add_point((20, 20))
    destination = engine.save(tmp_path / "drawing.png")
    image = cv2.imread(str(destination))
    assert image is not None and image.shape == (80, 100, 3)
