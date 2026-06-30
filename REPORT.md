# REPORT — SSB Listing Studio

How the system is built, why, how compliance and physical consistency are
guaranteed, what was AI-assisted, and how it was validated.

---

## 1. Architecture & Agent design

A FastAPI service wraps a **LangGraph** multi-agent pipeline. One spec-driven
graph serves single / multipack / combo generation; the `/chat` layer drives it
conversationally.

```
                 ┌───────────────────── FastAPI ─────────────────────┐
                 │ /products /product  /enrich  /listing  /chat       │
                 │ /trace(SSE) /jobs   /compliance /eval /review /diff │
                 │ /variants  /health                                  │
                 └───────────────┬────────────────────────────────────┘
                                 │ spec {kind, skus[], units}
        ┌────────────────────────▼─────────────────────────────┐
        │ LangGraph orchestration (Supervisor + agent nodes)    │
        │                                                       │
        │ supervisor → physical → copy → image → critic         │
        │                                  │   └─(fail,≤2)─┐     │
        │                                  ▼               │     │
        │            (pass) → aplus → compliance → END     │     │
        │                                  ▲───────────────┘     │
        └───────────────┬───────────────────────────────────────┘
                        │ tools
   ┌────────────────────┼───────────────────────────────────────┐
   │ llm (chat+vision)  │ imagegen (gpt-image-2)  research(Tavily)│
   │ physical.repack    │ compliance  metrics  db(introspect/mock)│
   └─────────────────────────────────────────────────────────────┘
```

**Agents / nodes and responsibilities**

| Agent | Role | Tools / output |
|---|---|---|
| **Supervisor** | plans the run, loads products, drives the retry decision | trace events |
| **Physical** | deterministically recomputes total weight, packaging, package dims | `physical.repack` |
| **Copy** | A+ title (brand-led, no promo), 5 benefit bullets, backend search terms, A+ module copy | `llm.chat_json` |
| **Image** | white-bg hero (JPEG, ≥1600px, snap-to-255), multipack count / combo same-frame | `imagegen` |
| **Critic / QA** | image-vs-spec consistency: white-bg pixels, coverage, count, 3-vote vision check | `llm.vision_json`, PIL |
| **A+** | builds 970×600 + 970×300 modules (image + headline + body + alt text) | `imagegen.generate_module` |
| **Compliance (B1)** | deterministic A+ rule validator over copy + images | `compliance.check_listing` |
| **Research (Tier 1)** | web enrichment with cited sources, confidence, conflicts | `research`(Tavily) + `llm` |

