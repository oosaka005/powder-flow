"""First-layer camera driver that returns captured bytes without re-encoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import threading

from PIL import Image


DEFAULT_TIMEOUT_MS = 100


@dataclass(frozen=True)
class CapturedImage:
    data: bytes
    media_type: str
    filename: str
    width: int
    height: int


class PowderCharacterizerCamera:
    def __init__(self, *, runner=subprocess.run) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self.status = "ready"

    def _capture(
        self,
        *,
        suffix: str,
        rotation: int,
        autofocus_mode: str,
        lens_position: float | None,
    ) -> CapturedImage:
        with self._lock:
            self.status = "busy"
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                    tmp_path = Path(handle.name)
                cmd = [
                    "rpicam-still",
                    "-o",
                    str(tmp_path),
                    "-t",
                    str(DEFAULT_TIMEOUT_MS),
                    "-n",
                ]
                if rotation:
                    cmd += ["--rotation", str(rotation)]
                if autofocus_mode:
                    cmd += ["--autofocus-mode", autofocus_mode]
                if autofocus_mode == "manual" and lens_position is not None:
                    cmd += ["--lens-position", str(lens_position)]
                self._runner(cmd, check=True)
                data = tmp_path.read_bytes()
                with Image.open(tmp_path) as image:
                    width, height = image.size
                media_type = "image/png" if suffix.lower() == ".png" else "image/jpeg"
                self.status = "ready"
                return CapturedImage(data, media_type, tmp_path.name, width, height)
            except Exception:
                self.status = "fault"
                raise
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

    def capture(
        self,
        *,
        rotation: int = 180,
        autofocus_mode: str = "auto",
        lens_position: float | None = None,
    ) -> CapturedImage:
        return self._capture(
            suffix=".jpg",
            rotation=rotation,
            autofocus_mode=autofocus_mode,
            lens_position=lens_position,
        )

    def capture_repose(self) -> CapturedImage:
        return self._capture(
            suffix=".png",
            rotation=180,
            autofocus_mode="manual",
            lens_position=32.0,
        )
