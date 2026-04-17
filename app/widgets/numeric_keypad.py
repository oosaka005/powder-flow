from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class NumericKeypadDialog(QDialog):
    def __init__(
        self,
        *,
        initial_text: str,
        allow_decimal: bool,
        title: str = "Numeric Input",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._allow_decimal = allow_decimal
        self._replace_on_next_key = bool(initial_text)
        self._build_ui(title, initial_text)

    def text(self) -> str:
        return self.display.text()

    def _build_ui(self, title: str, initial_text: str) -> None:
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(360, 420)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 20px; font-weight: 700;")

        self.display = QLineEdit(initial_text)
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignRight)
        self.display.setMinimumHeight(56)
        self.display.setStyleSheet("font-size: 24px; padding: 6px 10px;")

        keypad = QGridLayout()
        keypad.setSpacing(8)
        buttons = [
            ("7", 0, 0),
            ("8", 0, 1),
            ("9", 0, 2),
            ("4", 1, 0),
            ("5", 1, 1),
            ("6", 1, 2),
            ("1", 2, 0),
            ("2", 2, 1),
            ("3", 2, 2),
            ("0", 3, 0),
            (".", 3, 1),
            ("BS", 3, 2),
        ]
        for label, row, column in buttons:
            button = QPushButton(label)
            button.setMinimumHeight(56)
            button.setStyleSheet("font-size: 22px;")
            button.clicked.connect(lambda _checked=False, value=label: self._handle_key(value))
            button.setEnabled(label != "." or self._allow_decimal)
            keypad.addWidget(button, row, column)

        action_row = QHBoxLayout()
        clear_button = QPushButton("Clear")
        cancel_button = QPushButton("Cancel")
        ok_button = QPushButton("OK")
        for button in (clear_button, cancel_button, ok_button):
            button.setMinimumHeight(52)
            button.setStyleSheet("font-size: 20px;")
        clear_button.clicked.connect(self._clear)
        cancel_button.clicked.connect(self.reject)
        ok_button.clicked.connect(self.accept)
        action_row.addWidget(clear_button)
        action_row.addWidget(cancel_button)
        action_row.addWidget(ok_button)

        layout = QVBoxLayout()
        layout.addWidget(title_label)
        layout.addWidget(self.display)
        layout.addLayout(keypad)
        layout.addLayout(action_row)
        self.setLayout(layout)

    def _handle_key(self, key: str) -> None:
        current = self.display.text()
        if key == "BS":
            self._replace_on_next_key = False
            self.display.setText(current[:-1] if current else "")
            return
        if key == ".":
            if not self._allow_decimal:
                return
            if "." in current:
                return
            base = "" if self._replace_on_next_key else current
            self.display.setText(f"{base or '0'}.")
            self._replace_on_next_key = False
            return
        next_value = key if self._replace_on_next_key else f"{current}{key}"
        self.display.setText(next_value)
        self._replace_on_next_key = False

    def _clear(self) -> None:
        self.display.clear()
        self._replace_on_next_key = False
