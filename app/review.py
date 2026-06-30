"""B4 — human-in-the-loop review gate + original-vs-recomposed diff.

A generated listing is retained on its trace bus (bus.result). A reviewer can
approve/reject it before "publish" (publishing itself is out of scope per the
README — we stop at the content object). The diff compares two listings (e.g.
the original single listing vs. a recomposed multipack/combo) field by field so
a human can see exactly what changed.
"""

import threading
import time

from app import trace

_DECISIONS = {"approve", "reject", "pending"}
_reviews = {}
_lock = threading.Lock()


def set_decision(job_id: str, decision: str, note: str = "") -> dict:
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {sorted(_DECISIONS)}")
    bus = trace.get(job_id)
    if not bus:
        raise KeyError(job_id)
    rec = {"job_id": job_id, "decision": decision, "note": note,
           "reviewed_at": time.time()}
    with _lock:
        _reviews[job_id] = rec
    return rec


def get_decision(job_id: str) -> dict:
    with _lock:
        return _reviews.get(job_id, {"job_id": job_id, "decision": "pending",
                                     "note": "", "reviewed_at": None})


def _listing(job_id: str) -> dict:
    bus = trace.get(job_id)
    if not bus or not bus.result:
        raise KeyError(job_id)
    return bus.result


def _summarize(listing: dict) -> dict:
    copy = listing.get("copy", {})
    phys = listing.get("physical", {})
    return {
        "kind": (listing.get("spec") or {}).get("kind"),
        "skus": (listing.get("spec") or {}).get("skus"),
        "title": copy.get("title"),
        "bullets": copy.get("bullets", []),
        "search_terms": copy.get("search_terms"),
        "total_units": phys.get("total_units"),
        "total_weight_g": phys.get("total_weight_g"),
        "package_dimensions_cm": phys.get("package_dimensions_cm"),
        "a_plus_module_count": len(listing.get("a_plus_modules", [])),
        "main_image": (listing.get("main_image") or {}).get("file"),
        "compliant": listing.get("compliant"),
    }


def diff(base_job: str, recomposed_job: str) -> dict:
    a, b = _summarize(_listing(base_job)), _summarize(_listing(recomposed_job))
    changes = {}
    for k in a:
        if a[k] != b[k]:
            changes[k] = {"base": a[k], "recomposed": b[k]}
    return {"base_job": base_job, "recomposed_job": recomposed_job,
            "changed_fields": list(changes), "diff": changes,
            "base": a, "recomposed": b}
