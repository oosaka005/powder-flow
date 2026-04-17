from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ResultView(QWidget):
    save_requested = Signal()
    save_single_test_requested = Signal()
    discard_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._result: dict = {}
        self._preview_artifacts: list[tuple[str, dict]] = []
        self._preview_index = 0
        self._is_single_test = False
        self._stage: str | None = None
        self._summary_pages: list[str] = []
        self._summary_page_index: int = 0
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Result")

        self.title_label = QLabel("Result Mode")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")
        self.summary_label = QLabel("Result Summary")
        self.summary_label.setStyleSheet("font-weight: 700;")
        self.json_label = QLabel("Raw JSON")
        self.json_label.setStyleSheet("font-weight: 700;")
        self.image_section_label = QLabel("Preview Images")
        self.image_section_label.setStyleSheet("font-weight: 700;")
        self.status_label = QLabel("Review the result and choose whether to save it.")
        self.status_label.setWordWrap(True)
        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        self.image_label = QLabel("No preview available.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setVisible(False)
        self.image_caption = QLabel("")
        self.image_caption.setAlignment(Qt.AlignCenter)
        self.image_caption.setVisible(False)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setVisible(False)
        self.image_prev_button = QPushButton("<")
        self.image_next_button = QPushButton(">")
        self.image_prev_button.setVisible(False)
        self.image_next_button.setVisible(False)
        self.image_prev_button.clicked.connect(self._show_previous_preview)
        self.image_next_button.clicked.connect(self._show_next_preview)
        self.summary_prev_button = QPushButton("<")
        self.summary_next_button = QPushButton(">")
        self.summary_page_label = QLabel("")
        self.summary_page_label.setAlignment(Qt.AlignCenter)
        self.summary_prev_button.setVisible(False)
        self.summary_next_button.setVisible(False)
        self.summary_page_label.setVisible(False)
        self.summary_prev_button.clicked.connect(self._show_previous_summary_page)
        self.summary_next_button.clicked.connect(self._show_next_summary_page)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.save_button = QPushButton("Save Results")
        self.discard_button = QPushButton("Discard Results")

        self.save_button.clicked.connect(self._on_save)
        self.discard_button.clicked.connect(self._on_discard)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)

        left_panel = QVBoxLayout()
        left_panel.addWidget(self.summary_label)
        left_panel.addWidget(self.summary_text, 1)
        summary_nav = QHBoxLayout()
        summary_nav.addWidget(self.summary_prev_button)
        summary_nav.addWidget(self.summary_page_label, 1)
        summary_nav.addWidget(self.summary_next_button)
        left_panel.addLayout(summary_nav)
        left_panel.addWidget(self.json_label)
        left_panel.addWidget(self.result_text, 1)

        right_panel = QVBoxLayout()
        right_panel.addWidget(self.image_section_label)
        right_panel.addWidget(self.image_scroll, 1)
        image_controls = QHBoxLayout()
        image_controls.addWidget(self.image_prev_button)
        image_controls.addWidget(self.image_caption)
        image_controls.addWidget(self.image_next_button)
        right_panel.addLayout(image_controls)

        content_layout = QHBoxLayout()
        content_layout.addLayout(left_panel, 1)
        content_layout.addLayout(right_panel, 1)
        layout.addLayout(content_layout, 1)

        controls = QHBoxLayout()
        controls.addWidget(self.save_button)
        controls.addWidget(self.discard_button)
        layout.addLayout(controls)

        self.setLayout(layout)

    def set_result(self, result: dict) -> None:
        self._result = result
        display_result = result.get("result_data", result)
        if "metadata" not in display_result and "metadata" in result:
            display_result = {
                "metadata": result["metadata"],
                **display_result,
            }
        stage = display_result.get("metadata", {}).get("stage")
        is_single_test = bool(stage)
        self._is_single_test = is_single_test
        self._stage = stage
        if is_single_test:
            self.status_label.setText(
                f"Review the {self._single_test_stage_label(stage)} single test result."
            )
            self.save_button.setEnabled(True)
            self.discard_button.setText("Back to Single Test Mode")
        else:
            self.status_label.setText("Review the result and choose whether to save it.")
            self.save_button.setEnabled(True)
            self.discard_button.setText("Discard Results")
        if is_single_test:
            self.summary_label.setText("Result Summary")
            self.summary_text.setPlainText(self._build_summary_text(display_result))
            self.result_text.setPlainText(json.dumps(display_result, indent=2, ensure_ascii=False))
            self._summary_pages = []
            self.json_label.setVisible(True)
            self.result_text.setVisible(True)
            self.summary_prev_button.setVisible(False)
            self.summary_next_button.setVisible(False)
            self.summary_page_label.setVisible(False)
        else:
            pages = self._build_automated_summary_pages(display_result)
            self._summary_pages = pages
            self._summary_page_index = 0
            self._display_summary_page()
            self.json_label.setVisible(False)
            self.result_text.setVisible(False)
            self.summary_prev_button.setVisible(True)
            self.summary_next_button.setVisible(True)
            self.summary_page_label.setVisible(True)
        self._update_preview_image(result, stage)

    def current_result(self) -> dict:
        return self._result

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _build_summary_text(self, result_data: dict) -> str:
        stage = result_data.get("metadata", {}).get("stage")
        return self._build_single_test_summary_text(result_data, stage or "")

    def _build_automated_summary_pages(self, result_data: dict) -> list[str]:
        metadata = result_data.get("metadata", {})
        app_settings = metadata.get("app_settings", {})
        material = app_settings.get("material", {})
        calibration = result_data.get("calibration", {})
        repose = result_data.get("angle_of_repose", {})
        hausner = result_data.get("hausner", {})
        bulk_density = hausner.get("bulk_density", {})
        tapped_density = hausner.get("tapped_density", {})
        success = metadata.get("success", {})
        material_name = material.get("material_name", "-")

        page1_lines = [
            f"Sample Name: {material_name}",
            "",
            "Success:",
            f"  Calibration: {success.get('calibration', False)}",
            f"  Bulk Density: {success.get('bulk_density', False)}",
            f"  Tapped Density: {success.get('tapped_density', False)}",
            f"  Angle of Repose: {success.get('angle_of_repose', False)}",
        ]

        mean_mass = calibration.get("step_mass_mean")
        std_mass = calibration.get("step_mass_std")
        mean_str = f"{mean_mass:.3f}" if isinstance(mean_mass, float) else "-"
        std_str = f"{std_mass:.4f}" if isinstance(std_mass, float) else "-"
        page2_lines = [
            f"Sample Name: {material_name}",
            "",
            "Calibration:",
            f"  Optimized Vibration Level: {calibration.get('selected_vib_level', '-')}",
            f"  Optimized Vibration Time: {calibration.get('selected_vib_time', '-')}",
            f"  Mean Step Mass: {mean_str}",
            f"  Step Mass Std: {std_str}",
        ]

        angle_deg = repose.get("angle_deg")
        angle_str = f"{angle_deg:.2f}" if isinstance(angle_deg, (int, float)) else "-"
        repose_class = repose.get("class") or "-"
        bulk_mean = bulk_density.get("mean")
        bulk_str = f"{bulk_mean:.3f}" if isinstance(bulk_mean, (int, float)) else "-"
        tapped_mean = tapped_density.get("mean")
        tapped_str = f"{tapped_mean:.3f}" if isinstance(tapped_mean, (int, float)) else "-"
        ratio = hausner.get("ratio")
        ratio_str = f"{ratio:.3f}" if isinstance(ratio, (int, float)) else "-"
        hausner_class = hausner.get("class") or "-"
        page3_lines = [
            f"Sample Name: {material_name}",
            "",
            "Flowability:",
            f"  Angle of Repose: {angle_str}\u00b0 ({repose_class})",
            f"  Bulk Density: {bulk_str}",
            f"  Tapped Density: {tapped_str}",
            f"  Hausner Ratio: {ratio_str} ({hausner_class})",
        ]

        return ["\n".join(page1_lines), "\n".join(page2_lines), "\n".join(page3_lines)]

    def _display_summary_page(self) -> None:
        if not self._summary_pages:
            return
        page_titles = ["Success", "Calibration", "Flowability"]
        idx = self._summary_page_index
        title = page_titles[idx] if idx < len(page_titles) else f"Page {idx + 1}"
        self.summary_label.setText(title)
        self.summary_text.setPlainText(self._summary_pages[idx])
        self.summary_prev_button.setEnabled(idx > 0)
        self.summary_next_button.setEnabled(idx < len(self._summary_pages) - 1)
        self.summary_page_label.setText(f"{idx + 1} / {len(self._summary_pages)}")

    def _show_previous_summary_page(self) -> None:
        if self._summary_page_index <= 0:
            return
        self._summary_page_index -= 1
        self._display_summary_page()

    def _show_next_summary_page(self) -> None:
        if self._summary_page_index >= len(self._summary_pages) - 1:
            return
        self._summary_page_index += 1
        self._display_summary_page()

    def _build_single_test_summary_text(self, result_data: dict, stage: str) -> str:
        metadata = result_data.get("metadata", {})
        material_name = metadata.get("material_name", "-")
        success = metadata.get("success", False)

        if stage == "calibration":
            calibration = result_data.get("calibration", {})
            mean_mass = calibration.get('step_mass_mean')
            std_mass = calibration.get('step_mass_std')
            mean_str = f"{mean_mass:.3f}" if isinstance(mean_mass, float) else "-"
            std_str = f"{std_mass:.4f}" if isinstance(std_mass, float) else "-"
            lines = [
                f"Sample Name: {material_name}",
                f"Success: {success}",
                "",
                "Calibration:",
                f"  Optimized Vibration Level: {calibration.get('selected_vib_level', '-')}",
                f"  Optimized Vibration Time: {calibration.get('selected_vib_time', '-')}",
                f"  Mean Step Mass: {mean_str}",
                f"  Step Mass Std: {std_str}",
            ]
            return "\n".join(lines)

        if stage == "bulk_density":
            bulk_density = result_data.get("bulk_density", {})
            lines = [
                f"Sample Name: {material_name}",
                f"Success: {success}",
                "",
                "Flowability:",
                f"  Bulk Density: {bulk_density.get('mean', '-')}",
                f"  Measured Masses: {self._format_number_list(bulk_density.get('masses', []))}",
            ]
            return "\n".join(lines)

        if stage == "tapped_density":
            tapped_density = result_data.get("tapped_density", {})
            lines = [
                f"Sample Name: {material_name}",
                f"Success: {success}",
                "",
                "Flowability:",
                f"  Tapped Density: {tapped_density.get('mean', '-')}",
                f"  Measured Masses: {self._format_number_list(tapped_density.get('masses', []))}",
            ]
            return "\n".join(lines)

        if stage == "angle_of_repose":
            repose = result_data.get("angle_of_repose", {})
            lines = [
                f"Sample Name: {material_name}",
                f"Success: {success}",
                "",
                "Flowability:",
                f"  Angle of Repose: {repose.get('angle_deg', '-')}",
            ]
            if repose.get("error"):
                lines.append(f"  Error: {repose['error']}")
            return "\n".join(lines)

        lines = [
            f"Sample Name: {material_name}",
            f"Stage: {stage}",
            f"Success: {success}",
        ]
        return "\n".join(lines)

    def _format_number_list(self, values: list[object]) -> str:
        if not values:
            return "-"
        formatted: list[str] = []
        for value in values:
            if isinstance(value, (int, float)):
                formatted.append(f"{value:.6f}")
            else:
                formatted.append(str(value))
        return ", ".join(formatted)

    def _single_test_stage_label(self, stage: str) -> str:
        labels = {
            "calibration": "Calibration",
            "bulk_density": "Bulk Density",
            "tapped_density": "Tapped Density",
            "angle_of_repose": "Angle of Repose",
            "prep_dispense": "Prep Dispense",
            "step_timing": "Step Timing",
            "capture_image": "Capture Image",
        }
        return labels.get(stage, stage.replace("_", " ").title())

    def _update_preview_image(self, result: dict, stage: str | None) -> None:
        preview_artifacts = self._select_preview_artifacts(result, stage)
        self._preview_artifacts = preview_artifacts
        self._preview_index = 0
        if not preview_artifacts:
            self.image_scroll.setVisible(False)
            self.image_caption.setVisible(False)
            self.image_prev_button.setVisible(False)
            self.image_next_button.setVisible(False)
            self.image_label.clear()
            return
        self.image_scroll.setVisible(True)
        self.image_caption.setVisible(True)
        self.image_prev_button.setVisible(len(preview_artifacts) > 1)
        self.image_next_button.setVisible(len(preview_artifacts) > 1)
        self._display_preview_artifact()

    def _select_preview_artifacts(self, result: dict, stage: str | None) -> list[tuple[str, dict]]:
        artifacts = result.get("artifacts", {})
        if not artifacts:
            return []
        if not stage:
            selected: list[tuple[str, dict]] = []
            for key in ["calibration_level_plot", "calibration_time_plot"]:
                if key in artifacts:
                    selected.append((key, artifacts[key]))
            stability_keys = sorted(
                key for key in artifacts.keys() if key.startswith("calibration_stability_plot_")
            )
            for key in stability_keys:
                selected.append((key, artifacts[key]))
            for key in ["repose_cropped_image", "repose_processed_image", "repose_fit_image", "repose_raw_image"]:
                if key in artifacts:
                    selected.append((key, artifacts[key]))
            return selected
        if stage == "calibration":
            selected: list[tuple[str, dict]] = []
            for key in ["calibration_level_plot", "calibration_time_plot"]:
                if key in artifacts:
                    selected.append((key, artifacts[key]))
            stability_keys = sorted(
                key for key in artifacts.keys() if key.startswith("calibration_stability_plot_")
            )
            for key in stability_keys:
                selected.append((key, artifacts[key]))
            return selected
        if stage == "angle_of_repose":
            preferred_keys = [
                "repose_cropped_image",
                "repose_processed_image",
                "repose_fit_image",
            ]
            selected: list[tuple[str, dict]] = []
            for key in preferred_keys:
                artifact = artifacts.get(key)
                if artifact is not None:
                    selected.append((key, artifact))
            if not selected and artifacts.get("repose_raw_image"):
                selected.append(("repose_raw_image", artifacts["repose_raw_image"]))
            return selected
        return []

    def _display_preview_artifact(self) -> None:
        if not self._preview_artifacts:
            self.image_scroll.setVisible(False)
            self.image_caption.setVisible(False)
            self.image_label.clear()
            return
        label, artifact = self._preview_artifacts[self._preview_index]
        pixmap = QPixmap()
        if not pixmap.loadFromData(artifact.get("data", b"")):
            self.image_scroll.setVisible(False)
            self.image_caption.setVisible(False)
            self.image_label.clear()
            return
        self.image_caption.setText(
            f"{self._preview_label(label)} ({self._preview_index + 1}/{len(self._preview_artifacts)})"
        )
        self.image_prev_button.setEnabled(self._preview_index > 0)
        self.image_next_button.setEnabled(self._preview_index < len(self._preview_artifacts) - 1)
        self.image_label.setProperty("_original_pixmap", pixmap)
        self._refresh_preview_pixmap()
        QTimer.singleShot(0, self._refresh_preview_pixmap)

    def _show_previous_preview(self) -> None:
        if self._preview_index <= 0:
            return
        self._preview_index -= 1
        self._display_preview_artifact()

    def _show_next_preview(self) -> None:
        if self._preview_index >= len(self._preview_artifacts) - 1:
            return
        self._preview_index += 1
        self._display_preview_artifact()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_preview_pixmap()

    def _refresh_preview_pixmap(self) -> None:
        original = self.image_label.property("_original_pixmap")
        if not isinstance(original, QPixmap):
            return
        viewport_size = self.image_scroll.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        scaled = original.scaled(
            viewport_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _preview_label(self, artifact_key: str) -> str:
        labels = {
            "repose_raw_image": "Raw Image",
            "repose_cropped_image": "Cropped Image",
            "repose_processed_image": "Processed Image",
            "repose_fit_image": "Fit Image",
            "calibration_level_plot": "Level Exploration",
            "calibration_time_plot": "Time Exploration",
        }
        if artifact_key in labels:
            return labels[artifact_key]
        if artifact_key.startswith("calibration_stability_plot_"):
            idx = artifact_key.removeprefix("calibration_stability_plot_")
            return f"Stability Test {idx}"
        return artifact_key.replace("_", " ").title()

    def _on_save(self) -> None:
        answer = QMessageBox.question(
            self,
            "Update Material Database",
            "Update material_database.json with this result?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        self._result["update_material_database"] = (answer == QMessageBox.Yes)
        self.set_status("Saving result...")
        if self._is_single_test:
            self.save_single_test_requested.emit()
        else:
            self.save_requested.emit()

    def _on_discard(self) -> None:
        self.set_status("Discarding result...")
        self.discard_requested.emit()
