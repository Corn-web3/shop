"""Automated acceptance check = the objective function for "goal mode".

Translates the README requirements into executable PASS/FAIL checks. Runs the
app OFFLINE (blank keys -> synth images, deterministic, zero API cost) plus
filesystem checks for deliverables. Exit 0 only when every REQUIRED check
passes. Items only the user can do (demo video) are listed as MANUAL and never
block.

Run:  PYTHONPATH=. python scripts/check_acceptance.py
"""
import os, sys, time, json, subprocess

# force offline so the checker is free + deterministic
for k in ("LLM_API_KEY", "IMAGE_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY",
          "DATABASE_URL"):
    os.environ[k] = ""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

C = TestClient(app)
RESULTS = []  # (category, name, passed, detail, manual)


def check(cat, name, fn, manual=False):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"EXC {type(e).__name__}: {e}"
    RESULTS.append((cat, name, bool(ok), str(detail), manual))


def _run_job(path):
    jid = C.post(path).json()["job_id"]
    for _ in range(200):
        st = C.get(f"/jobs/{jid}").json()
        if st["done"]:
            return st
        time.sleep(0.02)
    return st


def _path(*p):
    return os.path.join(ROOT, *p)


def _exists(*p):
    return os.path.exists(_path(*p))


# ---------------- Tier 0 ----------------
def t0_health():
    j = C.get("/health").json()
    return ("db_source" in j and "llm_ready" in j), j

def t0_starts_no_keys():
    # we are running with blank keys; if /health 200, it started fine
    return C.get("/health").status_code == 200, "boots with no keys"

def t0_products():
    sk = C.get("/products").json()
    return len(sk) >= 3, f"{len(sk)} skus"

def t0_product_normalized():
    p = C.get("/product/SSB-001").json()
    need = {"sku","title","brand","category","color","material","unit_count",
            "length_cm","width_cm","height_cm","weight_g","price","image_urls"}
    return need.issubset(p), f"missing {need - set(p)}"

def t0_docker():
    return all(_exists(f) for f in ("Dockerfile","docker-compose.yml",
            ".env.example","requirements.txt")), "docker files"

def t0_no_secrets():
    gi = open(_path(".gitignore")).read() if _exists(".gitignore") else ""
    return ".env" in gi, ".env gitignored"

def t0_introspect():
    from app import db_postgres
    cm = db_postgres.build_colmap(["ItemID","Product_Name","Net_Weight"])
    return cm["sku"]=="ItemID" and cm["weight_g"]=="Net_Weight", "synonym mapping"

def t0_mysql_normalize():
    # pure-function unit conversion for the real fbm_sku schema (no DB needed)
    from app import db_mysql
    p = db_mysql.normalize({"sku":"X","title":"T","sku_length":"32.1",
        "sku_weight":"4.4","remark":"PACK OF 3","sku_category":"sports"})
    return (abs(p.length_cm-81.53)<0.1 and abs(p.weight_g-1995.8)<1
            and p.unit_count==3), f"len={p.length_cm} wt={p.weight_g} pack={p.unit_count}"


# ---------------- Tier 1 ----------------
def t1_enrich_shape():
    r = C.post("/enrich/SSB-001").json()
    ok = all(k in r for k in ("fields","conflicts","missing","sources",
             "search_available"))
    return ok, "record shape"

def t1_enrich_no_fabrication():
    # offline (no LLM) must not invent fields
    r = C.post("/enrich/SSB-002").json()
    return r["fields"] == [] and len(r["missing"]) >= 1, "no fabrication offline"

def t1_enrich_cache():
    C.post("/enrich/SSB-003")
    return C.post("/enrich/SSB-003").json().get("cached") is True, "cache hit"


# ---------------- Tier 2 ----------------
def t2_listing_copy():
    st = _run_job("/listing/SSB-001?units=1")
    cp = st["result"]["copy"]
    return (cp.get("title") and len(cp.get("bullets",[]))==5
            and "search_terms" in cp), "title+5 bullets+terms"

