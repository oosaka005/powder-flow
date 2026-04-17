from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QWidget

from app.widgets.numeric_keypad import NumericKeypadDialog


class _TapLineEdit(QLineEdit):
    tapped = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.tapped.emit()


class TouchNumericInput(QWidget):
    valueChanged = Signal(float)

    def __init__(
        self,
        *,
        minimum: float = 0.0,
        maximum: float = 99.0,
        step: float = 1.0,
        decimals: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = float(step)
        self._decimals = int(decimals)
        self._value = self._minimum
        self._build_ui()
        self._update_display()

    def value(self) -> int | float:
        if self._decimals == 0:
            return int(round(self._value))
        return round(self._value, self._decimals)

    def setValue(self, value: float) -> None:
        clamped = min(max(float(value), self._minimum), self._maximum)
        if self._decimals == 0:
            clamped = float(int(round(clamped)))
        else:
            clamped = round(clamped, self._decimals)
        if clamped == self._value:
            self._update_display()
            return
        self._value = clamped
        self._update_display()
        self.valueChanged.emit(float(self._value))

    def setRange(self, minimum: float, maximum: float) -> None:
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self.setValue(self._value)

    def setSingleStep(self, step: float) -> None:
        self._step = float(step)

    def setDecimals(self, decimals: int) -> None:
        self._decimals = int(decimals)
        self.setValue(self._value)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.display_field.setEnabled(enabled)
        self.decrement_button.setEnabled(enabled)
        self.increment_button.setEnabled(enabled)

    def _build_ui(self) -> None:
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.display_field = _TapLineEdit()
        self.display_field.setReadOnly(True)
        self.display_field.setAlignment(Qt.AlignLeft)
        self.display_field.setFixedHeight(30)
        self.display_field.setStyleSheet(
            """
            QLineEdit {
                font-size: 20px;
                padding: 2px 10px;
                min-height: 44px;
                max-height: 44px;
            }
            """
        )
        self.display_field.tapped.connect(self._open_keypad)

        self.decrement_button = QPushButton("-")
        self.increment_button = QPushButton("+")
        for button in (self.decrement_button, self.increment_button):
            button.setFixedSize(44, 44)
            button.setStyleSheet(
                """
                QPushButton {
                    font-size: 22px;
                    font-weight: 700;
                    padding: 0px;
                    border: 1px solid #8a8a8a;
                    border-radius: 2px;
                    background-color: #f3f3f3;
                    min-height: 44px;
                    max-height: 44px;
                }
                QPushButton:pressed {
                    background-color: #e2e2e2;
                }
                """
            )
        self.decrement_button.clicked.connect(lambda: self._step_by(-1))
        self.increment_button.clicked.connect(lambda: self._step_by(1))

        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self.display_field, 1)
        layout.addWidget(self.decrement_button)
        layout.addWidget(self.increment_button)
        self.setLayout(layout)

    def _format_value(self) -> str:
        if self._decimals == 0:
            return str(int(round(self._value)))
        return f"{self._value:.{self._decimals}f}"

    def _update_display(self) -> None:
        self.display_field.setText(self._format_value())

    def _step_by(self, direction: int) -> None:
        self.setValue(self._value + (direction * self._step))

    def _open_keypad(self) -> None:
        dialog = NumericKeypadDialog(
            initial_text=self._format_value(),
            allow_decimal=self._decimals > 0,
            title="Enter Value",
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        raw_text = dialog.text().strip()
        if not raw_text:
            self.setValue(self._minimum)
            return
        try:
            parsed = float(raw_text)
        except ValueError:
            return
        self.setValue(parsed)
