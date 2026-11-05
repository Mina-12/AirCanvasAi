from gesture_controller import (
    Gesture,
    GestureController,
    classify_gesture,
    is_drawing_gesture,
    should_draw,
)


def landmarks(extended=(False, False, False, False), thumb="folded"):
    """Synthetic 21-point palm landmarks; finger order is index to pinky."""
    points = [(0.5, 0.85)] * 21
    points[0] = (0.5, 0.85)
    finger_ids = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
    for j, ids in enumerate(finger_ids):
        x = (0.38, 0.46, 0.54, 0.62)[j]
        points[ids[0]] = (x, 0.72)
        if extended[j]:
            points[ids[1]] = (x, 0.58)
            points[ids[2]] = (x, 0.39)
            points[ids[3]] = (x, 0.20)
        else:
            points[ids[1]] = (x, 0.70)
            points[ids[2]] = (x, 0.76)
            points[ids[3]] = (x, 0.78)
    points[1:5] = [(0.37, .76), (.34, .78), (.32, .80), (.30, .82)]
    if thumb == "extended":
        points[4] = (.22, .70)
    elif thumb == "up":
        points[2], points[3], points[4] = (.39, .72), (.39, .55), (.39, .30)
    elif thumb == "pinch":
        points[4] = points[8]
    return points


def activate(controller, gesture, t):
    controller.update(gesture, t)
    return controller.update(gesture, t + .2)


def release(controller, t):
    controller.update(Gesture.NONE, t)
    controller.update(Gesture.NONE, t + .11)


def test_classifies_drawing_without_requiring_thumb_folded():
    assert is_drawing_gesture(landmarks((True, False, False, False)))
    assert is_drawing_gesture(landmarks((True, False, False, False), "extended"))
    assert classify_gesture(landmarks((True, False, False, False), "extended")) == Gesture.DRAW
    assert not is_drawing_gesture(landmarks((True, True, False, False)))


def test_classifies_control_gestures_from_normalized_landmarks():
    assert classify_gesture(landmarks((True, True, False, False))) == Gesture.PEACE
    assert classify_gesture(landmarks()) == Gesture.FIST
    assert classify_gesture(landmarks(thumb="up")) == Gesture.THUMBS_UP
    assert classify_gesture(landmarks((True, True, True, True), "extended")) == Gesture.OPEN_PALM
    assert classify_gesture(landmarks((False, False, False, True))) == Gesture.PINKY
    assert classify_gesture(landmarks((True, False, False, True))) == Gesture.CLEAR_REQUEST
    assert classify_gesture(landmarks(thumb="pinch")) == Gesture.PINCH


def test_drawing_state_requires_hand_pose_and_drawing_mode():
    controller = GestureController()
    active = controller.update(Gesture.DRAW, 0)
    assert active.drawing
    assert should_draw(True, True, paused=False)
    assert not should_draw(False, True, paused=False)
    assert not should_draw(True, False, paused=False)
    assert not should_draw(True, True, paused=True)
    assert not controller.no_hand(.1).drawing


def test_peace_sign_pauses_and_resumes_once_per_release():
    controller = GestureController(cooldown=.1)
    paused = activate(controller, Gesture.PEACE, 0)
    assert paused.paused and paused.actions == ("pause",) and not paused.drawing
    assert controller.update(Gesture.PEACE, 1).actions == ()
    release(controller, 1.1)
    resumed = activate(controller, Gesture.PEACE, 1.3)
    assert not resumed.paused and resumed.actions == ("resume",)


def test_fist_enters_navigation_once_and_navigation_blocks_drawing():
    controller = GestureController(cooldown=.1)
    nav = activate(controller, Gesture.FIST, 0)
    assert nav.navigation and nav.actions == ("navigation",) and not nav.drawing
    assert controller.update(Gesture.FIST, 1).actions == ()
    release(controller, 1.1)
    assert controller.update(Gesture.DRAW, 1.3).drawing is False
    controller.resume_drawing()
    assert controller.update(Gesture.DRAW, 1.4).drawing


def test_pinky_opens_palette_and_pinch_selects_once():
    controller = GestureController(cooldown=.1)
    assert activate(controller, Gesture.PINKY, 0).palette_open
    assert controller.update(Gesture.PINKY, 1).actions == ()
    release(controller, 1.1)
    controller.update(Gesture.PINCH, 1.3, pinch_x=.4)
    result = controller.update(Gesture.PINCH, 1.5, pinch_x=.4)
    assert result.color_index == 2 and result.actions == ("select_color:2",)
    assert not result.palette_open


def test_thumbs_up_undoes_once_and_open_palm_toggles_eraser():
    controller = GestureController(cooldown=.1)
    assert activate(controller, Gesture.THUMBS_UP, 0).actions == ("undo",)
    assert controller.update(Gesture.THUMBS_UP, 1).actions == ()
    release(controller, 1.1)
    result = activate(controller, Gesture.OPEN_PALM, 1.3)
    assert result.eraser and result.actions == ("eraser",)


def test_clear_request_needs_confirmation_and_can_cancel_or_expire():
    controller = GestureController(cooldown=.1, clear_timeout=2)
    requested = activate(controller, Gesture.CLEAR_REQUEST, 0)
    assert requested.clear_pending and not requested.drawing
    assert controller.resolve_clear(True)
    assert not controller.resolve_clear(False)

    cancelled = GestureController(cooldown=.1)
    assert activate(cancelled, Gesture.CLEAR_REQUEST, 0).clear_pending
    assert not cancelled.resolve_clear(False)
    assert cancelled.update(Gesture.DRAW, .3).drawing

    release(controller, .3)
    activate(controller, Gesture.CLEAR_REQUEST, .5)
    expired = controller.update(Gesture.NONE, 3.2)
    assert expired.actions == ("clear_timeout",)
    assert not expired.clear_pending


def test_neutral_release_rearms_commands_but_held_command_does_not_repeat():
    controller = GestureController(cooldown=.1)
    assert activate(controller, Gesture.PEACE, 0).actions == ("pause",)
    assert controller.update(Gesture.PEACE, 1).actions == ()
    release(controller, 1.1)
    assert activate(controller, Gesture.PEACE, 1.3).actions == ("resume",)
