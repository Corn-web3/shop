"""Read-only Postgres source: introspect schema, map arbitrary columns to the
normalized Product shape, load SKUs.

The SSB schema is "以实际为准" (unknown column names), so we map by SYNONYMS
rather than hardcoding columns, and parse combined fields (e.g. a "7x7x25 cm"
dimensions string, weight in g/kg) defensively. The mapping/normalization core
(build_colmap / normalize_row) is pure and unit-tested without a database.

Read-only is enforced three ways: a read-only transaction, autocommit off for
writes never issued, and we only ever run SELECT.
"""

import re
from typing import Dict, List, Optional

from app.db import Product

# normalized field -> candidate source column names (normalized: lowercased,
# non-alphanumerics stripped)
FIELD_SYNONYMS = {
    "sku": ["sku", "skuid", "skucode", "itemid", "id", "productid", "asin"],
    "title": ["title", "name", "productname", "producttitle", "itemname"],
    "brand": ["brand", "brandname", "manufacturer", "vendor"],
    "category": ["category", "categorypath", "producttype", "type", "department"],
    "color": ["color", "colour", "colorname"],
    "material": ["material", "fabric", "composition"],
    "unit_count": ["unitcount", "piececount", "pieces", "units", "quantity",
                   "qty", "packsize", "count"],
    "weight_g": ["weightg", "weightgrams", "weight", "itemweight", "netweight"],
    "length_cm": ["lengthcm", "length", "lengthmm", "depth", "depthcm"],
    "width_cm": ["widthcm", "width", "widthmm"],
    "height_cm": ["heightcm", "height", "heightmm"],
    "dimensions": ["dimensions", "size", "dims", "packagedimensions", "measurements"],
    "price": ["price", "listprice", "msrp", "amount", "unitprice"],
    "image_urls": ["imageurls", "imageurl", "images", "image", "imagelinks",
                   "mainimage", "photourl"],
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def build_colmap(columns: List[str]) -> Dict[str, Optional[str]]:
    """Map each normalized field to the best-matching actual column name."""
    norm_to_actual = {_norm(c): c for c in columns}
    colmap = {}
    for field, syns in FIELD_SYNONYMS.items():
        match = None
        for syn in syns:  # synonyms are priority-ordered
            if syn in norm_to_actual:
                match = norm_to_actual[syn]
                break
        colmap[field] = match
    return colmap


def _to_float(v, default=0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else default


def _to_grams(v) -> float:
    """Weight to grams. Detects kg/lb/oz from the string; bare numbers -> grams."""
    if v is None:
        return 0.0
    s = str(v).lower()
    n = _to_float(v)
    if "kg" in s:
        return round(n * 1000, 1)
    if "lb" in s or "pound" in s:
        return round(n * 453.592, 1)
    if "oz" in s or "ounce" in s:
        return round(n * 28.3495, 1)
    return round(n, 1)


def _to_cm(v) -> float:
    s = str(v).lower()
    n = _to_float(v)
    if "mm" in s:
        return round(n / 10, 2)
    if '"' in s or "in" in s or "inch" in s:
        return round(n * 2.54, 2)
    return round(n, 2)


def _parse_dims(v):
    """Parse '7x7x25 cm' / '7 * 7 * 25' -> (l, w, h) in cm, or None."""
    if not v:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", str(v))
    if len(nums) < 3:
        return None
    unit_scale = 0.1 if "mm" in str(v).lower() else (
        2.54 if "in" in str(v).lower() else 1.0)
    return tuple(round(float(n) * unit_scale, 2) for n in nums[:3])


def _parse_image_urls(v) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x]
    s = str(v).strip()
    if s.startswith("["):  # JSON-ish array
        try:
            import json
            return [str(x) for x in json.loads(s) if x]
        except Exception:
            pass
    return [u.strip() for u in re.split(r"[,\s|;]+", s) if u.strip().startswith("http")]


def normalize_row(colmap: Dict[str, Optional[str]], row: dict) -> Product:
    """Pure: turn a DB row dict + column map into a normalized Product."""
    def g(field):
        col = colmap.get(field)
        return row.get(col) if col else None

    dims = _parse_dims(g("dimensions"))
    if dims:
        length_cm, width_cm, height_cm = dims
    else:
        length_cm = _to_cm(g("length_cm"))
        width_cm = _to_cm(g("width_cm"))
        height_cm = _to_cm(g("height_cm"))

    unit_count = int(_to_float(g("unit_count"), default=1)) or 1

    return Product(
        sku=str(g("sku") or "").strip(),
        title=str(g("title") or "").strip(),
        brand=str(g("brand") or "").strip(),
        category=str(g("category") or "").strip(),
        color=str(g("color") or "").strip(),
        material=str(g("material") or "").strip(),
        unit_count=unit_count,
        length_cm=length_cm, width_cm=width_cm, height_cm=height_cm,
        weight_g=_to_grams(g("weight_g")),
        price=_to_float(g("price")),
        image_urls=_parse_image_urls(g("image_urls")),
    )


# ---- DB I/O (only runs when DATABASE_URL is set) ----

def _detect_table(cur) -> Optional[str]:
    """Find a table that looks like products: has a sku-like AND title-like col."""
    cur.execute("""
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    """)
    cols_by_table = {}
    for schema, table, col in cur.fetchall():
        cols_by_table.setdefault(f"{schema}.{table}", []).append(col)
    for table, cols in cols_by_table.items():
        norms = {_norm(c) for c in cols}
        has_sku = norms & set(FIELD_SYNONYMS["sku"])
        has_title = norms & set(FIELD_SYNONYMS["title"])
        if has_sku and has_title:
            return table
    return None


def load_all(dsn: str, table: Optional[str], limit: int = 500) -> Dict[str, Product]:
    import psycopg  # lazy: only needed in DB mode
    products: Dict[str, Product] = {}
    # read-only connection; we only ever issue SELECT
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            tbl = table or _detect_table(cur)
            if not tbl:
                raise RuntimeError("could not find a product-like table; set PRODUCTS_TABLE")
            cur.execute(f"SELECT * FROM {tbl} LIMIT %s", (limit,))
            columns = [d.name for d in cur.description]
            colmap = build_colmap(columns)
            if not colmap.get("sku") or not colmap.get("title"):
                raise RuntimeError(f"table {tbl} missing sku/title columns")
            for raw in cur.fetchall():
                row = dict(zip(columns, raw))
                p = normalize_row(colmap, row)
                if p.sku:
                    products[p.sku] = p
    return products
