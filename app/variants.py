"""B3 — variant management + pricing suggestion.

For a SKU, builds a parent/child variant family along the color (and, when a
size token is in the title, size) axes, and suggests a price. The pricing basis
prefers competitor prices surfaced by Tier 1 enrichment; with none available it
falls back to a transparent heuristic band around the current price.
"""

import re
import statistics

from app import enrich
from app.db import load_product

COMMON_COLORS = ["Black", "White", "Blue", "Red", "Green", "Silver", "Pink"]
PRICE_RE = re.compile(r"(?:\$|USD\s?)?(\d{1,4}(?:\.\d{1,2})?)")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _color_variants(p) -> list:
    out = [{"axis": "color", "value": p.color, "sku": p.sku, "is_current": True}]
    for c in COMMON_COLORS:
        if c.lower() not in p.color.lower() and len(out) < 4:
            out.append({"axis": "color", "value": c,
                        "sku": f"{p.sku}-{c[:3].upper()}", "is_current": False})
    return out


def _size_variants(p) -> list:
    m = re.search(r"(\d+)\s?(ml|l|oz|cm|mm|g|kg|pack)", p.title, re.I)
    if not m:
        return []
    base, unit = int(m.group(1)), m.group(2)
    out = []
    for factor in (0.7, 1.5):
        val = int(round(base * factor))
        out.append({"axis": "size", "value": f"{val}{unit}",
                    "sku": f"{p.sku}-{val}{unit.upper()}", "is_current": False})
    out.insert(0, {"axis": "size", "value": f"{base}{unit}",
                   "sku": p.sku, "is_current": True})
    return out


def _competitor_prices(enrichment: dict) -> list:
    prices = []
    for f in enrichment.get("fields", []):
        if "price" not in (f.get("name", "") + str(f.get("value", ""))).lower():
            # only mine fields that actually mention price/competitor specs
            if f.get("name") not in ("competitor_specs", "pricing"):
                continue
        for token in re.findall(r"\$\s?\d{1,4}(?:\.\d{1,2})?", str(f.get("value"))):
            m = PRICE_RE.search(token)
            if m:
                prices.append(float(m.group(1)))
    return prices


def _pricing(p, enrichment: dict) -> dict:
    base = p.price
    comp = _competitor_prices(enrichment)
    if comp:
        med = round(statistics.median(comp), 2)
        suggested = round((med + base) / 2, 2)
        basis = f"midpoint of current price and competitor median ${med} (from enrichment, {len(comp)} prices)"
    else:
        suggested = base
        basis = "heuristic +/-15% band; no competitor price data in enrichment"
    return {"current_price": round(base, 2), "suggested_price": suggested,
            "range": [round(base * 0.85, 2), round(base * 1.15, 2)],
            "basis": basis}


def build_family(sku: str) -> dict:
    p = load_product(sku)  # KeyError -> 404
    enrichment = enrich.run(sku)
    variants = _color_variants(p) + _size_variants(p)
    return {
        "parent": {"family_id": _slug(f"{p.brand} {p.title.split(',')[0]}"),
                   "brand": p.brand, "base_title": p.title,
                   "category": p.category},
        "axes": sorted({v["axis"] for v in variants}),
        "variants": variants,
        "pricing_suggestion": _pricing(p, enrichment),
    }
