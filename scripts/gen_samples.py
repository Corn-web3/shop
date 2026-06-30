"""Generate committed sample outputs (LIVE) for >=3 SKUs incl. 1 multipack +
1 combo. Runs the real pipeline (uses .env keys), writes JSON + copies the
generated images into samples/, rewriting image references to the copied files.
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(ROOT, "samples")
os.makedirs(SAMPLES, exist_ok=True)

from app import jobs, trace  # noqa: E402

SPECS = [
    ("SSB-003_single", {"kind": "single", "skus": ["SSB-003"], "units": 1}),
    ("SSB-001_multipack_x3", {"kind": "multipack", "skus": ["SSB-001"], "units": 3}),
    ("SSB-001+SSB-002_combo", {"kind": "combo", "skus": ["SSB-001", "SSB-002"], "units": 1}),
]


def _copy_img(meta: dict, prefix: str):
    """Copy a generated image into samples/ and point the meta at the copy."""
    if not meta or not meta.get("path") or not os.path.exists(meta["path"]):
        return
    base = f"{prefix}__{os.path.basename(meta['path'])}"
    shutil.copy(meta["path"], os.path.join(SAMPLES, base))
    meta["file"] = base
    meta["path"] = f"samples/{base}"


for name, spec in SPECS:
    print(f"[gen] {name} ...", flush=True)
    bus = trace.create()
    listing = jobs.run_sync(bus, spec)
    _copy_img(listing.get("main_image"), name)
    for m in listing.get("a_plus_modules", []):
        _copy_img(m.get("image"), name)
    if listing.get("images"):
        listing["images"]["main"] = listing.get("main_image")
        listing["images"]["a_plus"] = [m.get("image") for m in listing.get("a_plus_modules", [])]
    with open(os.path.join(SAMPLES, f"{name}.json"), "w") as f:
        json.dump(listing, f, indent=2, ensure_ascii=False)
    print(f"[gen] {name} done: compliant={listing.get('compliant')} "
          f"imgs main+{len(listing.get('a_plus_modules', []))}", flush=True)

print("[gen] ALL SAMPLES DONE", flush=True)
