"""B5 — evaluation harness.

Given SKUs, generate a listing for each and score it on two axes, deterministically:
  - quality (0-100): from the B1 compliance report + structural completeness
  - physical (0-100): fraction of the Critic's hard image checks that passed

No model-as-judge: scores derive from the same deterministic signals the
pipeline already produces, so the harness is reproducible and free to run.
"""

from app import jobs, trace
from app.db import load_product


def score_quality(listing: dict) -> dict:
    comp = listing.get("compliance", {})
    errors = comp.get("error_count", 0)
    warns = comp.get("warn_count", 0)
    score = 100 - 15 * errors - 3 * warns
    copy = listing.get("copy", {})
    if len(copy.get("bullets", [])) != 5:
        score -= 10
    if not listing.get("a_plus_modules"):
        score -= 10
    if not copy.get("search_terms"):
        score -= 5
    return {"score": max(0, min(100, score)),
            "compliance_errors": errors, "compliance_warnings": warns}


def score_physical(listing: dict) -> dict:
    critic = listing.get("critic", {})
    checks = critic.get("checks", [])
    hard = [c for c in checks
            if not c.get("skipped") and not c.get("informational")]
    passed = [c for c in hard if c.get("pass")]
    score = round(100 * len(passed) / len(hard)) if hard else 0
    return {"score": score, "checks_passed": len(passed),
            "checks_total": len(hard),
            "overall_pass": bool(critic.get("overall_pass"))}


def evaluate_one(sku: str, units: int = 1) -> dict:
    load_product(sku)  # KeyError -> caller maps to 404
    bus = trace.create()
    spec = {"kind": "multipack" if units > 1 else "single",
            "skus": [sku], "units": units}
    listing = jobs.run_sync(bus, spec)
    q = score_quality(listing)
    ph = score_physical(listing)
    return {"sku": sku, "units": units,
            "quality_score": q["score"], "physical_score": ph["score"],
            "compliant": listing.get("compliant"),
            "quality_detail": q, "physical_detail": ph}


def run(skus: list, units: int = 1) -> dict:
    scores = []
    for sku in skus:
        try:
            scores.append(evaluate_one(sku, units))
        except KeyError:
            scores.append({"sku": sku, "error": "unknown sku"})
    valid = [s for s in scores if "error" not in s]
    summary = {
        "count": len(valid),
        "avg_quality": round(sum(s["quality_score"] for s in valid) / len(valid), 1)
        if valid else 0,
        "avg_physical": round(sum(s["physical_score"] for s in valid) / len(valid), 1)
        if valid else 0,
        "compliant_rate": round(sum(1 for s in valid if s["compliant"]) / len(valid), 2)
        if valid else 0,
    }
    return {"scores": scores, "summary": summary}
