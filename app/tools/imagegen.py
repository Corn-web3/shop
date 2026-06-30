"""Image generation tool.

Online: OpenAI-compatible images endpoint (gpt-image-2), requested at a native
>=1536 size (no fake upscaling), then bg-cleaned so near-white pixels snap to
exactly (255,255,255) for strict Amazon main-image compliance.
Offline: PIL-synthesized white-bg image with `count` objects so the pipeline
still runs end-to-end without keys.
"""

import base64
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw

from app import metrics
from app.config import settings
from app.db import Product

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

SIZE = 1600              # final long edge (Amazon zoom threshold)
GEN_SIZE = "1536x1536"   # native gen size requested from the model
SNAP_TOL = 8             # near-white within this of 255 snaps to pure white

_COLORS = {
    "matte black": (30, 30, 30), "black": (20, 20, 20), "blue": (40, 90, 200),
    "red": (200, 40, 40), "green": (40, 160, 80), "forest green": (34, 90, 50),
    "white": (235, 235, 235), "silver": (180, 180, 185), "gray": (130, 130, 130),
    "grey": (130, 130, 130),
}


def _rgb(name: str):
    return _COLORS.get(name.lower(), (90, 90, 90))


def build_prompt(p: Product, count: int) -> str:
    item_word = "one item" if count == 1 else f"{count} identical items"
    return (
        f"Product photography of {item_word}: a {p.color} {p.material} "
        f"{p.title}. Show exactly {count} unit(s), no more, no less. "
        f"Pure white background (RGB 255,255,255), studio lighting, no shadow, "
        f"no props, no text or watermark. Product fills at least 85% of the "
        f"frame. Square 1:1 aspect ratio."
    )


def build_combo_prompt(products) -> str:
    items = "; ".join(
        f"a {p.color} {p.material} {p.title}" for p in products)
    n = len(products)
    return (
        f"Product photography of a bundle of {n} DIFFERENT items shown together "
        f"side by side in one frame: {items}. Show exactly one of each item "
        f"({n} items total). Pure white background (RGB 255,255,255), studio "
        f"lighting, no shadow, no props, no text or watermark. The group fills "
        f"at least 85% of the frame. Square 1:1 aspect ratio."
    )


def snap_white_background(img: Image.Image) -> Image.Image:
    """Snap near-white pixels to exactly (255,255,255). Generated images come
    back ~254; Amazon requires precise 255. Done with C-level band ops (a
    per-pixel Python loop over 1600^2 pixels would take seconds)."""
    t = 255 - SNAP_TOL
    bands = [b.point(lambda v: 255 if v >= t else 0).convert("1")
             for b in img.split()]
    mask = ImageChops.logical_and(ImageChops.logical_and(bands[0], bands[1]), bands[2])
    img.paste((255, 255, 255), (0, 0), mask)
    return img


def _synthesize(p: Product, count: int, path: str):
    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    d = ImageDraw.Draw(img)
    color = _rgb(p.color)
    margin = int(SIZE * 0.06)
    avail = SIZE - 2 * margin
    slot = avail / count
    body_w = min(slot * 0.6, avail * 0.5)
    for i in range(count):
        cx = margin + slot * (i + 0.5)
        x0, x1 = cx - body_w / 2, cx + body_w / 2
        d.rounded_rectangle([x0, margin + body_w * 0.4, x1, SIZE - margin],
                            radius=int(body_w * 0.25), fill=color)
        cap_w = body_w * 0.5
        d.rounded_rectangle([cx - cap_w / 2, margin, cx + cap_w / 2, margin + body_w * 0.5],
                            radius=int(cap_w * 0.2),
                            fill=tuple(int(c * 0.7) for c in color))
    _save(img, path)


def _synthesize_combo(products, path: str):
    """Offline placeholder: one differently-colored object per product."""
    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    d = ImageDraw.Draw(img)
    n = len(products)
    margin = int(SIZE * 0.06)
    avail = SIZE - 2 * margin
    slot = avail / n
    body_w = min(slot * 0.6, avail * 0.4)
    for i, p in enumerate(products):
        color = _rgb(p.color)
        cx = margin + slot * (i + 0.5)
        x0, x1 = cx - body_w / 2, cx + body_w / 2
        # full-height body so the group fills >=85% of the frame
        d.rounded_rectangle([x0, margin, x1, SIZE - margin],
                            radius=int(body_w * 0.25), fill=color)
    _save(img, path)


