"""
Simple wrapper for capturing still images with the Raspberry Pi Camera Module 3 NoIR.
"""

import subprocess
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT_MS = 100  # rpicam-still -t value (capture duration)


def capture_image(
    output_path: Path | str,
    *,
    rotation: int = 180,
    autofocus_mode: Optional[str] = None,
    lens_position: Optional[float] = None,
) -> None:
    """
    Capture a still image using rpicam-still.

    Args:
        output_path: Destination path for the captured image (JPEG by default).
        rotation: Rotate image by 0/90/180/270 degrees.
        autofocus_mode: Optional autofocus mode (e.g., "manual").
        lens_position: Optional lens position when autofocus_mode is manual.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rpicam-still",
        "-o",
        str(path),
        "-t",
        str(DEFAULT_TIMEOUT_MS),
        "-n",
    ]

    if rotation:
        cmd += ["--rotation", str(rotation)]
    if autofocus_mode is not None:
        cmd += ["--autofocus-mode", str(autofocus_mode)]
    if lens_position is not None:
        cmd += ["--lens-position", str(lens_position)]

    subprocess.run(cmd, check=True)


def capture_powder_image(output_path: Path | str) -> None:
    """
    Capture a still image optimized for powder imaging.
    """
    capture_image(
        output_path,
        rotation=180,
        autofocus_mode="manual",
        lens_position=32.0,
    )


__all__ = ["capture_image", "capture_powder_image", "DEFAULT_OUTPUT_DIR"]
