from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStackedWidget, QTabWidget

from app.views.manual import ManualView
from app.views.result import ResultView
from app.views.run import RunView
from app.views.single_test import SingleTestView
from app.views.setup import SetupView
from service.result_store import discard_results, save_results, save_single_test_result


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(
        """
        QWidget { font-size: 16px; }
        QPushButton {
            min-height: 52px;
            padding: 8px 14px;
            font-size: 18px;
        }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
            min-height: 44px;
            font-size: 17px;
        }
        QCheckBox {
            min-height: 36px;
            font-size: 17px;
            spacing: 10px;
        }
        QLabel { font-size: 16px; }
        """
    )

    setup_view = SetupView()
    run_view = RunView()
    result_view = ResultView()
    manual_view = ManualView()
    single_test_view = SingleTestView()
    mode_tabs = QTabWidget()
    mode_tabs.addTab(setup_view, "Setup Mode")
    mode_tabs.addTab(manual_view, "Manual Mode")
    mode_tabs.addTab(single_test_view, "Single Test Mode")

    stack = QStackedWidget()
    stack.addWidget(mode_tabs)
    stack.addWidget(run_view)
    stack.addWidget(result_view)

    def _show_run() -> None:
        stack.setCurrentWidget(run_view)
        QTimer.singleShot(50, run_view.start_automated_experiment_from_settings)

    def _show_result(result: dict) -> None:
        result_view.set_result(result)
        stack.setCurrentWidget(result_view)

    def _show_manual() -> None:
        mode_tabs.setCurrentWidget(manual_view)
        stack.setCurrentWidget(mode_tabs)

    def _show_setting() -> None:
        mode_tabs.setCurrentWidget(setup_view)
        stack.setCurrentWidget(mode_tabs)

    def _show_single_test() -> None:
        mode_tabs.setCurrentWidget(single_test_view)
        stack.setCurrentWidget(mode_tabs)

    def _save_result() -> None:
        save_results(result_view.current_result())
        result_view.set_status("Result saved. Returning to setup...")
        _show_setting()

    def _save_single_test_result() -> None:
        save_single_test_result(result_view.current_result())
        result_view.set_status("Result saved. Returning to single test...")
        _show_single_test()

    def _discard_result() -> None:
        discard_results(result_view.current_result())
        current_result = result_view.current_result()
        result_data = current_result.get("result_data", {})
        metadata = result_data.get("metadata")
        if metadata is None:
            metadata = current_result.get("metadata", {})
        if metadata.get("stage"):
            result_view.set_status("Returning to single test...")
            _show_single_test()
            return
        result_view.set_status("Result discarded. Returning to setup...")
        _show_setting()

    setup_view.proceed_to_run.connect(_show_run)
    run_view.result_ready.connect(_show_result)
    run_view.setup_requested.connect(_show_setting)
    result_view.save_requested.connect(_save_result)
    result_view.save_single_test_requested.connect(_save_single_test_result)
    result_view.discard_requested.connect(_discard_result)
    single_test_view.result_ready.connect(_show_result)

    stack.resize(800, 480)
    stack.setMinimumSize(800, 480)
    stack.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
