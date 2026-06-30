"""B2 — cost & observability.

Each generation job runs on a single thread (jobs.run_sync -> graph.invoke), so
a thread-local accumulator cleanly scopes per-job metrics without threading a
job_id through every tool call. Tools record token usage / image counts; the
graph wraps each node to record per-agent wall time. _assemble snapshots it into
the listing.

Costs are ESTIMATES (the gateway's gpt-5.x / gpt-image-2 prices aren't published
here); rates are overridable via env and clearly labelled as estimates.
"""

import os
import threading
import time
from contextlib import contextmanager

_local = threading.local()


def _rate(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default

# estimated USD rates (override via env)
USD_PER_1K_PROMPT = _rate("COST_PER_1K_PROMPT", 0.0005)
USD_PER_1K_COMPLETION = _rate("COST_PER_1K_COMPLETION", 0.0015)
USD_PER_IMAGE = _rate("COST_PER_IMAGE", 0.04)


def begin():
    _local.m = {
        "per_agent_seconds": {}, "llm_calls": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "image_calls": 0, "cache_hits": 0,
    }


def _m():
    m = getattr(_local, "m", None)
    if m is None:
        begin()
        m = _local.m
    return m


def add_llm(prompt_tokens=0, completion_tokens=0):
    m = _m()
    m["llm_calls"] += 1
    m["prompt_tokens"] += int(prompt_tokens or 0)
    m["completion_tokens"] += int(completion_tokens or 0)


def add_image(n=1):
    _m()["image_calls"] += n


def add_cache_hit(n=1):
    _m()["cache_hits"] += n


@contextmanager
def timed(agent: str):
    t0 = time.time()
    try:
        yield
    finally:
        m = _m()
        m["per_agent_seconds"][agent] = round(
            m["per_agent_seconds"].get(agent, 0.0) + (time.time() - t0), 3)


def snapshot() -> dict:
    m = _m()
    est_cost = round(
        m["prompt_tokens"] / 1000 * USD_PER_1K_PROMPT
        + m["completion_tokens"] / 1000 * USD_PER_1K_COMPLETION
        + m["image_calls"] * USD_PER_IMAGE, 4)
    return {
        **{k: m[k] for k in ("llm_calls", "prompt_tokens", "completion_tokens",
                             "image_calls", "cache_hits")},
        "per_agent_seconds": dict(m["per_agent_seconds"]),
        "total_seconds": round(sum(m["per_agent_seconds"].values()), 3),
        "estimated_cost_usd": est_cost,
        "cost_basis": "estimated; rates overridable via COST_PER_* env vars",
    }