def t2_aplus_modules():
    st = _run_job("/listing/SSB-001?units=1")
    mods = st["result"].get("a_plus_modules", [])
    ok = len(mods) >= 1 and all(m.get("alt_text") and m.get("image",{}).get("path")
                                and m.get("size") for m in mods)
    return ok, f"{len(mods)} modules w/ alt+image+size"

def t2_main_image_specs():
    from PIL import Image
    st = _run_job("/listing/SSB-001?units=1")
    img = st["result"]["main_image"]
    p = img["path"]
    im = Image.open(p)
    long_edge = max(im.size) >= 1600
    fmt_jpeg = im.format == "JPEG" or p.lower().endswith((".jpg",".jpeg"))
    return long_edge and fmt_jpeg, f"size={im.size} fmt={im.format}"

def t2_trace_reviewable():
    jid = C.post("/listing/SSB-001?units=1").json()["job_id"]
    for _ in range(200):
        if C.get(f"/jobs/{jid}").json()["done"]: break
        time.sleep(0.02)
    ev = C.get(f"/jobs/{jid}").json()["events"]
    agents = {e["agent"] for e in ev}
    return {"Supervisor","Copy","Image","Critic"}.issubset(agents), str(agents)

def t2_physical_consistency_critic():
    st = _run_job("/listing/SSB-001?units=3")
    checks = st["result"]["critic"]["checks"]
    names = {c["check"] for c in checks}
    return {"white_background","coverage"}.issubset(names) and any(
        c["check"]=="count_projection" for c in checks), str(names)


# ---------------- Tier 3 ----------------
def t3_multipack():
    r = C.post("/chat", json={"session_id":"g1","message":"make SSB-001 a 3 pack"}).json()
    if r.get("spec",{}).get("kind") != "multipack": return False, str(r.get("spec"))
    st = _run_job_jid(r["job_id"])
    ph = st["result"]["physical"]
    return ph["total_units"]==3 and ph["total_weight_g"]>900, ph

def t3_combo_multiturn():
    r = C.post("/chat", json={"session_id":"g1","message":"now combine it with SSB-002 as a combo"}).json()
    if r.get("spec",{}).get("kind") != "combo": return False, str(r.get("spec"))
    st = _run_job_jid(r["job_id"])
    return len(st["result"]["spec"]["skus"])==2, st["result"]["physical"]

def _run_job_jid(jid):
    for _ in range(200):
        st = C.get(f"/jobs/{jid}").json()
        if st["done"]: return st
        time.sleep(0.02)
    return st


# ---------------- Bonus ----------------
def b1_compliance():
    bad = C.post("/compliance", json={"title":"best free shipping bottle",
          "bullets":["x"]*6,"description":"d","search_terms":"y"}).json()
    good = C.post("/compliance", json={"title":"Acme Bottle Steel",
          "bullets":["benefit here"]*5,"description":"d","search_terms":"steel"}).json()
    return bad["compliant"] is False and good["compliant"] is True, "flags+passes"

def b2_observability():
    st = _run_job("/listing/SSB-001?units=1")
    r = st["result"]
    obs = r.get("observability") or r.get("cost") or r.get("metrics")
    if not obs: return False, "no observability block in listing"
    has_timing = any("agent" in k for k in obs)
    has_cost = "estimated_cost_usd" in obs or "cost" in str(obs).lower()
    has_tokens = any("token" in k for k in obs)
    return has_timing and has_cost and has_tokens, obs

def b3_variants():
    r = C.get("/variants/SSB-001")
    if r.status_code != 200: return False, f"/variants -> {r.status_code}"
    j = r.json()
    return ("variants" in j and "pricing_suggestion" in j), j

