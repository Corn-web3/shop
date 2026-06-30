"""Copy agent: produces the text half of an Amazon A+ listing.

Online (key set): one LLM call constrained to A+ rules.
Offline (no key): a deterministic template built straight from the product
record, so the rest of the pipeline still has real, compliant-shaped copy to
work with.
"""

from product import Product
import llm_client

SYSTEM = (
    "You are an Amazon listing copywriter. Follow Amazon A+ rules strictly: "
    "brand leads the title, title case, NO promotional/subjective words "
    "(best, free shipping, guaranteed, #1), title <= 150 chars. "
    "Exactly 5 benefit-led bullets, each <= 500 chars, no contact info. "
    "Backend search terms <= 250 bytes, space separated, no commas, no brand. "
    'Return JSON: {"title": str, "bullets": [str x5], "description": str, '
    '"search_terms": str}.'
)


def _user_prompt(p: Product) -> str:
    return (
        "Write a listing for this product. Stay factual to these specs:\n"
        f"- brand: {p.brand}\n- name: {p.title}\n- category: {p.category}\n"
        f"- color: {p.color}\n- material: {p.material}\n"
        f"- unit count: {p.unit_count}\n"
        f"- size: {p.length_cm}x{p.width_cm}x{p.height_cm} cm\n"
        f"- weight: {p.weight_g} g\n- price: {p.price}"
    )


def _offline(p: Product) -> dict:
    title = f"{p.brand} {p.title} {p.color} {p.material}"
    bullets = [
        f"MADE OF {p.material.upper()}: Durable {p.material.lower()} build in a clean {p.color.lower()} finish.",
        f"RIGHT SIZE: Measures {p.length_cm} x {p.width_cm} x {p.height_cm} cm and weighs {p.weight_g} g.",
        f"SINGLE UNIT: Each order includes {p.unit_count} item, ready to use out of the box.",
        f"EVERYDAY USE: Built for {p.category.split('/')[0].strip().lower()} and daily carry.",
        "EASY CARE: Simple to clean and maintain for long-lasting performance.",
    ]
    return {
        "title": title[:150],
        "bullets": bullets,
        "description": f"The {p.brand} {p.title} combines {p.material.lower()} "
        f"construction with a {p.color.lower()} finish for reliable everyday use.",
        "search_terms": f"{p.material.lower()} {p.color.lower()} bottle insulated reusable "
        "travel sport".strip()[:250],
    }


def run(p: Product) -> dict:
    if llm_client.available():
        try:
            return llm_client.chat_json(SYSTEM, _user_prompt(p))
        except Exception as e:
            print(f"  [Copy] LLM call failed ({e}); using offline template")
    else:
        print("  [Copy] no LLM key -> offline template")
    return _offline(p)
