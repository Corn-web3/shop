"""Tier 1 enrichment orchestration + cache.

Thin layer over the Research agent: loads the product, runs enrichment, and
caches the result per SKU (re-running web search + extraction on every call
would be slow and waste budget — the README's B2 asks for caching). A trace bus
is created so the research steps are auditable like generation jobs.
"""

import threading

from app import trace
from app.db import load_product
from app.agents import research_agent

_cache = {}
_lock = threading.Lock()

# only facts at/above this confidence AND carrying a real source_url are safe to
# feed into the listing copy (degraded model-knowledge fields never qualify).
HIGH_CONF = 0.7


def run(sku: str, refresh: bool = False) -> dict:
    p = load_product(sku)  # raises KeyError if unknown
    with _lock:
        if not refresh and sku in _cache:
            cached = dict(_cache[sku])
            cached["cached"] = True
            return cached

    bus = trace.create()
    bus.emit("Research", f"enrich accepted: {sku}")
    record = research_agent.enrich(p, bus.emit)
    record["job_id"] = bus.job_id
    record["cached"] = False
    bus.finish(result=record)
    with _lock:
        _cache[sku] = record
    return record


def keywords(sku: str) -> list:
    """Buyer keywords for SEO/conversion, mined from cached enrichment (selling
    points + compliance keywords that carry a source). Empty when no cached
    enrichment / no search — safe no-op."""
    with _lock:
        rec = _cache.get(sku)
    kws = []
    if rec:
        for f in rec.get("fields", []):
            if (f.get("name") in ("common_selling_points", "compliance_keywords")
                    and f.get("source_url")):
                v = f.get("value")
                kws += v if isinstance(v, list) else [v]
    # de-dupe, keep order
    seen, out = set(), []
    for k in kws:
        k = str(k).strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out[:20]


_kw_cache = {}


def buyer_keywords(sku: str) -> list:
    """SEO: high-intent buyer SEARCH keywords for the product, mined from a
    dedicated web search + LLM extraction (merged with enrichment keywords).
    Cached per SKU. Degrades to enrichment-only / empty when no search+LLM."""
    with _lock:
        if sku in _kw_cache:
            return _kw_cache[sku]
    from app.tools import research
    base = keywords(sku)  # from cached enrichment (selling points / compliance)
    if not (research.available() and llm_ready()):
        return base
    p = load_product(sku)
    hits = research.search(
        f"{p.category} {p.title} amazon best selling buyer search keywords",
        max_results=6)
    if not hits:
        return base
    src = "\n".join(f"- {h['title']}: {h['snippet'][:200]}" for h in hits)
    from app.tools import llm
    try:
        out = llm.chat_json(
            "Extract 10-15 high-intent Amazon buyer SEARCH keywords (short noun "
            "phrases shoppers actually type) for this product, taken from the "
            "sources. No brand names, no promotional words. "
            'Return JSON: {"keywords": [str]}.',
            f"Product: {p.brand} {p.title} | {p.category} | {p.material}\n"
            f"Sources:\n{src}")
        mined = [str(k).strip() for k in out.get("keywords", []) if str(k).strip()]
    except Exception:
        mined = []
    seen, merged = set(), []
    for k in mined + base:                 # mined (search-intent) first
        if k.lower() not in seen:
            seen.add(k.lower())
            merged.append(k)
    result = merged[:20]
    with _lock:
        _kw_cache[sku] = result
    return result


def llm_ready() -> bool:
    from app.tools import llm
    return llm.available()


def sourced_facts(sku: str) -> list:
    """HIGH-confidence, source-cited enrichment fields that are safe to feed
    into the Copy agent (closes the README's enrich -> generate loop). Uses the
    cache; only spends a fresh research call when web search is actually
    available, so degraded (source-less) facts are never injected."""
    from app.tools import research
    with _lock:
        record = _cache.get(sku)
    if record is None:
        if not research.available():
            return []          # no search -> nothing verifiable to inject
        record = run(sku)
    facts = []
    for f in record.get("fields", []):
        if f.get("source_url") and float(f.get("confidence") or 0) >= HIGH_CONF:
            facts.append({"name": f.get("name"), "value": f.get("value"),
                          "source_url": f.get("source_url"),
                          "confidence": f.get("confidence")})
    return facts
