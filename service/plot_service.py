from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


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
