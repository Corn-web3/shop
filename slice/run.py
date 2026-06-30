#!/usr/bin/env python3
"""Vertical slice: one SKU -> copy + main image -> critic -> listing JSON.

This is the walking skeleton. It deliberately does NOT yet use FastAPI,
LangGraph, or a UI -- it exists to prove the hardest assumption early:
can we generate an image that matches the database specs, and can the critic
catch when it doesn't?

Usage:
    python run.py            # main listing for the mock SKU
    python run.py --count 3  # pretend it's a 3-pack (multipack preview)
"""

import argparse
import json
import os
import sys

# load .env if present (no hard dependency on python-dotenv)
def _load_env():
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

import product as product_mod
import copy_agent
import image_agent
import critic_agent

OUT = os.path.join(os.path.dirname(__file__), "out")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", default="SSB-001")
    ap.add_argument("--count", type=int, default=1,
                    help="units shown (preview multipack physical consistency)")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    print(f"\n=== SSB Listing Studio — vertical slice ===")
    print(f"SKU={args.sku}  units={args.count}\n")

    # ---取数 ---
    print("[Supervisor] loading product record")
    p = product_mod.load_product(args.sku)
    print(f"  -> {p.brand} {p.title} | {p.color} | {p.material} | "
          f"unit_count={p.unit_count} | {p.weight_g}g")

    # --- Copy ---
    print("[Copy] generating title + bullets")
    copy = copy_agent.run(p)
    print(f"  -> title: {copy['title']}")

    # --- Image ---
    img_path = os.path.join(OUT, f"{p.sku}_x{args.count}.png")
    print(f"[Image] generating main image ({args.count} unit(s), white bg)")
    img = image_agent.run(p, args.count, img_path)
    print(f"  -> {img['mode']}: {img_path}")

    # --- Critic ---
    print("[Critic] checking image vs. specs")
    report = critic_agent.run(img_path, p, args.count)
    for c in report["checks"]:
        if c.get("skipped"):
            print(f"  - {c['check']}: SKIP ({c['reason']})")
        else:
            mark = "PASS" if c.get("pass") else "FAIL"
            extra = {k: v for k, v in c.items()
                     if k not in ("check", "pass", "skipped")}
            print(f"  - {c['check']}: {mark}  {extra}")
    verdict = "PASS" if report["overall_pass"] else "FAIL"
    print(f"[Critic] overall: {verdict}")

    # --- 产出 ---
    listing = {
        "sku": p.sku,
        "units": args.count,
        "product": p.to_dict(),
        "copy": copy,
        "main_image": img,
        "critic": report,
        "compliant": report["overall_pass"],
    }
    out_json = os.path.join(OUT, f"{p.sku}_x{args.count}.json")
    with open(out_json, "w") as f:
        json.dump(listing, f, indent=2, ensure_ascii=False)
    print(f"\n[done] listing -> {out_json}")
    print(f"       image   -> {img_path}\n")

    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
