"""AirCanvas AI single-window PySide6 desktop application."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from camera_worker import CameraWorker
from canvas_widget import CanvasWidget
from drawing_engine import DrawingEngine
from gesture_controller import CoordinateSmoother, Gesture, GestureController, classify_gesture


PALETTE = [
    ("Black", (24, 24, 24), "#181818"),
    ("Red", (50, 55, 220), "#dc3732"),
    ("Blue", (210, 95, 40), "#285fd2"),
    ("Green", (55, 160, 55), "#37a037"),
    ("Purple", (175, 65, 145), "#9141af"),
    ("Amber", (25, 155, 245), "#f59b19"),
    ("Cyan", (210, 150, 20), "#1496d2"),
]


class CameraPreview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(440, 320)
        self.setObjectName("cameraPreview")
        self.setText("Camera is offline\nSelect Start camera to begin")

    def set_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self._source = QPixmap.fromImage(image)
        self._scale_source()

    def _scale_source(self) -> None:
        if self._source is not None:
            self.setPixmap(self._source.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_source()


class AirCanvasWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AirCanvas AI")
        self.resize(1420, 900)
        self.setMinimumSize(1100, 720)

        self.engine = DrawingEngine(background=(250, 250, 250))
        self.controller = GestureController(color_count=len(PALETTE))
        self.smoother = CoordinateSmoother(min_alpha=0.38, max_alpha=0.88, speed_scale=0.025)
        self.worker: CameraWorker | None = None
        self.cursor_point: tuple[int, int] | None = None
        self.brush_size = 8
        self.clear_dialog: QMessageBox | None = None

        self._build_ui()
        self._install_shortcuts()
        self._refresh_mode()
        self._refresh_tool()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 22)
        outer.setSpacing(18)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("AirCanvas AI")
        title.setObjectName("title")
        subtitle = QLabel("DRAW IN THE AIR. CREATE ON SCREEN.")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.mode_badge = QLabel("DRAWING")
        self.mode_badge.setObjectName("modeBadge")
        header.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        left = self._make_panel("CAMERA & GESTURES", "Live hand tracking and mode status")
        right = self._make_panel("CANVAS", "Persistent drawing surface")
        columns.addWidget(left, 5)
        columns.addWidget(right, 6)
        outer.addLayout(columns, 1)

        help_label = QLabel("Space pause/resume  ·  U undo  ·  E eraser  ·  C color  ·  X clear  ·  S save  ·  N drawing mode  ·  Q quit")
        help_label.setObjectName("helpText")
        outer.addWidget(help_label)
        self.setCentralWidget(root)
        self.setStyleSheet(self._stylesheet())

        self.camera_status.setText("Camera offline")
        self._refresh_palette()

    def _make_panel(self, heading: str, hint: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        headings = QVBoxLayout()
        heading_label = QLabel(heading)
        heading_label.setObjectName("panelHeading")
        hint_label = QLabel(hint)
        hint_label.setObjectName("muted")
        headings.addWidget(heading_label)
        headings.addWidget(hint_label)
        top.addLayout(headings)
        top.addStretch(1)

        if heading.startswith("CAMERA"):
            self.hand_badge = QLabel("NO HAND")
            self.hand_badge.setObjectName("statusBadge")
            top.addWidget(self.hand_badge, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(top)
            self.camera_preview = CameraPreview()
            layout.addWidget(self.camera_preview, 1)
            self.gesture_label = QLabel("Gesture: —")
            self.gesture_label.setObjectName("diagnostic")
            layout.addWidget(self.gesture_label)
            self.coordinate_label = QLabel("Fingertip: —")
            self.coordinate_label.setObjectName("diagnostic")
            layout.addWidget(self.coordinate_label)
            status_row = QHBoxLayout()
            self.camera_status = QLabel("Camera offline")
            self.camera_status.setObjectName("muted")
            status_row.addWidget(self.camera_status, 1)
            self.camera_button = QPushButton("Start camera")
            self.camera_button.setObjectName("primaryButton")
            self.camera_button.clicked.connect(self.toggle_camera)
            status_row.addWidget(self.camera_button)
            layout.addLayout(status_row)
            self._left_layout = layout
        else:
            self.tool_badge = QLabel("BRUSH")
            self.tool_badge.setObjectName("toolBadge")
            top.addWidget(self.tool_badge, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(top)
            self.canvas_widget = CanvasWidget(self.engine)
            layout.addWidget(self.canvas_widget, 1)

            tool_row = QHBoxLayout()
            self.color_swatch = QLabel("Selected: Cyan")
            self.color_swatch.setObjectName("colorIndicator")
            tool_row.addWidget(self.color_swatch, 1)
            tool_row.addWidget(QLabel("Brush size"))
            self.size_slider = QSlider(Qt.Orientation.Horizontal)
            self.size_slider.setRange(2, 32)
            self.size_slider.setValue(self.brush_size)
            self.size_slider.setMaximumWidth(170)
            self.size_slider.valueChanged.connect(self._set_brush_size)
            tool_row.addWidget(self.size_slider)
            layout.addLayout(tool_row)

            self.palette_panel = QWidget()
            palette_layout = QHBoxLayout(self.palette_panel)
            palette_layout.setContentsMargins(0, 0, 0, 0)
            palette_layout.setSpacing(8)
            self.palette_buttons: list[QPushButton] = []
            for index, (name, _bgr, css_color) in enumerate(PALETTE):
                button = QPushButton(name)
                button.setToolTip(f"Select {name}")
                button.setStyleSheet(f"QPushButton {{ background:{css_color}; color:{'#fff' if name != 'Amber' else '#222'}; }}")
                button.clicked.connect(lambda _checked=False, i=index: self._select_color(i))
                palette_layout.addWidget(button)
                self.palette_buttons.append(button)
            layout.addWidget(self.palette_panel)
            self.palette_panel.hide()

            controls = QHBoxLayout()
            self.undo_button = QPushButton("Undo")
            self.undo_button.clicked.connect(self._undo)
            self.clear_button = QPushButton("Clear")
            self.clear_button.clicked.connect(self._request_clear)
            self.save_button = QPushButton("Save PNG")
            self.save_button.setObjectName("primaryButton")
            self.save_button.clicked.connect(self._save)
            self.pause_button = QPushButton("Pause")
            self.pause_button.clicked.connect(self._toggle_pause)
            self.navigation_button = QPushButton("Return to Drawing")
            self.navigation_button.clicked.connect(self._resume_drawing)
            for button in (self.undo_button, self.clear_button, self.save_button, self.pause_button, self.navigation_button):
                controls.addWidget(button)
            layout.addLayout(controls)

        return panel

    def _stylesheet(self) -> str:
        return """
        QWidget#root { background:#171b24; color:#e9edf5; font-family:'Segoe UI'; font-size:14px; }
        QFrame#panel { background:#222835; border:1px solid #30394a; border-radius:16px; }
        QLabel#title { color:#f3f6fb; font-size:30px; font-weight:700; }
        QLabel#subtitle { color:#42c9e8; font-size:11px; letter-spacing:2px; font-weight:600; }
        QLabel#panelHeading { color:#edf2fa; font-weight:700; font-size:16px; }
        QLabel#muted, QLabel#helpText { color:#9da9bb; }
        QLabel#helpText { padding:4px 2px; }
        QLabel#cameraPreview { background:#11151c; border:1px solid #3b4658; border-radius:12px; color:#aab5c5; font-size:16px; }
        QWidget#drawingCanvas { background:#fafafa; border:1px solid #d5dbe4; border-radius:12px; }
        QLabel#modeBadge, QLabel#statusBadge, QLabel#toolBadge { background:#173e4c; color:#63d9f0; border-radius:12px; padding:7px 12px; font-weight:700; }
        QLabel#diagnostic { color:#c5cfdd; background:#1a202b; border-radius:7px; padding:7px 9px; }
        QLabel#colorIndicator { color:#e9edf5; background:#1a202b; border-radius:7px; padding:8px; }
        QPushButton { background:#303949; color:#ecf1f8; border:1px solid #465267; border-radius:9px; padding:9px 12px; font-weight:600; }
        QPushButton:hover { background:#3b485d; }
        QPushButton#primaryButton { background:#087f9e; border-color:#1599b8; color:#fff; }
        QPushButton#primaryButton:hover { background:#0b91b2; }
        QSlider::groove:horizontal { height:5px; background:#424c5d; border-radius:2px; }
        QSlider::handle:horizontal { background:#42c9e8; width:14px; margin:-5px 0; border-radius:7px; }
        QMessageBox { background:#222835; }
        """

    def _install_shortcuts(self) -> None:
        shortcuts = [
            (QKeySequence(Qt.Key.Key_Space), self._toggle_pause),
            (QKeySequence("U"), self._undo),
            (QKeySequence("E"), self._toggle_eraser),
            (QKeySequence("C"), self._cycle_color),
            (QKeySequence("X"), self._request_clear),
            (QKeySequence("S"), self._save),
            (QKeySequence("N"), self._resume_drawing),
            (QKeySequence("Q"), self.close),
            (QKeySequence(Qt.Key.Key_Escape), self.close),
        ]
        self._shortcuts = []
        for key, callback in shortcuts:
            shortcut = QShortcut(key, self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def toggle_camera(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._stop_camera()
            return
        self.worker = CameraWorker(parent=self)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.status_changed.connect(self.camera_status.setText)
        self.worker.finished.connect(self._camera_finished)
        self.camera_button.setText("Stop camera")
        self.worker.start()

    def _stop_camera(self) -> None:
        if self.worker is None:
            return
        self.worker.stop()
        self.camera_button.setText("Stopping…")
        self.worker.wait(3000)
        self.engine.end_stroke()
        self.smoother.reset()
        self.canvas_widget.set_cursor(None)

    def _camera_finished(self) -> None:
        self.camera_button.setText("Start camera")
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _on_frame(self, frame, observation) -> None:
        self.camera_preview.set_frame(frame)
        now = time.monotonic()
        if observation is None:
            result = self.controller.no_hand(now)
            self.hand_badge.setText("NO HAND")
            self.hand_badge.setStyleSheet("background:#49333a; color:#ff9da7; border-radius:12px; padding:7px 12px; font-weight:700;")
            self.coordinate_label.setText("Fingertip: not detected")
            self.cursor_point = None
        else:
            gesture = classify_gesture(observation.landmarks, observation.handedness)
            pinch_x = (observation.landmarks[4][0] + observation.landmarks[8][0]) / 2
            result = self.controller.update(gesture, now, pinch_x)
            self.hand_badge.setText("HAND DETECTED")
            self.hand_badge.setStyleSheet("")
            mapped = self.engine.map_frame_point(observation.index_tip, frame.shape[1], frame.shape[0], self.engine.width, self.engine.height)
            self.cursor_point = mapped
            self.coordinate_label.setText(f"Frame ({observation.index_tip[0]:.0f}, {observation.index_tip[1]:.0f})  →  Canvas ({mapped[0]}, {mapped[1]})")

        self.gesture_label.setText(f"Raw: {result.gesture.value}   |   Stable: {result.stable_gesture.value}")
        self._process_actions(result.actions)
        if result.drawing:
            point = self.smoother.update(self.cursor_point)
            mapped = round(point[0]), round(point[1])
            self.cursor_point = mapped
            if self.controller.eraser:
                self.engine.erase_at(mapped, max(24, self.brush_size * 3))
            else:
                self.engine.add_interpolated_point(mapped, PALETTE[self.controller.color_index][1], self.brush_size)
        else:
            self.engine.end_stroke()
            self.smoother.reset()
        self.canvas_widget.set_cursor(self.cursor_point)
        self._refresh_mode()
        self._refresh_tool()

    def _process_actions(self, actions: tuple[str, ...]) -> None:
        for action in actions:
            if action == "undo":
                self._undo()
            elif action == "pause":
                self.engine.end_stroke()
                self.smoother.reset()
                self._notify("Drawing paused")
            elif action == "resume":
                self._notify("Drawing resumed")
            elif action == "navigation":
                self.engine.end_stroke()
                self.smoother.reset()
                self._notify("Navigation mode. Press N or Return to Drawing to resume.")
            elif action == "palette":
                self.palette_panel.setVisible(self.controller.palette_open)
                self._notify("Color palette opened" if self.controller.palette_open else "Color palette closed")
            elif action == "eraser":
                self._notify("Eraser enabled" if self.controller.eraser else "Brush enabled")
            elif action == "request_clear":
                self.engine.end_stroke()
                self.smoother.reset()
                self._show_clear_confirmation()
            elif action.startswith("select_color:"):
                self._refresh_palette()
                self._notify(f"Selected {PALETTE[self.controller.color_index][0]}")
            elif action == "clear_timeout":
                if self.clear_dialog is not None:
                    dialog, self.clear_dialog = self.clear_dialog, None
                    dialog.blockSignals(True)
                    dialog.close()
                self._notify("Clear request expired")

    def _refresh_mode(self) -> None:
        mode = self.controller.mode
        self.mode_badge.setText(mode)
        self.mode_badge.setStyleSheet("background:#49333a; color:#ff9da7; border-radius:12px; padding:7px 12px; font-weight:700;" if mode != "DRAWING" else "")
        self.pause_button.setText("Resume" if mode == "PAUSED" else "Pause")

    def _refresh_tool(self) -> None:
        self.tool_badge.setText("ERASER" if self.controller.eraser else "BRUSH")
        name, _bgr, css_color = PALETTE[self.controller.color_index]
        self.color_swatch.setText(f"Selected color: {name}")
        self.color_swatch.setStyleSheet(f"color:#edf2fa; background:#1a202b; border-left:6px solid {css_color}; border-radius:7px; padding:8px;")

    def _refresh_palette(self) -> None:
        for index, (button, (_name, _bgr, css_color)) in enumerate(zip(self.palette_buttons, PALETTE)):
            text_color = "#fff" if index != 5 else "#222"
            border = "3px solid #48d6f2" if index == self.controller.color_index else "1px solid #465267"
            button.setStyleSheet(f"QPushButton {{ background:{css_color}; color:{text_color}; border:{border}; border-radius:9px; padding:8px 10px; font-weight:600; }}")

    def _select_color(self, index: int) -> None:
        self.controller.color_index = index
        self.controller.palette_open = False
        self.palette_panel.setVisible(False)
        self._refresh_palette()
        self._refresh_tool()

    def _cycle_color(self) -> None:
        self._select_color((self.controller.color_index + 1) % len(PALETTE))

    def _toggle_eraser(self) -> None:
        self.controller.eraser = not self.controller.eraser
        self._refresh_tool()

    def _set_brush_size(self, value: int) -> None:
        self.brush_size = value

    def _undo(self) -> None:
        self._notify("Stroke undone" if self.engine.undo() else "Nothing to undo")
        self.canvas_widget.update()

    def _request_clear(self) -> None:
        if self.clear_dialog is not None:
            self.clear_dialog.raise_()
            return
        self.controller.request_clear(time.monotonic())
        self.engine.end_stroke()
        self.smoother.reset()
        self._show_clear_confirmation()

    def _show_clear_confirmation(self) -> None:
        if self.clear_dialog is not None:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Clear canvas?")
        dialog.setText("Clear the current drawing? This cannot be undone.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Confirm clear")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.finished.connect(self._clear_dialog_finished)
        self.clear_dialog = dialog
        dialog.open()
        QTimer.singleShot(int(self.controller.clear_timeout * 1000), self._clear_timeout)

    def _clear_dialog_finished(self, result: int) -> None:
        confirmed = result == QMessageBox.DialogCode.Accepted or result == QMessageBox.StandardButton.Yes
        do_clear = self.controller.resolve_clear(bool(confirmed))
        self.clear_dialog = None
        if do_clear:
            self.engine.clear()
            self.canvas_widget.update()
            self._notify("Canvas cleared")
        else:
            self._notify("Clear cancelled")

    def _clear_timeout(self) -> None:
        if self.controller.pending_clear_until is not None and time.monotonic() >= self.controller.pending_clear_until:
            self.controller.resolve_clear(False)
            if self.clear_dialog is not None:
                dialog, self.clear_dialog = self.clear_dialog, None
                dialog.blockSignals(True)
                dialog.close()
            self._notify("Clear request expired")

    def _save(self) -> None:
        filename = Path("output") / f"aircanvas-{time.strftime('%Y%m%d-%H%M%S')}.png"
        try:
            saved = self.engine.save(filename)
        except OSError as exc:
            self._notify(f"Save failed: {exc}")
        else:
            self._notify(f"Saved {saved}")

    def _toggle_pause(self) -> None:
        self.controller.toggle_pause()
        self.engine.end_stroke()
        self.smoother.reset()
        self._refresh_mode()

    def _resume_drawing(self) -> None:
        self.controller.resume_drawing()
        self.engine.end_stroke()
        self.smoother.reset()
        self._refresh_mode()

    def _notify(self, message: str) -> None:
        self.camera_status.setText(message)
        QTimer.singleShot(2500, lambda: self.camera_status.setText("Camera connected" if self.worker and self.worker.isRunning() else "Camera offline"))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(5000):
                event.ignore()
                self.camera_status.setText("Waiting for camera to release…")
                self.worker.finished.connect(self.close)
                return
        event.accept()


def main() -> None:
    app = QApplication([])
    window = AirCanvasWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