def b4_review_gate():
    st = _run_job("/listing/SSB-001?units=1")
    # expect a review endpoint to approve/reject + a diff endpoint
    rid = st["result"].get("job_id") or st["job_id"]
    appr = C.post(f"/review/{rid}", json={"decision":"approve"})
    return appr.status_code == 200, f"/review -> {appr.status_code}"

def b5_eval_harness():
    r = C.post("/eval", json={"skus":["SSB-001","SSB-002"]})
    if r.status_code != 200: return False, f"/eval -> {r.status_code}"
    j = r.json()
    return "scores" in j and len(j.get("scores",[])) >= 1, j


# ---------------- Deliverables ----------------
def d_report():
    if not _exists("REPORT.md"): return False, "REPORT.md missing"
    t = open(_path("REPORT.md")).read().lower()
    need = ["architecture","agent","prompt","compliance","physical","ai",
            "validation","cost"]
    miss = [w for w in need if w not in t]
    return not miss, f"missing sections: {miss}"

def d_readme_en():
    return _exists("README.en.md"), "README.en.md"

def d_git():
    return _exists(".git"), "git initialized"

def d_samples():
    # >=3 SKU listing JSONs + at least 1 multipack + 1 combo committed
    d = _path("samples")
    if not os.path.isdir(d): return False, "samples/ missing"
    files = os.listdir(d)
    jsons = [f for f in files if f.endswith(".json")]
    has_multi = any("multipack" in f or "pack" in f for f in files)
    has_combo = any("combo" in f for f in files)
    return len(jsons) >= 3 and has_multi and has_combo, \
        f"{len(jsons)} json, multipack={has_multi} combo={has_combo}"


CHECKS = [
    ("Tier0","health",t0_health),("Tier0","starts_no_keys",t0_starts_no_keys),
    ("Tier0","products>=3",t0_products),("Tier0","product_normalized",t0_product_normalized),
    ("Tier0","docker_files",t0_docker),("Tier0","no_secrets",t0_no_secrets),
    ("Tier0","db_introspection",t0_introspect),
    ("Tier0","mysql_normalize",t0_mysql_normalize),
    ("Tier1","enrich_shape",t1_enrich_shape),("Tier1","enrich_no_fabrication",t1_enrich_no_fabrication),
    ("Tier1","enrich_cache",t1_enrich_cache),
    ("Tier2","listing_copy",t2_listing_copy),("Tier2","aplus_modules",t2_aplus_modules),
    ("Tier2","main_image_specs",t2_main_image_specs),("Tier2","trace_reviewable",t2_trace_reviewable),
    ("Tier2","physical_critic",t2_physical_consistency_critic),
    ("Tier3","chat_multipack",t3_multipack),("Tier3","chat_combo_multiturn",t3_combo_multiturn),
    ("B1","compliance_validator",b1_compliance),
    ("B2","cost_observability",b2_observability),
    ("B3","variants_pricing",b3_variants),
    ("B4","review_gate_diff",b4_review_gate),
    ("B5","eval_harness",b5_eval_harness),
    ("Deliver","REPORT.md",d_report),("Deliver","README.en",d_readme_en),
    ("Deliver","git_repo",d_git),("Deliver","sample_outputs",d_samples),
]

MANUAL = [("Deliver","demo_video","<= 5 min walkthrough video (user records)")]

for cat, name, fn in CHECKS:
    check(cat, name, fn)

passed = [r for r in RESULTS if r[2]]
failed = [r for r in RESULTS if not r[2]]

print("=" * 62)
print("ACCEPTANCE CHECK — goal: all REQUIRED green")
print("=" * 62)
for cat, name, ok, detail, _ in RESULTS:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {cat:8} {name:24} {('' if ok else '- '+detail)[:60]}")
print("-" * 62)
for cat, name, why in MANUAL:
    print(f"  [MANUAL] {cat:8} {name:24} {why}")
print("-" * 62)
print(f"  {len(passed)}/{len(RESULTS)} required checks pass; {len(failed)} remaining")
print("=" * 62)

sys.exit(0 if not failed else 1)
