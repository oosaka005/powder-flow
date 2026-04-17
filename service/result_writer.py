from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_series_csv(path: Path, series: List[Dict[str, Any]]) -> None:
    """Save series results to CSV in the same format as powder_calibration.py."""
    _ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["condition", "step_index", "cumulative_mass_g", "per_step_mass_g", "success"]
        )
        for s in series:
            label = f"level{s['level']}_t{s['vib_time']}"
            for idx, (cum, step, ok) in enumerate(
                zip(s["cumulative"], s["per_step"], s["successes"]), 1
            ):
                writer.writerow([label, idx, f"{cum:.6f}", f"{step:.6f}", ok])


def save_calibration_config(
    calib_row: Dict[str, Any], *, config_path: Optional[Path] = None
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_path = config_path or repo_root / "config" / "P_calibration.csv"
    headers = [
        "dispenserID",
        "mat_name",
        "diskID",
        "calibration_date",
        "vib_level",
        "vib_time",
        "used_aug",
        "step_mass_mean",
        "density_g_per_ml",
    ]
    rows: List[Dict[str, Any]] = []
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(row)
    updated = False
    for idx, row in enumerate(rows):
        if (
            row.get("dispenserID") == calib_row.get("dispenserID")
            and row.get("mat_name") == calib_row.get("mat_name")
            and row.get("diskID") == calib_row.get("diskID")
        ):
            rows[idx] = calib_row
            updated = True
            break
    if not updated:
        rows.append(calib_row)
    _ensure_parent(config_path)
    with config_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def save_flowability_summary(path: Path, summary: Dict[str, Any]) -> None:
    headers = [
        "material_name",
        "powder_type",
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
        "angle_image_path",
    ]
    _ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow({key: summary.get(key, "") for key in headers})


def save_hausner_raw(
    path: Path,
    *,
    bulk_masses: Iterable[float],
    bulk_densities: Iterable[float],
    tapped_masses: Iterable[float],
    tapped_densities: Iterable[float],
) -> None:
    _ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mode", "index", "mass_g", "density_g_per_ml"])
        for idx, (mass, density) in enumerate(zip(bulk_masses, bulk_densities), 1):
            writer.writerow(["bulk", idx, f"{mass:.6f}", f"{density:.6f}"])
        for idx, (mass, density) in enumerate(zip(tapped_masses, tapped_densities), 1):
            writer.writerow(["tapped", idx, f"{mass:.6f}", f"{density:.6f}"])
