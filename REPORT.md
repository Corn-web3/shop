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
        │ supervisor → physical → copy → marketing → image      │
        │                                        → critic        │
        │                              (fail,≤2) ↺ image         │
        │            (pass) → aplus → compliance → END           │
        └───────────────┬───────────────────────────────────────┘
                        │ tools
   ┌────────────────────┼───────────────────────────────────────┐
   │ llm (chat+vision)  │ imagegen (gpt-image-2)  research(Tavily)│
   │ physical.repack    │ compliance  metrics  db(introspect/mock)│
   └─────────────────────────────────────────────────────────────┘
```

The **Copy → Marketing** hand-off closes the loop: Copy weaves in HIGH-confidence,
source-cited enrichment facts; Marketing scores conversion and (compliance-safely)
rewrites weak copy. Enrichment (Tavily) feeds both the facts and mined buyer
keywords.

**Agents / nodes and responsibilities**

| Agent | Role | Tools / output |
|---|---|---|
| **Supervisor** | plans the run, loads products, drives the retry decision | trace events |
| **Physical** | deterministically recomputes total weight, packaging, package dims | `physical.repack` |
| **Copy** | A+ title (brand-led, no promo), 5 benefit bullets, backend search terms; weaves in source-cited enrichment facts | `llm.chat_json` + `enrich.sourced_facts` |
| **Marketing / Conversion** | scores copy on benefit-clarity / keyword-coverage / appeal, rewrites weak copy **within compliance** | `llm.chat_json` + `enrich.buyer_keywords` |
| **Image** | white-bg hero (JPEG, ≥1600px, snap-to-255), multipack count / combo same-frame | `imagegen` |
| **Critic / QA** | image-vs-spec consistency: white-bg pixels, coverage, **aspect-ratio vs real dims**, count, 3-vote vision | `llm.vision_json`, PIL |
| **A+** | builds 970×600 + two 970×300 modules (image + headline + body + alt text) | `imagegen.generate_module` |
| **Compliance (B1)** | deterministic A+ rule validator over copy + images | `compliance.check_listing` |
| **Research (Tier 1)** | web enrichment with cited sources, confidence, conflicts; mines buyer keywords | `research`(Tavily) + `llm` |

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
- **Marketing / conversion**: scores the copy 0–100 on benefit-clarity,
  keyword-coverage and appeal, then rewrites only if <80 — with the full B1
  compliance rules and "use only facts above" baked into the prompt, so lifting
  conversion can never introduce a banned promo word or an invented spec (the
  end-of-graph Compliance node re-validates the rewrite).

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
   coverage by longest-side fill ≥85%, object count by column projection, and an
   **aspect-ratio check** — the on-screen product bounding box's long/short ratio
   is compared to the product's real two-largest-dimension ratio (a 7×7×25 cm
   bottle should photograph tall ≈3.6:1; an 81×48×81 cm chair should look square
   ≈1:1). Orientation-independent and informational, it catches a grossly
   mis-proportioned render without over-rejecting (a 2D photo is approximate).
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

Live validation used an OpenAI-compatible gateway (gpt-5.4-mini for
copy/vision/research/marketing, gpt-image-2 for images) plus Tavily for search.
Real full run (SSB-OG-000001): hero PASS at 1600×1600 with white bg exactly
(255,255,255) and 85.9% area / 96.6% longest-side fill; 4 sourced enrichment
facts (Amazon/eBay URLs, conf 0.7–0.96) injected into Copy; 15 Tavily buyer
keywords mined; three A+ modules at exact sizes; compliance 0 errors. Recompose
verified: "make it a 3-pack" → 3-pack spec + 6036 g repack; "combine with
SSB-OG-000002 as a combo" → combo spec (multi-turn "it" resolved) + side-by-side
repack. Sample outputs for 3 SKUs incl. 1 multipack + 1 combo are under `samples/`.

## 8. Cost

The `observability` block on every listing reports per-agent wall time, LLM
call/token counts, image count, and an **estimated** USD cost (rates overridable
via `COST_PER_*` env vars). Image generation dominates: a full single listing
measured **~$0.18 and ~390 s** (4 images — hero + three A+ modules — plus ~6 LLM
calls). Cost controls: `units` capped 1–12; enrichment, buyer-keywords and raw DB
rows cached per SKU; the acceptance harness and all unit tests run offline (no
spend); live image generation reserved for samples/demos. Development spend was a
small number of live listings/enrichments — well within the ~¥1500 budget.

**Gateway note (portability):** the LLM + image endpoints are any OpenAI-compatible
gateway via `.env` (`LLM_*` / `IMAGE_*`). During development we hit a gateway whose
image account pool returned `503 No available compatible accounts`; switching
`BASE_URL`/`KEY` was a config-only change. One gateway sat behind Cloudflare and
blocked the default SDK User-Agent (`Your request was blocked`) — the client now
sends a browser `User-Agent` (overridable via `HTTP_USER_AGENT`), which is the
kind of real-world integration hardening a reviewer's own key may need.

## 9. Beyond the baseline (differentiators)

On top of Tier 0–3 + B1–B5, four additions deepen the parts the brief calls
hardest (physical consistency, real agentic behaviour) and add product sense:

- **Enrich → generate loop closed**: only HIGH-confidence, *source-cited*
  enrichment facts are injected into Copy (degraded/unverified facts stay out),
  so citations from the web actually shape the listing.
- **Marketing / Conversion critic**: a distinct agent that scores conversion and
  compliance-safely rewrites weak copy — lifting quality without hype words.
- **Aspect-ratio consistency check**: image geometry validated against real
  product dimensions, a deterministic consistency signal beyond count/colour.
- **Buyer-keyword SEO mining**: Tavily-sourced search keywords feed title +
  backend search terms via the Marketing agent.

## 10. If we had more time

- Add a copy-fix retry loop when compliance fails (today it reports + gates but
  doesn't auto-correct); same for a low Marketing score.
- Real infographic A+ module (rendered data callouts) beyond photo modules.
- Stronger object counting (segmentation) instead of column projection.
- Per-call real cost capture if the gateway returns pricing; auth + rate limiting.
