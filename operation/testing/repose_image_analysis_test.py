from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import cv2

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from operation.repose_analysis import (
    _analyze_direct_profile_angle,
    _preprocess_direct_profile,
    load_image,
)

# TODO: Update these before running the test.
MATERIAL_NAME = "ETHOCEL Std"
IMAGE_PATH = Path("/home/sdl-5/powder-flow/logs/experiments/20260116_144231_ETHOCEL Std/flowability/20260116_raw_image.png")


def main() -> None:
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(__file__).resolve().parent / "output"
    output_dir = output_root / f"{timestamp}_{MATERIAL_NAME}_image_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    arr = load_image(str(IMAGE_PATH))
    cropped, binary, binary_morph = _preprocess_direct_profile(arr)
    overlay, contour_overlay, left_angle, right_angle, mean_angle = _analyze_direct_profile_angle(
        cropped,
        binary_morph,
    )

    cv2.imwrite(str(output_dir / "00_original.png"), arr)
    cv2.imwrite(str(output_dir / "01_cropped.png"), cropped)
    cv2.imwrite(str(output_dir / "02_binary.png"), binary)
    cv2.imwrite(str(output_dir / "03_binary_morph.png"), binary_morph)
    cv2.imwrite(str(output_dir / "04_overlay_lines.png"), overlay)
    cv2.imwrite(str(output_dir / "05_contour_points.png"), contour_overlay)

    print(f"[repose] left_angle={left_angle:.6f}")
    print(f"[repose] right_angle={right_angle:.6f}")
    print(f"[repose] mean_angle={mean_angle:.6f}")
    print(f"[repose] outputs saved to {output_dir}")


if __name__ == "__main__":
    main()
