"""Deterministic physical recomputation for multipack / combo.

Tier 3 requires that when a SKU becomes a 3-pack (or A+B becomes a combo) the
physical parameters are RE-COMPUTED, not guessed by the LLM: total weight,
packaging weight, and package dimensions. Doing this in code (not the model)
keeps the numbers correct and auditable; assumptions are returned alongside the
result so the listing can be transparent.
"""

import math
from typing import List, Tuple

from app.db import Product

# transparent, tunable packing assumptions
BOX_BASE_G = 25.0        # empty box + label
PAD_PER_ITEM_G = 8.0     # padding/separator per unit
PAD_CM = 1.0             # padding added to each package dimension


def _grid(n: int) -> Tuple[int, int]:
    """Arrange n identical items in a near-square grid (cols, rows)."""
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return cols, rows


def repack(items: List[Tuple[Product, int]], kind: str) -> dict:
    """items: list of (product, qty). Returns recomputed physical block."""
    total_units = sum(q for _, q in items)
    product_weight = sum(p.weight_g * q for p, q in items)
    packaging_weight = round(BOX_BASE_G + PAD_PER_ITEM_G * total_units, 1)
    total_weight = round(product_weight + packaging_weight, 1)

    if kind == "combo":
        # different products placed side by side
        L = sum(p.length_cm for p, _ in items) + PAD_CM * (len(items) + 1)
        W = max(p.width_cm for p, _ in items) + 2 * PAD_CM
        H = max(p.height_cm for p, _ in items) + 2 * PAD_CM
        arrangement = "side-by-side"
    else:
        # identical units in a near-square grid (single product, qty = units)
        p = items[0][0]
        cols, rows = _grid(total_units)
        L = cols * p.length_cm + PAD_CM * (cols + 1)
        W = rows * p.width_cm + PAD_CM * (rows + 1)
        H = p.height_cm + 2 * PAD_CM
        arrangement = f"{cols}x{rows} grid"

    return {
        "total_units": total_units,
        "product_weight_g": round(product_weight, 1),
        "packaging_weight_g": packaging_weight,
        "total_weight_g": total_weight,
        "package_dimensions_cm": {
            "length": round(L, 1), "width": round(W, 1), "height": round(H, 1)},
        "arrangement": arrangement,
        "assumptions": [
            f"box+label base {BOX_BASE_G} g",
            f"padding {PAD_PER_ITEM_G} g and {PAD_CM} cm per unit/side",
            "units packed upright" if kind != "combo" else "items packed side by side",
        ],
    }
