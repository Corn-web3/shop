"""Marketing / Conversion critic agent.

A second-order critic for the COPY (the Image Critic handles the picture). It
scores the listing on conversion levers — benefit clarity, keyword coverage,
and (compliance-safe) appeal — and, when the score is weak, rewrites the bullets
and title to be more persuasive WITHOUT breaking Amazon rules (no promo/subjective
words, brand-led title, length limits) and WITHOUT inventing specs.

This adds a real, distinct agent to the graph and lifts conversion quality while
staying inside the B1 compliance envelope (compliance still validates at the end).
"""

from typing import List

from app.db import Product
from app.tools import llm

REWRITE_BELOW = 80  # overall score under this triggers a compliance-safe rewrite

SCORE_SYSTEM = (
    "You are an Amazon conversion analyst. Score a listing on how well it will "
    "convert, then optionally improve it. HARD COMPLIANCE RULES you must keep: "
    "brand leads the title; NO promotional/subjective words (best, #1, top, "
    "guaranteed, free shipping, sale); title <= 150 chars; exactly 5 bullets, "
    "each <= 500 chars, benefit-led, no contact info; never invent specs not "
    "present in the input; PRESERVE any pack-size or bundle wording already in "
    "the title (e.g. 'Pack of 3', 'Bundle', '2-Pack') and the item count. "
    "Score each 0-100: benefit_clarity (features turned "
    "into buyer benefits), keyword_coverage (important buyer keywords present in "
    "title + bullets + search_terms), appeal (compelling but compliant). "
    "If overall < 80, return improved title/bullets/search_terms that raise the "
    "score while obeying every rule; otherwise echo the originals. "
    'Return JSON: {"scores": {"benefit_clarity": int, "keyword_coverage": int, '
    '"appeal": int, "overall": int}, "notes": str, "title": str, '
    '"bullets": [str x5], "search_terms": str}.'
)


def _user(copy: dict, products: List[Product], keywords: List[str]) -> str:
    kw = ", ".join(keywords[:20]) if keywords else "(none provided)"
    specs = "; ".join(f"{p.brand} {p.title} | {p.color} | {p.material}"
                      for p in products)
    return (
        f"Product(s): {specs}\n"
        f"Important buyer keywords to cover where truthful: {kw}\n\n"
        f"Current listing:\n"
        f"- title: {copy.get('title','')}\n"
        f"- bullets:\n" + "\n".join(f"  {i+1}. {b}" for i, b in
                                    enumerate(copy.get('bullets', []))) + "\n"
        f"- search_terms: {copy.get('search_terms','')}\n\n"
        "Score it, and if overall < 80 rewrite to convert better while keeping "
        "every compliance rule and only using facts above."
    )


def run(copy: dict, products: List[Product], keywords: List[str] = None,
        emit=lambda *a, **k: None) -> dict:
    """Returns {"copy": possibly-improved copy, "score": {...}}. Offline (no LLM)
    it is a no-op that reports it was skipped."""
    keywords = keywords or []
    if not llm.available():
        emit("Marketing", "no LLM key -> skipping conversion scoring")
        return {"copy": copy, "score": {"skipped": True}}
    try:
        out = llm.chat_json(SCORE_SYSTEM, _user(copy, products, keywords))
    except Exception as e:
        emit("Marketing", f"scoring failed ({e}); keeping original copy")
        return {"copy": copy, "score": {"skipped": True, "error": str(e)}}

    scores = out.get("scores", {}) or {}
    overall = scores.get("overall")
    # accept a rewrite only if it is well-formed (5 bullets + a title)
    improved = dict(copy)
    rewrote = False
    if (isinstance(overall, (int, float)) and overall < REWRITE_BELOW
            and out.get("title") and len(out.get("bullets", []) or []) == 5):
        improved["title"] = out["title"]
        improved["bullets"] = out["bullets"]
        if out.get("search_terms"):
            improved["search_terms"] = out["search_terms"]
        rewrote = True
    emit("Marketing", f"conversion score {overall} "
                      f"(benefit {scores.get('benefit_clarity')}, "
                      f"keywords {scores.get('keyword_coverage')}, "
                      f"appeal {scores.get('appeal')})"
                      + ("; rewrote copy to lift it" if rewrote else ""))
    return {"copy": improved,
            "score": {"skipped": False, "rewrote": rewrote,
                      "scores": scores, "notes": out.get("notes", "")}}
