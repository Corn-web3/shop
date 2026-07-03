"""Persistent listing library.

Completed listings are written to data/listings/{job_id}.json and indexed so the
UI's Library survives restarts (the trace bus is in-memory only). Images already
live in app/out and are served at /out/{file}.
"""

import json
import os
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_ROOT, "data", "listings")
os.makedirs(DATA_DIR, exist_ok=True)

_lock = threading.Lock()


def _summary(job_id: str, listing: dict) -> dict:
    spec = listing.get("spec", {})
    return {
        "job_id": job_id,
        "kind": spec.get("kind"),
        "skus": spec.get("skus", []),
        "title": (listing.get("copy") or {}).get("title", ""),
        "main_image": (listing.get("main_image") or {}).get("file"),
        "compliant": listing.get("compliant"),
        "units": (listing.get("physical") or {}).get("total_units"),
        "created_at": listing.get("created_at") or time.time(),
    }


def save(job_id: str, listing: dict) -> None:
    listing.setdefault("created_at", time.time())
    listing["job_id"] = job_id
    with _lock:
        with open(os.path.join(DATA_DIR, f"{job_id}.json"), "w") as f:
            json.dump(listing, f, ensure_ascii=False, indent=2)


def get(job_id: str):
    path = os.path.join(DATA_DIR, f"{job_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def list_summaries() -> list:
    out = []
    with _lock:
        files = [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]
    for fn in files:
        try:
            with open(os.path.join(DATA_DIR, fn)) as f:
                out.append(_summary(fn[:-5], json.load(f)))
        except Exception:
            continue
    return sorted(out, key=lambda s: s["created_at"], reverse=True)
