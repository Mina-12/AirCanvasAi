"""Persistent OpenCV drawing surface and stroke operations."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class DrawingEngine:
    def __init__(self, width: int = 960, height: int = 640, background: tuple[int, int, int] = (15, 19, 27)):
        self.width, self.height = width, height
        self.background = background
        self.canvas = np.full((height, width, 3), background, dtype=np.uint8)
        self._active: list[tuple[int, int]] | None = None
        self._active_style = ((255, 210, 60), 8)
        self._undo: list[list[tuple[int, int]]] = []
        self._styles: list[tuple[tuple[int, int, int], int]] = []

    @staticmethod
    def map_frame_point(point: tuple[float, float], frame_width: int, frame_height: int, canvas_width: int, canvas_height: int) -> tuple[int, int]:
        """Map frame-pixel coordinates to canvas pixels without treating them as normalized."""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Frame dimensions must be positive")
        x = round(point[0] / frame_width * canvas_width)
        y = round(point[1] / frame_height * canvas_height)
        return int(np.clip(x, 0, canvas_width - 1)), int(np.clip(y, 0, canvas_height - 1))

    def _point(self, point: tuple[int, int]) -> tuple[int, int]:
        return int(np.clip(point[0], 0, self.width - 1)), int(np.clip(point[1], 0, self.height - 1))

    def add_point(self, point: tuple[int, int], color: tuple[int, int, int] = (255, 210, 60), thickness: int = 8) -> None:
        point = self._point(point)
        thickness = max(1, int(thickness))
        if self._active is None:
            self._active = []
            self._active_style = (color, thickness)
        if self._active:
            cv2.line(self.canvas, self._active[-1], point, color, thickness, cv2.LINE_AA)
        cv2.circle(self.canvas, point, max(1, thickness // 2), color, -1, cv2.LINE_AA)
        self._active.append(point)

    def add_interpolated_point(self, point: tuple[int, int], color: tuple[int, int, int] = (255, 210, 60), thickness: int = 8) -> None:
        point = self._point(point)
        if not self._active:
            self.add_point(point, color, thickness)
            return
        start = self._active[-1]
        distance = float(np.hypot(point[0] - start[0], point[1] - start[1]))
        spacing = max(1.0, thickness * 0.45)
        steps = max(1, int(np.ceil(distance / spacing)))
        for step in range(1, steps + 1):
            fraction = step / steps
            sample = (round(start[0] + (point[0] - start[0]) * fraction), round(start[1] + (point[1] - start[1]) * fraction))
            self.add_point(sample, color, thickness)

    def end_stroke(self) -> None:
        if self._active:
            self._undo.append(self._active)
            self._styles.append(self._active_style)
        self._active = None

    def clear(self) -> None:
        self._active = None
        self._undo.clear()
        self._styles.clear()
        self.canvas[:] = self.background

    def erase_at(self, point: tuple[int, int], thickness: int = 30) -> None:
        self.end_stroke()
        cv2.circle(self.canvas, self._point(point), max(1, int(thickness) // 2), self.background, -1, cv2.LINE_AA)

    def undo(self) -> bool:
        self.end_stroke()
        if not self._undo:
            return False
        self._undo.pop()
        self._styles.pop()
        self.canvas[:] = self.background
        for stroke, (color, thickness) in zip(self._undo, self._styles):
            for index, point in enumerate(stroke):
                if index:
                    cv2.line(self.canvas, stroke[index - 1], point, color, thickness, cv2.LINE_AA)
                cv2.circle(self.canvas, point, max(1, thickness // 2), color, -1, cv2.LINE_AA)
        return True

    def save(self, path: str | Path) -> Path:
        self.end_stroke()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), self.canvas):
            raise OSError(f"Could not save drawing to {path}")
        return path

    def image(self) -> np.ndarray:
        return self.canvas.copy()
