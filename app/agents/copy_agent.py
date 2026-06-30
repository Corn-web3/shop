"""Copy agent: title + 5 bullets + description + backend search terms.

Spec-aware: single, multipack (one SKU x N), or combo (distinct SKUs bundled).
Uses the recomputed physical block so bullets state the correct total weight.
"""

from typing import List

from app.db import Product
from app.tools import llm

SYSTEM = (
    "You are an Amazon listing copywriter. Follow Amazon A+ rules strictly: "
    "brand leads the title, title case, NO promotional/subjective words "
    "(best, free shipping, guaranteed, #1), title <= 150 chars. "
    "Exactly 5 benefit-led bullets, each <= 500 chars, no contact info. "
    "Backend search terms <= 250 bytes, space separated, no commas, no brand. "
    'Return JSON: {"title": str, "bullets": [str x5], "description": str, '
    '"search_terms": str}.'
)


def _multipack_user(p: Product, units: int, physical: dict) -> str:
    pack = "" if units == 1 else f"\n- this listing is a PACK OF {units} units"
    return (
        "Write a listing for this product. Stay factual to these specs:\n"
        f"- brand: {p.brand}\n- name: {p.title}\n- category: {p.category}\n"
        f"- color: {p.color}\n- material: {p.material}\n"
        f"- units per order: {units}{pack}\n"
        f"- single-unit size: {p.length_cm}x{p.width_cm}x{p.height_cm} cm\n"
        f"- total package weight: {physical['total_weight_g']} g\n- price: {p.price}"
    )


def _combo_user(products: List[Product], physical: dict) -> str:
    lines = []
    for p in products:
        lines.append(f"  * {p.brand} {p.title} | {p.color} | {p.material} | "
                     f"{p.weight_g} g")
    return (
        "Write ONE combined Amazon listing for a bundle of these distinct "
        "products (a combo). Merge and de-duplicate the selling points, and "
        "make the title clearly convey it is a bundle of both items:\n"
        + "\n".join(lines)
        + f"\n- total package weight: {physical['total_weight_g']} g"
    )


def _offline_multipack(p: Product, units: int, physical: dict) -> dict:
    pack = "" if units == 1 else f" (Pack of {units})"
    qty = f"{units} item" + ("" if units == 1 else "s")
    return {
        "title": f"{p.brand} {p.title}{pack} {p.color} {p.material}"[:150],
        "bullets": [
            f"MADE OF {p.material.upper()}: Durable {p.material.lower()} in a {p.color.lower()} finish.",
            f"RIGHT SIZE: Each unit measures {p.length_cm} x {p.width_cm} x {p.height_cm} cm.",
            f"PACK CONTENTS: Includes {qty}; total package weight {physical['total_weight_g']} g.",
            f"EVERYDAY USE: Built for {p.category.split('/')[0].strip().lower()} and daily carry.",
            "EASY CARE: Simple to clean and maintain for long-lasting performance.",
        ],
        "description": f"The {p.brand} {p.title} combines {p.material.lower()} "
        f"construction with a {p.color.lower()} finish for reliable everyday use.",
        "search_terms": f"{p.material.lower()} {p.color.lower()} reusable travel sport"[:250],
    }


def _offline_combo(products: List[Product], physical: dict) -> dict:
    names = " + ".join(p.title for p in products)
    brand = products[0].brand
    return {
        "title": f"{brand} {names} Bundle"[:150],
        "bullets": [
            f"COMPLETE BUNDLE: Includes {', '.join(p.title for p in products)} in one set.",
            *[f"{p.title.upper()}: {p.color} {p.material}, {p.height_cm} cm tall."
              for p in products[:2]],
            f"PACKED TOGETHER: Total package weight {physical['total_weight_g']} g.",
            "EVERYDAY USE: A coordinated set for daily hydration on the go.",
        ][:5],
        "description": f"This {brand} bundle pairs the "
        f"{' and '.join(p.title for p in products)} for everyday use.",
        "search_terms": "bundle set reusable travel sport hydration"[:250],
    }


# A+ module plan: (type, width, height). 970x600 full-width + 970x300 standard.
MODULE_PLAN = [("lifestyle", 970, 600), ("feature", 970, 300)]

APLUS_SYSTEM = (
    "You write Amazon A+ content modules. For each requested module return a "
    "short marketing headline (<= 60 chars), a body (<= 300 chars), and "
    "keyword-rich alt text describing the image (<= 100 chars). Factual to the "
    'specs. Return JSON: {"modules": [{"type": str, "headline": str, '
    '"body": str, "alt_text": str}]}.'
)


def _aplus_offline(kind, products, physical) -> List[dict]:
    p = products[0]
    names = " + ".join(x.title for x in products)
    out = []
    for mtype, w, h in MODULE_PLAN:
        if mtype == "lifestyle":
            head = f"{p.brand} {names} in Everyday Life"
            body = (f"See the {names} in action — {p.color.lower()} "
                    f"{p.material.lower()} built for daily use.")
            alt = f"{p.color} {p.material} {names} used in a lifestyle setting"
        else:
            head = f"Built From {p.material}"
            body = (f"Durable {p.material.lower()} construction, "
                    f"{physical['total_weight_g']} g total package weight.")
            alt = f"close-up of {p.color} {p.material} {p.title} features"
        out.append({"type": mtype, "headline": head, "body": body, "alt_text": alt})
    return out


def aplus_modules(kind: str, products: List[Product], physical: dict,
                  emit=lambda *a, **k: None) -> List[dict]:
    """Text for each A+ module (headline/body/alt). Image is added by the
    A+ agent. Online uses the LLM; offline falls back to templates."""
    if not llm.available():
        emit("A+", "writing A+ module copy (offline)")
        return _aplus_offline(kind, products, physical)
    specs = "\n".join(f"- {p.brand} {p.title} | {p.color} | {p.material}"
                      for p in products)
    want = ", ".join(f"{t} ({w}x{h})" for t, w, h in MODULE_PLAN)
    user = (f"Products:\n{specs}\nTotal package weight {physical['total_weight_g']} g."
            f"\nWrite these modules: {want}.")
    try:
        out = llm.chat_json(APLUS_SYSTEM, user)
        mods = out.get("modules", [])
        if mods:
            emit("A+", f"wrote {len(mods)} A+ module(s)")
            return mods
    except Exception as e:
        emit("A+", f"LLM failed ({e}); offline template")
    return _aplus_offline(kind, products, physical)


def run(kind: str, products: List[Product], units: int, physical: dict,
        emit=lambda *a, **k: None) -> dict:
    online = llm.available()
    if kind == "combo":
        emit("Copy", f"merging copy for combo of {len(products)} products"
                     + ("" if online else " (offline)"))
        if online:
            try:
                return llm.chat_json(SYSTEM, _combo_user(products, physical))
            except Exception as e:
                emit("Copy", f"LLM failed ({e}); offline template")
        return _offline_combo(products, physical)

    p = products[0]
    emit("Copy", f"generating A+ copy for {units}-unit listing"
                 + ("" if online else " (offline)"))
    if online:
        try:
            out = llm.chat_json(SYSTEM, _multipack_user(p, units, physical))
            emit("Copy", f"title: {out.get('title', '')[:80]}")
            return out
        except Exception as e:
            emit("Copy", f"LLM failed ({e}); offline template")
    out = _offline_multipack(p, units, physical)
    emit("Copy", f"title: {out['title'][:80]}")
    return out
