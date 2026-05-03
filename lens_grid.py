"""
lens_grid.py - compose extracted video frames into a single labeled grid image.

Vision models on Groq (Llama 3.2 / Llama 4) accept one image per request,
so we tile every frame into one grid with timestamp labels burned on each
tile. The resulting JPEG is small enough to fit in a single API call.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Optional


def build_frame_grid(frames, *, max_size_kb: int = 3500) -> Optional[str]:
    """Compose frames into one labeled grid image. Returns base64 JPEG.

    Iteratively shrinks tile dims and JPEG quality until the encoded image
    fits under max_size_kb. Returns None if PIL is unavailable or the
    frames list is empty.
    """
    if not frames:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    n = len(frames)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))

    tile_w = 480
    tile_h = 270
    quality = 78

    def _compose(tw: int, th: int, q: int) -> bytes:
        canvas = Image.new("RGB", (tw * cols, th * rows), color=(20, 20, 20))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(14, th // 16))
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("arial.ttf", max(14, th // 16))
            except (OSError, IOError):
                font = ImageFont.load_default()

        for idx, frame in enumerate(frames):
            row = idx // cols
            col = idx % cols
            x = col * tw
            y = row * th
            try:
                img_bytes = base64.standard_b64decode(frame.base64_jpeg)
                im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                im_w, im_h = im.size
                ratio = min(tw / im_w, th / im_h)
                new_w = max(1, int(im_w * ratio))
                new_h = max(1, int(im_h * ratio))
                im = im.resize((new_w, new_h), Image.LANCZOS)
                offset_x = x + (tw - new_w) // 2
                offset_y = y + (th - new_h) // 2
                canvas.paste(im, (offset_x, offset_y))
            except Exception:
                continue

            label = frame.clock()
            try:
                bbox = draw.textbbox((0, 0), label, font=font)
                txt_w = bbox[2] - bbox[0]
                txt_h = bbox[3] - bbox[1]
            except AttributeError:
                txt_w, txt_h = draw.textsize(label, font=font)
            pad = 4
            draw.rectangle(
                [(x + 2, y + 2), (x + 2 + txt_w + pad * 2, y + 2 + txt_h + pad * 2)],
                fill=(0, 0, 0),
            )
            draw.text((x + 2 + pad, y + 2 + pad), label, fill=(255, 255, 255), font=font)

        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=q, optimize=True)
        return buf.getvalue()

    img_bytes = _compose(tile_w, tile_h, quality)
    while len(img_bytes) > max_size_kb * 1024 and (tile_w > 240 or quality > 50):
        if quality > 60:
            quality -= 8
        else:
            tile_w = int(tile_w * 0.85)
            tile_h = int(tile_h * 0.85)
        img_bytes = _compose(tile_w, tile_h, quality)

    return base64.standard_b64encode(img_bytes).decode("ascii")
