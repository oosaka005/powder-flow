from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "material": {
        "material_name": "ETHOCEL Std",
        "part_type": "metal",
        "disk_id": "D06",
    },
    "calibration": {
        "vib_levels": [4, 3, 2],
        "vib_time_candidates": [1.0],
        "steps_per_level": 5,
        "stability_steps": 8,
        "noise_threshold_g": 0.005,
    },
    "bulk_density": {
        "repeats": 7,
        "weak_vib_level": 1,
        "strong_vib_level": 4,
        "vib_sec_default": 1.0,
    },
    "tapped_density": {
        "repeats": 7,
        "vib_level": 4,
        "vib_sec": 4.0,
    },
    "manual": {
        "manual_vibration_level": 3,
        "manual_vibration_sec": 3.0,
        "manual_use_aug": True,
        "manual_dose_count": 1,
        "manual_camera_focus_mode": "auto",
        "manual_camera_lens_position": 15.0,
    },
    "paths": {
        "log_root": "logs/experiments",
    },
    "disk_master": {
        "D01": {"volume_ml": 0.007},
        "D02": {"volume_ml": 0.03},
        "D03": {"volume_ml": 0.075},
        "D04": {"volume_ml": 0.105},
        "D05": {"volume_ml": 0.26},
        "D06": {"volume_ml": 0.6},
        "D07": {"volume_ml": 0.9},
        "D08": {"volume_ml": 1.5},
        "D09": {"volume_ml": 3.5},
        "D10": {"volume_ml": 5.5},
        "D11": {"volume_ml": 8.0},
    },
}


class SettingsValidationError(ValueError):
    pass


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate(settings: dict[str, Any]) -> None:
    material = settings.get("material", {})
    part_type = material.get("part_type")
    if part_type not in {"metal", "plastic"}:
        raise SettingsValidationError("material.part_type must be 'metal' or 'plastic'.")
    disk_id = str(material.get("disk_id", "")).strip().upper()

    cal = settings.get("calibration", {})
    if not cal.get("vib_levels"):
        raise SettingsValidationError("calibration.vib_levels must not be empty.")
    if not cal.get("vib_time_candidates"):
        raise SettingsValidationError("calibration.vib_time_candidates must not be empty.")
    if float(cal.get("noise_threshold_g", 0.0)) < 0:
        raise SettingsValidationError("calibration.noise_threshold_g must be >= 0.")

    disk_master = settings.get("disk_master", {})
    if disk_id and disk_id not in disk_master:
        raise SettingsValidationError(f"material.disk_id '{disk_id}' was not found in disk_master.")
    for key, entry in disk_master.items():
        volume = float(entry.get("volume_ml", 0.0))
        if volume <= 0:
            raise SettingsValidationError(f"disk_master.{key}.volume_ml must be > 0.")


def load_settings(path: str | Path = "config/app_settings.json") -> dict[str, Any]:
    settings_path = Path(path)
    if not settings_path.exists():
        settings = deepcopy(DEFAULT_SETTINGS)
        save_settings(settings, settings_path)
        return settings

    with settings_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    merged = _deep_merge(DEFAULT_SETTINGS, loaded)
    _validate(merged)
    return merged


def save_settings(settings: dict[str, Any], path: str | Path = "config/app_settings.json") -> None:
    _validate(settings)
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)


def update_settings(
    partial: dict[str, Any],
    path: str | Path = "config/app_settings.json",
) -> dict[str, Any]:
    current = load_settings(path)
    updated = _deep_merge(current, partial)
    save_settings(updated, path)
    return updated
