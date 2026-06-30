"""Critic / QA agent: image vs. spec consistency + Amazon main-image rules.

Layers:
  1. Deterministic pixel checks (reliable, zero-cost): pure white bg, coverage
     by longest side, object count by column projection.
  2. Vision check (when key set): the vision model judges count/color/material
     against the CLAIMED spec and returns booleans.
The vision count is authoritative; projection is informational when vision runs.
"""

from PIL import Image

from app.tools import llm

WHITE_TOL = 6
COVERAGE_MIN = 0.85
CORNER_FRAC = 0.05


def white_bg_check(img: Image.Image) -> dict:
    w, h = img.size
    s = int(min(w, h) * CORNER_FRAC)
    boxes = [(0, 0, s, s), (w - s, 0, w, s), (0, h - s, s, h), (w - s, h - s, w, h)]
    worst = [255, 255, 255]
    for box in boxes:
        px = list(img.crop(box).getdata())
        mean = [round(sum(c[i] for c in px) / len(px)) for i in range(3)]
        worst = [min(worst[i], mean[i]) for i in range(3)]
    return {"check": "white_background",
            "pass": all(c >= 255 - WHITE_TOL for c in worst),
            "worst_channel_rgb": worst, "required": [255, 255, 255]}


def coverage_check(img: Image.Image) -> dict:
    # longest-side fill, not bbox area (a tall narrow product should still
    # "fill the frame" along its long axis)
    gray = img.convert("L")
    bbox = gray.point(lambda v: 0 if v >= 255 - WHITE_TOL else 255).getbbox()
    if not bbox:
        return {"check": "coverage", "pass": False, "longest_side_fill": 0.0,
                "required_min": COVERAGE_MIN}
    W, H = img.size
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    fill = max(bw / W, bh / H)
    return {"check": "coverage", "pass": fill >= COVERAGE_MIN,
            "longest_side_fill": round(fill, 3),
            "area_ratio": round((bw * bh) / (W * H), 3),
            "required_min": COVERAGE_MIN}


def count_by_projection(img: Image.Image) -> int:
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    runs, prev = 0, False
    for x in range(w):
        has = any(px[x, y] < 255 - WHITE_TOL for y in range(0, h, 4))
        if has and not prev:
            runs += 1
        prev = has
    return runs


VISION_SAMPLES = 3  # majority vote: vision verdicts are non-deterministic and
                    # a single flaky FAIL would otherwise trigger a costly regen


def vision_check(image_path: str, items: list, expected_count: int) -> dict:
    """items: list of {"title","color","material"} expected to appear. For a
    multipack there is one entry but expected_count = pack size; for a combo
    there is one entry per distinct product and expected_count = #products."""
    if not llm.available():
        return {"check": "vision", "skipped": True, "reason": "no LLM key"}
    item_lines = "\n".join(
        f"  - {it['title']}: color {it['color']}, material {it['material']}"
        for it in items)
    system = (
        "You verify a product photo against claimed specs. Be strict but allow "
        "semantically equivalent terms (e.g. 'metal' is consistent with "
        "'stainless steel'). Judge ONLY what is visible. items_ok means every "
        "claimed item appears with the right color and material. "
        'Return JSON: {"count_seen": int, "count_ok": bool, "items_ok": bool, '
        '"notes": str}.'
    )
    user = (f"Claimed: {expected_count} total item(s) in the photo.\n"
            f"Expected item(s):\n{item_lines}\n"
            "Does the image match (correct total count, and each item present "
            "with right color/material)?")

    verdicts = []
    for _ in range(VISION_SAMPLES):
        try:
            verdicts.append(llm.vision_json(system, user, image_path))
        except Exception as e:
            # key present but verification failed -> do NOT silently pass
            if not verdicts:
                return {"check": "vision", "skipped": False, "error": True,
                        "pass": False, "needs_review": True,
                        "reason": f"vision failed: {e}"}
            break  # vote on the samples we did get

    def majority(field):
        votes = [bool(v.get(field)) for v in verdicts]
        return sum(votes) > len(votes) / 2

    fields = {f: majority(f) for f in ("count_ok", "items_ok")}
    ok = all(fields.values())
    return {"check": "vision", "skipped": False, "pass": ok,
            "voted": fields, "samples": len(verdicts), "verdicts": verdicts}


def run(image_path: str, kind: str, products, units: int,
        emit=lambda *a, **k: None) -> dict:
    expected_count = len(products) if kind == "combo" else units
    items = [{"title": p.title, "color": p.color, "material": p.material}
             for p in (products if kind == "combo" else products[:1])]

    img = Image.open(image_path).convert("RGB")
    checks = [white_bg_check(img), coverage_check(img)]
    vision = vision_check(image_path, items, expected_count)
    proj = count_by_projection(img)
    checks.append({"check": "count_projection",
                   "informational": not vision.get("skipped"),
                   "pass": proj == expected_count,
                   "counted": proj, "expected": expected_count})
    checks.append(vision)

    hard = [c for c in checks
            if not c.get("skipped") and not c.get("informational")]
    overall = all(c.get("pass", False) for c in hard)
    for c in checks:
        tag = ("SKIP" if c.get("skipped") else "INFO" if c.get("informational")
               else "PASS" if c.get("pass") else "FAIL")
        emit("Critic", f"{c['check']}: {tag}")
    emit("Critic", f"overall: {'PASS' if overall else 'FAIL'}")
    return {"overall_pass": overall, "expected_count": expected_count,
            "checks": checks}
