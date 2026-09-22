from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from sila2_servers.powder_characterizer_camera_server.drivers.camera import (
    PowderCharacterizerCamera,
)


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (7, 5), (20, 80, 140)).save(stream, format="PNG")
    return stream.getvalue()


def test_camera_returns_exact_captured_bytes_without_reencoding() -> None:
    expected = _png_bytes()

    def runner(command: list[str], *, check: bool) -> None:
        assert check is True
        output = Path(command[command.index("-o") + 1])
        output.write_bytes(expected)

    camera = PowderCharacterizerCamera(runner=runner)
    image = camera.capture_repose()

    assert image.data == expected
    assert image.media_type == "image/png"
    assert (image.width, image.height) == (7, 5)
