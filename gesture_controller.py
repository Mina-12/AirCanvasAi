"""Normalized hand-pose classification and edge-triggered application controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import hypot
from typing import Sequence


class Gesture(str, Enum):
    NONE = "NEUTRAL"
    DRAW = "INDEX ONLY"
    PEACE = "PEACE SIGN"
    FIST = "CLOSED FIST"
    THUMBS_UP = "THUMBS UP"
    OPEN_PALM = "OPEN PALM"
    PINKY = "PINKY ONLY"
    CLEAR_REQUEST = "INDEX + PINKY"
    PINCH = "PINCH"


@dataclass(frozen=True)
class GestureResult:
    gesture: Gesture
    stable_gesture: Gesture
    actions: tuple[str, ...]
    drawing: bool
    paused: bool
    color_index: int
    eraser: bool
    notification: str = ""
    navigation: bool = False
    palette_open: bool = False
    clear_pending: bool = False


class CoordinateSmoother:
    """Speed-adaptive exponential smoothing for fingertip coordinates."""

    def __init__(self, min_alpha: float = 0.28, max_alpha: float = 0.82, speed_scale: float = 0.035):
        self.min_alpha, self.max_alpha, self.speed_scale = min_alpha, max_alpha, speed_scale
        self.value: tuple[float, float] | None = None

    def reset(self) -> None:
        self.value = None

    def update(self, point: tuple[float, float]) -> tuple[float, float]:
        point = float(point[0]), float(point[1])
        if self.value is None:
            self.value = point
            return point
        distance = hypot(point[0] - self.value[0], point[1] - self.value[1])
        alpha = min(self.max_alpha, self.min_alpha + distance * self.speed_scale)
        self.value = (self.value[0] + alpha * (point[0] - self.value[0]), self.value[1] + alpha * (point[1] - self.value[1]))
        return self.value


def _finger_extensions(points: Sequence[tuple[float, float]]) -> list[bool]:
    wrist = points[0]
    result = []
    for tip, pip, mcp in ((8, 6, 5), (12, 10, 9), (16, 14, 13), (20, 18, 17)):
        base = hypot(points[mcp][0] - wrist[0], points[mcp][1] - wrist[1])
        tip_distance = hypot(points[tip][0] - wrist[0], points[tip][1] - wrist[1])
        pip_distance = hypot(points[pip][0] - wrist[0], points[pip][1] - wrist[1])
        result.append(tip_distance > base * 1.12 and tip_distance > pip_distance * 1.12)
    return result


def is_drawing_gesture(points: Sequence[tuple[float, float]] | None) -> bool:
    """Index extended; middle, ring, and pinky folded. Thumb is ignored."""
    return bool(points is not None and len(points) >= 21 and _finger_extensions(points) == [True, False, False, False])


def should_draw(hand_detected: bool, drawing_gesture: bool, paused: bool = False) -> bool:
    """The single drawing gate shared by the UI and hardware-independent tests."""
    return bool(hand_detected and drawing_gesture and not paused)


def classify_gesture(points: Sequence[tuple[float, float]] | None, handedness: str = "Right") -> Gesture:
    if points is None or len(points) < 21:
        return Gesture.NONE
    wrist = points[0]
    extended = _finger_extensions(points)
    if extended == [True, False, False, False]:
        return Gesture.DRAW
    hand_scale = max(hypot(points[mcp][0] - wrist[0], points[mcp][1] - wrist[1]) for mcp in (5, 9, 13, 17))
    sign = -1 if handedness.lower() == "right" else 1
    thumb_extended = (points[4][0] - points[3][0]) * sign > hand_scale * 0.25 and hypot(points[4][0] - wrist[0], points[4][1] - wrist[1]) > hypot(points[2][0] - wrist[0], points[2][1] - wrist[1]) * 1.05
    thumb_up = points[4][1] < points[3][1] - 0.045 and not any(extended)
    pinch = hypot(points[4][0] - points[8][0], points[4][1] - points[8][1]) < hand_scale * 0.30
    if pinch:
        return Gesture.PINCH
    count = sum(extended)
    if thumb_up:
        return Gesture.THUMBS_UP
    if count == 4 and thumb_extended:
        return Gesture.OPEN_PALM
    if count == 0 and not thumb_extended:
        return Gesture.FIST
    if not thumb_extended and extended == [True, True, False, False]:
        return Gesture.PEACE
    if not thumb_extended and extended == [False, False, False, True]:
        return Gesture.PINKY
    if not thumb_extended and extended == [True, False, False, True]:
        return Gesture.CLEAR_REQUEST
    return Gesture.NONE


class GestureController:
    """Gesture dwell, release latch, drawing mode, palette, and clear confirmation."""

    def __init__(self, dwell_seconds: float = 0.18, cooldown: float = 0.45, release_seconds: float = 0.10, clear_timeout: float = 5.0, color_count: int = 7):
        self.dwell_seconds = dwell_seconds
        self.cooldown = cooldown
        self.release_seconds = release_seconds
        self.clear_timeout = clear_timeout
        self.color_count = color_count
        self.mode = "DRAWING"
        self.eraser = False
        self.color_index = 0
        self.palette_open = False
        self.pending_clear_until: float | None = None
        self._candidate = Gesture.NONE
        self._candidate_since = 0.0
        self._armed = True
        self._last_activation = float("-inf")

    @property
    def paused(self) -> bool:
        return self.mode == "PAUSED"

    @property
    def navigation(self) -> bool:
        return self.mode == "NAVIGATION"

    def update(self, gesture: Gesture, now: float, pinch_x: float | None = None) -> GestureResult:
        actions: list[str] = []
        note = ""
        if gesture != self._candidate:
            if self._candidate in (Gesture.NONE, Gesture.DRAW) and now - self._candidate_since >= self.release_seconds:
                self._armed = True
            self._candidate, self._candidate_since = gesture, now
        if gesture in (Gesture.NONE, Gesture.DRAW) and now - self._candidate_since >= self.release_seconds:
            self._armed = True
        stable = gesture if gesture == Gesture.DRAW or now - self._candidate_since >= self.dwell_seconds else Gesture.NONE

        if self.pending_clear_until is not None and now >= self.pending_clear_until:
            self.pending_clear_until = None
            actions.append("clear_timeout")
            note = "Clear confirmation expired"

        if stable == Gesture.PINCH and self.palette_open and self._armed and now - self._last_activation >= self.cooldown and pinch_x is not None:
            self.color_index = min(self.color_count - 1, max(0, int(pinch_x * self.color_count)))
            self.palette_open = False
            actions.append(f"select_color:{self.color_index}")
            note = "Color selected"
            self._armed = False
            self._last_activation = now
        elif stable in (Gesture.PEACE, Gesture.FIST, Gesture.PINKY, Gesture.THUMBS_UP, Gesture.OPEN_PALM, Gesture.CLEAR_REQUEST):
            if self._armed and now - self._last_activation >= self.cooldown:
                self._armed = False
                self._last_activation = now
                if stable == Gesture.PEACE:
                    self.mode = "PAUSED" if self.mode == "DRAWING" else "DRAWING"
                    actions.append("pause" if self.paused else "resume")
                    note = "Paused" if self.paused else "Drawing resumed"
                elif stable == Gesture.FIST:
                    self.mode = "NAVIGATION"
                    actions.append("navigation")
                    note = "Navigation mode"
                elif stable == Gesture.PINKY:
                    self.palette_open = not self.palette_open
                    actions.append("palette")
                    note = "Color palette opened" if self.palette_open else "Color palette closed"
                elif stable == Gesture.THUMBS_UP:
                    actions.append("undo")
                    note = "Undo"
                elif stable == Gesture.OPEN_PALM:
                    self.eraser = not self.eraser
                    actions.append("eraser")
                    note = "Eraser on" if self.eraser else "Brush on"
                elif stable == Gesture.CLEAR_REQUEST:
                    self.pending_clear_until = now + self.clear_timeout
                    actions.append("request_clear")
                    note = "Confirm or cancel clearing"

        drawing = stable == Gesture.DRAW and self.mode == "DRAWING" and not self.palette_open and self.pending_clear_until is None
        return GestureResult(gesture, stable, tuple(actions), drawing, self.paused, self.color_index, self.eraser, note, self.navigation, self.palette_open, self.pending_clear_until is not None)

    def resolve_clear(self, confirmed: bool) -> bool:
        was_pending = self.pending_clear_until is not None
        self.pending_clear_until = None
        return bool(was_pending and confirmed)

    def set_navigation(self) -> None:
        self.mode = "NAVIGATION"

    def resume_drawing(self) -> None:
        self.mode = "DRAWING"

    def toggle_pause(self) -> None:
        self.mode = "PAUSED" if self.mode == "DRAWING" else "DRAWING"

    def request_clear(self, now: float) -> None:
        self.pending_clear_until = now + self.clear_timeout

    def no_hand(self, now: float) -> GestureResult:
        return self.update(Gesture.NONE, now)
