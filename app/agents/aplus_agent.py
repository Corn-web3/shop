"""A+ content agent: builds the A+ image-text modules + scene image set.

Runs after the main (hero) image is finalized. For each planned module it pairs
LLM-written copy (headline/body/alt) with a generated module image at the exact
Amazon module dimensions (970x600, 970x300). Module images may be lifestyle /
feature shots, so they are NOT held to the pure-white-bg hero rule — but each
must carry alt text (checked by the B1 validator).
"""

import os
from typing import List

from app.config import OUT_DIR
from app.db import Product
from app.agents import copy_agent
from app.tools import imagegen


def _image_prompt(mtype: str, products: List[Product]) -> str:
    desc = " and ".join(f"a {p.color} {p.material} {p.title}" for p in products)
    if mtype == "lifestyle":
        return (f"Lifestyle product photograph of {desc} being used in a bright "
                f"everyday setting, photorealistic, true to the product's color "
                f"and material, no text, no watermark.")
    return (f"Clean studio feature shot of {desc} on a soft neutral gradient "
            f"background, highlighting material and finish, no text, no watermark.")


def run(kind: str, products: List[Product], physical: dict, job_id: str,
        emit=lambda *a, **k: None) -> List[dict]:
    plan = {t: (w, h) for t, w, h in copy_agent.MODULE_PLAN}
    mod_copy = copy_agent.aplus_modules(kind, products, physical, emit)

    modules = []
    for i, mc in enumerate(mod_copy):
        mtype = mc.get("type", "feature")
        w, h = plan.get(mtype, (970, 600))
        fname = f"aplus_{job_id}_m{i}_{mtype}_{w}x{h}.png"
        path = os.path.join(OUT_DIR, fname)
        emit("A+", f"generating module image {mtype} {w}x{h}")
        img = imagegen.generate_module(
            products, w, h, _image_prompt(mtype, products),
            mc.get("headline", ""), path)
        img["file"] = fname
        modules.append({
            "type": mtype, "size": [w, h],
            "headline": mc.get("headline", ""), "body": mc.get("body", ""),
            "alt_text": mc.get("alt_text", ""), "image": img,
        })
    emit("A+", f"built {len(modules)} A+ module(s)")
    return modules
