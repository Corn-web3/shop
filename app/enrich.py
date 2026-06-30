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
