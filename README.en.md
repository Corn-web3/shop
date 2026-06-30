# SSB Listing Studio — Solution

> English run/architecture guide for this implementation. The original challenge
> brief is in [README.md](./README.md). See [REPORT.md](./REPORT.md) for design
> rationale, prompt iteration, and validation.

An agentic service that turns SSB product-database rows into Amazon-A+-compliant,
physically-consistent listings, and recomposes them via chat into multipacks /
combos. Multi-agent orchestration (LangGraph), reviewable SSE trace, deterministic
physical recompute, and a Critic that checks the generated image against the specs.

## Quick start

```bash
# 1) configure keys (optional — the service starts and runs in degraded mode without them)
cp .env.example .env   # then fill in LLM / image / (optional) Tavily / DATABASE_URL

# 2a) Docker (one command)
docker compose up --build          # -> http://localhost:8000

# 2b) or local
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

No keys? It still boots: a built-in 3-SKU mock DB is used, copy/critic/research
fall back to offline/degraded modes, images are synthesized placeholders. Every
key-dependent endpoint returns a clear note instead of failing.

## Endpoints

| Method & path | What it does |
|---|---|
| `GET /health` | status + which DB source / which keys are configured |
| `GET /products`, `GET /product/{sku}` | normalized product records |
| `POST /enrich/{sku}` | **Tier 1** web enrichment: cited fields + confidence + conflicts/missing |
| `POST /listing/{sku}?units=N` | **Tier 2** multi-agent generation → `job_id` |
| `GET /trace/{job_id}` (SSE), `GET /jobs/{job_id}` | reviewable agent trace / final listing |
| `POST /chat` | **Tier 3** conversational recompose (multipack / combo, multi-turn) |
| `POST /compliance` | **B1** copy/image compliance validator |
| `POST /eval` | **B5** quality + physical-consistency scoring over SKUs |
| `POST /review/{job_id}`, `GET /diff?base=&recomposed=` | **B4** review gate + original-vs-recomposed diff |
| `GET /variants/{sku}` | **B3** parent/child variants + pricing suggestion |

## Architecture (generation graph)

```
supervisor → physical → copy → image → critic ─(pass)─→ aplus → compliance → END
                                          └─(fail, ≤2 retries)─→ image
```

- **Supervisor** plans + loads products; **Physical** recomputes weight/packaging/dims
  (code, not the LLM); **Copy** writes A+ title/5 bullets/search terms; **Image**
  generates the white-bg hero (JPEG, ≥1600px, snap-to-255 background); **Critic**
  verifies the image vs. specs (white-bg pixels, coverage, count, and a 3-sample
  majority-vote vision check of count/color/material); **A+** builds 970×600 / 970×300
  modules with alt text; **Compliance** runs the B1 validator.
- Real orchestration via LangGraph with a Critic-driven retry loop — not a single
  prompt or regex state machine.

## Data source

Set `DATABASE_URL` to a read-only Postgres and the schema is introspected:
arbitrary column names are mapped to the normalized shape by synonyms, and
combined fields (e.g. `30x20x15 cm`, weight in kg/lb/oz) are parsed defensively.
The connection is read-only (no writes ever issued). Without `DATABASE_URL`, the
built-in 3-SKU mock is used.

## Tests & acceptance

```bash
PYTHONPATH=. python scripts/check_acceptance.py   # runs offline (zero API cost)
```

Maps every README requirement to an automated PASS/FAIL check; exits 0 when all
required items pass.

## Cost & safety

`units` is capped (1–12); the acceptance checker and all unit tests run offline
(synth images, no API spend); enrichment is cached per SKU. The `observability`
block on each listing reports per-agent timing, token counts, image count, and an
estimated cost (rates overridable via `COST_PER_*` env vars).
