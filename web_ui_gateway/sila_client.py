"""The gateway's only application backend: Powder Characterizer SiLA 2."""

from __future__ import annotations

import json
import os
from typing import Any

from sila2.client import SilaClient


class PowderCharacterizerClient:
    def __init__(self) -> None:
        host = os.getenv("POWDER_CHARACTERIZER_SILA_HOST", "127.0.0.1")
        port = int(os.getenv("POWDER_CHARACTERIZER_SILA_PORT", "50065"))
        insecure = os.getenv("SILA_INSECURE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._client = SilaClient(host, port, insecure=insecure)
        self._feature = self._client.PowderCharacterizer

    def close(self) -> None:
        self._client.close()

    def current_run(self) -> dict[str, Any]:
        return json.loads(self._feature.CurrentRun.get())

    def get_settings(self) -> dict[str, Any]:
        return json.loads(self._feature.GetSettings().SettingsJson)

    def update_settings(self, settings: dict[str, Any]) -> None:
        self._feature.UpdateSettings(
            SettingsJson=json.dumps(settings, ensure_ascii=False)
        )

    def get_material_database(self) -> Any:
        return json.loads(self._feature.GetMaterialDatabase().DatabaseJson)

    @staticmethod
    def _execution(instance: Any) -> dict[str, str]:
        return {"execution_id": str(instance.execution_uuid)}

    def run_automated(self) -> dict[str, str]:
        return self._execution(self._feature.RunAutomatedExperiment())

    def run_single(self, stage: str) -> dict[str, str]:
        return self._execution(self._feature.RunSingleTest(Stage=stage))

    def run_manual(
        self,
        *,
        vibration_level: int,
        vibration_seconds: float,
        dose_count: int,
        use_auger: bool,
    ) -> dict[str, str]:
        return self._execution(
            self._feature.RunManualExperiment(
                VibrationLevel=vibration_level,
                VibrationSeconds=vibration_seconds,
                DoseCount=dose_count,
                UseAuger=use_auger,
            )
        )

    def clear_clog(self) -> dict[str, Any]:
        return json.loads(self._feature.ClearClog().ResultJson)

    def abort(self) -> None:
        self._feature.AbortCurrentOperation()

    def save_results(self, update_material_database: bool) -> None:
        self._feature.SaveResults(
            UpdateMaterialDatabase=update_material_database
        )

    def discard_results(self) -> None:
        self._feature.DiscardResults()

    def camera_preview(self, focus_mode: str, lens_position: float) -> tuple[bytes, str, str]:
        response = self._feature.CaptureCameraPreview(
            FocusMode=focus_mode,
            LensPosition=lens_position,
        )
        return bytes(response.ImageData), str(response.MediaType), str(response.Filename)

    def repose_preview(self) -> tuple[bytes, str, str]:
        response = self._feature.CaptureReposePreview()
        return bytes(response.ImageData), str(response.MediaType), str(response.Filename)

    def artifact(self, run_id: str, filename: str) -> tuple[bytes, str]:
        response = self._feature.GetArtifact(RunId=run_id, Filename=filename)
        return bytes(response.ArtifactData), str(response.MediaType)
