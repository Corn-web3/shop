"""Image agent: produces the main image (pure white background).

The prompt injects the physical specs (count, color, material, proportions)
so the picture is supposed to match the database. The whole point of this
slice is to find out how well that holds up.

Online: OpenAI-compatible images endpoint (e.g. gpt-image-1).
Offline: synthesize a white-background image with `count` colored objects via
PIL, so the deterministic critic checks (white bg, coverage, count) have a
real image to chew on even with no keys.
"""

import base64
import os
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw

from product import Product

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

SIZE = 1600  # long edge >= 1600px so Amazon enables zoom

IMAGE_API_KEY = os.environ.get("IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL") or "gpt-image-1"

# crude color-name -> RGB map for the offline synthesizer
_COLORS = {
    "matte black": (30, 30, 30), "black": (20, 20, 20), "blue": (40, 90, 200),
    "red": (200, 40, 40), "green": (40, 160, 80), "white": (235, 235, 235),
    "silver": (180, 180, 185), "gray": (130, 130, 130), "grey": (130, 130, 130),
}


def _rgb(color_name: str):
    return _COLORS.get(color_name.lower(), (90, 90, 90))


def build_prompt(p: Product, count: int) -> str:
    item_word = "item" if count == 1 else f"{count} identical items"
    return (
        f"Product photography of {item_word}: a {p.color} {p.material} "
        f"{p.title}. Show exactly {count} unit(s), no more, no less. "
        f"Pure white background (RGB 255,255,255), studio lighting, no shadow, "
        f"no props, no text or watermark. Product fills at least 85% of the "
        f"frame. Aspect ratio square."
    )


def _synthesize(p: Product, count: int, path: str):
    """Draw `count` bottle-ish shapes on a pure-white canvas."""
    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    d = ImageDraw.Draw(img)
    color = _rgb(p.color)
    margin = int(SIZE * 0.06)
    avail = SIZE - 2 * margin
    slot = avail / count
    body_w = min(slot * 0.6, avail * 0.5)
    for i in range(count):
        cx = margin + slot * (i + 0.5)
        x0 = cx - body_w / 2
        x1 = cx + body_w / 2
        y0 = margin
        y1 = SIZE - margin
        # body
        d.rounded_rectangle([x0, y0 + body_w * 0.4, x1, y1],
                            radius=int(body_w * 0.25), fill=color)
        # cap
        cap_w = body_w * 0.5
        d.rounded_rectangle([cx - cap_w / 2, y0, cx + cap_w / 2, y0 + body_w * 0.5],
                            radius=int(cap_w * 0.2), fill=tuple(int(c * 0.7) for c in color))
    img.save(path)


def _online(p: Product, count: int, path: str) -> bool:
    if not (IMAGE_API_KEY and OpenAI is not None):
        return False
    try:
        kwargs = {"api_key": IMAGE_API_KEY}
        if IMAGE_BASE_URL:
            kwargs["base_url"] = IMAGE_BASE_URL
        client = OpenAI(**kwargs)
        resp = client.images.generate(
            model=IMAGE_MODEL,
            prompt=build_prompt(p, count),
            size="1024x1024",
        )
        b64 = resp.data[0].b64_json
        img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
        img = img.resize((SIZE, SIZE))
        img.save(path)
        return True
    except Exception as e:
        print(f"  [Image] gen failed ({e}); synthesizing placeholder")
        return False


def run(p: Product, count: int, path: str) -> dict:
    if _online(p, count, path):
        mode = "generated"
    else:
        if not (IMAGE_API_KEY and OpenAI is not None):
            print("  [Image] no image key -> synthesizing placeholder")
        _synthesize(p, count, path)
        mode = "synthesized"
    return {"path": path, "mode": mode, "intended_count": count,
            "prompt": build_prompt(p, count)}
