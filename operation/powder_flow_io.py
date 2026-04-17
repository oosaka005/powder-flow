from __future__ import annotations

from pathlib import Path
import csv
from typing import Any, Dict, Iterable, List, Optional


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_series_csv(path: Path, series: List[Dict[str, Any]]) -> None:
    """
    Save series results to CSV in the same format as powder_calibration.py.
    """
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


def plot_level_exploration(
    series: List[Dict[str, Any]], optimal: Dict[str, Any], out_path: Path
) -> None:
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError("matplotlib is required for plotting.") from exc

    plt.figure(figsize=(10, 6))
    max_steps = max(len(s["cumulative"]) for s in series)
    non_optimal = [s for s in series if s is not optimal]
    shades = np.linspace(0.2, 0.8, num=len(non_optimal)) if non_optimal else []
    for idx, s in enumerate(non_optimal):
        color = str(shades[idx])
        plt.plot(
            range(1, len(s["cumulative"]) + 1),
            s["cumulative"],
            label=f"L{s['level']}",
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=4,
        )
    plt.plot(
        range(1, len(optimal["cumulative"]) + 1),
        optimal["cumulative"],
        label=f"L{optimal['level']} (optimal)",
        color="red",
        linewidth=2.8,
        marker="o",
        markersize=5,
    )
    plt.xlabel("Step #")
    plt.ylabel("Cumulative mass [g]")
    plt.title("Powder calibration - level exploration")
    plt.xticks(range(1, max_steps + 1))
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def plot_time_exploration(
    series: List[Dict[str, Any]], optimal_time: Dict[str, Any], out_path: Path
) -> None:
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError("matplotlib is required for plotting.") from exc

    plt.figure(figsize=(10, 6))
    max_steps = max(len(s["cumulative"]) for s in series)
    non_optimal = [s for s in series if s is not optimal_time]
    shades = np.linspace(0.2, 0.8, num=len(non_optimal)) if non_optimal else []
    for idx, s in enumerate(non_optimal):
        color = str(shades[idx])
        plt.plot(
            range(1, len(s["cumulative"]) + 1),
            s["cumulative"],
            label=f"{s['vib_time']:.2f}s",
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=4,
        )
    plt.plot(
        range(1, len(optimal_time["cumulative"]) + 1),
        optimal_time["cumulative"],
        label=f"{optimal_time['vib_time']:.2f}s (optimal)",
        color="red",
        linewidth=2.8,
        marker="o",
        markersize=5,
    )
    plt.xlabel("Step #")
    plt.ylabel("Cumulative mass [g]")
    plt.title(
        f"Powder calibration - time exploration (level {optimal_time['level']})"
    )
    plt.xticks(range(1, max_steps + 1))
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def plot_stability(series: Dict[str, Any], out_path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise RuntimeError("matplotlib is required for plotting.") from exc

    plt.figure(figsize=(10, 6))
    steps = range(1, len(series["per_step"]) + 1)
    plt.plot(steps, series["per_step"], marker="o", linestyle="-", label="Per-step mass")
    mean = series.get("mean_step_mass", 0.0)
    std = series.get("std_step_mass", 0.0)
    repeatability = (std / mean * 100.0) if mean else 0.0
    plt.axhline(mean, color="red", linestyle="--", label=f"Mean={mean:.6f}g")
    plt.xlabel("Step #")
    plt.ylabel("Per-step mass [g]")
    plt.title(
        f"Powder calibration - stability test (level {series['level']}, time {series['vib_time']:.2f}s)"
    )
    plt.xticks(range(1, len(series["per_step"]) + 1))
    plt.grid(True, alpha=0.3)
    summary_lines = [
        f"Mean: {mean:.3f} [g] (n={len(series['per_step'])})",
        f"Std. Dev.: {std:.3f} [g]",
        f"Repeatability: {repeatability:.2f} %",
    ]
    plt.gca().text(
        0.98,
        0.05,
        "\n".join(summary_lines),
        transform=plt.gca().transAxes,
        ha="right",
        va="bottom",
        fontsize=12,
        bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": "black"},
    )
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


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
