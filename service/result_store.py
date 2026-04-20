from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from service.settings_store import load_settings


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _write_series_csv(path: Path, series: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["condition", "step_index", "cumulative_mass_g", "per_step_mass_g", "success"]
        )
        for entry in series:
            label = f"level{entry['level']}_t{entry['vib_time']}"
            for idx, (cum, step_mass, ok) in enumerate(
                zip(entry["cumulative"], entry["per_step"], entry["successes"]),
                1,
            ):
                writer.writerow([label, idx, f"{cum:.6f}", f"{step_mass:.6f}", ok])


def _write_flowability_summary_csv(path: Path, result_data: dict[str, Any]) -> None:
    metadata = result_data["metadata"]
    material = metadata["app_settings"]["material"]
    calibration = result_data["calibration"]
    repose = result_data["angle_of_repose"]
    hausner = result_data["hausner"]
    bulk_density = hausner["bulk_density"]
    tapped_density = hausner["tapped_density"]

    headers = [
        "material_name",
        "part_type",
        "disk_id",
        "measurement_date",
        "vib_level",
        "vib_sec",
        "bulk_density_mean",
        "bulk_density_stdev",
        "tapped_density_mean",
        "tapped_density_stdev",
        "hausner_ratio",
        "hausner_class",
        "angle_of_repose_deg",
        "repose_class",
    ]
    row = {
        "material_name": material["material_name"],
        "part_type": material["part_type"],
        "disk_id": material["disk_id"],
        "measurement_date": metadata["timestamp"],
        "vib_level": calibration["selected_vib_level"],
        "vib_sec": calibration["selected_vib_time"],
        "bulk_density_mean": bulk_density["mean"],
        "bulk_density_stdev": bulk_density["stdev"],
        "tapped_density_mean": tapped_density["mean"],
        "tapped_density_stdev": tapped_density["stdev"],
        "hausner_ratio": hausner["ratio"],
        "hausner_class": hausner["class"],
        "angle_of_repose_deg": repose["angle_deg"],
        "repose_class": repose["class"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def _write_hausner_raw_csv(
    path: Path,
    *,
    bulk_masses: Iterable[float],
    bulk_densities: Iterable[float],
    tapped_masses: Iterable[float],
    tapped_densities: Iterable[float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mode", "index", "mass_g", "density_g_per_ml"])
        for idx, (mass, density) in enumerate(zip(bulk_masses, bulk_densities), 1):
            writer.writerow(["bulk", idx, f"{mass:.6f}", f"{density:.6f}"])
        for idx, (mass, density) in enumerate(zip(tapped_masses, tapped_densities), 1):
            writer.writerow(["tapped", idx, f"{mass:.6f}", f"{density:.6f}"])


def _write_artifacts(
    calibration_dir: Path,
    flowability_dir: Path,
    artifacts: dict[str, dict[str, Any]],
) -> None:
    for key, payload in artifacts.items():
        filename = payload["filename"]
        data = payload["data"]
        target_dir = calibration_dir if key.startswith("calibration_") else flowability_dir
        output_path = target_dir / filename
        output_path.write_bytes(data)


def _load_disk_volume(disk_id: str) -> float | None:
    disk_master_path = Path(__file__).resolve().parents[1] / "config" / "disk_master.csv"
    if not disk_master_path.exists():
        return None
    import csv as _csv
    with disk_master_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in _csv.DictReader(handle):
            if row.get("DiskID") == disk_id:
                try:
                    return float(row["Volume[ml(cm3)]"])
                except (ValueError, KeyError):
                    return None
    return None


def _update_material_database(payload: dict[str, Any], *, sources_update: dict[str, str | None] | None = None) -> None:
    """Merge payload fields into material_database.json, keyed by mat_name + diskID.

    Only fields present in payload (besides the keys) are overwritten;
    existing fields not in payload are preserved.
    """
    db_path = Path(__file__).resolve().parents[1] / "config" / "material_database.json"
    existing: list[dict[str, Any]] = []
    if db_path.exists():
        with db_path.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)

    mat_name = payload["mat_name"]
    disk_id = payload["diskID"]

    record: dict[str, Any] | None = None
    rec_idx: int | None = None
    for idx, row in enumerate(existing):
        if row.get("mat_name") == mat_name and row.get("diskID") == disk_id:
            record = dict(row)
            rec_idx = idx
            break

    if record is None:
        record = {
            "dispenserID": "powder_dispenser",
            "mat_name": mat_name,
            "diskID": disk_id,
            "volume_ml": None,
            "vib_level": None,
            "vib_time": None,
            "used_aug": None,
            "step_mass_mean": None,
            "step_mass_std": None,
            "density_g_per_ml": None,
            "bulk_density_mean": None,
            "bulk_density_stdev": None,
            "tapped_density_mean": None,
            "tapped_density_stdev": None,
            "hausner_ratio": None,
            "hausner_class": None,
            "angle_of_repose_deg": None,
            "repose_class": None,
            "sources": {
                "calibration": None,
                "bulk_density": None,
                "tapped_density": None,
                "angle_of_repose": None,
            },
        }
        existing.append(record)
        rec_idx = len(existing) - 1

    record["volume_ml"] = _load_disk_volume(disk_id)
    update_keys = set(payload) - {"mat_name", "diskID"}
    for key in update_keys:
        record[key] = payload[key]

    # Recalculate Hausner ratio whenever bulk or tapped density values are present.
    bulk = record.get("bulk_density_mean")
    tapped = record.get("tapped_density_mean")
    if bulk is not None and tapped is not None and bulk > 0:
        from operation.powder_flow_api import classify_hausner
        ratio = tapped / bulk
        record["hausner_ratio"] = ratio
        record["hausner_class"] = classify_hausner(ratio)

    # Update sources tracking.
    if sources_update:
        if not isinstance(record.get("sources"), dict):
            record["sources"] = {
                "calibration": None,
                "bulk_density": None,
                "tapped_density": None,
                "angle_of_repose": None,
            }
        for stage, folder in sources_update.items():
            record["sources"][stage] = folder

    existing[rec_idx] = record
    _write_json(db_path, existing)


def _write_repose_result_csv(path: Path, repose_data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["angle_deg", "class", "success"])
        writer.writeheader()
        writer.writerow({
            "angle_deg": repose_data.get("angle_deg", ""),
            "class": repose_data.get("class", ""),
            "success": repose_data.get("success", ""),
        })


def _write_density_raw_csv(
    path: Path,
    masses: list[float],
    densities: list[float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "mass_g", "density_g_per_ml"])
        for idx, (mass, density) in enumerate(zip(masses, densities), 1):
            writer.writerow([idx, f"{mass:.6f}", f"{density:.6f}"])


def _write_density_summary_csv(path: Path, density_data: dict[str, Any]) -> None:
    n_total = len(density_data.get("densities", []))
    n_used = (n_total - 4) if n_total >= 5 else n_total
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["mean_density_g_per_ml", "stdev_density_g_per_ml", "n_total", "n_used"],
        )
        writer.writeheader()
        writer.writerow({
            "mean_density_g_per_ml": density_data.get("mean", ""),
            "stdev_density_g_per_ml": density_data.get("stdev", ""),
            "n_total": n_total,
            "n_used": n_used,
        })


def save_results(result: dict[str, Any]) -> None:
    result_data = result["result_data"]
    artifacts = result.get("artifacts", {})

    settings = load_settings()
    log_root = Path(settings["paths"]["log_root"])
    run_id = result_data["metadata"]["run_id"]
    run_dir = log_root / "all" / run_id
    calibration_dir = run_dir / "calibration"
    flowability_dir = run_dir / "flowability"

    _ensure_dir(run_dir)
    _ensure_dir(calibration_dir)
    _ensure_dir(flowability_dir)

    _write_json(run_dir / "result.json", result_data)

    timestamp = result_data["metadata"]["timestamp"]
    date_prefix = f"{timestamp[:8]}_"
    calibration = result_data["calibration"]
    hausner = result_data["hausner"]
    bulk_density = hausner["bulk_density"]
    tapped_density = hausner["tapped_density"]

    _write_series_csv(
        calibration_dir / f"{date_prefix}level_exploration.csv",
        calibration["level_results"],
    )
    if calibration["time_results"]:
        _write_series_csv(
            calibration_dir / f"{date_prefix}vib_time_exploration.csv",
            calibration["time_results"],
        )
    for idx, stability_result in enumerate(calibration["stability_results"], 1):
        _write_series_csv(
            calibration_dir / f"{date_prefix}stability_test_{idx}.csv",
            [stability_result],
        )

    _write_flowability_summary_csv(
        flowability_dir / f"{date_prefix}flowability_summary.csv",
        result_data,
    )
    _write_hausner_raw_csv(
        flowability_dir / f"{date_prefix}hausner_raw.csv",
        bulk_masses=bulk_density["masses"],
        bulk_densities=bulk_density["densities"],
        tapped_masses=tapped_density["masses"],
        tapped_densities=tapped_density["densities"],
    )
    _write_artifacts(calibration_dir, flowability_dir, artifacts)
    if result.get("update_material_database"):
        calibration = result_data["calibration"]
        hausner = result_data["hausner"]
        repose = result_data["angle_of_repose"]
        bulk_density = hausner["bulk_density"]
        tapped_density = hausner["tapped_density"]
        material = result_data["metadata"]["app_settings"]["material"]
        folder_path = f"all/{run_id}"
        _update_material_database({
            "dispenserID": "powder_dispenser",
            "mat_name": material["material_name"],
            "diskID": material["disk_id"],
            "vib_level": calibration["selected_vib_level"],
            "vib_time": calibration["selected_vib_time"],
            "used_aug": True,
            "step_mass_mean": calibration["step_mass_mean"],
            "step_mass_std": calibration.get("step_mass_std"),
            "density_g_per_ml": calibration.get("density_g_per_ml"),
            "bulk_density_mean": bulk_density["mean"],
            "bulk_density_stdev": bulk_density["stdev"],
            "tapped_density_mean": tapped_density["mean"],
            "tapped_density_stdev": tapped_density["stdev"],
            "hausner_ratio": hausner["ratio"],
            "hausner_class": hausner["class"],
            "angle_of_repose_deg": repose.get("angle_deg"),
            "repose_class": repose.get("class"),
        }, sources_update={
            "calibration": folder_path,
            "bulk_density": folder_path,
            "tapped_density": folder_path,
            "angle_of_repose": folder_path if repose.get("angle_deg") is not None else None,
        })


def save_single_test_result(result: dict[str, Any]) -> None:
    metadata = result["metadata"]
    stage = metadata["stage"]
    material_name = metadata["material_name"]
    timestamp = metadata["timestamp"]
    artifacts = result.get("artifacts", {})

    settings = load_settings()
    log_root = Path(settings["paths"]["log_root"])
    folder_name = f"{timestamp}_{material_name}_{stage}"
    run_dir = log_root / "single" / folder_name
    _ensure_dir(run_dir)

    date_prefix = f"{timestamp[:8]}_"
    result_json_data: dict[str, Any] = {"metadata": metadata, **result["result_data"]}
    _write_json(run_dir / "result.json", result_json_data)

    stage_data = result["result_data"][stage]

    if stage == "calibration":
        calibration = stage_data
        _write_series_csv(
            run_dir / f"{date_prefix}level_exploration.csv",
            calibration["level_results"],
        )
        if calibration.get("time_results"):
            _write_series_csv(
                run_dir / f"{date_prefix}vib_time_exploration.csv",
                calibration["time_results"],
            )
        for idx, sr in enumerate(calibration["stability_results"], 1):
            _write_series_csv(run_dir / f"{date_prefix}stability_test_{idx}.csv", [sr])
        for payload in artifacts.values():
            (run_dir / payload["filename"]).write_bytes(payload["data"])
        if result.get("update_material_database"):
            _update_material_database({
                "dispenserID": "powder_dispenser",
                "mat_name": material_name,
                "diskID": metadata["app_settings"]["material"]["disk_id"],
                "vib_level": calibration["selected_vib_level"],
                "vib_time": calibration["selected_vib_time"],
                "used_aug": True,
                "step_mass_mean": calibration["step_mass_mean"],
                "step_mass_std": calibration.get("step_mass_std"),
                "density_g_per_ml": calibration.get("density_g_per_ml"),
            }, sources_update={"calibration": f"single/{folder_name}"})

    elif stage == "angle_of_repose":
        repose = stage_data
        _write_repose_result_csv(run_dir / f"{date_prefix}repose_result.csv", repose)
        for payload in artifacts.values():
            (run_dir / payload["filename"]).write_bytes(payload["data"])
        if result.get("update_material_database"):
            _update_material_database({
                "mat_name": material_name,
                "diskID": metadata["app_settings"]["material"]["disk_id"],
                "angle_of_repose_deg": repose.get("angle_deg"),
                "repose_class": repose.get("class"),
            }, sources_update={"angle_of_repose": f"single/{folder_name}" if repose.get("angle_deg") is not None else None})

    elif stage == "bulk_density":
        density = stage_data
        _write_density_raw_csv(
            run_dir / f"{date_prefix}bulk_density_raw.csv",
            density["masses"],
            density["densities"],
        )
        _write_density_summary_csv(
            run_dir / f"{date_prefix}bulk_density_summary.csv",
            density,
        )
        if result.get("update_material_database"):
            _update_material_database({
                "mat_name": material_name,
                "diskID": metadata["app_settings"]["material"]["disk_id"],
                "bulk_density_mean": density.get("mean"),
                "bulk_density_stdev": density.get("stdev"),
            }, sources_update={"bulk_density": f"single/{folder_name}"})

    elif stage == "tapped_density":
        density = stage_data
        _write_density_raw_csv(
            run_dir / f"{date_prefix}tapped_density_raw.csv",
            density["masses"],
            density["densities"],
        )
        _write_density_summary_csv(
            run_dir / f"{date_prefix}tapped_density_summary.csv",
            density,
        )
        if result.get("update_material_database"):
            _update_material_database({
                "mat_name": material_name,
                "diskID": metadata["app_settings"]["material"]["disk_id"],
                "tapped_density_mean": density.get("mean"),
                "tapped_density_stdev": density.get("stdev"),
            }, sources_update={"tapped_density": f"single/{folder_name}"})


def discard_results(result: dict[str, Any]) -> None:
    # No cleanup is needed right now because the result is kept in memory until save.
    _ = result
