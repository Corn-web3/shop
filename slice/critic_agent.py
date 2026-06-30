"""Critic / QA agent: checks the generated image against the spec.

Two layers, exactly as the README asks for:
  1. Deterministic pixel checks (no model needed, so always reliable):
       - pure white background, RGB sampled at the corners
       - product coverage >= 85% of the frame (bounding box)
       - object count via column projection (cross-check / works offline)
  2. Vision check (when a key is set): a vision model counts the items and
     reports color + material, which we compare to the database record.

Output is a structured report with per-check pass/fail and the deltas.
"""

from PIL import Image

from product import Product
import llm_client

WHITE_TOL = 6          # channel within this of 255 counts as white
COVERAGE_MIN = 0.85
CORNER_FRAC = 0.05     # sample 5% squares in each corner


def white_bg_check(img: Image.Image) -> dict:
    # Track the per-channel minimum across all corner means: a corner can have a
    # high channel SUM yet still fail on one channel (a colored tint), so summing
    # would let it slip through. We keep the lowest value seen per channel.
    w, h = img.size
    s = int(min(w, h) * CORNER_FRAC)
    boxes = [(0, 0, s, s), (w - s, 0, w, s), (0, h - s, s, h), (w - s, h - s, w, h)]
    worst = [255, 255, 255]
    for box in boxes:
        px = list(img.crop(box).getdata())
        mean = [round(sum(c[i] for c in px) / len(px)) for i in range(3)]
        worst = [min(worst[i], mean[i]) for i in range(3)]
    ok = all(c >= 255 - WHITE_TOL for c in worst)
    return {"check": "white_background", "pass": ok,
            "worst_channel_rgb": worst, "required": [255, 255, 255]}


def coverage_check(img: Image.Image) -> dict:
    # Amazon judges "product fills >=85% of the frame" by the LONGEST extent,
    # not bounding-box area (a tall narrow bottle has small area but should
    # still fill the frame vertically). So we use max-side fill, and keep the
    # area ratio as an informational field.
    gray = img.convert("L")
    mask = gray.point(lambda v: 0 if v >= 255 - WHITE_TOL else 255)
    bbox = mask.getbbox()
    if not bbox:
        return {"check": "coverage", "pass": False, "longest_side_fill": 0.0,
                "required_min": COVERAGE_MIN}
    W, H = img.size
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    longest_fill = max(bw / W, bh / H)
    return {"check": "coverage", "pass": longest_fill >= COVERAGE_MIN,
            "longest_side_fill": round(longest_fill, 3),
            "area_ratio": round((bw * bh) / (W * H), 3),
            "required_min": COVERAGE_MIN}


def count_by_projection(img: Image.Image) -> int:
    """Count side-by-side objects via vertical column projection."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    col_has = []
    for x in range(w):
        has = any(px[x, y] < 255 - WHITE_TOL for y in range(0, h, 4))
        col_has.append(has)
    runs, prev = 0, False
    for has in col_has:
        if has and not prev:
            runs += 1
        prev = has
    return runs


def vision_check(image_path: str, p: Product, expected_count: int) -> dict:
    """Have the vision model judge consistency against the CLAIMED spec.

    We pass the database values in and ask the model to decide whether the
    image is consistent with each, returning booleans + notes. This is far
    more robust than letting it free-form describe and then string-matching on
    our side (e.g. "stainless steel" vs the model saying "metal").
    """
    if not llm_client.available():
        return {"check": "vision", "skipped": True, "reason": "no LLM key"}
    system = (
        "You verify a product photo against claimed specs. Be strict but allow "
        "semantically equivalent terms (e.g. 'metal' is consistent with "
        "'stainless steel'). Judge ONLY what is visible. "
        'Return JSON: {"count_seen": int, "count_ok": bool, "color_ok": bool, '
        '"material_ok": bool, "notes": str}.'
    )
    user = (
        f"Claimed specs:\n- unit count: {expected_count}\n- color: {p.color}\n"
        f"- material: {p.material}\n- product: {p.title}\n"
        "Does the image match each claim?"
    )
    try:
        v = llm_client.vision_json(system, user, image_path)
    except Exception as e:
        # A key IS configured but verification failed: we must NOT silently pass
        # a listing we couldn't actually verify. Mark it as a hard fail needing
        # review (distinct from the no-key case above, which is an expected skip).
        return {"check": "vision", "skipped": False, "error": True,
                "pass": False, "needs_review": True, "reason": f"vision failed: {e}"}
    ok = bool(v.get("count_ok") and v.get("color_ok") and v.get("material_ok"))
    return {"check": "vision", "skipped": False, "verdict": v, "pass": ok}


def run(image_path: str, p: Product, expected_count: int) -> dict:
    img = Image.open(image_path).convert("RGB")
    checks = [white_bg_check(img), coverage_check(img)]

    vision = vision_check(image_path, p, expected_count)

    # Object count: the vision model is the reliable judge (column projection
    # merges touching items / shadows into one). So projection is only a HARD
    # gate when vision is unavailable; otherwise it's informational.
    proj = count_by_projection(img)
    checks.append({"check": "count_projection",
                   "informational": not vision.get("skipped"),
                   "pass": proj == expected_count,
                   "counted": proj, "expected": expected_count})

    checks.append(vision)

    hard = [c for c in checks
            if not c.get("skipped") and not c.get("informational")]
    overall = all(c.get("pass", False) for c in hard)
    return {"overall_pass": overall, "expected_count": expected_count,
            "checks": checks}
