"""Image agent: generates the main image (pure white bg, correct items).

Spec-aware: multipack/single -> N identical units of one product; combo ->
all distinct products together in one frame.
"""

import os
from typing import List

from app.config import OUT_DIR
from app.db import Product
from app.tools import imagegen


def run(kind: str, products: List[Product], units: int, job_id: str,
        attempt: int = 1, emit=lambda *a, **k: None) -> dict:
    if kind == "combo":
        tag = "+".join(p.sku for p in products)
        fname = f"combo_{tag}_{job_id}_a{attempt}.jpg"  # hero image -> JPEG (§6)
        desc = f"combo of {len(products)} products"
        gen = lambda path: imagegen.generate_combo(products, path)
    else:
        tag = f"{products[0].sku}_x{units}"
        fname = f"{tag}_{job_id}_a{attempt}.jpg"  # hero image -> JPEG (§6)
        desc = f"{units} unit(s)"
        gen = lambda path: imagegen.generate(products[0], units, path)

    path = os.path.join(OUT_DIR, fname)
    emit("Image", f"generating main image: {desc}, white bg (attempt {attempt})")
    try:
        meta = gen(path)
    except Exception as e:
        emit("Image", f"generation failed: {e}")
        return {"path": None, "mode": "error", "error": str(e)}
    meta["file"] = fname
    emit("Image", f"{meta['mode']}: {fname}")
    return meta
