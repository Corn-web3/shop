"""LangGraph orchestration for listing generation (single / multipack / combo).

    supervisor -> physical -> copy -> image -> critic --(pass)--> END
                                                  \--(fail, retries)--> image

Driven by a `spec` = {"kind": "single"|"multipack"|"combo", "skus": [...],
"units": int}. Real multi-agent orchestration: a Supervisor, distinct agent
nodes, intermediate state passed along, a deterministic physical-recompute node,
and a Critic-driven retry loop back to the Image agent on consistency failure.
"""

from typing import TypedDict, List

from langgraph.graph import StateGraph, END

from app import metrics, trace
from app.db import load_product
from app.physical import repack
from app import compliance
from app.agents import copy_agent, image_agent, critic_agent, aplus_agent

MAX_ATTEMPTS = 2


class GenState(TypedDict, total=False):
    job_id: str
    spec: dict
    physical: dict
    copy: dict
    compliance: dict
    image: dict
    critic: dict
    aplus: list
    attempt: int


def _emit(job_id):
    bus = trace.get(job_id)
    if not bus:
        return lambda *a, **k: None
    return lambda agent, msg, **d: bus.emit(agent, msg, **d)


def _products(spec) -> List:
    return [load_product(s) for s in spec["skus"]]


def _items(spec):
    """(product, qty) pairs for the physical recompute."""
    prods = _products(spec)
    if spec["kind"] == "combo":
        return [(p, 1) for p in prods]
    return [(prods[0], spec.get("units", 1))]


def supervisor_node(state: GenState) -> dict:
    emit = _emit(state["job_id"])
    spec = state["spec"]
    emit("Supervisor",
         f"plan: kind={spec['kind']} skus={spec['skus']} units={spec.get('units', 1)} "
         f"-> Physical -> Copy -> Image -> Critic (max_attempts={MAX_ATTEMPTS})")
    for p in _products(spec):
        emit("Supervisor",
             f"loaded {p.sku}: {p.brand} {p.title} | {p.color} | {p.material}")
    return {"attempt": 0}


def physical_node(state: GenState) -> dict:
    emit = _emit(state["job_id"])
    spec = state["spec"]
    phys = repack(_items(spec), spec["kind"])
    emit("Physical", f"recomputed: total {phys['total_weight_g']} g, "
                     f"pkg {phys['package_dimensions_cm']}, {phys['arrangement']}")
    return {"physical": phys}


def copy_node(state: GenState) -> dict:
    spec = state["spec"]
    out = copy_agent.run(spec["kind"], _products(spec), spec.get("units", 1),
                         state["physical"], _emit(state["job_id"]))
    return {"copy": out}


def compliance_node(state: GenState) -> dict:
    emit = _emit(state["job_id"])
    brand = _products(state["spec"])[0].brand
    rep = compliance.check_listing(state["copy"], brand=brand,
                                   a_plus_modules=state.get("aplus"),
                                   main_image=state.get("image"))
    verdict = "PASS" if rep["compliant"] else "FAIL"
    emit("Compliance", f"copy compliance: {verdict} "
                       f"({rep['error_count']} errors, {rep['warn_count']} warnings)")
    for v in rep["violations"]:
        emit("Compliance", f"{v['severity'].upper()} {v['field']}/{v['rule']}: {v['detail']}")
    return {"compliance": rep}


def image_node(state: GenState) -> dict:
    spec = state["spec"]
    attempt = state.get("attempt", 0) + 1
    meta = image_agent.run(spec["kind"], _products(spec), spec.get("units", 1),
                           state["job_id"], attempt, _emit(state["job_id"]))
    return {"image": meta, "attempt": attempt}


def critic_node(state: GenState) -> dict:
    emit = _emit(state["job_id"])
    img = state.get("image") or {}
    if not img.get("path"):
        emit("Critic", "no image to check -> FAIL")
        return {"critic": {"overall_pass": False, "error": "no image"}}
    spec = state["spec"]
    rep = critic_agent.run(img["path"], spec["kind"], _products(spec),
                           spec.get("units", 1), emit)
    return {"critic": rep}


def aplus_node(state: GenState) -> dict:
    spec = state["spec"]
    mods = aplus_agent.run(spec["kind"], _products(spec), state["physical"],
                           state["job_id"], _emit(state["job_id"]))
    return {"aplus": mods}


def after_critic(state: GenState) -> str:
    emit = _emit(state["job_id"])
    if state.get("critic", {}).get("overall_pass"):
        return "done"
    if state.get("attempt", 0) >= MAX_ATTEMPTS:
        emit("Supervisor", "max attempts reached; returning flagged non-compliant")
        return "done"
    emit("Supervisor", "critic failed; sending back to Image agent to regenerate")
    return "retry"


def _timed(agent: str, fn):
    """Wrap a node so its wall time is recorded per agent (B2 observability)."""
    def wrapped(state):
        with metrics.timed(agent):
            return fn(state)
    return wrapped


def build_graph():
    g = StateGraph(GenState)
    g.add_node("supervisor", _timed("Supervisor", supervisor_node))
    g.add_node("physical", _timed("Physical", physical_node))
    g.add_node("copy", _timed("Copy", copy_node))
    g.add_node("image", _timed("Image", image_node))
    g.add_node("critic", _timed("Critic", critic_node))
    g.add_node("aplus", _timed("A+", aplus_node))
    g.add_node("compliance", _timed("Compliance", compliance_node))
    g.set_entry_point("supervisor")
    g.add_edge("supervisor", "physical")
    g.add_edge("physical", "copy")
    g.add_edge("copy", "image")
    g.add_edge("image", "critic")
    g.add_conditional_edges("critic", after_critic,
                            {"retry": "image", "done": "aplus"})
    g.add_edge("aplus", "compliance")
    g.add_edge("compliance", END)
    return g.compile()
