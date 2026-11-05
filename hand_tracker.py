"""MediaPipe hand landmark extraction, isolated from the UI and drawing engine."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import mediapipe as mp

from gesture_controller import is_drawing_gesture


@dataclass(frozen=True)
class HandObservation:
    """Landmark observation; index_tip and other named points are frame pixels."""
    index_tip: tuple[float, float]
    index_pip: tuple[float, float]
    index_mcp: tuple[float, float]
    thumb_tip: tuple[float, float]
    middle_tip: tuple[float, float]
    drawing: bool
    landmarks: tuple[tuple[float, float], ...]
    handedness: str


class HandTracker:
    def __init__(self, max_hands: int = 1, detection_confidence: float = 0.6, tracking_confidence: float = 0.6):
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=max_hands,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._draw = mp.solutions.drawing_utils
        self._connections = mp.solutions.hands.HAND_CONNECTIONS

    def process(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)
        observation = None
        if result.multi_hand_landmarks:
            landmarks = result.multi_hand_landmarks[0].landmark
            h, w = frame.shape[:2]
            def xy(i):
                return (landmarks[i].x * w, landmarks[i].y * h)
            index_tip, index_pip, index_mcp = xy(8), xy(6), xy(5)
            middle_tip = xy(12)
            label = "Right"
            if result.multi_handedness:
                label = result.multi_handedness[0].classification[0].label
            normalized = tuple((point.x, point.y) for point in landmarks)
            observation = HandObservation(
                index_tip, index_pip, index_mcp, xy(4), middle_tip,
                is_drawing_gesture(normalized), normalized, label,
            )
            self._draw.draw_landmarks(frame, result.multi_hand_landmarks[0], self._connections)
        return frame, observation

    def close(self):
        self._hands.close()
