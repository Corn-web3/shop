"""Research agent (Tier 1 enrichment).

Given a product, searches the web for category norms, competitor specs, common
selling points, compliance keywords, and certifications, then has the LLM
extract STRUCTURED fields that each cite a source URL, carry a confidence, and
flag conflicts / missing data. Hard rule: never fabricate numeric specs; if a
fact isn't supported by a source, it is marked low-confidence or listed under
`missing`.
"""

from typing import List

from app.db import Product
from app.tools import llm, research

TARGET_FIELDS = [
    "category_norms", "common_selling_points", "compliance_keywords",
    "certifications", "competitor_specs",
]

SYSTEM = (
    "You are a product-listing research analyst. Extract enrichment fields for "
    "an Amazon listing. STRICT RULES: (1) cite a source_url for every field, "
    "taken ONLY from the provided sources; (2) NEVER invent numeric "
    "specifications — if a number isn't in a source, leave it out; (3) if "
    "sources disagree, add an entry to conflicts; (4) if a target field has no "
    "support, add it to missing with a short note. confidence is 0..1. "
    'Return JSON: {"fields": [{"name": str, "value": str|list, "source_url": '
    'str, "confidence": number, "note": str}], "conflicts": [{"field": str, '
    '"values": list, "sources": list, "note": str}], "missing": [{"field": '
    'str, "note": str}]}.'
)

DEGRADED_SYSTEM = (
    "You are a product-listing research analyst with NO web access. Provide "
    "GENERAL, category-level guidance only. STRICT RULES: (1) set source_url to "
    "null for every field; (2) confidence must be <= 0.4; (3) note must say "
    "'unverified model knowledge'; (4) do NOT provide numeric competitor specs "
    "or certifications you cannot verify — list those under missing. "
    'Return JSON: {"fields": [{"name": str, "value": str|list, "source_url": '
    'null, "confidence": number, "note": str}], "conflicts": [], "missing": '
    '[{"field": str, "note": str}]}.'
)


def _queries(p: Product) -> List[str]:
    cat = p.category.split("/")[-1].strip()
    return [
        f"{cat} Amazon listing requirements category guidelines",
        f"{p.title} {p.material} specifications competitor products",
        f"{cat} common selling points buyer features",
        f"{cat} safety compliance certifications {p.material}",
    ]


def _gather(p: Product, emit) -> list:
    sources, seen = [], set()
    for q in _queries(p):
        for r in research.search(q, max_results=4):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            sources.append(r)
    emit("Research", f"collected {len(sources)} unique sources from web search")
    return sources


def enrich(p: Product, emit=lambda *a, **k: None) -> dict:
    base = {"sku": p.sku, "targets": TARGET_FIELDS,
            "search_available": research.available()}

    if not llm.available():
        emit("Research", "no LLM key -> cannot extract; returning empty record")
        return {**base, "fields": [], "conflicts": [],
                "missing": [{"field": f, "note": "no LLM configured"}
                            for f in TARGET_FIELDS],
                "sources": []}

    sources = _gather(p, emit) if research.available() else []
    prod = (f"Product: {p.brand} {p.title} | category {p.category} | "
            f"color {p.color} | material {p.material} | "
            f"size {p.length_cm}x{p.width_cm}x{p.height_cm} cm | {p.weight_g} g")

    if sources:
        src_block = "\n".join(
            f"[{i+1}] {s['url']}\n{s['snippet'][:600]}" for i, s in enumerate(sources))
        user = (f"{prod}\n\nTarget fields: {', '.join(TARGET_FIELDS)}\n\n"
                f"Sources:\n{src_block}")
        system = SYSTEM
    else:
        emit("Research", "no web search available -> degraded model-knowledge mode")
        user = (f"{prod}\n\nTarget fields: {', '.join(TARGET_FIELDS)}\n"
                "No web sources are available.")
        system = DEGRADED_SYSTEM

    try:
        out = llm.chat_json(system, user)
    except Exception as e:
        emit("Research", f"extraction failed: {e}")
        return {**base, "fields": [], "conflicts": [],
                "missing": [{"field": f, "note": f"extraction failed: {e}"}
                            for f in TARGET_FIELDS], "sources": []}

    fields = out.get("fields", [])
    emit("Research", f"extracted {len(fields)} field(s), "
                     f"{len(out.get('conflicts', []))} conflict(s), "
                     f"{len(out.get('missing', []))} missing")
    return {**base, "fields": fields, "conflicts": out.get("conflicts", []),
            "missing": out.get("missing", []),
            "sources": [s["url"] for s in sources]}
