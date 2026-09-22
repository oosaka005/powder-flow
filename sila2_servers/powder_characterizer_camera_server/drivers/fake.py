from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from .camera import CapturedImage


class FakePowderCharacterizerCamera:
    status = "ready"

    @staticmethod
    def _image(media_type: str) -> CapturedImage:
        image = Image.new("RGB", (800, 480), (231, 228, 217))
        draw = ImageDraw.Draw(image)
        draw.text((36, 36), "Powder Characterizer Camera Fake", fill=(20, 78, 61))
        stream = BytesIO()
        is_png = media_type == "image/png"
        image.save(stream, format="PNG" if is_png else "JPEG")
        suffix = "png" if is_png else "jpg"
        return CapturedImage(
            stream.getvalue(), media_type, f"fake_preview.{suffix}", 800, 480
        )

    def capture(self, **_kwargs) -> CapturedImage:
        return self._image("image/jpeg")

    def capture_repose(self) -> CapturedImage:
        return self._image("image/png")
