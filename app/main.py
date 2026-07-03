"""FastAPI service: data -> multi-agent generation -> reviewable trace.

Endpoints:
  GET  /health
  GET  /products                list normalized SKUs
  GET  /product/{sku}           one normalized record
  POST /enrich/{sku}            Tier 1: web enrichment with cited sources
  POST /listing/{sku}?units=N   start a generation job -> {job_id}
  POST /chat                    conversational recompose (multipack / combo)
  POST /compliance              B1 validator: check listing copy -> pass/fail
  GET  /jobs/{job_id}           poll job state / final listing
  GET  /trace/{job_id}          SSE stream of the agent execution trace
  /out/...                      generated image files (static)
"""

import asyncio
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import (chat, compliance, db, enrich, eval_harness, jobs, review,
                 store, trace, variants)
from app.config import MAX_UNITS, OUT_DIR, settings

app = FastAPI(title="SSB Listing Studio")
app.mount("/out", StaticFiles(directory=OUT_DIR), name="out")

_WEB = os.path.join(os.path.dirname(__file__), "web", "index.html")


@app.get("/")
def home():
    return FileResponse(_WEB)


@app.get("/api")
def index():
    return {
        "service": "SSB Listing Studio", "docs": "/docs", "ui": "/",
        "db_source": db.source(),
        "endpoints": {
            "health": "GET /health", "products": "GET /products",
            "product": "GET /product/{sku}", "enrich": "POST /enrich/{sku}",
            "listing": "POST /listing/{sku}?units=N",
            "trace": "GET /trace/{job_id} (SSE)", "job": "GET /jobs/{job_id}",
            "chat": "POST /chat", "compliance": "POST /compliance",
            "eval": "POST /eval",
            "review": "POST /review/{job_id} | GET /diff?base=&recomposed=",
            "variants": "GET /variants/{sku}", "images": "GET /out/{file}",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "db_source": db.source(),
            "llm_ready": settings.llm_ready, "image_ready": settings.image_ready,
            "search_ready": settings.search_ready,
            "note": None if settings.llm_ready else
            "no LLM key configured; copy/critic run in offline/degraded mode"}


@app.get("/products")
def products():
    return [db.load_product(s).to_dict() for s in db.list_skus()]


@app.get("/product/{sku}")
def product(sku: str):
    try:
        return db.load_product(sku).to_dict()
    except KeyError:
        raise HTTPException(404, f"unknown sku {sku}")


@app.get("/product/{sku}/raw")
def product_raw(sku: str):
    """Every source column for a SKU (untouched fbm_sku row on MySQL)."""
    try:
        return db.raw_row(sku)
    except KeyError:
        raise HTTPException(404, f"unknown sku {sku}")


@app.post("/enrich/{sku}")
def enrich_sku(sku: str, refresh: bool = False):
    try:
        return enrich.run(sku, refresh=refresh)
    except KeyError:
        raise HTTPException(404, f"unknown sku {sku}")


@app.get("/variants/{sku}")
def variants_for(sku: str):
    try:
        return variants.build_family(sku)
    except KeyError:
        raise HTTPException(404, f"unknown sku {sku}")


@app.post("/listing/{sku}")
def create_listing(sku: str, units: int = 1):
    try:
        db.load_product(sku)
    except KeyError:
        raise HTTPException(404, f"unknown sku {sku}")
    if units < 1 or units > MAX_UNITS:
        raise HTTPException(422, f"units must be between 1 and {MAX_UNITS}")
    spec = {"kind": "multipack" if units > 1 else "single",
            "skus": [sku], "units": units}
    job_id = jobs.start(spec)
    return {"job_id": job_id, "trace": f"/trace/{job_id}", "result": f"/jobs/{job_id}"}


class ChatIn(BaseModel):
    session_id: str = "default"
    message: str


@app.post("/chat")
def chat_endpoint(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(422, "message is empty")
    return chat.handle(body.session_id, body.message)


class ComplianceIn(BaseModel):
    title: str = ""
    bullets: list[str] = []
    description: str = ""
    search_terms: str = ""
    brand: str = ""


@app.post("/compliance")
def compliance_check(body: ComplianceIn):
    return compliance.check_listing(
        {"title": body.title, "bullets": body.bullets,
         "description": body.description, "search_terms": body.search_terms},
        brand=body.brand)


class EvalIn(BaseModel):
    skus: list[str]
    units: int = 1


@app.post("/eval")
def eval_listings(body: EvalIn):
    if not body.skus:
        raise HTTPException(422, "skus is empty")
    return eval_harness.run(body.skus, body.units)


class ReviewIn(BaseModel):
    decision: str
    note: str = ""


@app.post("/review/{job_id}")
def review_decision(job_id: str, body: ReviewIn):
    try:
        return review.set_decision(job_id, body.decision, body.note)
    except KeyError:
        raise HTTPException(404, f"unknown job {job_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/review/{job_id}")
def review_status(job_id: str):
    return review.get_decision(job_id)


@app.get("/diff")
def listing_diff(base: str, recomposed: str):
    try:
        return review.diff(base, recomposed)
    except KeyError:
        raise HTTPException(404, "unknown job (or listing not finished)")


@app.get("/library")
def library():
    return store.list_summaries()


@app.get("/library/{job_id}")
def library_item(job_id: str):
    item = store.get(job_id)
    if not item:
        raise HTTPException(404, "not in library")
    return item


@app.get("/jobs/{job_id}")
def job_state(job_id: str):
    bus = trace.get(job_id)
    if not bus:
        raise HTTPException(404, "unknown job")
    return {"job_id": job_id, "done": bus.done, "error": bus.error,
            "events": bus.events, "result": bus.result}


@app.get("/trace/{job_id}")
async def trace_stream(job_id: str):
    bus = trace.get(job_id)
    if not bus:
        raise HTTPException(404, "unknown job")

    async def gen():
        idx = 0
        while True:
            while idx < len(bus.events):
                yield f"data: {json.dumps(bus.events[idx])}\n\n"
                idx += 1
            if bus.done:
                payload = {"done": True, "compliant":
                           bool((bus.result or {}).get("compliant")),
                           "error": bus.error}
                yield f"event: end\ndata: {json.dumps(payload)}\n\n"
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")