GEN_SIZE_LANDSCAPE = "1536x1024"  # for landscape A+ module / scene images


def _fetch(prompt: str, gen_size: str) -> Image.Image:
    """Call the image model and return a PIL RGB image (b64 or url response)."""
    metrics.add_image()
    kwargs = {"api_key": settings.image_api_key}
    if settings.image_base_url:
        kwargs["base_url"] = settings.image_base_url
    resp = OpenAI(**kwargs).images.generate(
        model=settings.image_model, prompt=prompt, size=gen_size)
    datum = resp.data[0]
    # Most OpenAI-compatible image models return base64; some return a URL.
    if getattr(datum, "b64_json", None):
        raw = base64.b64decode(datum.b64_json)
    elif getattr(datum, "url", None):
        import urllib.request
        with urllib.request.urlopen(datum.url) as r:
            raw = r.read()
    else:
        raise RuntimeError("image response had neither b64_json nor url")
    return Image.open(BytesIO(raw)).convert("RGB")


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    """Cover-crop to exactly (w, h) without distortion."""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((max(w, int(sw * scale)), max(h, int(sh * scale))))
    sw, sh = img.size
    left, top = (sw - w) // 2, (sh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _save(img: Image.Image, path: str):
    """Save honoring extension. Main/hero images are JPEG (Amazon §6) at high
    quality + 4:4:4 chroma so the flat white background stays at exactly 255
    (lossy subsampling would otherwise shift near-edge whites)."""
    if path.lower().endswith((".jpg", ".jpeg")):
        img.save(path, "JPEG", quality=95, subsampling=0)
    else:
        img.save(path)


def _render_online(prompt: str, path: str):
    img = _fetch(prompt, GEN_SIZE)
    if max(img.size) < SIZE:
        img = img.resize((SIZE, SIZE))
    _save(snap_white_background(img), path)


def _online_ready() -> bool:
    return bool(settings.image_ready and OpenAI is not None)


def generate(p: Product, count: int, path: str) -> dict:
    """Multipack/single main image. Raises on online failure so the caller
    decides whether to fall back or surface the error."""
    prompt = build_prompt(p, count)
    if _online_ready():
        _render_online(prompt, path)
        mode = "generated"
    else:
        _synthesize(p, count, path)
        mode = "synthesized"
    return {"path": path, "mode": mode, "intended_count": count, "prompt": prompt}


def generate_combo(products, path: str) -> dict:
    """Combo main image: all distinct products together in one frame."""
    prompt = build_combo_prompt(products)
    if _online_ready():
        _render_online(prompt, path)
        mode = "generated"
    else:
        _synthesize_combo(products, path)
        mode = "synthesized"
    return {"path": path, "mode": mode, "intended_count": len(products),
            "prompt": prompt}


def _synthesize_module(products, w: int, h: int, headline: str, path: str):
    """Offline A+ module placeholder at exact (w, h): product color swatch +
    a headline bar, so layout/dimension checks run without keys."""
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    n = len(products)
    pad = int(h * 0.12)
    bw = (w - pad * (n + 1)) / n
    for i, p in enumerate(products):
        x0 = pad + i * (bw + pad)
        d.rounded_rectangle([x0, pad, x0 + bw, h - pad * 2.2],
                            radius=int(min(bw, h) * 0.06), fill=_rgb(p.color))
    d.rectangle([0, h - pad * 1.6, w, h], fill=(20, 20, 20))
    d.text((pad, h - int(pad * 1.3)), headline[:60], fill=(255, 255, 255))
    img.save(path)


def generate_module(products, w: int, h: int, prompt: str, headline: str,
                    path: str) -> dict:
    """Generate one A+ module / scene image at exact (w, h). No white-bg snap:
    A+ modules may be lifestyle/infographic, not pure-white hero shots."""
    if _online_ready():
        gen = GEN_SIZE_LANDSCAPE if w >= h else GEN_SIZE
        _fit(_fetch(prompt, gen), w, h).save(path)
        mode = "generated"
    else:
        _synthesize_module(products, w, h, headline, path)
        mode = "synthesized"
    return {"path": path, "mode": mode, "size": [w, h], "prompt": prompt}
