"""Background webcam capture and MediaPipe inference for the Qt interface."""

from __future__ import annotations

import threading

import cv2
from PySide6.QtCore import QThread, Signal

from hand_tracker import HandTracker


class CameraWorker(QThread):
    frame_ready = Signal(object, object)
    status_changed = Signal(str)

    def __init__(self, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        camera = None
        tracker = None
        try:
            self.status_changed.emit("Connecting to camera…")
            camera = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                self.status_changed.emit("Camera unavailable. Check permissions or close other camera apps.")
                return
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            tracker = HandTracker()
            self.status_changed.emit("Camera connected")
            while not self._stop_event.is_set():
                ok, frame = camera.read()
                if not ok:
                    self.status_changed.emit("Camera frame read failed")
                    break
                frame = cv2.flip(frame, 1)
                preview, observation = tracker.process(frame)
                self.frame_ready.emit(preview, observation)
                self.msleep(20)
        except Exception as exc:
            self.status_changed.emit(f"Camera/tracker error: {exc}")
        finally:
            if tracker is not None:
                tracker.close()
            if camera is not None:
                camera.release()
            if self._stop_event.is_set():
                self.status_changed.emit("Camera stopped")
