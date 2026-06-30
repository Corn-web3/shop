"""B1 — deterministic Amazon listing-copy compliance validator.

Complements the Critic (which checks the IMAGE against physical specs): this
checks the TEXT against Amazon A+ rules and produces a pass/fail report with
per-rule violations and severities. Pure functions, zero model calls -> fully
reliable and cheap. Used as a graph node and reflected in the listing's
`compliant` flag.

Numbers follow the README's §6 acceptance checklist.
"""

import os
import re

TITLE_MAX = 200          # hard cap (most categories)
TITLE_RECOMMENDED = 150  # warn beyond this
BULLET_MAX = 500         # per bullet
BULLETS_MAX_COUNT = 5
SEARCH_TERMS_MAX_BYTES = 250

# Subjective / promotional phrases Amazon prohibits in titles & bullets.
# Conservative list (word-boundary matched) to avoid false positives on common
# words like "new" or "sale" used factually.
BANNED_PHRASES = [
    "best seller", "bestseller", "best-selling", "#1", "number one",
    "free shipping", "guarantee", "guaranteed", "money back", "money-back",
    "satisfaction guaranteed", "cheapest", "lowest price", "on sale",
    "top rated", "top-rated", "100% satisfaction", "best in class",
]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
_URL = re.compile(r"https?://|www\.")


def _find_banned(text: str):
    low = text.lower()
    hits = []
    for phrase in BANNED_PHRASES:
        # word-boundary-ish: phrase surrounded by non-alphanumerics or ends
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", low):
            hits.append(phrase)
    return hits


ALT_TEXT_MAX = 100        # A+ module alt text
VALID_MODULE_SIZES = {(970, 600), (970, 300), (300, 300), (150, 300), (600, 180)}


MAIN_IMAGE_MAX_MB = 10


def check_listing(copy: dict, brand: str = "", a_plus_modules: list = None,
                  main_image: dict = None) -> dict:
    """copy: {title, bullets[], description, search_terms}.
    a_plus_modules: optional list of {type, size, alt_text, image}.
    main_image: optional {path, ...}. Returns report."""
    violations = []

    def add(field, rule, severity, detail):
        violations.append({"field": field, "rule": rule,
                           "severity": severity, "detail": detail})

    title = (copy.get("title") or "").strip()
    bullets = copy.get("bullets") or []
    description = (copy.get("description") or "").strip()
    search_terms = (copy.get("search_terms") or "")

    # --- title ---
    if not title:
        add("title", "present", "error", "title is empty")
    else:
        if len(title) > TITLE_MAX:
            add("title", "length", "error", f"{len(title)} > {TITLE_MAX} chars")
        elif len(title) > TITLE_RECOMMENDED:
            add("title", "length", "warn",
                f"{len(title)} chars; recommend <= {TITLE_RECOMMENDED}")
        if brand and not title.lower().startswith(brand.lower()):
            add("title", "brand_leads", "warn", f"title should start with brand '{brand}'")
        for p in _find_banned(title):
            add("title", "banned_phrase", "error", f"contains '{p}'")

    # --- bullets ---
    if len(bullets) > BULLETS_MAX_COUNT:
        add("bullets", "count", "error",
            f"{len(bullets)} bullets > max {BULLETS_MAX_COUNT}")
    elif len(bullets) < BULLETS_MAX_COUNT:
        add("bullets", "count", "warn",
            f"{len(bullets)} bullets; {BULLETS_MAX_COUNT} recommended")
    for i, b in enumerate(bullets):
        b = b or ""
        if len(b) > BULLET_MAX:
            add(f"bullets[{i}]", "length", "error", f"{len(b)} > {BULLET_MAX} chars")
        for p in _find_banned(b):
            add(f"bullets[{i}]", "banned_phrase", "error", f"contains '{p}'")
        if _EMAIL.search(b) or _URL.search(b) or _PHONE.search(b):
            add(f"bullets[{i}]", "contact_info", "error",
                "contains contact info (email/url/phone)")

    # --- description ---
    if not description:
        add("description", "present", "warn", "description is empty")

    # --- backend search terms ---
    nbytes = len(search_terms.encode("utf-8"))
    if nbytes > SEARCH_TERMS_MAX_BYTES:
        add("search_terms", "byte_length", "error",
            f"{nbytes} > {SEARCH_TERMS_MAX_BYTES} bytes")
    if "," in search_terms:
        add("search_terms", "no_commas", "warn",
            "commas waste bytes; use spaces")
    if brand and brand.lower() in search_terms.lower():
        add("search_terms", "no_brand", "warn",
            "backend terms should not repeat the brand")

    # --- A+ content modules (Tier 2): each needs an image + alt text, and a
    # valid Amazon module dimension ---
    for i, m in enumerate(a_plus_modules or []):
        fld = f"a_plus[{i}]"
        if not (m.get("image") or {}).get("path"):
            add(fld, "image_present", "error", "module has no image")
        alt = (m.get("alt_text") or "").strip()
        if not alt:
            add(fld, "alt_text", "error", "module missing alt text")
        elif len(alt) > ALT_TEXT_MAX:
            add(fld, "alt_text", "warn", f"{len(alt)} > {ALT_TEXT_MAX} chars")
        size = tuple(m.get("size") or [])
        if size and size not in VALID_MODULE_SIZES:
            add(fld, "module_size", "warn", f"{size} not a standard A+ size")

    # --- main image (Amazon §6): JPEG, <10MB ---
    mpath = (main_image or {}).get("path")
    if mpath:
        if not mpath.lower().endswith((".jpg", ".jpeg")):
            add("main_image", "format", "error", "main image must be JPEG")
        try:
            mb = os.path.getsize(mpath) / 1_048_576
            if mb > MAIN_IMAGE_MAX_MB:
                add("main_image", "file_size", "error",
                    f"{mb:.1f} MB > {MAIN_IMAGE_MAX_MB} MB")
        except OSError:
            pass

    errors = [v for v in violations if v["severity"] == "error"]
    return {
        "compliant": len(errors) == 0,
        "error_count": len(errors),
        "warn_count": len(violations) - len(errors),
        "violations": violations,
    }
