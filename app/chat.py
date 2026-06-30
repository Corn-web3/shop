"""Conversational recompose layer (Tier 3).

Holds chat sessions, drives the intent agent to turn a message into a recompose
spec, kicks off a generation job (reusing the same multi-agent graph), and
remembers the focus SKUs so follow-up turns can say "it"/"this".
"""

import threading
from typing import Dict, Optional

from app import db, jobs, trace
from app.agents import intent_agent
from app.config import MAX_UNITS

_sessions: Dict[str, dict] = {}
_lock = threading.Lock()


def _session(session_id: str) -> dict:
    with _lock:
        s = _sessions.get(session_id)
        if s is None:
            s = {"focus_skus": [], "history": [], "last_job": None}
            _sessions[session_id] = s
        return s


def _coerce_units(v) -> Optional[int]:
    """The LLM may return units as int, "3", or null. Coerce safely; reject
    out-of-range so /chat matches /listing's 1..MAX_UNITS bound."""
    try:
        u = int(v)
    except (TypeError, ValueError):
        return 1  # default to single when unspecified
    if u < 1 or u > MAX_UNITS:
        return None
    return u


def _validate_spec(action: dict) -> Optional[dict]:
    kind = action.get("kind")
    skus = db.list_skus()
    if kind == "multipack":
        base = action.get("base_sku")
        units = _coerce_units(action.get("units"))
        if base not in skus or units is None:
            return None
        return {"kind": "multipack" if units > 1 else "single",
                "skus": [base], "units": units}
    if kind == "combo":
        a, b = action.get("base_sku"), action.get("second_sku")
        if a not in skus or b not in skus or a == b:
            return None
        return {"kind": "combo", "skus": [a, b], "units": 1}
    return None


def handle(session_id: str, message: str) -> dict:
    s = _session(session_id)
    bus = trace.create()
    emit = lambda agent, msg, **d: bus.emit(agent, msg, **d)

    action = intent_agent.run(message, s["focus_skus"], db.list_skus(), emit)
    spec = _validate_spec(action)
    if not spec:
        bus.finish(error="unresolved intent")
        s["history"].append({"message": message, "action": action, "spec": None})
        return {"session_id": session_id, "job_id": bus.job_id,
                "reply": action.get("reply", "Sorry, I couldn't resolve that."),
                "action": action, "spec": None,
                "note": "specify a known SKU and a pack size or a second SKU"}

    emit("Supervisor", f"recompose accepted: {spec}")
    # run on this session's trace bus, in the background
    threading.Thread(target=lambda: _run(bus, spec), daemon=True).start()

    s["focus_skus"] = spec["skus"]
    s["last_job"] = bus.job_id
    s["history"].append({"message": message, "action": action, "spec": spec})
    return {"session_id": session_id, "job_id": bus.job_id,
            "trace": f"/trace/{bus.job_id}", "result": f"/jobs/{bus.job_id}",
            "reply": action.get("reply", f"Working on {spec['kind']}..."),
            "action": action, "spec": spec}


def _run(bus, spec):
    try:
        jobs.run_sync(bus, spec)
    except Exception:
        pass  # recorded on the bus