Real orchestration (Supervisor, distinct nodes, shared state passed along, a
Critic-driven retry edge back to Image) — **not a single mega-prompt or a regex
state machine**. `/chat` parses intent with an LLM intent agent (offline keyword
fallback is flagged degraded, never the scored path), so recompose is
agent-driven and supports multi-turn reference ("make it a 3-pack" → "now combine
it with SSB-002").

## 2. Prompt iteration

- **Copy**: started free-form; tightened to a strict system prompt enforcing
  brand-leading title, no promotional words, exactly 5 bullets, byte-bounded
  search terms — because the B1 validator kept flagging violations otherwise.
- **Critic vision**: first asked the model to *describe* the image, then string-
  matched on our side. That broke immediately ("stainless steel" vs the model's
  "metal"). Reworked to pass the *claimed* spec in and have the model judge
  consistency (booleans + notes). Then added **3-sample majority voting** after
  observing single verdicts flip on the same image (which had triggered a wasted
  ~96s image regeneration).
- **Image**: injected structured specs (count, color, material, "exactly N
  units", pure-white bg) into the prompt; this is what makes the picture match
  the database. Combo prompt explicitly asks for "one of each, N items total".
- **Research**: two prompts — a sourced one ("cite only provided URLs, never
  invent numeric specs") and a degraded one ("no web access → source_url=null,
  confidence ≤0.4, push unverifiable specs to missing").

## 3. How A+ compliance is guaranteed

A deterministic validator (`app/compliance.py`, zero model calls) runs as a graph
node and gates the listing's `compliant` flag. It enforces the README §6
checklist: title present / ≤200 chars (warn >150) / brand-leads / no banned promo
phrases; ≤5 bullets, each ≤500 chars, no contact info; backend search terms ≤250
**bytes**; A+ modules each carry an image + alt text at a standard module size;
main image is JPEG and <10MB. Violations carry field/rule/severity and stream to
the trace. Because it is deterministic it is reproducible and free.

## 4. How image physical consistency is guaranteed

Two layers in the Critic:
1. **Deterministic pixel checks** (always reliable): white background sampled at
   the corners (per-channel minimum, snapped to exactly 255 in post), product
   coverage by longest-side fill ≥85%, object count by column projection.
2. **Vision verification** (3-sample majority vote): the model judges the image
   against the claimed unit count, color, and material; for combos it confirms
   each distinct item is present. On failure the Supervisor sends the job back to
   the Image agent (≤2 attempts).

The deterministic count is demoted to informational when vision is available
(projection merges touching items / shadows); the vision count is authoritative.
Validated live: gpt-image-2 produced a correct single bottle and a clean 3-pack;
combo showed both a matte-black bottle and a forest-green cup.

Honest limitation: a painted/coated metal product (matte-black stainless bottle)
doesn't visually reveal its base material, so the material check can over-reject
unless a visual cue (steel cap) is present.

## 5. Physical recompute (multipack / combo)

`app/physical.py` recomputes in code, not the LLM: total weight = Σ unit weights
+ box/padding; package dimensions via a near-square grid for multipacks and
side-by-side for combos; assumptions are returned for transparency (e.g. 3-pack
of the 320 g bottle → 960 g product + 49 g packaging = 1009 g).

## 6. AI tool usage (what was AI-written vs. reworked)

- **AI-drafted, kept**: boilerplate (FastAPI handlers, dataclasses, PIL synth
  placeholders), first drafts of agent prompts, the synonym table for DB
  introspection.
- **AI-drafted, reworked/overruled**: the Critic's vision check (described →
  judge-against-spec → majority vote); coverage metric (bbox area → longest-side
  fill, because tall/narrow products failed); the count gate (projection →
  vision-authoritative); main image format (PNG → JPEG 4:4:4 q95 so the white bg
  survives lossy compression).
- **Human-driven decisions**: build a vertical slice first to retire the physical-
  consistency risk before scaffolding; spec-driven single graph for all three
  modes; deterministic compliance/physical rather than trusting the model;
  honest degraded modes (no fabricated citations/specs).

## 7. Validation record

An automated acceptance harness (`scripts/check_acceptance.py`) maps every README
requirement to a PASS/FAIL check and runs **offline** (synth images, zero API
cost). It is the project's definition of done — it exits 0 only when all required
items pass. Covered: Tier 0 (health, ≥3 SKUs, normalized records, Docker files,
no committed secrets, DB introspection), Tier 1 (enrich shape, no-fabrication,
cache), Tier 2 (copy structure, A+ modules, JPEG ≥1600 main image, reviewable
trace, physical-consistency Critic), Tier 3 (chat multipack + combo multi-turn),
B1–B5, and deliverables.

Live validation used the aiprox gateway (gpt-5.4-mini for copy/vision/research,
gpt-image-2 for images): single SSB-001 (hero PASS + 2 A+ modules), 3-pack
(correct 3 bottles), combo SSB-001+002 (both items, same frame). Sample outputs
for 3 SKUs incl. 1 multipack + 1 combo are committed under `samples/`.

## 8. Cost

The `observability` block on every listing reports per-agent wall time, LLM
call/token counts, image count, and an **estimated** USD cost (rates overridable
via `COST_PER_*` env vars; the gateway's gpt-5.x / gpt-image-2 prices aren't
published). Image generation dominates (~96 s and the bulk of spend per image;
3 images per listing). Cost controls: `units` capped 1–12; enrichment cached per
SKU; the acceptance harness and all unit tests run offline (no spend); live image
generation reserved for final sample outputs. Actual spend during development was
a small number of live listings/enrichments — well within the ~¥1500 budget.

## 9. If we had more time

- Wire **high-confidence, sourced** enrichment fields into the Copy agent (kept
  separate now so degraded-mode unverified facts can't leak into listings).
- Add a copy-fix retry loop when compliance fails (today it reports + gates but
  doesn't auto-correct).
- Real infographic A+ module (data callouts) beyond lifestyle/feature shots.
- Persist jobs/listings (currently in-memory) and add auth + rate limiting.
- Stronger object counting (segmentation) instead of column projection.
- Per-call real cost capture if the gateway returns pricing.
