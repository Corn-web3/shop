"""Intent agent: natural language -> a structured recompose action.

Tier 3 must be agent-driven, so the primary path asks the LLM to resolve the
request (including multi-turn references like "it") into a structured action.
A keyword fallback exists ONLY for the no-key degraded mode and is clearly
flagged as such; it is not the scored path.

Action shape:
  {"kind": "multipack"|"combo"|"unknown",
   "base_sku": str|None, "units": int|None, "second_sku": str|None,
   "reply": str}
"""

import re

from app.tools import llm

SYSTEM = (
    "You translate an e-commerce operator's request into a structured action "
    "for a listing tool. Kinds: 'multipack' (one product sold as a pack of N), "
    "'combo' (two distinct products bundled), or 'unknown'. Resolve references "
    "like 'it'/'this' using the current focus SKUs. Only use SKUs from the "
    "provided list. "
    'Return JSON: {"kind": str, "base_sku": str|null, "units": int|null, '
    '"second_sku": str|null, "reply": str}. reply is a short confirmation.'
)


def _llm(message: str, focus_skus, available) -> dict:
    user = (
        f"Available SKUs: {available}\n"
        f"Current focus SKUs (for 'it'/'this'): {focus_skus or 'none'}\n"
        f"Operator says: {message!r}"
    )
    return llm.chat_json(SYSTEM, user)


def _offline(message: str, focus_skus, available) -> dict:
    """Degraded keyword fallback (no LLM key). NOT the scored path."""
    text = message.lower()
    found = [s for s in available if s.lower() in text]
    is_combo = any(w in text for w in ("combo", "组合", "bundle", "套装"))
    # number before a pack word ("3件", "3-pack") OR after one ("pack of 3")
    m = (re.search(r"(\d+)\s*(?:件|个|pack|x|×|-pack)", text)
         or re.search(r"(?:pack of|包|套)\s*(\d+)", text))
    units = int(m.group(1)) if m else None

    if is_combo:
        # merge focus ("it") with explicitly-named SKUs, de-duped, keep order
        candidates = []
        for s in (focus_skus or []) + found:
            if s not in candidates:
                candidates.append(s)
        base = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        return {"kind": "combo", "base_sku": base, "units": 1,
                "second_sku": second,
                "reply": f"[offline] combo of {base} + {second}"}
    if units:
        base = found[0] if found else (focus_skus[0] if focus_skus else None)
        return {"kind": "multipack", "base_sku": base, "units": units,
                "second_sku": None,
                "reply": f"[offline] {base} pack of {units}"}
    base = found[0] if found else None
    return {"kind": "unknown", "base_sku": base, "units": None,
            "second_sku": None,
            "reply": "[offline] could not parse; specify a pack size or a combo"}


def run(message: str, focus_skus, available, emit=lambda *a, **k: None) -> dict:
    if llm.available():
        emit("Intent", f"parsing (agent): {message!r}")
        try:
            return _llm(message, focus_skus, available)
        except Exception as e:
            emit("Intent", f"LLM parse failed ({e}); offline fallback")
    else:
        emit("Intent", f"parsing (offline keyword fallback): {message!r}")
    return _offline(message, focus_skus, available)
