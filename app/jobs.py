"""Runs generation jobs (single/multipack/combo) in a background thread."""

import threading

from app import metrics, store, trace
from app.db import load_product
from app.graph import build_graph

_graph = build_graph()


def _assemble(spec: dict, state: dict) -> dict:
    critic = state.get("critic", {})
    compliance = state.get("compliance", {})
    # a listing is compliant only if BOTH the image (Critic) and the copy
    # (compliance validator) pass
    image_ok = bool(critic.get("overall_pass"))
    copy_ok = bool(compliance.get("compliant", True))
    aplus = state.get("aplus") or []
    main_image = state.get("image") or {}
    return {
        "spec": spec,
        "products": [load_product(s).to_dict() for s in spec["skus"]],
        "physical": state.get("physical"),
        "copy": state.get("copy"),
        "a_plus_modules": aplus,
        "images": {
            "main": main_image,
            "a_plus": [m.get("image") for m in aplus],
        },
        "compliance": compliance,
        "marketing": state.get("marketing"),
        "observability": metrics.snapshot(),
        "main_image": main_image,
        "critic": critic,
        "compliant": image_ok and copy_ok,
        "image_compliant": image_ok,
        "copy_compliant": copy_ok,
        "attempts": state.get("attempt"),
    }


def run_sync(bus, spec: dict) -> dict:
    """Run a job to completion on the current thread; returns the listing."""
    bus.emit("Supervisor", f"job accepted: {spec}")
    metrics.begin()
    try:
        final = _graph.invoke({"job_id": bus.job_id, "spec": spec})
        listing = _assemble(spec, final)
        bus.finish(result=listing)
        try:
            store.save(bus.job_id, listing)  # persist to the Library
        except Exception as e:
            bus.emit("Supervisor", f"warn: could not persist listing ({e})")
        bus.emit("Supervisor", "job complete")
        return listing
    except Exception as e:
        bus.emit("Supervisor", f"job error: {e}")
        bus.finish(error=str(e))
        raise


def start(spec: dict) -> str:
    bus = trace.create()
    threading.Thread(target=lambda: _safe(bus, spec), daemon=True).start()
    return bus.job_id


def _safe(bus, spec):
    try:
        run_sync(bus, spec)
    except Exception:
        pass  # already recorded on the bus
